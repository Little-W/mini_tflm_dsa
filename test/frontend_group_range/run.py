#!/usr/bin/env python3
"""证明前端通道范围寄存状态与当前组内剩余通道数逐周期一致。"""
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
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="3587da43")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    start = current.index("  // 各种通道来源并行计算组内范围，接收边沿只选择相应标志。")
    end = current.index("  // 每条通道直接检查字内偏移", start)
    body = current[start:end]
    ref_start = reference.index("  // 两个写入通道直接比较当前通道和配置组末值")
    ref_end = reference.index("  // 每条通道直接检查字内偏移", ref_start)
    declarations = ("  logic [3:0] group_range_q, group_range_cfg;\n"
                    "  logic [5:0][15:0] group_range_channel;\n"
                    "  logic [5:0][3:0] group_range_next;\n")
    normalized = current.replace(body, reference[ref_start:ref_end], 1).replace(declarations, "", 1)
    normalized = re.sub(r"\s*group_range_q\s*<=\s*[^;]+;", "", normalized)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Frontend changes outside the range state require verification")

    channel_updates = list(re.finditer(r"\bch_q\s*<=\s*([^;]+);", current))
    range_updates = list(re.finditer(r"\bgroup_range_q\s*<=\s*([^;]+);", current))
    if len(channel_updates) != 9 or len(range_updates) != 10:
        raise RuntimeError("Unexpected channel or range state assignments")
    expected_indices = [None, 1, 1, 0, 5, 0, 2, 3, 4]
    bindings = {}
    for channel, index in zip(channel_updates, expected_indices):
        tail = current[channel.end():]
        flag = re.search(r"\bgroup_range_q\s*<=\s*([^;]+);", tail)
        control = re.search(r"\b(?:if|else|case|end|begin|always_ff)\b", tail)
        if flag is None or (control is not None and control.start() < flag.start()):
            raise RuntimeError("Channel update does not carry the matching range state")
        expected = "4'b0000" if index is None else f"group_range_next[{index}]"
        if tokens(flag[1]) != tokens(expected):
            raise RuntimeError("Unexpected range state source")
        if index is not None:
            rhs = channel[1].replace("incoming_ch", "ch0").strip()
            if index in bindings and tokens(bindings[index]) != tokens(rhs):
                raise RuntimeError("A range source is associated with different channel values")
            bindings[index] = rhs
    if re.findall(r"\bincoming_ch\s*=(?!=)\s*([^;]+);", current) != ["ch0"]:
        raise RuntimeError("Incoming channel source requires verification")
    if "wire [31:0] ky0=32'(ky0_q), kx0=32'(kx0_q), ch0=32'(ch0_q);" not in current:
        raise RuntimeError("Row channel extension requires verification")
    if re.findall(r"\bc\s*<=\s*([^;]+);", current) != ["'0", "cfg"]:
        raise RuntimeError("Configuration state lifetime requires verification")
    if "c<=cfg; configured<=0; error<=!cfg_basic_valid;\n        group_range_q <= group_range_cfg;" not in current:
        raise RuntimeError("Configuration acceptance must update the range state")
    if "assign cfg_ready = state==IDLE &&" not in current:
        raise RuntimeError("Configuration must be accepted only in the idle state")
    if "Q_DECODE: begin" not in current or "Q_WAIT: if (decode_index==q0) begin" not in current:
        raise RuntimeError("Decode state update conditions require verification")
    threshold_names = ("last_group_channel_q", "group_minus_two_q", "group_minus_three_q", "group_high_minus_one_q")
    updates = {name: re.findall(r"\b" + name + r"\s*<=\s*([^;]+);", current) for name in threshold_names}
    if any(len(values) != 2 for values in updates.values()):
        raise RuntimeError("Unexpected configuration threshold updates")
    first = current.index("last_group_channel_q <= 16'hffff;")
    block_start = current.rfind("  always_ff @(posedge clk or negedge rst_n) begin", 0, first)
    block_end = current.index("\n  end\n", first)
    threshold_block = current[block_start:block_end]
    if "end else if (cfg_valid && cfg_ready) begin" not in threshold_block:
        raise RuntimeError("Threshold state uses a different update event")
    for name in threshold_names:
        if len(re.findall(r"\b" + name + r"\s*<=", threshold_block)) != 2:
            raise RuntimeError("Threshold state spans additional sequential blocks")

    proof = out / "range_state.sv"
    reset_thresholds = "\n".join(f"      {name} <= {values[0]};" for name, values in updates.items())
    config_thresholds = "\n".join(f"      {name} <= {values[1]};" for name, values in updates.items())
    branch_updates = "\n".join(
        f"        3'd{index}: begin ch_q <= {bindings[index]}; group_range_q <= group_range_next[{index}]; end"
        for index in range(6))
    source_checks = " &&\n".join(
        f"    group_range_channel[{index}] == ({bindings[index]})" for index in range(6))
    proof.write_text("""module range_state_proof #(parameter int LANES=4)(
    input logic clk, rst_n, config_accept, channel_update,
    input logic [2:0] channel_source,
    input logic [15:0] cfg_group_c, ch0_q, next_channel,
    input logic [31:0] q0, decode_inner,
    input logic [4:0] current_q_div3,
    output logic equivalent
);
  typedef struct packed {logic [15:0] group_c;} config_t;
  localparam int p_group_low_w=LANES>1 && LANES<=32768 ? $clog2(LANES) : 1;
  localparam int p_group_high_w=16-p_group_low_w;
  config_t c, cfg;
  logic [15:0] ch_q, last_group_channel_q, group_minus_two_q, group_minus_three_q;
  logic [p_group_high_w-1:0] group_high_minus_one_q;
  logic [16:0] group_remaining;
  logic [LANES-1:0] group_lane_allowed, reference_allowed;
  wire [31:0] ch0=32'(ch0_q);
  assign cfg.group_c=cfg_group_c;
  assign group_remaining={1'b0,c.group_c}-{1'b0,ch_q};
""" + declarations + body + """
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c <= '0;
      ch_q <= 16'd0;
      group_range_q <= 4'b0000;
""" + reset_thresholds + """
    end else if (config_accept) begin
      c <= cfg;
      group_range_q <= group_range_cfg;
""" + config_thresholds + """
    end else if (channel_update) begin
      case (channel_source)
""" + branch_updates + """
        default: ;
      endcase
    end
  end
  for (genvar lane=0;lane<LANES;lane++) begin:g_reference
    assign reference_allowed[lane]=17'(lane)<group_remaining;
  end
  assign equivalent=group_lane_allowed==reference_allowed &&
    last_group_channel_q==(c.group_c-16'd1) &&
    group_minus_two_q==(c.group_c-16'd2) &&
    group_minus_three_q==(c.group_c-16'd3) &&
    group_high_minus_one_q==(c.group_c[15:p_group_low_w]-p_group_high_w'(1)) &&
""" + source_checks + ";\nendmodule\n")
    cases = []
    for lanes in (1, 2, 3, 4, 8):
        script, log_path = out / f"lanes{lanes}.ys", out / f"lanes{lanes}.log"
        script.write_text(f"read_slang --top range_state_proof -GLANES={lanes} " + shlex.quote(str(proof)) +
            "\nprep -top range_state_proof -flatten\nasync2sync\n" +
            "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 8\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "Induction step proven: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Range state induction incomplete")
        cases.append(dict(lanes=lanes, passed=True, initial_reset=True,
                          config_and_channel_inputs_constrained=False, channel_sources=6,
                          log_sha256=digest(log_path.read_bytes()), script_sha256=digest(script.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_range_state=True, channel_assignments_checked=9, range_assignments_checked=10,
        configuration_and_channel_update_guards_checked=True, actual_source_comparison_logic=True,
        actual_source_channel_values=True, added_register_bits=4,
        proof_sha256=digest(proof.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
