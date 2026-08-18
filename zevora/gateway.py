"""Lifecycle controller for the local ZEVORA web gateway."""
import json, os, secrets, socket, subprocess, sys, time
import psutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from agent.config import ROOT

RUNTIME=ROOT/'data'/'runtime'; META=RUNTIME/'gateway.json'; TOKEN=RUNTIME/'gateway.token'
HOST='127.0.0.1'; DEFAULT_PORT=7432

def url(port): return f'http://{HOST}:{port}'
def _port(start=DEFAULT_PORT):
    for port in range(start,start+100):
        with socket.socket() as sock:
            if sock.connect_ex((HOST,port)) != 0: return port
    raise RuntimeError('No free ZEVORA gateway port found')
def _metadata():
    try: return json.loads(META.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return {}
def _health(port):
    try:
        with urlopen(f'{url(port)}/health',timeout=1) as response:
            return response.status==200 and json.loads(response.read()).get('service')=='zevora'
    except (URLError,TimeoutError,OSError,json.JSONDecodeError): return False
def status():
    data=_metadata(); port=data.get('port')
    if port and _health(port): return {'running':True,**data,'url':url(port)}
    return {'running':False,'port':None}
def _write(pid,port):
    RUNTIME.mkdir(parents=True,exist_ok=True)
    META.write_text(json.dumps({'pid':pid,'host':HOST,'port':port,'started_at':datetime.now(timezone.utc).isoformat(),'status':'running'}),encoding='utf-8')
def _listener_pid(port):
    try:
        for connection in psutil.net_connections(kind='tcp'):
            if connection.laddr and connection.laddr.ip == HOST and connection.laddr.port == port and connection.pid:
                return connection.pid
    except (psutil.Error, OSError): pass
    return None
def start(background=True):
    current=status()
    if current['running']: return current
    # Re-adopt the canonical gateway if metadata was deleted or corrupted.
    if _health(DEFAULT_PORT):
        _write(_listener_pid(DEFAULT_PORT),DEFAULT_PORT)
        return status()
    port=_port()
    shutdown_token=secrets.token_urlsafe(32)
    # Redirect stderr to a log file so startup errors are diagnosable.
    RUNTIME.mkdir(parents=True,exist_ok=True)
    TOKEN.write_text(shutdown_token,encoding='utf-8')
    stderr_log = open(RUNTIME/'startup.log','w',encoding='utf-8')
    # On Windows, suppress the console window for the uvicorn subprocess unconditionally.
    if os.name=='nt':
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP |
                 subprocess.DETACHED_PROCESS |
                 subprocess.CREATE_NO_WINDOW)
        extra: dict = {}
    else:
        si = None; flags = 0; extra = {'start_new_session': True}
    child_env={**os.environ,'ZEVORA_SHUTDOWN_TOKEN':shutdown_token}
    process = None
    try:
        process=subprocess.Popen(
            [sys.executable,'-m','uvicorn','main:app','--host',HOST,'--port',str(port)],
            cwd=ROOT, env=child_env,
            stdin=subprocess.DEVNULL, stdout=stderr_log, stderr=stderr_log,
            creationflags=flags, startupinfo=si, **extra
        )
        # 45 iterations x 0.5s = up to 22.5s; covers slow provider-discovery startup.
        for _ in range(45):
            time.sleep(.5)
            if _health(port):
                stderr_log.close()
                # Windows virtual-environment launchers may spawn the interpreter
                # that owns the socket, so persist the listener rather than its parent.
                _write(_listener_pid(port) or process.pid,port)
                return status()
            if process.poll() is not None:
                # Process died; surface the log so the caller can report it.
                stderr_log.close()
                log = (RUNTIME/'startup.log').read_text(encoding='utf-8',errors='replace')[-2000:]
                raise RuntimeError(f'Gateway process exited before health check passed.\n{log}')
        stderr_log.close(); process.terminate()
        raise RuntimeError('Gateway did not pass its health check within 22 s')
    except Exception:
        if not stderr_log.closed:
            stderr_log.close()
        if process is not None and process.poll() is None:
            process.terminate()
        TOKEN.unlink(missing_ok=True)
        raise
def stop(timeout=10):
    current=status()
    if not current['running']:
        META.unlink(missing_ok=True); TOKEN.unlink(missing_ok=True); return False
    try:
        token=TOKEN.read_text(encoding='utf-8').strip()
        request=Request(
            f"{current['url']}/shutdown",method='POST',
            headers={'X-ZEVORA-Shutdown-Token':token},
        )
        urlopen(request,timeout=2).read()
    except (URLError,TimeoutError,OSError): pass
    for _ in range(timeout*2):
        if not _health(current['port']):
            META.unlink(missing_ok=True); TOKEN.unlink(missing_ok=True); return True
        time.sleep(.5)
    # Metadata can contain a virtual-environment launcher PID. Resolve the
    # current socket owner before the forced fallback so no serving child remains.
    target_pid=_listener_pid(current['port']) or current.get('pid')
    try:
        if target_pid: os.kill(int(target_pid),9 if os.name!='nt' else 15)
    except OSError: pass
    META.unlink(missing_ok=True); TOKEN.unlink(missing_ok=True); return True
def restart(): stop(); return start()
