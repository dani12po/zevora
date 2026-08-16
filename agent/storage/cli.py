import argparse
from pathlib import Path
from .cleanup import CleanupManager
from ..config import ROOT

def main():
    parser=argparse.ArgumentParser(description='ZEVORA lifecycle maintenance')
    sub=parser.add_subparsers(dest='command',required=True); clean=sub.add_parser('cleanup'); clean.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.command=='cleanup': print(CleanupManager(ROOT).run(dry_run=args.dry_run))
if __name__=='__main__': main()
