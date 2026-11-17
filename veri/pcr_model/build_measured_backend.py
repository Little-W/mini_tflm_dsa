#!/usr/bin/env python3
"""Build the shared GEMM backend with the streaming compressed PS store."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    sys.argv = [str(ROOT / "veri/python_model/build_backend.py"), "--ps-compress", *sys.argv[1:]]
    if not any(arg == "--output-root" or arg.startswith("--output-root=") for arg in sys.argv):
        sys.argv += ["--output-root", str(ROOT / "build/pcr_model")]
    runpy.run_path(sys.argv[0], run_name="__main__")
