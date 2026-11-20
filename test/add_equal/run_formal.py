#!/usr/bin/env python3
"""对二项加法等式检查器证明所有输入取值，包括输入进位和模运算溢出。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 4, 8, 16, 28, 32, 33, 64)
MITER = """module add_equal_proof #(
    parameter int unsigned p_width = 32
) (
    input logic [p_width-1:0] i_a, i_b, i_target,
    input logic i_carry_in,
    output logic o_equivalent
);
    logic [p_width-1:0] reference_sum;
    logic unused_reference_carry;
    logic candidate_equal;
    add_equal #(.p_width(p_width)) u_compare (
        .i_a(i_a), .i_b(i_b), .i_target(i_target),
        .i_carry_in(i_carry_in), .o_equal(candidate_equal)
    );
    assign {unused_reference_carry, reference_sum} =
        {1'b0, i_a} + {1'b0, i_b} + {{p_width{1'b0}}, i_carry_in};
    assign o_equivalent = (candidate_equal == (reference_sum == i_target));
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/common/add_equal.sv"
    snapshot = out / source.name
    snapshot.write_bytes(source.read_bytes())
    miter = out / "miter.sv"
    miter.write_text(MITER)
    summary = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "miter_sha256": hashlib.sha256(miter.read_bytes()).hexdigest(),
        "method": "Combinational SAT comparison against native unsigned addition",
        "inputs_constrained": False,
        "runs": [],
    }
    for width in WIDTHS:
        script = out / f"width_{width}.ys"
        log = out / f"width_{width}.log"
        script.write_text("read_slang --top add_equal_proof -Gp_width=" + str(width) + " " +
                          shlex.quote(str(snapshot)) + " " + shlex.quote(str(miter)) + "\n" +
                          "prep -top add_equal_proof -flatten\n" +
                          "sat -verify -prove o_equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            process = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                      "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT)
        passed = process.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in log.read_text()
        result = {"width": width, "unconstrained_input_bits": 3 * width + 1,
                  "passed": passed, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        summary["runs"].append(result)
        summary["passed"] = all(run["passed"] for run in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        if not passed:
            raise RuntimeError("Addition equality proof did not complete for width " + str(width))
    assert snapshot.read_bytes() == source.read_bytes()


if __name__ == "__main__":
    main()
