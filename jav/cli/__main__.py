"""`python -m jav.cli <command>` (208, plan G-process-core R2: the command line is a package; its entry point is
`jav.cli.main`). Guarded, because the start-up preload imports every module (`jav/runtime/preload.py`)."""

import sys

from jav.cli import main

if __name__ == "__main__":
    sys.exit(main())
