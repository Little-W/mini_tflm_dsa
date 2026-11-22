#!/usr/bin/env python3
"""证明待发请求资格在复位和每次状态更新后的精确关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = Path("rtl/npu/loaders/kernel_loader_ctrl.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--profiles", nargs="+", default=("16:32:29", "1:8:1", "4:16:16", "16:32:33"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / RTL
    source_hash = digest(source)
    text = source.read_text()
    marker = "    output logic [REG_WIDTH-1:0]        repeat_dbg\n"
    assert text.count(marker) == 1
    text = text.replace(marker, marker.rstrip() + ",\n    output logic formal_pending_ok\n", 1)
    marker = "  logic                 all_loads_issued;"
    assert text.count(marker) == 1
    text = text.replace(marker, marker + "\n  assign formal_pending_ok = "
                        "load_pending_q == ((state == S_RUN) && !all_loads_issued);", 1)
    instrumented = out / "controller.sv"
    instrumented.write_text(text)
    common = sorted(path for path in (args.source_root / "rtl/common").glob("*")
                    if path.suffix in (".sv", ".v"))
    profiles = []
    for profile in args.profiles:
        size, width, count = map(int, profile.split(":"))
        folder = out / profile.replace(":", "_")
        folder.mkdir(exist_ok=True)
        commands = [f"read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 -GSIZE={size} "
                    f"-GREG_WIDTH={width} -GCOUNT_WIDTH={count} --top kernel_loader_ctrl " +
                    shlex.join(map(str, [instrumented, *common])),
                    "prep -top kernel_loader_ctrl -flatten", "async2sync", "opt_clean",
                    "sat -verify -seq 1 -set rst_n 0 -prove formal_pending_ok 1",
                    "sat -verify -tempinduct -tempinduct-inductonly -seq 1 -maxsteps 1 "
                    "-timeout 40 -prove formal_pending_ok 1"]
        script, log = folder / "prove.ys", folder / "proof.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=100)
        profiles.append(dict(SIZE=size, REG_WIDTH=width, COUNT_WIDTH=count, passed=True,
                             log_sha256=digest(log)))
    if source_hash != digest(source):
        raise RuntimeError("验证期间源文件发生变化")
    report = dict(passed=True, source_sha256=source_hash, profiles=profiles,
                  external_inputs_constrained=False,
                  dependency_sha256={str(path): digest(path) for path in common})
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
