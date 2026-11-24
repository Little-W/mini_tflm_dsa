#!/usr/bin/env python3
"""验证描述符核位置选择和双组步长加法的数值及四态语义。"""
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

from check_state_context import Statements

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
FOUR_STATE_CASES = 4096
INPUTS = {
    "incoming_window_context": 1, "incoming_position_same_tap": 1,
    "incoming_position_previous_row": 1, "incoming_position_forward_tap": 1,
    "incoming_position_backward_tap": 1, "o_incoming_next_tile_fast": 1,
    "o_incoming_skip_tap": 1, "incoming_q_equal": 1, "i_incoming_tap_wrap": 1,
    "i_kx0_q": 16, "i_tap0": 32, "window_next_tap": 32,
    "tap_candidates": 160, "descriptor_reduction": 32, "group_c": 16,
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instance(source, kind, name):
    match = re.search(re.escape(kind) + r" #\([^;]*?\) " + re.escape(name) + r" \([^;]*?\);", source, re.S)
    if match is None:
        raise ValueError(name)
    return match.group()


def tap_assignment(source):
    return re.search(r"    assign incoming_tap_values\[candidate\] =.*?;", source, re.S).group()


def legacy_tap(source, target):
    first = source.index("  always_comb begin\n    incoming_tap=i_tap0;")
    last = source.index("`ifdef SYNTHESIS", first)
    body = source[first:last] + "end\n"
    count = 0

    def selected(statement):
        nonlocal count
        match = re.fullmatch(r"incoming_tap\s*=\s*(.*);", statement, re.S)
        if match is None:
            return ""
        count += 1
        return f"{target} = {match[1]};"

    text = Statements(body[body.index("begin"):], select_assignment=selected).statement()
    if count != 7:
        raise ValueError(f"Expected all seven kernel-position assignments, found {count}")
    return text


def unchanged_logic(current, reference):
    candidate = current.replace("  logic [9:0][31:0] incoming_tap_values;\n", "").replace(
        "  logic [31:0] incoming_tap_selected;\n", "").replace("      incoming_tap = incoming_tap_selected;\n", "")
    candidate = candidate.replace(tap_assignment(current) + "\n", "")
    candidate = candidate.replace("  // 核位置直接选择已经完成的候选，窗口资格只参与末级数据归并。\n", "")
    candidate = candidate.replace("  " + instance(current, "onehot_mux", "u_incoming_tap") + "\n", "")
    candidate = candidate.replace("  // 双组步长占低十七位，高段的两种结果提前计算，低段进位仅选择结果。\n", "")
    candidate = candidate.replace(instance(current, "parallel_prefix_add", "u_skip_group"),
                                  instance(reference, "parallel_prefix_add", "u_skip_group"))
    if candidate != reference:
        raise ValueError("Logic outside kernel-position selection and the skip-group adder changed")


def declarations(direction=""):
    return [f"{direction}logic" + (f" [{width-1}:0]" if width > 1 else "") + " " + name
            for name, width in INPUTS.items()]


def model(current, reference):
    unchanged_logic(current, reference)
    first = current.index("  always_comb begin\n    prepared_padding_select")
    last = current.index("  // 地址、坐标与像素先组成互斥候选", first)
    select = current[first:last]
    ref_first = reference.index("  always_comb begin\n    prepared_padding_select")
    ref_last = reference.index("  // 地址、坐标与像素先组成互斥候选", ref_first)
    if select != reference[ref_first:ref_last]:
        raise ValueError("Candidate selection conditions changed")
    current_adder = instance(current, "parallel_prefix_add", "u_skip_group")
    reference_adder = instance(reference, "parallel_prefix_add", "u_skip_group").replace(
        "u_skip_group", "u_reference_skip_group").replace("skip_group_sum", "reference_skip_group_sum").replace(
        "unused_skip_group_carry", "reference_skip_group_carry")
    ports = declarations("input ") + ["output logic [65:0] actual_value,expected_value", "output logic equivalent"]
    return "module proof #(parameter bit p_register_descriptor=0)(\n" + ",\n".join(ports) + ''');
 typedef struct packed {logic [15:0] group_c;} config_t;
 config_t i_c;
 logic [4:0][31:0] incoming_tap_candidate;
 logic [9:0][31:0] incoming_tap_values;
 logic [31:0] incoming_tap_selected,actual_tap,expected_tap;
 logic [9:0] prepared_word_select;
 logic [8:0] prepared_padding_select;
 logic [32:0] prepared_group_i_a,skip_group_sum,reference_skip_group_sum;
 logic unused_skip_group_carry,reference_skip_group_carry;
 wire incoming_window_match=incoming_position_same_tap || incoming_position_previous_row ||
     incoming_position_forward_tap || incoming_position_backward_tap;
 wire o_incoming_next_position_fast=incoming_window_context && incoming_window_match;
 assign i_c.group_c=group_c;
 assign incoming_tap_candidate=tap_candidates;
 assign prepared_group_i_a={1'b0,descriptor_reduction};
''' + select + "\nfor(genvar candidate=0;candidate<10;candidate++)begin\n" + tap_assignment(current) + "\nend\n" + \
        instance(current, "onehot_mux", "u_incoming_tap") + "\n" + current_adder + "\n" + reference_adder + \
        "\nalways_comb " + legacy_tap(reference, "expected_tap") + \
        "\nalways_comb begin\n" + legacy_tap(current, "actual_tap") + '''
`ifdef SYNTHESIS
 if(!p_register_descriptor)actual_tap=incoming_tap_selected;
`endif
end
 assign actual_value={actual_tap,unused_skip_group_carry,skip_group_sum};
 assign expected_value={expected_tap,reference_skip_group_carry,reference_skip_group_sum};
 assign equivalent=actual_value===expected_value;
endmodule
'''


def four_state_test(registered):
    width = sum(INPUTS.values())
    padded = (width + 31)//32*32
    return "module tb;\n" + ";\n".join(declarations()) + f''';
 logic [65:0] actual_value,expected_value;
 logic equivalent;
 logic [{padded-1}:0] pattern;
 proof #(.p_register_descriptor({registered})) dut(.*);
 initial begin
  for(integer sample=0;sample<{FOUR_STATE_CASES};sample++)begin
   for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
   if(sample%3==0)pattern[(sample/3)%{width}]=1'bx;
   if(sample%5==0)pattern[(sample/5)%{width}]=1'bz;
''' + "{" + ",".join(INPUTS) + "}=pattern;\n" + f'''
   #1;
   if(equivalent!==1'b1)$fatal(1,"Descriptor data mismatch sample=%0d actual=%h expected=%h",sample,actual_value,expected_value);
  end
  $display("DESCRIPTOR_DATA_FOUR_STATE_PASS checks={FOUR_STATE_CASES}");$finish;
 end
endmodule
'''


def run(command, log):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root/SOURCE
    helpers = [root/"rtl/common"/name for name in ("onehot_mux.sv", "parallel_prefix_add.sv")]
    original = read_reference_file(root, args.reference_ref, str(SOURCE), text=True)
    generated = out/"model.sv"
    generated.write_text(model(source.read_text(), original).replace("always_comb", "always @*"))
    tracked = [source, *helpers, generated, Path(__file__).resolve(), Path(__file__).with_name("check_state_context.py")]
    hashes = {str(path): digest(path) for path in tracked}
    rows = []
    for registered in (0, 1):
        name = f"descriptor{registered}"
        script, log = out/(name+".ys"), out/(name+".formal.log")
        script.write_text(f"read_slang -D SYNTHESIS=1 --top proof -Gp_register_descriptor={registered} "+
                          shlex.join(map(str,(*helpers,generated)))+
                          "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script), log)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb, binary, build, simulation = (out/(name+suffix) for suffix in
                                         (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(four_state_test(registered))
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary, *helpers, generated, tb), build)
        run((shutil.which("vvp") or "vvp", binary), simulation)
        if f"DESCRIPTOR_DATA_FOUR_STATE_PASS checks={FOUR_STATE_CASES}" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        rows.append({"register_descriptor": registered, "formal_passed": True, "four_state_checks": FOUR_STATE_CASES,
                     "formal_log_sha256": digest(log), "simulation_log_sha256": digest(simulation)})
        print("DESCRIPTOR_DATA_PASS", name, flush=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "source_sha256": hashes, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(original.encode()).hexdigest(), "cases": rows,
              "tap_assignment_sites": 7, "other_logic_preserved": True,
              "domain": "Arbitrary candidate data, selector flags, descriptor reduction and group width"}
    (out/"summary.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
