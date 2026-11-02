"""Portable fallback launcher for a cloned repository."""
import subprocess, sys
from pathlib import Path
from zevora.bootstrap import Bootstrap, ROOT
bootstrap=Bootstrap(); bootstrap.quick_check()
if not bootstrap.python.exists():
    subprocess.run([sys.executable,str(ROOT/'bootstrap.py')],check=True)
raise SystemExit(subprocess.call([str(bootstrap.python),'-m','zevora',*sys.argv[1:]],cwd=ROOT))
