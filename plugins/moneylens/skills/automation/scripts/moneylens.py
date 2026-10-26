#!/usr/bin/env python3
"""MoneyLens command interface; works from any current directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moneylens.app import run

if __name__ == '__main__':
    sys.exit(run())
