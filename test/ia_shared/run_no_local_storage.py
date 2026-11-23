#!/usr/bin/env python3
"""检查完整 NPU 在共享 IA 存储不可用时的错误完成与 DMA 抑制。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/rtl"))
from source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = with_dependencies([root / "rtl/npu/top/npu_top.sv",
        Path(__file__).with_name("tb_no_local_storage.sv")], root)
    tracked = input_files([*sources, Path(__file__).resolve(), ROOT / "scripts/rtl/source_files.py"], root)
    hashes = {str(path): digest(path) for path in tracked}
    command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
        "--top-module", "tb_no_local_storage", "--output-groups", "0",
        "--output-split", "10000", "--output-split-cfuncs", "1000",
        "-DGEMPACT_PS_COMPRESS=1", "-DGEMMORA_PS_POOL_BYTES=49152", "-DGEMMORA_PS_FORCE_RAW=1",
        "-I" + str(root / "include"), "-I" + str(root / "rtl/npu/ps_compact"),
        "--Mdir", str(out / "obj"), "-j", str(args.jobs),
        "-CFLAGS", "-std=c++20 -O0", "-MAKEFLAGS", "OPT_FAST=-O0 OPT_SLOW=-O0", *map(str, sources)]
    with (out / "compile.log").open("w") as stream:
        subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=1800, check=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Build inputs changed during compilation")
    binary = out / "obj/Vtb_no_local_storage"
    result = subprocess.run([str(binary)], cwd=out, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=120)
    (out / "run.log").write_text(result.stdout)
    match = re.search(r"NO_LOCAL_STORAGE_PASS tasks=(\d+) cycles=(\d+)", result.stdout)
    if result.returncode or match is None or int(match[1]) != 8:
        raise RuntimeError("Shared storage configuration check failed: " + result.stdout[-3000:])
    summary = dict(passed=True, tasks=int(match[1]), checked_cycles=int(match[2]),
        source_sha256=hashes, binary_sha256=digest(binary), compile_command=command,
        sources_unchanged=True, axi_transactions=0, dma_initializations=0)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ("source_sha256", "compile_command")}))


if __name__ == "__main__":
    main()
