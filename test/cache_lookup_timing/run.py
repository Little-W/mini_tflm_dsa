#!/usr/bin/env python3
"""对全部输入证明缓存快照匹配与工作请求握手保持相同组合结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_read_cache.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def assignment(source, name):
    matches = re.findall(r"  assign " + name + r"\s*=.*?;", source, re.S)
    if len(matches) != 1:
        raise RuntimeError("Unexpected assignment count: " + name)
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="af11d787")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    start = current.index("  // 两种请求分别匹配已有快照，队首出队直接使用工作请求的匹配结果。")
    end = current.index(";", current.index("  assign lookup_ready =", start)) + 1
    comparison = current[start:end]
    normalized = current.replace("  logic work_lookup_ready, demand_lookup_ready;\n", "", 1)
    normalized = normalized.replace(comparison, assignment(reference, "lookup_ready"), 1)
    normalized = normalized.replace(assignment(current, "work_ready"), assignment(reference, "work_ready"), 1)
    if normalized != reference:
        raise RuntimeError("Additional cache changes require verification")
    common = "\n".join(assignment(current, name) for name in ("lookup_addr", "lookup_set"))
    for name in ("lookup_addr", "lookup_set"):
        if assignment(current, name) != assignment(reference, name):
            raise RuntimeError("Lookup address selection changed")
    proof = out / "lookup.sv"
    current_logic = comparison + "\n" + assignment(current, "work_ready")
    reference_logic = assignment(reference, "lookup_ready") + "\n" + assignment(reference, "work_ready")
    for name in ("work_ready", "lookup_ready"):
        current_logic = re.sub(r"\b" + name + r"\b", "current_" + name, current_logic)
        reference_logic = re.sub(r"\b" + name + r"\b", "reference_" + name, reference_logic)
    proof.write_text("""module lookup_proof #(
    parameter int SETS=128, DEMAND_DEPTH=4,
    parameter int SI=$clog2(SETS), DQ_CW=$clog2(DEMAND_DEPTH+1)
) (
    input logic configured, clearing, bypass_q, lookup_snapshot_valid,
    input logic [1:0] fg_state,
    input logic [SI-1:0] lookup_snapshot_set, demand_set, demand_fill_set, request_set,
    input logic [31:0] demand_addr, request_address,
    input logic [31:2] lookup_snapshot_word,
    input logic [DQ_CW-1:0] response_count,
    output logic equivalent
);
  localparam logic [1:0] FG_IDLE=2'd0, FG_MISS=2'd1, FG_RESP=2'd2;
  typedef struct packed {logic [31:0] address; logic [SI-1:0] set_index;} request_t;
  request_t work_request;
  logic [31:0] lookup_addr;
  logic [SI-1:0] lookup_set;
  logic work_lookup_ready, demand_lookup_ready;
  logic current_lookup_ready, reference_lookup_ready;
  logic current_work_ready, reference_work_ready;
  assign work_request.address=request_address;
  assign work_request.set_index=request_set;
""" + common + "\n" + reference_logic + "\n" + current_logic + """
  assign equivalent=current_lookup_ready==reference_lookup_ready &&
                    current_work_ready==reference_work_ready;
endmodule
""")
    cases = []
    for sets, depth in ((2, 1), (16, 4), (32, 4), (128, 4), (256, 8)):
        name = f"sets{sets}_depth{depth}"
        script, log_path = out / (name + ".ys"), out / (name + ".log")
        script.write_text(f"read_slang --top lookup_proof -GSETS={sets} -GDEMAND_DEPTH={depth} " +
            shlex.quote(str(proof)) + "\nprep -top lookup_proof -flatten\n" +
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Lookup comparison incomplete")
        cases.append(dict(sets=sets, demand_depth=depth, passed=True, inputs_constrained=False,
                          log_sha256=digest(log_path.read_bytes()), script_sha256=digest(script.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_lookup_comparisons=True, actual_source_expressions=True,
        observed_result_bits=2, proof_sha256=digest(proof.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
