#!/usr/bin/env python3
"""逐周期比较写入队列的通用模式和字节合并模式。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path("rtl/npu/conv/vector_writeback.sv")
CASES = [(1, 32, 1), (3, 64, 1), (15, 64, 0), (15, 64, 1),
         (16, 32, 0), (16, 64, 0), (16, 128, 0),
         (16, 32, 1), (16, 64, 1), (16, 128, 1), (32, 64, 1)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        result = subprocess.run([str(value) for value in command], cwd=ROOT,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--reference", default="4dee27ffec4dc891daf2681379f8b3fd27fd41f2")
    parser.add_argument("--out", type=Path, default=ROOT / "build/vector_writeback_equivalence")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_text = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"],
                                             cwd=ROOT, text=True)
    reference = out / "reference.sv"
    reference.write_text(reference_text.replace("module vector_writeback #(",
                                                "module vector_writeback_reference #("))
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in [ROOT / SOURCE, HERE / "miter.sv", HERE / "run.py"]}
    results = []
    for tile, bus, mode in CASES:
        folder = out / f"t{tile}_b{bus}_m{mode}"
        folder.mkdir(exist_ok=True)
        run([args.verilator, "--binary", "--timing", "--assert", "-j", args.jobs,
             "--top-module", "miter", "-Wno-fatal", f"-GTILE={tile}", f"-GBUS_WIDTH={bus}",
             f"-GBYTE_ONLY={mode}", "--Mdir", folder / "obj", HERE / "miter.sv",
             ROOT / SOURCE, reference], folder / "build.log")
        run([folder / "obj/Vmiter"], folder / "run.log")
        text = (folder / "run.log").read_text()
        match = re.search(r"WRITEBACK_EQUIVALENCE_PASS (.+)", text)
        if not match:
            raise RuntimeError("逐周期比较未完成")
        result = {key: int(value) for key, value in
                  (item.split("=") for item in match.group(1).split())}
        result.update(passed=True, log_sha256=digest(folder / "run.log"))
        results.append(result)
        print(match.group(0), flush=True)
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError("构建期间源文件发生变化")
    report = dict(passed=True, reference=args.reference,
                  reference_sha256=hashlib.sha256(reference_text.encode()).hexdigest(),
                  source_sha256=hashes, runs=results)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
