#!/usr/bin/env python3
"""比较前端及缓存、预测器的全部状态与公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = "rtl/npu/conv/conv_im2col_frontend.sv"
COMMON = (
    "rtl/npu/conv/conv_im2col_pkg.sv",
    "rtl/npu/dma/cache/conv_read_cache.sv",
    "rtl/npu/dma/cache/conv_sdp_ram.sv",
    "rtl/npu/dma/cache/conv_next_use_predictor.sv",
    "rtl/npu/conv/conv_axi_span_reader.sv",
    "rtl/common/onehot_check.sv",
    "rtl/common/add_equal.sv",
    "rtl/common/REGFILE.v",
)
CASES = {
    "size4_policy0": {"SIZE": 4, "LANES": 1, "BUS_WIDTH": 32, "CACHE_SETS": 8, "CACHE_POLICY": 0},
    "size4_policy1": {"SIZE": 4, "LANES": 2, "BUS_WIDTH": 32, "CACHE_SETS": 8, "CACHE_POLICY": 1},
    "size8_policy2": {"SIZE": 8, "LANES": 4, "BUS_WIDTH": 64, "CACHE_SETS": 8, "CACHE_POLICY": 2},
    "size16_policy3": {"SIZE": 16, "LANES": 2, "BUS_WIDTH": 64, "CACHE_SETS": 128, "CACHE_POLICY": 3},
    "size16_lanes4_policy3": {"SIZE": 16, "LANES": 4, "BUS_WIDTH": 64, "CACHE_SETS": 128, "CACHE_POLICY": 3},
}
for line_bytes in (8, 32, 64, 128, 256):
    CASES[f"size4_line{line_bytes}"] = {"SIZE": 4, "LANES": 4, "BUS_WIDTH": 64,
        "CACHE_SETS": 8, "CACHE_POLICY": 3, "LINE_BYTES": line_bytes}
CASES["size4_lanes3"] = {"SIZE": 4, "LANES": 3, "BUS_WIDTH": 64, "CACHE_SETS": 8, "CACHE_POLICY": 3}
DERIVED_STATE = {
    "row_wrap_q": "row_wrap",
    "tap_wrap_q": "tap_wrap",
    "incoming_tap_wrap_q": "incoming_tap_wrap",
    "row_last_q": "row_idx + 1 == rows_q",
    "p_fast_wrap": "c.output_w != 16'd0 && p_fast_x[15:0] == last_output_col_q",
    "group_minus_two_q": "c.group_c - 16'd2",
    "group_minus_three_q": "c.group_c - 16'd3",
}
DERIVED_WIDTHS = {"group_minus_two_q": 16, "group_minus_three_q": 16}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-ref", default="d9abf98")
    parser.add_argument("--current-source", type=Path)
    parser.add_argument("--group-proof", type=Path,
                        help="组合与时序归纳均完成的组末状态关系报告")
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    original_reference = subprocess.check_output(
        ["git", "show", args.reference_ref + ":" + FRONTEND], cwd=ROOT)
    current_source = args.current_source.resolve() if args.current_source else ROOT / FRONTEND
    current = current_source.read_bytes()
    group_proof = None
    if args.group_proof:
        group_proof = json.loads(args.group_proof.read_text())
        if (not group_proof.get("passed") or not group_proof.get("derived_state", {}).get("passed") or
                group_proof["source_sha256"] != hashlib.sha256(current).hexdigest() or
                group_proof["reference_sha256"] != hashlib.sha256(original_reference).hexdigest() or
                not group_proof.get("unchanged_outside_address_and_group_boundaries") or
                not group_proof.get("reference_group_branch_from_source")):
            raise RuntimeError("Group proof does not describe these frontend sources")
    observations = {name: value for name, value in DERIVED_STATE.items()
                    if re.search(rb"\blogic\b[^;]*\b" + name.encode() + rb"\b", current)
                    and not re.search(rb"\b(?:logic|wire)\b[^;]*\b" + name.encode() + rb"\b", original_reference)}
    (out / "reference_original_frontend.sv").write_bytes(original_reference)
    for label in ("reference", "current"):
        path = out / (label + "_frontend.sv")
        content = original_reference if label == "reference" else current
        if label == "reference" and observations:
            # 新增寄存状态由原设计的组合表达式观察，每项状态关系都参与证明。
            declarations = "\n".join(
                f"(* keep *) wire " +
                (f"[{DERIVED_WIDTHS[name]-1}:0] " if name in DERIVED_WIDTHS else "") +
                f"{name} = {value};" for name, value in observations.items())
            before, after = content.rsplit(b"endmodule", 1)
            content = before + declarations.encode() + b"\nendmodule" + after
        path.write_bytes(content)
        snapshots[label] = path
    report = {
        "reference_ref": args.reference_ref,
        "source_sha256": {name: digest(current_source if name == FRONTEND else ROOT / name)
                          for name in (FRONTEND, *COMMON)},
        "reference_frontend_sha256": hashlib.sha256(original_reference).hexdigest(),
        "proof_reference_sha256": digest(snapshots["reference"]),
        "derived_state_observations": observations,
        "inputs_constrained": False,
        "method": "Complete-state equivalence with simple SAT and temporal induction",
        "runs": [],
    }
    if group_proof is not None:
        report["group_proof_sha256"] = digest(args.group_proof)
        report["method"] = "Complete-state SAT comparison composed with source-derived group arithmetic and state induction"
    for name in args.cases:
        folder = out / name
        folder.mkdir(exist_ok=True)
        parameters = {"CACHE_WAYS": 2, "LINE_BYTES": 16, **CASES[name]}
        options = " ".join(f"-G{key}={value}" for key, value in parameters.items())
        commands = []
        for label, source in snapshots.items():
            sources = [ROOT / COMMON[0], source, *(ROOT / path for path in COMMON[1:])]
            commands.extend([
                "read_slang --top conv_im2col_frontend " + options + " " +
                " ".join(shlex.quote(str(path)) for path in sources),
                "prep -top conv_im2col_frontend -flatten", "memory_map", "async2sync", "opt_clean",
                "rename conv_im2col_frontend " + label, "design -stash " + label,
            ])
        commands.extend([
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "opt_merge", "equiv_simple -short -seq 1", "opt_clean",
        ])
        if group_proof is None:
            commands += ["equiv_induct -seq 1", "equiv_status -assert"]
        else:
            commands += ["equiv_status"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        log_path = folder / "formal.log"
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        log = log_path.read_text()
        matched = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log)
        passed = result.returncode == 0 and "Equivalence successfully proven" in log
        composed_points = []
        if group_proof is not None and result.returncode == 0 and matched:
            points = re.findall(r"Unproven \$equiv .*?: \\([^ ]+)_gold \[(\d+)\] \\([^ ]+)_gate \[(\d+)\]", log)
            allowed_lanes = {item["lanes"] for item in group_proof["group_cases"] if item["passed"]}
            composed_points = [int(first_bit) for first, first_bit, second, second_bit in points
                               if first == second == "group_lane_allowed" and first_bit == second_bit]
            passed = (len(points) == len(composed_points) == int(matched.group(2)) and
                      (not points or parameters["LANES"] in allowed_lanes) and
                      all(0 <= bit < parameters["LANES"] for bit in composed_points))
        case = {"case": name, "parameters": parameters, "passed": passed,
                "equivalent_bits": int(matched.group(1)) + len(composed_points) if matched else None,
                "log_sha256": digest(log_path)}
        if group_proof is not None:
            case["sat_equivalent_bits"] = int(matched.group(1)) if matched else None
            case["composed_group_points"] = [f"group_lane_allowed[{bit}]" for bit in composed_points]
        report["runs"].append(case)
        report["passed"] = all(item["passed"] for item in report["runs"])
        report["equivalent_bits"] = sum(item["equivalent_bits"] or 0 for item in report["runs"])
        (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(case), flush=True)
        if not passed:
            print(log[-6000:])
            raise SystemExit(1)
    for name, sha in report["source_sha256"].items():
        if digest(current_source if name == FRONTEND else ROOT / name) != sha:
            raise RuntimeError("Source changed during equivalence: " + name)


if __name__ == "__main__":
    main()
