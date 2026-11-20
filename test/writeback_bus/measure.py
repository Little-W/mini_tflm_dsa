#!/usr/bin/env python3
"""在相同参数下综合 S8 输出 FIFO，记录逻辑资源与组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/vec_s8_to_fifo.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="3f2e612")
    parser.add_argument("--size", type=int, default=16)
    parser.add_argument("--bus-width", type=int, default=64)
    parser.add_argument("--banks", type=int, default=32)
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_bytes()
    reference = subprocess.check_output(
        ["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT)
    cases = {}
    for name, content in (("reference", reference), ("current", current)):
        source = out / f"{name}.sv"
        source.write_bytes(content)
        cases[name] = {
            "top": "vec_s8_to_fifo_full",
            "sources": [str(source), "rtl/common/REGFILE.v"],
            "options": [f"-GVLEN={args.size}", f"-GBANKS={args.banks}",
                        f"-GBUS_WIDTH={args.bus_width}", "-GENABLE_TRANSPOSE=1"],
            "configuration": f"SIZE={args.size}, BUS_WIDTH={args.bus_width}, BANKS={args.banks}",
        }
    config = out / "cases.json"
    config.write_text(json.dumps(cases, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--case-config", str(config), "--cases", "reference", "current",
               "--out", str(out / "results")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    if args.resume:
        command += ["--resume"]
    subprocess.run(command, cwd=ROOT, check=True)
    if current != (ROOT / SOURCE).read_bytes():
        raise RuntimeError("RTL changed during synthesis")
    manifest = {"reference": args.reference,
                "source_sha256": hashlib.sha256(current).hexdigest(),
                "reference_sha256": hashlib.sha256(reference).hexdigest(),
                "results": str(out / "results/summary.json")}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
