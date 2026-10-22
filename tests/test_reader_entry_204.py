"""204 (R1a): importing the reader process's entry module leaves the importing process's import path alone.

The worker's start-up preload imports every module, this one too; its path set-up belongs to the reader process only.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_importing_the_reader_entry_keeps_the_import_path():
    code = ("import sys; sys.argv = ['worker', 'elsewhere']; before = list(sys.path); "
            "import jav.readers.worker; print(sys.path == before)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert done.stdout.strip() == "True"
