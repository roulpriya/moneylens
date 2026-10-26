#!/usr/bin/env python3
"""Standalone PDF extraction and verified local credential reuse."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == '__main__':
    runpy.run_module('moneylens.pdf_extract', run_name='__main__')
