#!/usr/bin/env python3
"""比较写回控制及部分和存储的完整公开输出和共同状态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source, read_current_source as read_rtl_text

CASES = {
    "oa_n4_b32": ("oa_writer", "rtl/npu/writeback/oa_writer.sv",
                    dict(VLEN=4, BUS_WIDTH=32, COUNT_WIDTH=8)),
    "oa_n16_b32": ("oa_writer", "rtl/npu/writeback/oa_writer.sv",
                     dict(VLEN=16, BUS_WIDTH=32, COUNT_WIDTH=29)),
    "oa_n16_b64": ("oa_writer", "rtl/npu/writeback/oa_writer.sv",
                     dict(VLEN=16, BUS_WIDTH=64, COUNT_WIDTH=29)),
    "oa_n32_b128": ("oa_writer", "rtl/npu/writeback/oa_writer.sv",
                      dict(VLEN=32, BUS_WIDTH=128, COUNT_WIDTH=32)),
    "ps_internal": ("ps_frame_store", "rtl/npu/ps_compact/ps_frame_store.sv",
                      dict(MAX_FRAME_ROWS=47, FRAME_COUNT=16, POOL_BYTES=4096,
                           BANK_BYTES=2048, EXTERNAL_RAM=0)),
    "ps_external": ("ps_frame_store", "rtl/npu/ps_compact/ps_frame_store.sv",
                      dict(MAX_FRAME_ROWS=512, FRAME_COUNT=16, POOL_BYTES=57344,
                           BANK_BYTES=8192, EXTERNAL_RAM=1, p_fixed_ps_channels=1)),
    "ps_rotating": ("ps_frame_store", "rtl/npu/ps_compact/ps_frame_store.sv",
                      dict(MAX_FRAME_ROWS=16, FRAME_COUNT=4, POOL_BYTES=14336,
                           BANK_BYTES=2048, EXTERNAL_RAM=1, p_fixed_ps_channels=0)),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="ef0dc75342997721bdc4110b2841445df962018e")
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    common = sorted(path for path in (source_root / "rtl/common").iterdir()
                    if path.suffix in (".sv", ".v"))
    report = dict(reference=args.reference, input_value_constraints=None,
                  all_public_outputs_compared_each_cycle=True, runs=[])
    for name in args.cases:
        top, relative, parameters = CASES[name]
        folder = output / name
        folder.mkdir(exist_ok=True)
        current_path = source_root / relative
        hashes = {str(path.relative_to(source_root)): digest(path)
                  for path in [current_path, *common]}
        original = ((args.reference_root / relative).read_bytes() if args.reference_root else
                    read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT))
        reference_path = folder / "reference.sv"
        reference_path.write_bytes(original)
        commands = []
        for label, path in (("reference", reference_path), ("current", current_path)):
            import runpy
            resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
            compilation_files = resolver([path, *common], source_root)
            arguments = ["read_slang", "--top", top,
                         *[f"-G{key}={value}" for key, value in parameters.items()],
                         *map(str, compilation_files)]
            commands += [" ".join(map(shlex.quote, arguments)),
                         f"prep -top {top} -flatten", "async2sync", "opt_clean",
                         f"rename {top} {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2",
                     "equiv_status -assert"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        log = folder / "formal.log"
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                 "--worker", str(script)], cwd=ROOT, stdout=stream,
                stderr=subprocess.STDOUT, timeout=480)
        text = read_rtl_text(log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        passed = result.returncode == 0 and "Equivalence successfully proven" in text
        row = dict(case=name, top=top, parameters=parameters, passed=passed,
                   equivalent_bits=int(match[1]) if match else None,
                   source_sha256=hashes,
                   reference_sha256=hashlib.sha256(original).hexdigest(),
                   script_sha256=digest(script), log_sha256=digest(log))
        report["runs"].append(row)
        if hashes != {str(path.relative_to(source_root)): digest(path)
                      for path in [current_path, *common]}:
            raise RuntimeError("RTL changed during verification")
        report["passed"] = all(item["passed"] for item in report["runs"])
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: row[key] for key in ("case", "passed", "equivalent_bits")}), flush=True)
        if not passed:
            raise RuntimeError(f"Module equivalence did not complete: {log}")


if __name__ == "__main__":
    main()
