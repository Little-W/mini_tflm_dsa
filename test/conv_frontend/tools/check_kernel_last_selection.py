#!/usr/bin/env python3
"""验证描述符核末列与地址候选共用选择时的完整输入等价关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from check_frontend_range_comparisons import bench, declarations, mapping_wrapper, module, section, CHECKS

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
DESCRIPTOR = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
INPUTS = {"i_last_kernel_col_q": 16, "i_kx0_q": 16, "window_next_kx": 16,
          "incoming_window_context": 1, "incoming_position_same_tap": 1,
          "incoming_position_forward_tap": 1, "incoming_position_backward_tap": 1,
          "incoming_position_previous_row": 1, "o_incoming_next_tile_fast": 1,
          "o_incoming_skip_tap": 1, "incoming_q_equal": 1, "i_incoming_tap_wrap": 1}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def circuit(source, name):
    kernel = section(source, "  if (!p_register_descriptor) begin : g_direct_kernel_end",
                     "  if (p_register_descriptor) begin : g_commit_kernel_end")
    choices = section(source, "  // 各候选分别组合完整优先条件", "  // 地址、坐标与像素先组成互斥候选")
    return "module " + name + "(\n" + ",\n".join(declarations(INPUTS, "input ") +
        ["output logic incoming_kx_last"]) + ''');
  localparam bit p_register_descriptor=0;
  logic incoming_window_match,o_incoming_next_position_fast;
  logic [9:0][5:0] incoming_word_flags;
  logic [8:0][5:0] incoming_padding_flags;
  logic [9:0] incoming_word_choice,prepared_word_select;
  logic [8:0] incoming_padding_choice,prepared_padding_select;
  assign incoming_window_match=incoming_position_same_tap || incoming_position_forward_tap ||
      incoming_position_backward_tap || incoming_position_previous_row;
  assign o_incoming_next_position_fast=incoming_window_context && incoming_window_match;
''' + kernel + choices + "\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [root/DESCRIPTOR, root/"rtl/common/add_equal.sv", root/"rtl/common/onehot_mux.sv",
             Path(__file__).resolve(), Path(__file__).with_name("check_frontend_range_comparisons.py")]
    hashes = {str(path): digest(path) for path in paths}
    source = (root/DESCRIPTOR).read_text()
    reference = read_reference_file(root, args.reference_ref, str(DESCRIPTOR), text=True)
    expected_relations = (
        "assign incoming_position_forward_tap = window_forward_allowed_q &&\n      incoming_tap_match_o_equal[1];",
        "assign incoming_position_backward_tap = window_backward_allowed_q &&\n      incoming_tap_match_o_equal[2];",
        "assign incoming_position_previous_row = window_previous_allowed_q &&\n      incoming_tap_match_o_equal[3];",
        ".i_select({window_previous_allowed_q, window_backward_allowed_q, window_forward_allowed_q, 1'b1})",
        ".i_data({incoming_tap_match_o_equal[3:1], incoming_position_same_tap})",
        "assign o_incoming_next_position_fast = incoming_window_context && incoming_window_match;",
    )
    if any(item not in source or item not in reference for item in expected_relations):
        raise ValueError("窗口匹配与位置标志的生产关系发生变化")
    helper = out/"descriptor_qualify.sv"
    helper.write_text(module(source, "conv_descriptor_qualify"))
    generated = out/"kernel_selection_model.sv"
    text = circuit(source, "current_kernel") + circuit(reference, "reference_kernel") + \
        "module proof(\n" + ",\n".join(declarations(INPUTS, "input ") +
        ["output logic equivalent,actual_value,expected_value"]) + ''');
  current_kernel actual(.incoming_kx_last(actual_value),.*);
  reference_kernel expected(.incoming_kx_last(expected_value),.*);
  assign equivalent=actual_value===expected_value;
endmodule
'''
    generated.write_text(text.replace("always_comb", "always @*"))
    support = [root/"rtl/common/add_equal.sv", root/"rtl/common/onehot_mux.sv", helper, generated]
    script, log = out/"kernel_selection.ys", out/"kernel_selection.formal.log"
    script.write_text("read_slang -DSYNTHESIS --top proof " + shlex.join(map(str, support)) +
        "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
        "prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log.open("w") as handle:
        subprocess.run([sys.executable, str(root/"scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=180)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError(str(log))
    tb, binary, build, simulation = [out/("kernel_selection"+suffix) for suffix in
                                    (".sv", ".vvp", ".build.log", ".four_state.log")]
    tb.write_text(bench(INPUTS, 1, '''
  case(sample%8)
    0:i_last_kernel_col_q=i_kx0_q;
    1:i_last_kernel_col_q=window_next_kx;
    2:i_last_kernel_col_q=window_next_kx+16'd1;
    3:i_last_kernel_col_q=window_next_kx-16'd1;
    4:i_last_kernel_col_q=i_kx0_q+16'd1;
    5:i_last_kernel_col_q=16'd0;
    6:i_last_kernel_col_q=16'd1;
    7:i_last_kernel_col_q=16'd2;
  endcase
'''))
    with build.open("w") as handle:
        subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                        *map(str, support+[tb])], stdout=handle, stderr=subprocess.STDOUT, check=True)
    with simulation.open("w") as handle:
        subprocess.run([args.vvp, str(binary)], stdout=handle, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    if "FRONTEND_COMPARISONS_FOUR_STATE_PASS" not in simulation.read_text():
        raise RuntimeError(str(simulation))
    binary.unlink()
    cases = {}
    for kind in ("actual", "expected"):
        wrapper = out/(kind+"_mapping.sv")
        wrapper.write_text(mapping_wrapper(INPUTS, 1, kind))
        cases[kind] = dict(top="comparison_mapping", options=["-D", "SYNTHESIS=1"],
                           sources=list(map(str, support+[wrapper])),
                           configuration="Complete registered kernel column selection")
    (out/"mapping_cases.json").write_text(json.dumps(cases, indent=2)+"\n")
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError("检查期间源码发生变化")
    report = dict(passed=True, formal_proofs=1, four_state_checks=CHECKS,
                  input_bits=sum(INPUTS.values()), all_input_bits_x_z=True, inputs_constrained=False,
                  source_sha256=hashes, sources_unchanged=True, reference_ref=args.reference_ref,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  model_sha256=digest(generated), formal_log_sha256=digest(log),
                  simulation_log_sha256=digest(simulation))
    (out/"summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")
    print("KERNEL_LAST_SELECTION_PASS", flush=True)


if __name__ == "__main__":
    main()
