"""Thin shim so `python main.py …` keeps working. The real CLI lives in
testgen/cli.py and is also installed as the `testgen` console script."""

import sys

from testgen.cli import main

if __name__ == "__main__":
    sys.exit(main())
