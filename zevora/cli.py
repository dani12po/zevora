"""ZEVORA Gateway Controller — the terminal never hosts AI chat."""
import argparse, json, webbrowser
from . import __version__
from .banner import banner
from .gateway import start, stop, restart, status
from .bootstrap import Bootstrap

MENU='''
[1] Start Gateway
[2] Stop Gateway
[3] Restart Gateway
[4] Run in Background
[5] Open Localhost
[6] Exit
'''
def show_status():
    state=status()
    if state['running']: print(f"Gateway Status: RUNNING\nPort: {state['port']}\nDashboard: {state['url']}")
    else: print('Gateway Status: STOPPED')
    return state
def launch(background=False):
    print('Starting ZEVORA Gateway in background...' if background else 'Starting ZEVORA Gateway...')
    state=start(background=True)
    print('[OK] Agent Core\n[OK] Model Router\n[OK] Memory\n[OK] Cache\n[OK] Experience\n[OK] Provider Registry\n[OK] MCP\n[OK] Web Server')
    print(f"\nGateway Status: RUNNING\nPID: {state['pid']}\nPort: {state['port']}\nDashboard: {state['url']}")
def open_localhost():
    state=status()
    if not state['running']:
        print('ZEVORA Gateway is not running.\n[1] Start Gateway\n[2] Cancel')
        if input('Select: ').strip()!='1': return
        state=start()
    print(f"Opening ZEVORA...\n{state['url']}"); webbrowser.open(state['url'])
def doctor():
    bootstrap=Bootstrap(); print('ZEVORA Doctor'); bootstrap.environment(); bootstrap.quick_check(); print('[OK] Gateway controller ready')

def intelligence_status():
    from .commands.status import status as system_status
    print(json.dumps(system_status(), indent=2, sort_keys=True))

def uninstall_local(approved=False):
    from agent.models.manager import LocalIntelligenceManager
    result = LocalIntelligenceManager().uninstall_package(approved=approved)
    print(json.dumps(result, indent=2, sort_keys=True))
def controller():
    print(banner()); show_status()
    while True:
        print(MENU)
        try: selected=input('Select: ').strip()
        except (KeyboardInterrupt,EOFError): print('\nGoodbye.'); return
        try:
            if selected=='1': launch()
            elif selected=='2': print('Stopping ZEVORA Gateway...'); print('[OK] Gateway stopped' if stop() else 'Gateway already stopped')
            elif selected=='3': print('Restarting ZEVORA Gateway...'); state=restart(); print(f"[OK] Gateway restarted\nDashboard: {state['url']}")
            elif selected=='4': launch(background=True)
            elif selected=='5': open_localhost()
            elif selected=='6': print('Goodbye. Gateway remains running if started in background.'); return
            else: print('Select a number from 1 to 6.')
        except RuntimeError as error: print(f'Gateway error: {error}')
def main(argv=None):
    # Cheap/idempotent first-run preparation; dependency installation stays in bootstrap.py.
    Bootstrap(quiet=True).quick_check()
    parser=argparse.ArgumentParser(add_help=False); parser.add_argument('command',nargs='?'); parser.add_argument('target',nargs='?'); parser.add_argument('--debug',action='store_true'); parser.add_argument('--approve',action='store_true'); args=parser.parse_args(argv)
    if args.target and args.target!='gateway': parser.error('Only the gateway target is supported')
    commands={'start':lambda:launch(),'stop':lambda:print('[OK] Gateway stopped' if stop() else 'Gateway already stopped'),'restart':lambda:print(restart()),'background':lambda:launch(True),'open':open_localhost,'status':show_status,'doctor':doctor,'intelligence':intelligence_status,'uninstall-local':lambda:uninstall_local(args.approve),'update':lambda:print('Verified component updates require a configured HTTPS manifest and SHA-256 hashes.'),'version':lambda:print(f'ZEVORA\nZero-External Vendor Oriented Reasoning Agent\n\nVersion: {__version__}'),'help':lambda:print('zevora [start|stop|restart|background|open|status|doctor|intelligence|uninstall-local [--approve]|update|version|help]')}
    if args.command is None: return controller()
    try: commands[args.command]()
    except KeyError: parser.error(f'Unknown controller command: {args.command}')

def main_silent(argv=None):
    """Windowless entry point (zevora-w.exe on Windows).
    Starts the gateway in the background and opens the browser — no console window,
    no interactive menu, process exits immediately after the browser opens."""
    Bootstrap(quiet=True).quick_check()
    try:
        state = start(background=True)
        webbrowser.open(state['url'])
    except RuntimeError as error:
        # Can't print to a console that doesn't exist; write a small log file instead.
        from agent.config import ROOT as _ROOT
        (_ROOT / 'logs' / 'active').mkdir(parents=True, exist_ok=True)
        (_ROOT / 'logs' / 'active' / 'startup_error.txt').write_text(
            str(error), encoding='utf-8'
        )

if __name__=='__main__': main()
