#!/usr/bin/env python3
"""证明前端配置地址进位与短通道范围检查，并核对其余前端源码。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="16913ce0")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    start = current.index("  // 每个字节并行判断地址进位，最后合并四段结果。")
    end = current.index("  // Configuration products cross register boundaries before overflow checks.", start)
    body = current[start:end]
    new_declarations = "  logic cfg_address_overflow;\n  logic [3:0] cfg_address_generate, cfg_address_propagate;\n"
    old_assignment = "    cfg_address_sum={1'b0,c.input_base}+{1'b0,cfg_tensor_product[31:0]};\n"
    normalized = current.replace(body, "").replace(new_declarations, "  logic [32:0] cfg_address_sum;\n")
    normalized = normalized.replace("    cfg_ok=cfg_basic_saved", old_assignment + "    cfg_ok=cfg_basic_saved")
    normalized = normalized.replace("!cfg_address_overflow", "!cfg_address_sum[32]")
    group_start = current.index("  end else if (LANES <= 4) begin : g_short_group_lane")
    group_end = current.index("  end else if (LANES <= 32768) begin : g_group_lane_range", group_start)
    group_body = current[group_start:group_end]
    normalized = normalized.replace(group_body, "")
    for line in (
        "  logic [15:0] group_minus_two_q, group_minus_three_q;\n",
        "      group_minus_two_q <= 16'hfffe;\n",
        "      group_minus_three_q <= 16'hfffd;\n",
        "      group_minus_two_q <= cfg.group_c - 16'd2;\n",
        "      group_minus_three_q <= cfg.group_c - 16'd3;\n",
    ):
        if normalized.count(line) != 1:
            raise RuntimeError("Group threshold state requires verification")
        normalized = normalized.replace(line, "")
    if normalized != reference:
        raise RuntimeError("Additional frontend source changes require verification")
    proof = out / "proof.sv"
    proof.write_text("module address_overflow_proof(input logic [31:0] input_base,input_bytes, output logic equivalent);\n" +
        new_declarations + "logic [32:0] reference_sum;\n" +
        body.replace("c.input_base", "input_base").replace("cfg_tensor_product", "input_bytes") +
        "assign reference_sum={1'b0,input_base}+{1'b0,input_bytes};\n" +
        "assign equivalent=cfg_address_overflow==reference_sum[32];\nendmodule\n")
    script, log_path = out / "run.ys", out / "formal.log"
    script.write_text("read_slang --top address_overflow_proof " + shlex.quote(str(proof)) + "\n" +
                      "prep -top address_overflow_proof\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if "SUCCESS" not in log_path.read_text():
        raise RuntimeError("Address overflow comparison incomplete")
    group_proof = out / "group_proof.sv"
    reference_group_start = reference.index("  end else if (LANES <= 32768) begin : g_group_lane_range")
    reference_group_end = reference.index("  end else begin : g_group_lane_range_wide", reference_group_start)
    reference_group_body = reference[reference_group_start:reference_group_end].split("\n", 1)[1]
    group_proof.write_text("module group_boundary_proof #(parameter int LANES=4) (" +
        "input logic [15:0] group_c,ch_q, output logic equivalent);\n" +
        "localparam int p_group_low_w=2,p_group_high_w=14;\n" +
        "typedef struct packed {logic [15:0] group_c;} cfg_t;\ncfg_t c;\n" +
        "logic [15:0] last_group_channel_q,group_minus_two_q,group_minus_three_q;\n" +
        "logic [13:0] group_high_minus_one_q;\n" +
        "logic [LANES-1:0] group_lane_allowed,reference_allowed,arithmetic_allowed;\nlogic [16:0] remaining;\n" +
        "assign c.group_c=group_c;\nassign last_group_channel_q=group_c-16'd1;\n" +
        "assign group_minus_two_q=group_c-16'd2;\nassign group_minus_three_q=group_c-16'd3;\n" +
        "assign group_high_minus_one_q=group_c[15:2]-14'd1;\n" +
        "if (LANES<=32768) begin:g_reference\n" +
        reference_group_body.replace("group_lane_allowed", "reference_allowed") + "\nend\n" +
        group_body.split("\n", 1)[1] + "\n" +
        "assign remaining={1'b0,group_c}-{1'b0,ch_q};\n" +
        "for (genvar lane=0;lane<LANES;lane++) assign arithmetic_allowed[lane]=17'(lane)<remaining;\n" +
        "assign equivalent=group_lane_allowed==reference_allowed && reference_allowed==arithmetic_allowed;\nendmodule\n")
    group_results = []
    for lanes in (3, 4):
        group_script, group_log = out / f"group{lanes}.ys", out / f"group{lanes}.log"
        group_script.write_text(f"read_slang --top group_boundary_proof -GLANES={lanes} " +
            shlex.quote(str(group_proof)) + "\nprep -top group_boundary_proof -flatten\n" +
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with group_log.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(group_script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SUCCESS" not in group_log.read_text():
            raise RuntimeError("Group boundary comparison incomplete")
        group_results.append(dict(lanes=lanes, input_bits=32, result_bits=lanes, passed=True,
                                  log_sha256=hashlib.sha256(group_log.read_bytes()).hexdigest()))
    threshold_names = ("group_high_minus_one_q", "last_group_channel_q", "group_minus_two_q", "group_minus_three_q")
    threshold_updates = {name: re.findall(r"\b" + name + r"\s*<=\s*([^;]+);", current) for name in threshold_names}
    if any(len(values) != 2 for values in threshold_updates.values()):
        raise RuntimeError("Unexpected threshold state updates")
    first_update = min(re.search(r"\b" + name + r"\s*<=", current).start() for name in threshold_names)
    sequential_start = current.rfind("  always_ff", 0, first_update)
    sequential_end = current.index("\n  end\n", first_update)
    sequential = current[sequential_start:sequential_end]
    if "end else if (cfg_valid && cfg_ready) begin" not in sequential:
        raise RuntimeError("Thresholds do not use the configuration acceptance event")
    for name in threshold_names:
        if len(re.findall(r"\b" + name + r"\s*<=", sequential)) != 2:
            raise RuntimeError("Threshold assignments span additional sequential blocks")
    if re.findall(r"\bc\s*<=\s*([^;]+);", current) != ["'0", "cfg"]:
        raise RuntimeError("Configuration state lifetime changed")
    c_update = current.index("c<=cfg;")
    c_guard = current.rfind("if (cfg_valid && cfg_ready) begin", 0, c_update)
    if c_guard < current.rfind("  always_ff", 0, c_update):
        raise RuntimeError("Configuration storage uses a different event")
    state_proof = out / "threshold_state.sv"
    state_proof.write_text("module threshold_state_proof(input logic clk,rst_n,cfg_fire,\n" +
        "input logic [15:0] cfg_group_c, output logic equivalent);\n" +
        "localparam int p_group_low_w=2,p_group_high_w=14;\n" +
        "typedef struct packed {logic [15:0] group_c;} cfg_t;\ncfg_t c,cfg;\n" +
        "logic [13:0] group_high_minus_one_q;\n" +
        "logic [15:0] last_group_channel_q,group_minus_two_q,group_minus_three_q;\n" +
        "assign cfg.group_c=cfg_group_c;\n" +
        "always_ff @(posedge clk or negedge rst_n) begin\nif(!rst_n) begin\nc<='0;\n" +
        "\n".join(f"{name}<={values[0]};" for name, values in threshold_updates.items()) +
        "\nend else if(cfg_fire) begin\nc<=cfg;\n" +
        "\n".join(f"{name}<={values[1]};" for name, values in threshold_updates.items()) +
        "\nend\nend\n" +
        "assign equivalent=group_high_minus_one_q==(c.group_c[15:2]-14'd1) &&\n" +
        "last_group_channel_q==(c.group_c-16'd1) && group_minus_two_q==(c.group_c-16'd2) &&\n" +
        "group_minus_three_q==(c.group_c-16'd3);\nendmodule\n")
    state_script, state_log = out / "threshold_state.ys", out / "threshold_state.log"
    state_script.write_text("read_slang --top threshold_state_proof " + shlex.quote(str(state_proof)) + "\n" +
        "prep -top threshold_state_proof\nasync2sync\n" +
        "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 4\n")
    with state_log.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(state_script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if "Induction step proven: SUCCESS!" not in state_log.read_text():
        raise RuntimeError("Threshold state induction incomplete")
    digest = lambda value: hashlib.sha256(value).hexdigest()
    report = dict(passed=True, reference_ref=args.reference, input_bits=64, result_bits=1,
                  inputs_constrained=False, unchanged_outside_address_and_group_boundaries=True,
                  source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
                  proof_sha256=digest(proof.read_bytes()), log_sha256=digest(log_path.read_bytes()),
                  group_cases=group_results, group_proof_sha256=digest(group_proof.read_bytes()),
                  reference_group_branch_from_source=True,
                  derived_state=dict(passed=True, register_bits=62, input_events_constrained=False,
                      initial_reset=True, assignments=threshold_updates,
                      source_sha256=digest(state_proof.read_bytes()), log_sha256=digest(state_log.read_bytes())))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
