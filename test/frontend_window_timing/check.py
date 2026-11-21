#!/usr/bin/env python3
"""证明窗口候选选择的完整组合功能，并生成相同寄存输入输出条件下的综合案例。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
PACKAGE = "rtl/npu/conv/conv_im2col_pkg.sv"
INPUTS = {
    "c": "conv_im2col_pkg::conv_cfg_t",
    **{name: "logic [31:0]" for name in (
        "tile_p0", "tile_q0", "p0", "q0", "window_next_q", "window_next_p", "tap0",
        "row_base_pixel", "row_base_addr", "row_group_base", "window_next_tap",
        "window_next_pixel", "window_next_addr", "window_next_group_base",
        "tap_wrap_bytes", "tap_step_bytes", "next_row_pixel", "next_row_addr",
        "next_row_group_base", "incoming_pixel_next", "addr", "word_addr")},
    **{name: "logic [15:0]" for name in (
        "window_next_kx", "last_kernel_col_q", "window_next_ch", "window_next_ky",
        "ch0_q", "kx0_q", "ky0_q")},
    **{name: "logic" for name in (
        "row_base_valid", "coordinate_address_valid", "incoming_group_fits",
        "window_next_valid", "geometry_tile", "incoming_base_padding", "window_next_padding",
        "next_row_padding", "incoming_tap_wrap", "incoming_wrap_padding", "incoming_step_padding")},
    **{name: "logic signed [34:0]" for name in (
        "row_base_ix", "row_base_iy", "window_next_ix", "window_next_iy",
        "next_row_ix", "next_row_iy", "incoming_wrap_ix", "incoming_wrap_iy", "incoming_step_ix")},
    "tap_wrap_pixels": "logic signed [32:0]", "tap_wrap_dx": "logic signed [32:0]",
    "next_group_q": "logic [32:0]", "tile_rows": "logic [RW-1:0]",
    "tile_cols": "logic [RW-1:0]", "rows_q": "logic [RW-1:0]",
    "incoming_wrap_low_sum": "logic [p_word_shift:0]",
    "incoming_step_low_sum": "logic [p_word_shift:0]",
}
OUTPUTS = {
    **{name: 1 for name in (
        "incoming_skip_tap", "incoming_q_fast", "incoming_same_position_fast",
        "incoming_position_same_tap", "incoming_position_forward_tap",
        "incoming_position_backward_tap", "incoming_position_previous_row",
        "incoming_next_position_fast", "incoming_next_tile_fast", "incoming_fast",
        "incoming_padding", "incoming_word_i_carry_in")},
    **{name: 32 for name in ("incoming_delta", "incoming_tap", "incoming_ch",
        "incoming_kx", "incoming_ky", "incoming_pixel", "incoming_addr", "incoming_group_base")},
    "incoming_ix": 35, "incoming_iy": 35,
}
PARAMETERS = "parameter int SIZE=16, CACHE_POLICY=3, RW=$clog2(SIZE+1), p_word_shift=2"
HELPERS = """
localparam int COORD_W=35, TILE_COUNT_W=RW;
logic [5:0] incoming_fast_i_flags;
logic [1:0] incoming_position_equal;
logic incoming_q_equal;
logic [31:0] ch0,kx0,ky0;
assign ch0={16'd0,ch0_q};
assign kx0={16'd0,kx0_q};
assign ky0={16'd0,ky0_q};
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def extract(text):
    first = text.index("  // 描述符字段分组比较")
    end = text.index("  // 每个空间位置的首个有效卷积核位置", first)
    position = text.find("  // 位置递增和保存值的匹配并行计算", first, end)
    if position >= 0:
        end = position
    selection = text.index("  always_comb begin\n    incoming_tap=tap0;", end)
    candidate_start = text.find("  // 各候选坐标和填充状态独立计算", end)
    if candidate_start >= 0:
        selection = candidate_start
    last = text.index("  // 每个字节并行判断地址进位", selection)
    declarations = ""
    if candidate_start >= 0:
        start = text.index("  logic [3:0][32:0] incoming_tap_match_i_a")
        finish = text.index("  logic channel_descriptor_valid", start)
        declarations = text[start:finish]
    preparation = ""
    if "logic window_forward_allowed_q" in text:
        declarations += "logic window_forward_allowed_q,window_backward_allowed_q,window_previous_allowed_q;\n"
        preparation += "assign window_forward_allowed_q=window_next_kx<last_kernel_col_q;\n"
        preparation += "assign window_backward_allowed_q=window_next_kx!=16'd0;\n"
        preparation += "assign window_previous_allowed_q=c.kernel_w==16'd3 && window_next_kx==16'd0 && window_next_ky!=16'd0;\n"
    group_range = text.find("  // 新分块列数只参与低位加法")
    if group_range >= 0:
        declarations += "logic [1:0] incoming_tile_group_fits;\n"
        preparation += text[group_range:text.index("  assign incoming_tap_wrap", group_range)]
    address = text.find("  logic [6:0][1:0][31:0] incoming_address_i_a")
    if address >= 0:
        address_end = text.index("  // 行、核位置和像素地址", address)
        pair = text.find("  // 双核位置步长在配置准备期间保存", address, address_end)
        if pair >= 0:
            address_end = pair
            declarations += "logic signed [COORD_W-1:0] tap_pair_dx;\nlogic [31:0] tap_pair_pixels,tap_pair_bytes;\n"
            preparation += "assign tap_pair_dx=$signed(COORD_W'(tap_wrap_dx))+$signed(COORD_W'(c.dilation_w));\n"
            preparation += "assign tap_pair_pixels=32'(tap_wrap_pixels)+32'(c.dilation_w);\n"
            preparation += "assign tap_pair_bytes=tap_wrap_bytes+tap_step_bytes;\n"
        declarations += text[address:address_end]
        start = text.index("  // 七种地址候选依次为", address)
        preparation += text[start:text.index("  for (genvar target = 0; target < 2; target++) begin : g_next_row_match", start)]
    coordinate = text.find("  logic [6:0][COORD_W-1:0] candidate_coordinate_i_a")
    if coordinate < 0:
        coordinate = text.find("  logic [4:0][COORD_W-1:0] candidate_coordinate_i_a")
    if coordinate >= 0:
        preparation += text[coordinate:candidate_start]
    return declarations + preparation + text[first:end] + text[selection:last]


def unit(name, source):
    width = sum(OUTPUTS.values())
    ports = ",\n".join("input " + typ + " " + key for key, typ in INPUTS.items())
    declarations = "\n".join("logic " + ("signed " if key in ("incoming_ix", "incoming_iy") else "") +
        ("[" + str(bits-1) + ":0] " if bits > 1 else "") + key + ";" for key, bits in OUTPUTS.items())
    return "module " + name + " #(" + PARAMETERS + ")(\n" + ports + ",\noutput logic [" + str(width-1) + ":0] observed);\n" + \
        HELPERS + declarations + "\n" + extract(source) + "\nassign observed={" + ",".join(OUTPUTS) + "};\nendmodule\n"


def registered(name):
    width = sum(OUTPUTS.values())
    ports = ",\n".join("input " + typ + " i_" + key for key, typ in INPUTS.items())
    declarations = "\n".join(typ + " " + key + ";" for key, typ in INPUTS.items())
    connections = ",".join("." + key + "(" + key + ")" for key in INPUTS)
    updates = "\n".join(key + " <= i_" + key + ";" for key in INPUTS)
    return "module " + name + "_registered #(" + PARAMETERS + ")(input logic clk,\n" + ports + ",\noutput logic [" + str(width-1) + ":0] o_observed);\n" + \
        declarations + "\nlogic [" + str(width-1) + ":0] observed;\n" + name + \
        " #(.SIZE(SIZE),.CACHE_POLICY(CACHE_POLICY),.RW(RW),.p_word_shift(p_word_shift)) u_decode(" + \
        connections + ",.observed(observed));\nalways_ff @(posedge clk) begin\n" + updates + \
        "\no_observed <= observed;\nend\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="4dee27ffec4dc891daf2681379f8b3fd27fd41f2")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate = args.candidate.resolve()
    current = candidate.read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)
    units = {}
    synthesis_cases = {}
    for label, source in (("reference", reference), ("candidate", current)):
        name = label + "_window_decode"
        units[label] = unit(name, source)
        target = out / (name + ".sv")
        target.write_text(units[label] + registered(name))
        synthesis_cases[label + "_window_decode"] = dict(
            top=name + "_registered", options=[],
            sources=[PACKAGE, "rtl/common/add_equal.sv", "rtl/common/parallel_prefix_add.sv", str(target)],
            configuration="16 列窗口候选选择，所有输入与输出使用相同寄存条件")
    ports = ",\n".join("input " + typ + " " + key for key, typ in INPUTS.items())
    connections = ",".join("." + key + "(" + key + ")" for key in INPUTS)
    width = sum(OUTPUTS.values())
    miter = "\n".join(units.values()) + "module comparison #(" + PARAMETERS + ")(\n" + ports + \
        ",\noutput logic equivalent);\nlogic [" + str(width-1) + ":0] expected, actual;\n"
    for label, target in (("reference", "expected"), ("candidate", "actual")):
        miter += label + "_window_decode #(.SIZE(SIZE),.CACHE_POLICY(CACHE_POLICY),.RW(RW)," + \
            ".p_word_shift(p_word_shift)) u_" + label + "(" + connections + ",.observed(" + target + "));\n"
    miter += "assign equivalent=expected==actual;\nendmodule\n"
    proof = out / "comparison.sv"
    proof.write_text(miter)
    cases = []
    for size, policy in ((4, 0), (4, 3), (16, 0), (16, 3), (64, 0), (64, 3)):
        label = f"s{size}_p{policy}"
        script = out / (label + ".ys")
        log = out / (label + ".log")
        script.write_text("read_slang --top comparison " + f"-GSIZE={size} -GCACHE_POLICY={policy} " +
            " ".join(shlex.quote(str(p)) for p in (ROOT/PACKAGE, ROOT/"rtl/common/add_equal.sv",
                ROOT/"rtl/common/parallel_prefix_add.sv", proof)) +
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT/"scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("组合等价证明未完成: " + label)
        cases.append(dict(size=size, cache_policy=policy, passed=True, log_sha256=digest(log.read_bytes())))
        print("WINDOW_DECODE_EQUIVALENCE_PASS", label, flush=True)
    if current != candidate.read_text():
        raise RuntimeError("证明期间前端源码发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=digest(current.encode()),
        reference_sha256=digest(reference.encode()), inputs_constrained=False,
        compared_output_bits=width, cases=cases)
    (out/"summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")
    (out/"synthesis_cases.json").write_text(json.dumps(synthesis_cases, indent=2, ensure_ascii=False)+"\n")


if __name__ == "__main__":
    main()
