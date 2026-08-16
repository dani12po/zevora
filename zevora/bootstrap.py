"""Idempotent, standard-library bootstrap for a cloned ZEVORA repository."""
import argparse, os, platform, shutil, subprocess, sys, venv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VENV=ROOT/'.venv'

class Bootstrap:
    def __init__(self, root=ROOT, quiet=False): self.root=Path(root); self.quiet=quiet
    def log(self, level, message):
        if not self.quiet: print(f'[{level}] {message}')
    @property
    def python(self): return self.root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    def environment(self):
        compatible=(3,11)<=sys.version_info[:2]<(3,14)
        self.log('OK' if compatible else 'ERROR',f'Python {sys.version_info.major}.{sys.version_info.minor}')
        self.log('INFO',f'{platform.system()} / {platform.machine()}')
        if not compatible: raise RuntimeError('Python 3.11, 3.12, or 3.13 is required')
    def ensure_venv(self):
        if self.python.exists(): self.log('OK','Existing virtual environment detected'); return
        self.log('INFO','Creating virtual environment...'); venv.EnvBuilder(with_pip=True,clear=False).create(self.root/'.venv'); self.log('OK','Virtual environment created')
    def dependencies(self):
        self.log('INFO','Checking dependencies from pyproject.toml...')
        command=[str(self.python),'-m','pip','install','--disable-pip-version-check']
        if os.name=='nt':
            command.extend([
                '--prefer-binary','--extra-index-url',
                'https://abetlen.github.io/llama-cpp-python/whl/cpu',
            ])
        command.extend(['-e',str(self.root)])
        for attempt in range(1,4):
            result=subprocess.run(command,cwd=self.root,capture_output=True,text=True)
            if result.returncode==0: self.log('OK','Dependencies ready'); return
            if attempt<3: self.log('WARN',f'Dependency install failed; retrying ({attempt}/3)')
        raise RuntimeError('Dependencies could not be installed. Check the network, then run python bootstrap.py --debug')
    def configuration(self):
        target=self.root/'.env'; example=self.root/'.env.example'
        if not target.exists() and example.exists(): shutil.copyfile(example,target); self.log('OK','Created .env from safe template')
        else: self.log('OK','Existing configuration detected')
    def storage(self):
        for name in ('data/database','data/memory','data/cache','data/experience','data/runtime','logs','projects','cache','workspace'): (self.root/name).mkdir(parents=True,exist_ok=True)
        self.log('OK','Storage ready')
    def mcp(self):
        target=self.root/'config'/'mcp.json'; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('{"permissions":"approval-gated","tools":["filesystem","terminal","git","project"]}\n',encoding='utf-8') if not target.exists() else None
        self.log('OK','MCP configuration and tool registry ready')

    def register_command(self):
        if os.name!='nt': self.log('INFO','Console command is registered by the virtual environment'); return
        scripts=Path(os.environ.get('APPDATA',str(Path.home()/'AppData/Roaming')))/'Python'/f'Python{sys.version_info.major}{sys.version_info.minor}'/'Scripts'; scripts.mkdir(parents=True,exist_ok=True)
        command=scripts/'zevora.cmd'; command.write_text(f'@echo off\r\n"{self.python}" -m zevora %*\r\n',encoding='utf-8')
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment',0,winreg.KEY_READ|winreg.KEY_WRITE) as key:
                try: user_path,_=winreg.QueryValueEx(key,'Path')
                except FileNotFoundError: user_path=''
                if str(scripts).lower() not in [p.lower() for p in user_path.split(';')]: winreg.SetValueEx(key,'Path',0,winreg.REG_EXPAND_SZ,(user_path.rstrip(';')+';'+str(scripts)).lstrip(';'))
            self.log('INFO','Open a new terminal once to use the zevora command globally')
        except OSError: self.log('WARN','Could not update user PATH; use python launcher.py')
        self.log('OK',f'ZEVORA launcher prepared: {command}')
    def run(self, register=True):
        self.log('INFO','ZEVORA Bootstrap'); self.environment(); self.ensure_venv(); self.dependencies(); self.configuration(); self.storage(); self.mcp()
        if register: self.register_command()
        self.log('OK','ZEVORA installation complete')
    def quick_check(self):
        self.configuration(); self.storage(); self.mcp()

def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument('--check',action='store_true'); parser.add_argument('--debug',action='store_true'); args=parser.parse_args(argv)
    try:
        bootstrap=Bootstrap(); bootstrap.quick_check() if args.check else bootstrap.run()
    except Exception as error:
        print(f'[ERROR] {error}')
        if args.debug: raise
        raise SystemExit(1)
if __name__=='__main__': main()
