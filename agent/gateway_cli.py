import argparse, asyncio
from .config import ROOT
from .models.registry import ModelRegistry
from .providers.discovery import ProviderDiscovery
from .routing.task_classifier import TaskClassifier
from .routing.model_selector import ModelSelector

async def run(args):
    registry=ModelRegistry(ROOT/'data'/'database'/'model_registry.db'); discovery=ProviderDiscovery(registry)
    if args.command=='providers':
        for item in await discovery.providers(): print(f"{item['provider']:10} {item['health_status'].upper()}")
    elif args.command=='models':
        if args.action=='refresh': print(await discovery.refresh(args.provider))
        else:
            for item in registry.list(args.provider): print(f"{item['provider']:10} {item['model_id']:35} {','.join(item['capabilities']) or 'unknown':20} {item['health_status']}")
    elif args.command=='route':
        task=TaskClassifier().classify(args.prompt); choice=ModelSelector().select(registry.list(),task.required_capabilities)
        print({'task':task.labels,'required_capabilities':task.required_capabilities,'selection':choice.__dict__ if choice else None})
def main():
    parser=argparse.ArgumentParser(prog='hybrid-agent'); sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('providers'); models=sub.add_parser('models'); models.add_argument('action',choices=['list','refresh'],nargs='?',default='list'); models.add_argument('--provider'); route=sub.add_parser('route'); route.add_argument('prompt')
    asyncio.run(run(parser.parse_args()))
if __name__=='__main__': main()
