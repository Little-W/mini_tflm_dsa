#!/usr/bin/env python3
"""读取预测器实际源码，证明配置取整加法对全部输入保持相同结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_next_use_predictor.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="626902ef")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    start = current.index("  logic [32:0] cfg_block_round;")
    end = current.index("  assign cfg_r_shift =", start)
    arithmetic = current[start:end]
    original = re.search(r"  wire \[32:0\] cfg_block_round = .*?;", reference)[0]
    normalized = current.replace(arithmetic, original + "\n", 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside the configuration round expression require verification")
    proof = out / "block_round.sv"
    proof.write_text("""module block_round_proof(
    input logic [31:0] cfg_points_q, block_rows_q,
    output logic equivalent
);
""" + arithmetic + original.replace("cfg_block_round", "reference_round") +
        "\n  assign equivalent=cfg_block_round==reference_round;\nendmodule\n")
    script, log_path = out / "run.ys", out / "formal.log"
    script.write_text("read_slang --top block_round_proof " + shlex.quote(str(proof)) +
        "\nprep -top block_round_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
        raise RuntimeError("Configuration round comparison incomplete")
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_block_round=True, actual_source_expressions=True,
        input_bits=64, result_bits=33, inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()), script_sha256=digest(script.read_bytes()),
        log_sha256=digest(log_path.read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
