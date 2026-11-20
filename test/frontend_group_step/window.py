#!/usr/bin/env python3
"""复用同源参考 FPGA 模型，比较实际窗口事务与逐周期记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rtl_hashes(report):
    return {"rtl/" + path.rsplit("/rtl/", 1)[1]: value
            for path, value in report["source_sha256"].items() if "/rtl/" in path}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-model", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator-modern")
    args = parser.parse_args()
    reference_dir, out = args.reference_model.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = json.loads(args.proof.read_text())
    reference = json.loads((reference_dir / "summary.json").read_text())
    if not proof["passed"] or not reference["passed"] or not reference["fpga"]:
        raise RuntimeError("A proved candidate and completed FPGA reference are required")
    if rtl_hashes(reference)[SOURCE] != proof["reference_sha256"]:
        raise RuntimeError("The reference model uses a different frontend")
    for path, expected in reference["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise RuntimeError("Reference source changed: " + path)
    with (out / "driver.log").open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "test/window_dma/run.py"),
            "--out", str(out), "--verilator", args.verilator, "--jobs", "1", "--fpga"],
            cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    current = json.loads((out / "summary.json").read_text())
    expected, actual = rtl_hashes(reference), rtl_hashes(current)
    if actual[SOURCE] != proof["source_sha256"]:
        raise RuntimeError("The current model differs from the formal proof")
    if {name for name, value in actual.items() if expected.get(name) != value} != {SOURCE}:
        raise RuntimeError("The models differ in additional RTL")
    if current["tests"] != reference["tests"]:
        raise RuntimeError("Window transaction statistics differ")
    if (out / "resident_stream.csv").read_bytes() != (reference_dir / "resident_stream.csv").read_bytes():
        raise RuntimeError("Window cycle records differ")
    reference_link = out / "reference"
    if not reference_link.exists():
        reference_link.symlink_to(reference_dir, target_is_directory=True)
    if reference_link.resolve() != reference_dir:
        raise RuntimeError("Reference model directory differs")
    current.update(reference=reference, reference_ref=proof["reference_commit"],
        reference_model=str(reference_dir), reference_model_sha256=digest(reference_dir / "summary.json"),
        resident_stream_cycle_equivalent=True)
    (out / "summary.json").write_text(json.dumps(current, indent=2) + "\n")
    print("WINDOW_GROUP_STEP_PASS cycles=" + str(current["resident_stream_cycles"]), flush=True)


if __name__ == "__main__":
    main()
