#!/usr/bin/env python3
"""执行 AXI 双项缓冲的完整状态归纳证明和四态比较。"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    arguments = sys.argv[1:]
    if not any(value == "--out" or value.startswith("--out=") for value in arguments):
        arguments += ["--out", str(ROOT / "build/soc_pingpong")]
    subprocess.run([sys.executable, str(ROOT / "test/axi_occupancy/run.py"), *arguments],
                   cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
