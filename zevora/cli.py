"""ZEVORA Gateway Controller - the terminal never hosts AI chat."""
import argparse
import asyncio
import json
import sys
import webbrowser
from pathlib import Path

from agent.providers.configuration import PROVIDER_SCHEMA_VERSION, PROTOCOLS, RUNTIMES
from agent.providers.service import ProviderService

from . import __version__
from .banner import banner
from .bootstrap import Bootstrap
from .gateway import restart, start, status, stop

MENU = '''
[1] Start Gateway
[2] Stop Gateway
[3] Restart Gateway
[4] Run in Background
[5] Open Localhost
[6] Exit
'''


def show_status():
    state = status()
    if state['running']:
        print(f"Gateway Status: RUNNING\nPort: {state['port']}\nDashboard: {state['url']}")
    else:
        print('Gateway Status: STOPPED')
    return state


def launch(background=False):
    print('Starting ZEVORA Gateway in background...' if background else 'Starting ZEVORA Gateway...')
    state = start(background=True)
    print('[OK] Agent Core\n[OK] Model Router\n[OK] Memory\n[OK] Cache\n[OK] Experience\n[OK] Provider Registry\n[OK] MCP\n[OK] Web Server')
    print(f"\nGateway Status: RUNNING\nPID: {state['pid']}\nPort: {state['port']}\nDashboard: {state['url']}")


def open_localhost():
    state = status()
    if not state['running']:
        print('ZEVORA Gateway is not running.\n[1] Start Gateway\n[2] Cancel')
        if input('Select: ').strip() != '1':
            return
        state = start()
    print(f"Opening ZEVORA...\n{state['url']}")
    webbrowser.open(state['url'])


def doctor():
    bootstrap = Bootstrap()
    print('ZEVORA Doctor')
    bootstrap.environment()
    bootstrap.quick_check()
    service = ProviderService()
    providers = service.list()
    runtime = service.runtime_availability()
    print('[OK] Gateway controller ready')
    print(f"[INFO] Provider schema: {PROVIDER_SCHEMA_VERSION}")
    print(f"[INFO] Custom providers: {len(providers)}")
    print(f"[INFO] Runtime sandbox: {runtime.get('sandbox', 'unavailable')}")
    for name in sorted(RUNTIMES):
        available = bool(runtime.get(name))
        print(f"[{'OK' if available else 'INFO'}] Runtime {name}: {'available' if available else 'unavailable'}")
    for provider in providers:
        credential = provider.get('credential') or {}
        print(
            f"[INFO] Provider {provider['provider_id']}: state={provider['state']} "
            f"trusted={bool((provider.get('runtime') or {}).get('trusted'))} "
            f"credential={'configured' if credential.get('configured') else 'not configured'}"
        )


def intelligence_status():
    from .commands.status import status as system_status
    print(json.dumps(system_status(), indent=2, sort_keys=True))


def uninstall_local(approved=False):
    from agent.models.manager import LocalIntelligenceManager
    result = LocalIntelligenceManager().uninstall_package(approved=approved)
    print(json.dumps(result, indent=2, sort_keys=True))


def controller():
    print(banner())
    show_status()
    while True:
        print(MENU)
        try:
            selected = input('Select: ').strip()
        except (KeyboardInterrupt, EOFError):
            print('\nGoodbye.')
            return
        try:
            if selected == '1':
                launch()
            elif selected == '2':
                print('Stopping ZEVORA Gateway...')
                print('[OK] Gateway stopped' if stop() else 'Gateway already stopped')
            elif selected == '3':
                print('Restarting ZEVORA Gateway...')
                state = restart()
                print(f"[OK] Gateway restarted\nDashboard: {state['url']}")
            elif selected == '4':
                launch(background=True)
            elif selected == '5':
                open_localhost()
            elif selected == '6':
                print('Goodbye. Gateway remains running if started in background.')
                return
            else:
                print('Select a number from 1 to 6.')
        except RuntimeError as error:
            print(f'Gateway error: {error}')


def _provider_parser():
    parser = argparse.ArgumentParser(prog='zevora provider', description='Manage universal AI providers.')
    commands = parser.add_subparsers(dest='provider_command', required=True)
    commands.add_parser('list', help='List secret-free provider summaries.')

    add = commands.add_parser('add', help='Add a provider from explicit options.')
    add.add_argument('--id', required=True, dest='provider_id')
    add.add_argument('--name', required=True)
    add.add_argument('--protocol', required=True, choices=sorted(PROTOCOLS))
    add.add_argument('--base-url', default='')
    add.add_argument('--model', default='', dest='default_model')
    add.add_argument('--credential-env', default='')
    add.add_argument('--runtime', choices=sorted(RUNTIMES))
    add.add_argument('--script', type=Path)
    add.add_argument('--disabled', action='store_true')

    for command in ('test', 'remove', 'runtime-test'):
        item = commands.add_parser(command)
        item.add_argument('provider_id')
        if command == 'runtime-test':
            item.add_argument('--approve', action='store_true')

    imported = commands.add_parser('import', help='Import a secret-free provider manifest.')
    imported.add_argument('manifest', type=Path)
    imported.add_argument('--script', type=Path)

    exported = commands.add_parser('export', help='Export a secret-free provider manifest.')
    exported.add_argument('provider_id')
    exported.add_argument('--output', type=Path)
    return parser


def _read_text(path: Path | None) -> str | None:
    return path.read_text(encoding='utf-8') if path else None


def _provider_command(argv):
    parser = _provider_parser()
    args = parser.parse_args(argv)
    service = ProviderService()
    command = args.provider_command
    if command == 'list':
        result = service.list()
    elif command == 'add':
        if args.protocol == 'custom-runtime' and (not args.runtime or not args.script):
            parser.error('custom-runtime requires --runtime and --script')
        if args.protocol != 'custom-runtime' and (args.runtime or args.script):
            parser.error('--runtime and --script are only valid for custom-runtime')
        runtime = None
        if args.runtime:
            runtime = {
                'runtime': args.runtime,
                'entrypoint': args.script.name,
                'trusted': False,
            }
        payload = {
            'provider_id': args.provider_id,
            'name': args.name,
            'protocol': args.protocol,
            'base_url': args.base_url,
            'default_model': args.default_model,
            'credential': {'source': 'environment', 'name': args.credential_env},
            'enabled': not args.disabled,
            'runtime': runtime,
        }
        result = service.save(payload, script=_read_text(args.script))
    elif command == 'import':
        payload = json.loads(args.manifest.read_text(encoding='utf-8'))
        result = service.import_manifest(payload, script=_read_text(args.script))
    elif command == 'export':
        result = service.export_manifest(args.provider_id)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            result = {'provider': args.provider_id, 'output': str(args.output), 'secret_free': True}
    elif command == 'remove':
        result = {'provider': args.provider_id, 'removed': service.remove(args.provider_id)}
    elif command == 'runtime-test':
        if not args.approve:
            parser.error('runtime-test requires --approve')
        result = asyncio.run(service.test(args.provider_id, runtime_approved=True))
    else:
        result = asyncio.run(service.test(args.provider_id))
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def _controller_parser():
    parser = argparse.ArgumentParser(add_help=False, prog='zevora')
    parser.add_argument('command', nargs='?')
    parser.add_argument('target', nargs='?')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--approve', action='store_true')
    return parser


def main(argv=None):
    # Cheap/idempotent first-run preparation; dependency installation stays in bootstrap.py.
    Bootstrap(quiet=True).quick_check()
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments and arguments[0] == 'provider':
        return _provider_command(arguments[1:])
    parser = _controller_parser()
    args = parser.parse_args(arguments)
    if args.target and args.target != 'gateway':
        parser.error('Only the gateway target is supported')
    commands = {
        'start': lambda: launch(),
        'stop': lambda: print('[OK] Gateway stopped' if stop() else 'Gateway already stopped'),
        'restart': lambda: print(restart()),
        'background': lambda: launch(True),
        'open': open_localhost,
        'status': show_status,
        'doctor': doctor,
        'intelligence': intelligence_status,
        'uninstall-local': lambda: uninstall_local(args.approve),
        'update': lambda: print('Verified component updates require a configured HTTPS manifest and SHA-256 hashes.'),
        'version': lambda: print(f'ZEVORA\nZero-External Vendor Oriented Reasoning Agent\n\nVersion: {__version__}'),
        'help': lambda: print(
            'zevora [start|stop|restart|background|open|status|doctor|intelligence|'
            'uninstall-local [--approve]|update|version|help]\n'
            'zevora provider [list|add|test|remove|import|export|runtime-test]'
        ),
    }
    if args.command is None:
        return controller()
    try:
        return commands[args.command]()
    except KeyError:
        parser.error(f'Unknown controller command: {args.command}')

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
