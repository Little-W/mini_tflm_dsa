#!/usr/bin/env python3
"""测量实际四项窗口队列的寄存器、存储与反馈组合深度。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/dma/conv_window_queue.sv"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="b20921b3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    snapshot = out / "reference_queue.sv"
    snapshot.write_bytes(reference)
    cases = {}
    for label, source in (("reference", snapshot.relative_to(ROOT)), ("current", SOURCE)):
        cases[label] = dict(top="conv_window_queue",
            options=["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1", "-GDEPTH=4", "-GTAG_W=2", "-GCOL_W=4"],
            sources=[str(source)], configuration="4 entries, 2-bit tags, 16 output columns")
    config = out / "cases.json"
    config.write_text(json.dumps(cases, indent=2) + "\n")
    with (out / "driver.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
            "--source-root", str(ROOT), "--out", str(out / "native"), "--case-config", str(config),
            "--cases", "reference", "current", "--lock-file", str(args.lock_file)],
            cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if (ROOT / SOURCE).read_bytes() != current:
        raise RuntimeError("Queue source changed during mapping")
    measurements = {}
    for label in cases:
        path = out / "native" / label / "metrics.json"
        data = json.loads(path.read_text())
        measurements[label] = dict(metrics=data, metrics_sha256=digest(path.read_bytes()))
        print(label, data["resources"]["logic_lut_cells"], data["resources"]["flip_flops"],
            data["paths"]["longest_register_path_cells"], flush=True)
    report = dict(passed=True, reference_commit=subprocess.check_output(
        ["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current), reference_sha256=digest(reference),
        configuration=dict(DEPTH=4, TAG_W=2, COL_W=4, p_max_cols=16), cases=measurements)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
