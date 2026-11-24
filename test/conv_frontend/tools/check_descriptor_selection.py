#!/usr/bin/env python3
"""验证实际描述符匹配与候选资格选择，并测量其完整组合电路。"""
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/conv/conv_im2col_descriptor.sv")
CASES = 8192
INPUTS = {
    "i_tile_p0": 32, "i_tile_q0": 32, "i_p0": 32, "i_q0": 32,
    "window_next_p": 32, "window_next_q": 32,
    "i_skip_group_q": 33, "i_next_group_q": 33, "target_inputs": 99,
    "i_kx0_q": 16, "group_c": 16, "kernel_w": 16,
    "i_last_group_channel_q": 16, "i_group_nonzero_q": 1,
    "windowed": 1, "window_next_valid": 1, "i_geometry_tile": 1,
    "i_row_base_valid": 1, "i_coordinate_address_valid": 1,
    "incoming_group_fits": 1, "i_incoming_tile_group_fits": 2,
    "window_forward_allowed_q": 1, "window_backward_allowed_q": 1,
    "window_previous_allowed_q": 1, "i_incoming_tap_wrap": 1,
    "i_tile_rows": "p_rw", "i_rows_q": "p_tile_count_w",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def between(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def regions(source):
    matches = between(source, "  assign incoming_compare_a[0]", "`ifndef SYNTHESIS\n  logic [32:0] reduction_difference;")
    targets = between(source, "  // 相邻核位置只需要三种步长", "  // 空间分块起点保留")
    context = between(source, "  // 空间分块起点保留", "  // 位置递增和保存值的匹配并行计算")
    choices = between(source, "  always_comb begin\n    prepared_padding_select", "  // 地址、坐标与像素先组成互斥候选")
    if "  assign incoming_word_flags[9]" in source:
        choices = between(source, "  // 各候选分别组合完整优先条件", "  // 地址、坐标与像素先组成互斥候选")
    return matches, targets, context, choices


def preserved_state(source):
    text = regions(source)[1]
    return re.search(r"      always_ff @\(posedge i_clk\) begin\n.*?\n      end", text, re.S).group()


def unchanged_logic(current, reference):
    if preserved_state(current) != preserved_state(reference):
        raise ValueError("Window target register updates changed")
    normalized = []
    for text in (current, reference):
        for index, region in enumerate(regions(text)):
            text = text.replace(region, f"REGION_{index}\n")
        text = re.sub(r"  output logic \[9:0\]\[p_coord_w-1:0\] o_incoming_y_candidates,\n", "", text)
        text = text.replace("    assign o_incoming_y_candidates[candidate] = coordinate_y;\n", "")
        for declaration in (
            "logic incoming_window_position_match, incoming_single_row;",
            "logic incoming_next_tile_context;", "logic [9:0][5:0] incoming_word_flags;",
            "logic [8:0][5:0] incoming_padding_flags;", "logic [9:0] incoming_word_choice;",
            "logic [8:0] incoming_padding_choice;",
        ):
            text = text.replace("  " + declaration + "\n", "")
        if "// 原始字段完整比较" in text:
            first = text.index("// 原始字段完整比较")
            last = text.index("`default_nettype wire", first)
            text = text[:first] + text[last:]
        normalized.append(text)
    if normalized[0] != normalized[1]:
        raise ValueError("Logic outside descriptor matching and candidate selection changed")


def ports(direction="input "):
    return [f"{direction}logic" + (f" [{width}-1:0]" if width != 1 else "") + " " + name
            for name, width in INPUTS.items()]


def helper_modules(source):
    first = source.index('// 原始字段完整比较')
    return source[first:source.index('`default_nettype wire', first)]


def model(name, source):
    matches, targets, context, choices = regions(source)
    target_update = preserved_state(source)
    targets = targets.replace(target_update, "      assign target_q = target_inputs[33*target+:33];")
    # 各比较输出分别连接，再组成观察向量，保留每个结果的驱动方式。
    matches = matches.replace("incoming_tap_match_o_equal[0]", "skip_reduction_match")
    targets = targets.replace("incoming_tap_match_o_equal[target+1]", "target_match_value[target]")
    # 目标值已在已有寄存器输出处作为输入；其未连接的写入加法不属于当前组合电路。
    targets = re.sub(r"      parallel_prefix_add #[\s\S]*?      \);\n", "", targets, count=1)
    parameters = "parameter int p_rw=5,p_tile_count_w=5,p_cache_policy=3,parameter bit p_register_descriptor=0"
    return f"module {name} #({parameters})(\n" + ",\n".join(ports()) + ''',
 output logic [9:0] word_select,output logic [8:0] padding_select,
 output logic [10:0] matched);
 typedef struct packed {logic windowed;logic [15:0] group_c,kernel_w;} config_t;
 config_t i_c;
 logic i_clk,i_rst_n,window_prepare_write;
 logic [2:0][32:0] incoming_compare_a,incoming_compare_b;
 logic [2:0][10:0] incoming_part_equal;
 logic [2:0][1:0] incoming_group_equal;
 logic [1:0] incoming_position_equal;
 logic incoming_q_equal;
 logic skip_reduction_match;
 logic [2:0] target_match_value;
 (* keep=1 *) wire [3:0] incoming_tap_match_o_equal={target_match_value,skip_reduction_match};
 logic [16:0] negative_group;
 logic [2:0][32:0] target_difference;
 logic [2:0] target_difference_match;
 logic [32:0] reduction_difference;
 logic [31:0] incoming_tile_match_i_a,incoming_tile_match_i_b,incoming_tile_match_i_target;
 logic incoming_tile_match_i_carry_in,incoming_tile_match_o_equal;
 logic o_incoming_skip_tap,incoming_q_fast;
 logic [5:0] incoming_fast_i_flags;
 logic incoming_same_position_fast;
 logic incoming_position_same_tap,incoming_position_forward_tap;
 logic incoming_position_backward_tap,incoming_position_previous_row;
 (* keep=1 *) logic incoming_window_context,incoming_window_match;
 logic o_incoming_next_position_fast,o_incoming_next_tile_fast,o_incoming_fast;
 logic incoming_window_position_match,incoming_single_row,incoming_next_tile_context;
 logic [9:0][5:0] incoming_word_flags;
 logic [8:0][5:0] incoming_padding_flags;
 logic [9:0] incoming_word_choice;
 logic [8:0] incoming_padding_choice;
 (* keep=1 *) logic [9:0] prepared_word_select;
 (* keep=1 *) logic [8:0] prepared_padding_select;
 assign i_c={windowed,group_c,kernel_w};
 assign {i_clk,i_rst_n,window_prepare_write}=3'b000;
 assign reduction_difference={1'b0,i_tile_q0}-{1'b0,window_next_q};
''' + matches + targets + context + choices + '''
 assign word_select=prepared_word_select;
 assign padding_select=prepared_padding_select;
 assign matched={incoming_q_equal,incoming_tap_match_o_equal,incoming_window_context,
   incoming_window_match,o_incoming_next_position_fast,o_incoming_next_tile_fast,o_incoming_skip_tap,o_incoming_fast};
endmodule
'''


def proof_model(current, reference):
    connections = ",".join("."+name for name in INPUTS)
    parameters = ".p_rw(p_rw),.p_tile_count_w(p_tile_count_w),.p_cache_policy(p_cache_policy),.p_register_descriptor(p_register_descriptor)"
    return helper_modules(current) + model("candidate", current) + model("reference", reference) + \
        "module proof #(parameter int p_rw=5,p_tile_count_w=5,p_cache_policy=3,parameter bit p_register_descriptor=0)(\n" + \
        ",\n".join(ports()) + ''',output logic equivalent);
 logic [29:0] actual,expected;
''' + f"candidate #({parameters}) u_candidate ({connections},.word_select(actual[29:20]),.padding_select(actual[19:11]),.matched(actual[10:0]));\n" + \
        f"reference #({parameters}) u_reference ({connections},.word_select(expected[29:20]),.padding_select(expected[19:11]),.matched(expected[10:0]));\n" + \
        "assign equivalent=actual===expected;\nendmodule\n"


def four_state_bench(width, policy, registered):
    total = sum(value if isinstance(value, int) else width for value in INPUTS.values())
    padded = (total+31)//32*32
    return f"module tb;localparam int p_rw={width},p_tile_count_w={width};\n" + ";\n".join(ports("")) + f''';
 logic equivalent;logic [{padded-1}:0] pattern;
 proof #(.p_rw(p_rw),.p_tile_count_w(p_tile_count_w),.p_cache_policy({policy}),.p_register_descriptor({registered})) dut(.*);
 initial begin
  for(integer sample=0;sample<{CASES};sample++)begin
   for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
''' + "{" + ",".join(INPUTS) + "}=pattern;\n" + '''
   i_tile_rows=1;
   if(sample%2==0)i_tile_p0=window_next_p;else i_tile_p0=i_p0+32'(i_rows_q);
   case(sample%6)
    0:i_tile_q0=window_next_q;
    1:i_tile_q0=target_inputs[31:0];
    2:i_tile_q0=target_inputs[64:33];
    3:i_tile_q0=target_inputs[97:66];
    4:i_tile_q0=i_q0;
    5:i_tile_q0=i_skip_group_q[31:0];
   endcase
   if(sample%3==0)i_tile_q0[sample%32]=1'bx;
   if(sample%5==0)i_tile_p0[sample%32]=1'bz;
   if(sample%7==0)windowed=1'bx;
   if(sample%11==0)window_next_valid=1'bz;
   if(sample%13==0)window_forward_allowed_q=1'bx;
   if(sample%17==0)i_incoming_tile_group_fits[sample%2]=1'bz;
   #1;if(equivalent!==1'b1)$fatal(1,"Descriptor selection differs at sample %0d",sample);
  end
''' + f'  $display("DESCRIPTOR_SELECTION_FOUR_STATE_PASS checks={CASES}");$finish;\n end\nendmodule\n'


def run(command, log):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT, check=True, timeout=240)


def mapping(root, out, model_path):
    sys.path.insert(0, str(ROOT / "test/conv_frontend/tools"))
    from measure_complete_paths import measure
    reports = []
    for top in ("reference", "candidate"):
        script, log, netlist = (out / (top + suffix) for suffix in (".ys", ".mapping.log", ".json"))
        script.write_text("read_slang --best-effort-hierarchy -D SYNTHESIS=1 --top " + top + " " +
            shlex.join(map(str, (root/"rtl/common/add_equal.sv", root/"rtl/common/onehot_mux.sv", model_path))) +
            f"\nsynth_xilinx -family xc7 -top {top} -flatten -noiopad -noclkbuf\n"
            "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nflatten -noscopeinfo\ndelete t:$scopeinfo\nopt_clean\n" +
            "write_json " + shlex.quote(str(netlist)) + "\n")
        run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script), log)
        report = measure(json.loads(netlist.read_text())["modules"][top])
        if not report["graph_complete"]:
            raise RuntimeError("The extracted descriptor circuit contains unclassified logic")
        (out/(top+".paths.json")).write_text(json.dumps(report, indent=2)+"\n")
        reports.append({"top": top, "maximum_combinational_cells": report["maximum_combinational_cells"],
                        "graph_complete": report["graph_complete"], "resources": report["resources"],
                        "boundary": "Descriptor fields, stored targets, range qualifications and configuration flags"})
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root/SOURCE).read_text()
    reference = read_reference_file(root, args.reference_ref, str(SOURCE), text=True)
    unchanged_logic(current, reference)
    path = out/"model.sv"
    path.write_text(proof_model(current, reference).replace("always_comb", "always @*"))
    helpers = [root/"rtl/common"/name for name in ("add_equal.sv", "onehot_mux.sv")]
    tracked = [root/SOURCE, *helpers, path, Path(__file__).resolve()]
    hashes = {str(p): digest(p) for p in tracked}
    rows = []
    for width in (5, 17):
        for policy in (0, 3):
            for registered in (0, 1):
                name = f"rw{width}_policy{policy}_registered{registered}"
                script, log = out/(name+".ys"), out/(name+".formal.log")
                script.write_text(f"read_slang -D SYNTHESIS=1 --top proof -Gp_rw={width} -Gp_tile_count_w={width} " +
                    f"-Gp_cache_policy={policy} -Gp_register_descriptor={registered} " + shlex.join(map(str, (*helpers, path))) +
                    "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
                run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script), log)
                if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                    raise RuntimeError(str(log))
                tb, binary, build, simulation = (out/(name+suffix) for suffix in
                    (".sv", ".vvp", ".build.log", ".four_state.log"))
                tb.write_text(four_state_bench(width, policy, registered))
                run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary, *helpers, path, tb), build)
                run((shutil.which("vvp") or "vvp", binary), simulation)
                if f"DESCRIPTOR_SELECTION_FOUR_STATE_PASS checks={CASES}" not in simulation.read_text():
                    raise RuntimeError(str(simulation))
                rows.append({"input_width": width, "policy": policy, "registered": registered,
                             "formal_passed": True, "four_state_checks": CASES,
                             "formal_log_sha256": digest(log), "simulation_log_sha256": digest(simulation)})
                print("DESCRIPTOR_SELECTION_PASS", name, flush=True)
    mapped = mapping(root, out, path) if args.map else []
    if hashes != {str(p): digest(p) for p in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(), "source_sha256": hashes,
              "cases": rows, "mapping": mapped, "register_updates_preserved": True,
              "other_logic_preserved": True, "domain": "Arbitrary descriptor inputs, stored targets and qualification flags"}
    (out/"summary.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
