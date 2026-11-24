#!/usr/bin/env python3
"""验证有效缓存请求的行号、窗口索引和 epoch 在静态选择后保持一致。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from check_request_qualification import inline_control

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
FRONTEND = Path("rtl/npu/conv/conv_im2col_frontend.sv")
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")
FOUR_STATE_SAMPLES = 2048
KNOWN_SELECTION_SAMPLES = 32 * 16
FIELDS = {"request_y": 35, "request_output_y": 32, "req_index_valid": 1,
          "req_index": 32, "req_epoch": 32, "request_address_value": 32}
INPUTS = {
    "state_index": 5, "cache_rsp_valid": 1, "cache_rsp_error": 1,
    "cache_rsp_success": 1, "cache_rsp_failure": 1,
    "tile_valid": 1, "tile_ready_static": 1, "cfg_valid": 1,
    "tile_prepared_valid": 1, "tile_commit": 1, "wr_ready": 1,
    "row_last_q": 1, "row_base_valid": 1, "geometry_tile": 1,
    "next_row_padding": 1, "next_row_word_hit": 1, "current_word_hit": 1,
    "incoming_fast": 1, "incoming_padding": 1, "incoming_word_hit": 1,
    "tile_rows": 5, "tile_cols": 5, "tile_q_before_end": 1, "tile_rows_in_range": 1,
    "group_after_chunk": 1, "word_boundary": 1, "coordinate_address_valid": 1,
    "next_tap_padding": 1, "next_word_o_equal": 1, "pad_q": 1,
    "group_end_o_equal": 1, "past_active_q": 1, "row_coordinate_valid": 1,
    "incoming_y_candidates": 350, "next_row_iy": 35, "next_tap_iy": 35, "iy": 35,
    "incoming_next_position_fast": 1, "incoming_next_tile_fast": 1,
    "window_next_y": 16, "row_wrap": 1, "oy": 32, "window_index_valid_q": 1,
    "incoming_pixel_candidates": 320, "incoming_pixel_select": 10,
    "short_pixel_q": 1, "next_row_pixel": 32,
    "window_index_shift_q": 5, "next_tap_pixel": 32, "current_req_index": 32,
    "epoch_o_sum": 160, "input_s16": 1,
    "group_offset": 16, "current_req_epoch": 32,
    "narrow_output": 1, "word_output_q": 1,
    "incoming_addr": 32, "next_row_addr": 32, "next_tap_addr": 32,
    "stream_request_addr": 32, "addr": 32,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise ValueError(f"Cannot find assignment: {name}")
    return match.group()


def section(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def normalize_stream(text):
    return re.sub(r"(?<!\.)\b[io]_(\w+)\b", lambda match: match[1], text)


def metadata(source, prefix):
    match = re.search(r"always_comb begin\s+request_y=.*?\n  end", source, re.S)
    if match is None:
        raise ValueError("Cannot find metadata selection")
    text = re.sub(r"\b(" + "|".join(FIELDS) + r")\b",
                  lambda found: prefix + "_" + found[1], match.group())
    if prefix == "expected":
        # 参考值独立使用条件表达式，避免复用被测候选归并结果。
        text = re.sub(r"(?ms)^    case\b.*?^    endcase\n", "", text)
        text = re.sub(r"\bincoming_req_(index|epoch)\b", lambda found: "reference_" + found[0], text)
    saved_address = re.search(r"request_addr_q\s*<=\s*(.*?);", source)
    if saved_address is None:
        raise ValueError("Cannot find the saved request address")
    return text + f"\nassign {prefix}_request_address_value={saved_address[1]};\n"


def inputs(lanes):
    return {**INPUTS, "column_lane_allowed_q": lanes + 1,
            "active_lane_allowed_q": lanes + 1, "group_lane_allowed": lanes,
            "word_available_q": lanes}


def declarations(values, direction=""):
    result = []
    for name, width in values.items():
        shape = " [4:0][31:0]" if name == "epoch_o_sum" else \
            " [9:0][31:0]" if name == "incoming_pixel_candidates" else \
            " [9:0][34:0]" if name == "incoming_y_candidates" else (f" [{width-1}:0]" if width > 1 else "")
        result.append(f"{direction}logic{shape} {name}")
    return result


def reference_preparation(source, geometry):
    if "begin : g_parallel_request_index" in source:
        text = section(source, "  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index",
                       "  // 换核位置的元数据")
        text = re.sub(r"\bincoming_req_(index|epoch)\b", lambda found: "reference_" + found[0], text)
        # 参考表达式只读取入站索引和纪元，移除其余未使用的组合选择输出。
        if "  if (1) begin : g_request_epoch" in text:
            text = text[:text.index("  if (1) begin : g_request_epoch")]
        text = re.sub(r"(?m)^\s*logic\s+[^;]*\brequest_(?:select|candidate)\s*;\n", "", text)
        text = re.sub(r"(?m)^\s*assign\s+request_(?:select|candidate)\[[^;]*;\n", "", text)
        text = re.sub(r"(?ms)^\s*onehot_mux\s*#\([^;]*?\)\s+u_request_select\s*\([^;]*?\);\n", "", text)
        if re.search(r"\brequest_(?:select|candidate|y_selected|index_selected|epoch_selected)\b", text):
            raise ValueError("参考模型包含未处理的请求选择依赖")
        return '''if (1) begin : g_reference_preparation
  logic [1:0][31:0] incoming_epoch_candidate;
''' + text + "\nend\n"
    text = normalize_stream("\n".join(assignment(geometry, name) for name in
        ("incoming_epoch_channel", "o_incoming_req_index", "o_incoming_req_epoch")))
    return re.sub(r"\bincoming_req_(index|epoch)\b", lambda found: "reference_" + found[0], text)


def selection_model(current, reference, geometry):
    """独立遍历请求来源资格，覆盖其所有运行阶段组合。"""
    ports = {**INPUTS, "descriptor_context": 1, "row_context": 1,
             "tap_context": 1, "stream_context": 1, "cache_req_addr": 32}
    preparation = section(current, "  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index",
                          "  // 换核位置的元数据")
    prepared_reference = reference_preparation(reference, geometry)
    values = "\n".join(";\n".join(declarations({prefix + "_" + name: width for name, width in FIELDS.items()})) + ";"
                       for prefix in ("actual", "expected"))
    return "module proof #(parameter bit REGISTER_DESCRIPTOR=0)(\n" + ",\n".join(
        declarations(ports, "input ") + ["output logic equivalent", "output logic [163:0] actual_value, expected_value"]) + ''');
  import conv_im2col_pkg::*;
  localparam int COORD_W=35,LINE_BYTES=128;
  conv_cfg_t c;
  logic request_descriptor_metadata_context,request_row_metadata_context,request_tap_context,request_stream_context;
  logic [31:0] incoming_pixel,incoming_req_index,incoming_req_epoch,incoming_epoch_channel,request_address_value;
  logic [31:0] reference_incoming_req_index,reference_incoming_req_epoch;
  logic [31:0] request_epoch_selected,request_index_selected,request_progress_selected;
  logic [34:0] incoming_iy,request_y_selected;
  logic [1:0][31:0] incoming_epoch_candidate;
  always_comb begin c='0;c.input_s16=input_s16;c.group_offset=group_offset;end
  assign request_descriptor_metadata_context=!REGISTER_DESCRIPTOR && descriptor_context;
  assign request_row_metadata_context=row_context;
  assign request_tap_context=tap_context;
  assign request_stream_context=stream_context;
  assign request_address_value=request_row_metadata_context ? next_row_addr : cache_req_addr;
''' + "assign incoming_pixel=" + " | ".join(
            f"(incoming_pixel_candidates[{candidate}] & {{32{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + \
        "assign incoming_iy=" + " | ".join(
            f"(incoming_y_candidates[{candidate}] & {{35{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + values + "\n" + prepared_reference + "\n" + preparation + \
        "\n" + metadata(current, "actual") + "\n" + metadata(reference, "expected") + \
        "\nassign actual_value={" + ",".join("actual_" + name for name in FIELDS) + "};\n" + \
        "assign expected_value={" + ",".join("expected_" + name for name in FIELDS) + "};\n" + \
        "assign equivalent=actual_value===expected_value;\nendmodule\n"


def mapping_model(source):
    ports = {**INPUTS, "request_descriptor_metadata_context": 1,
             "request_row_metadata_context": 1, "request_tap_context": 1,
             "request_stream_context": 1, "request_pending": 1,
             "cache_port_ready": 1, "cache_req_addr": 32}
    outputs = {"request_y_q": 16, "request_index_q": 32,
               "request_epoch_q": 32, "request_progress_q": 32}
    preparation = section(source, "  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index",
                          "  // 换核位置的元数据")
    values = ";\n".join(declarations({"actual_" + name: width for name, width in FIELDS.items()})) + ";\n"
    return "module metadata_mapping(input logic clk,\n" + ",\n".join(
        declarations(ports, "input ") + declarations(outputs, "output ")) + ''');
import conv_im2col_pkg::*;
localparam int COORD_W=35,LINE_BYTES=128;
localparam bit REGISTER_DESCRIPTOR=0;
conv_cfg_t c;
always_comb begin c='0;c.input_s16=input_s16;c.group_offset=group_offset;end
logic [31:0] request_epoch_selected,request_index_selected,request_progress_selected;
logic [31:0] incoming_pixel,incoming_req_index,incoming_req_epoch,request_address_value;
logic [1:0][31:0] incoming_epoch_candidate;
logic [34:0] request_y_selected,incoming_iy;
''' + "assign incoming_pixel=" + " | ".join(
            f"(incoming_pixel_candidates[{candidate}] & {{32{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + \
        "assign incoming_iy=" + " | ".join(
            f"(incoming_y_candidates[{candidate}] & {{35{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + \
        "assign request_address_value=request_row_metadata_context ? next_row_addr : cache_req_addr;\n" + \
        values + preparation + metadata(source, "actual") + '''
always_ff @(posedge clk) begin
  if (!request_pending || cache_port_ready) begin
    request_index_q <= actual_req_index;
    request_epoch_q <= actual_req_epoch;
    request_y_q <= actual_request_y[15:0];
    request_progress_q <= actual_request_output_y;
  end
end
endmodule
'''


def coverage_declarations(width):
    if FOUR_STATE_SAMPLES - KNOWN_SELECTION_SAMPLES < width:
        raise ValueError("四态样本数不足以覆盖每个输入位")
    return f'''logic [{width-1}:0] applied,seen_x='0,seen_z='0;
logic [31:0] seen_shift='0;
logic [9:0] seen_candidate='0;
'''


def inject_unknowns(widths):
    width = sum(widths.values())
    packed = "{" + ",".join(widths) + "}"
    return f'''if(sample>={KNOWN_SELECTION_SAMPLES})begin
  pattern={packed};
  pattern[(sample-{KNOWN_SELECTION_SAMPLES})%{width}]=1'bx;
  pattern[(sample-{KNOWN_SELECTION_SAMPLES}+{width//2})%{width}]=1'bz;
  {packed}=pattern;
end
'''


def record_coverage(widths):
    width = sum(widths.values())
    packed = "{" + ",".join(widths) + "}"
    return f'''applied={packed};
for(integer bit_index=0;bit_index<{width};bit_index++)begin
  if(applied[bit_index]===1'bx)seen_x[bit_index]=1'b1;
  if(applied[bit_index]===1'bz)seen_z[bit_index]=1'b1;
end
if(sample<{KNOWN_SELECTION_SAMPLES})seen_shift[window_index_shift_q]=1'b1;
for(integer candidate=0;candidate<10;candidate++)begin
  if(incoming_pixel_select===(10'b1<<candidate))seen_candidate[candidate]=1'b1;
end
'''


def check_coverage(width):
    return f'''if(seen_x!=='1 || seen_z!=='1 || seen_shift!=='1 || seen_candidate!=='1)
  $fatal(1,"Incomplete input coverage x=%0d z=%0d shifts=%0d candidates=%0d",
    $countones(seen_x),$countones(seen_z),$countones(seen_shift),$countones(seen_candidate));
$display("REQUEST_METADATA_INPUT_COVERAGE x_bits={width} z_bits={width} shifts=32 candidates=10");
'''


def selection_four_state_test(descriptor):
    widths = {**INPUTS, "descriptor_context": 1, "row_context": 1,
              "tap_context": 1, "stream_context": 1, "cache_req_addr": 32}
    width = sum(widths.values())
    padded = (width + 31) // 32 * 32
    return "module tb;\n" + ";\n".join(declarations(widths)) + ''';
logic equivalent;
logic [163:0] actual_value,expected_value;
logic [511:0] seen_context_shift='0;
logic [7:0] seen_unknown_control='0;
logic seen_zero=0,seen_multiple=0;
''' + coverage_declarations(width) + \
        f"logic [{padded-1}:0] pattern;\nproof #(.REGISTER_DESCRIPTOR({descriptor})) dut(.*);\n" + \
        f"initial begin\nfor(integer sample=0;sample<{FOUR_STATE_SAMPLES};sample++)begin\n" + \
        f"for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;\n" + \
        "{" + ",".join(widths) + "}=pattern;\n" + '''
  {descriptor_context,row_context,tap_context,stream_context}=4'(sample);
  window_index_shift_q=5'(sample/16);
  incoming_pixel_select=10'b1<<(sample%10);
''' + f"  if(sample>={KNOWN_SELECTION_SAMPLES})begin\n" + '''
    if(sample%4==2)incoming_pixel_select='0;
    if(sample%4==3)incoming_pixel_select='1;
    if(sample%17==0)incoming_pixel_select[(sample/17)%10]=1'bx;
    if(sample%19==0)incoming_pixel_select[(sample/19)%10]=1'bz;
    if(sample%23==0)short_pixel_q=1'bx;
    if(sample%29==0)window_index_shift_q='x;
    case(sample%8)
      0:descriptor_context=1'bx;
      1:descriptor_context=1'bz;
      2:row_context=1'bx;
      3:row_context=1'bz;
      4:tap_context=1'bx;
      5:tap_context=1'bz;
      6:stream_context=1'bx;
      7:stream_context=1'bz;
    endcase
  end
''' + inject_unknowns(widths) + '''
  #1;
  if(equivalent!==1'b1)$fatal(1,"Selection mismatch sample=%0d actual=%h expected=%h",sample,actual_value,expected_value);
''' + record_coverage(widths) + f'''if(sample<{KNOWN_SELECTION_SAMPLES})
  seen_context_shift[{{window_index_shift_q,descriptor_context,row_context,tap_context,stream_context}}]=1'b1;
''' + '''
  if(descriptor_context===1'bx)seen_unknown_control[0]=1;
  if(descriptor_context===1'bz)seen_unknown_control[1]=1;
  if(row_context===1'bx)seen_unknown_control[2]=1;
  if(row_context===1'bz)seen_unknown_control[3]=1;
  if(tap_context===1'bx)seen_unknown_control[4]=1;
  if(tap_context===1'bz)seen_unknown_control[5]=1;
  if(stream_context===1'bx)seen_unknown_control[6]=1;
  if(stream_context===1'bz)seen_unknown_control[7]=1;
  if(incoming_pixel_select==='0)seen_zero=1;
  if(incoming_pixel_select==='1)seen_multiple=1;
end
''' + check_coverage(width) + '''
if(seen_context_shift!=='1 || seen_unknown_control!=='1 || !seen_zero || !seen_multiple)
  $fatal(1,"Incomplete source-selection coverage");
$display("REQUEST_SELECTION_COVERAGE context_shift_pairs=512 unknown_controls=8 zero_selection=1 multiple_selection=1");
''' + f'$display("REQUEST_SELECTION_FOUR_STATE_PASS checks={FOUR_STATE_SAMPLES}");\n' + \
        "$finish;\nend\nendmodule\n"


def model(current, reference, stream, geometry, lanes):
    for helper, instance in (("conv_im2col_chunk_lane", "u_static_end"),
                             ("conv_im2col_chunk_end_select", "u_end")):
        if "module " + helper in stream:
            stream = inline_control(stream, helper, instance)
    stream = re.sub(r"\(([A-Za-z_]\w*)\)(?=\[)", r"\1", stream)
    controls = "\n".join(assignment(current, name) for name in
                         ("wr_valid", "wr_last", "finishing_tile", "tile_ready_context", "tile_ready"))
    if "assign stream_output_accept" in current:
        controls += "\n" + assignment(current, "stream_output_accept")
    request_control = ""
    request_names = ("incoming_request", "o_cache_req_valid")
    if "module conv_im2col_request_control" in stream:
        expanded = inline_control(stream, "conv_im2col_request_control", "u_request_control")
        request_control = section(expanded, "  logic descriptor_request;", "  assign o_incoming_context")
        request_names = ()
    stream_controls = "\n".join(assignment(stream, name) for name in (
        "stream_context", "stream_request_eligible", "row_request_eligible",
        "o_stream_next_request", "o_request_stream_context", "o_request_row_context",
        "o_request_tap_context", "o_next_row_request", *request_names,
        "o_incoming_context", "o_cache_req_addr")) + "\n" + request_control
    if "module conv_im2col_stream_control" in stream:
        expanded = inline_control(stream, "conv_im2col_stream_control", "u_stream_control")
        stream_controls += "\n" + section(expanded,
            "  // 各运行来源先形成目标状态", "  // 接收条件只改变 FETCH")
    else:
        stream_controls += "\n" + section(stream, "  always_comb begin\n    stream_static_state = FETCH;",
                                          "  always_comb begin\n    o_stream_advance_state")
    remaining = section(stream, "  if (p_tile_count_w >= p_chunk_count_w) begin : g_stream_remaining",
                        "  assign stream_context")
    lanes_logic = section(stream, "  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_word_lane",
                          "  // 八位输入的配置偏移范围")
    count_logic = section(stream, "  always_comb begin\n    group_remaining=", "  // 字节移位仅选择")
    static_context = assignment(current, "request_row_metadata_context")
    if "assign request_descriptor_metadata_context" in current:
        static_context += "\n" + "\n".join(assignment(current, name) for name in
            ("descriptor_payload_context", "request_descriptor_metadata_context"))
    if "begin : g_parallel_request_address" in current:
        # 实际双地址归并电路由前置检查证明等价，此处组合其完整语义验证元数据。
        static_context += "\nassign request_address_value=request_row_metadata_context ? next_row_addr : cache_req_addr;"
    else:
        static_context += "\n" + (assignment(current, "request_address_value") if "assign request_address_value" in current else
                                  "assign request_address_value=cache_req_addr;")
    prepared_reference = reference_preparation(reference, geometry)
    if "begin : g_parallel_request_index" in current:
        preparation = section(current, "  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index",
                              "  // 换核位置的元数据")
    else:
        preparation = "assign incoming_req_index=reference_incoming_req_index;\nassign incoming_req_epoch=reference_incoming_req_epoch;\n"
    outputs = ["output logic equivalent", "output logic range_exclusive", "output logic observed",
               "output logic [163:0] actual_value, expected_value"]
    ports = declarations(inputs(lanes), "input ") + outputs
    values = "\n".join(";\n".join(declarations({prefix + "_" + name: width for name, width in FIELDS.items()})) + ";"
                       for prefix in ("actual", "expected"))
    return "module proof #(parameter bit REGISTER_DESCRIPTOR=0, REGISTER_ROW_ADDRESS=0, REGISTER_CACHE_REQUEST=1)(\n" + \
        ",\n".join(ports) + ''');
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
''' + f"  localparam int p_lanes={lanes};\n" + '''
  localparam int p_size=16, p_rw=5, LINE_BYTES=128, p_line_bytes=LINE_BYTES, p_narrow_lanes=8, p_tile_count_w=5, COORD_W=35;
  localparam int p_chunk_count_w=$clog2(p_lanes+1), p_cache_read_bytes=p_lanes;
  localparam int p_word_shift=$clog2(p_lanes);
  localparam bit p_saved_word_range=1;
  localparam bit p_register_descriptor=REGISTER_DESCRIPTOR;
  localparam bit p_register_row_address=REGISTER_ROW_ADDRESS;
  localparam bit p_register_cache_request=REGISTER_CACHE_REQUEST;
  logic [26:0] state;
  st_t stream_static_state;
  conv_cfg_t c;
  logic wr_valid,wr_last,finishing_tile,tile_ready_context,tile_ready,stream_output_accept;
  logic request_row_metadata_context,request_descriptor_metadata_context,descriptor_payload_context;
  logic [31:0] request_address_value,cache_req_addr;
  logic [31:0] request_epoch_selected;
  logic [COORD_W-1:0] request_y_selected,incoming_iy;
  logic [31:0] request_index_selected,request_progress_selected;
  logic [31:0] incoming_pixel,incoming_req_index,incoming_req_epoch,incoming_epoch_channel;
  logic [31:0] reference_incoming_req_index,reference_incoming_req_epoch;
  logic [1:0][31:0] incoming_epoch_candidate;
  logic stream_context,stream_request_eligible,row_request_eligible;
  logic stream_next_request,request_stream_context,request_row_context,request_tap_context;
  logic next_row_request,incoming_request,cache_req_valid,incoming_context;
  logic stream_request_selected,stream_row_selected,stream_tap_selected;
  logic column_after_chunk,active_after_chunk,chunk_reaches_end;
  logic [p_lanes-1:0] word_lane_s8,word_lane_s16,word_lane_allowed;
  logic [p_lanes-1:0] lane_context_allowed,chunk_data_allowed,chunk_lane_allowed;
  logic [p_lanes-1:0] chunk_static_end,chunk_end_s8,chunk_end_s16;
  logic [p_chunk_count_w-1:0] chunk_count;
  logic [4:0] col_remaining,active_remaining;
  logic [16:0] group_remaining;
  logic [15:0] ch_q;
  assign state=27'b1<<state_index;
  always_comb begin c='0;c.input_s16=input_s16;c.group_offset=group_offset;end
  assign ch_q='0;
  assign col_remaining='0;
  assign active_remaining='0;
''' + "assign incoming_pixel=" + " | ".join(
            f"(incoming_pixel_candidates[{candidate}] & {{32{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + \
        "assign incoming_iy=" + " | ".join(
            f"(incoming_y_candidates[{candidate}] & {{35{{incoming_pixel_select[{candidate}]}}}})"
            for candidate in range(10)) + ";\n" + values + "\n" + controls + "\n" + normalize_stream(remaining + lanes_logic + count_logic + stream_controls) + \
        "\n" + prepared_reference + "\n" + preparation + \
        "\n" + static_context + "\n" + metadata(current, "actual") + "\n" + metadata(reference, "expected") + \
        "\nassign actual_value={" + ",".join("actual_" + name for name in FIELDS) + "};\n" + \
        "assign expected_value={" + ",".join("expected_" + name for name in FIELDS) + "};\n" + \
        "assign observed=cache_req_valid===1'b1;\n" + \
        "assign equivalent=actual_value===expected_value;\n" + \
        "assign range_exclusive=!(column_after_chunk && chunk_reaches_end);\nendmodule\n"


def four_state_test(lanes, descriptor, row, request):
    widths = inputs(lanes)
    width = sum(widths.values())
    padded = (width + 31) // 32 * 32
    return "module tb;\n" + ";\n".join(declarations(widths)) + ''';
 logic equivalent,range_exclusive,observed;
 logic [163:0] actual_value,expected_value;
 integer checks=0,requests=0,static_rows=0;
logic [27:0] seen_state='0;
''' + coverage_declarations(width) + f"logic [{padded-1}:0] pattern;\n" + \
        f"proof #(.REGISTER_DESCRIPTOR({descriptor}),.REGISTER_ROW_ADDRESS({row}),.REGISTER_CACHE_REQUEST({request})) dut(.*);\n" + '''
 initial begin
''' + f"  for(integer sample=0;sample<{FOUR_STATE_SAMPLES};sample++)begin\n" + \
        f"for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;\n" + \
        "{" + ",".join(widths) + "}=pattern;\n" + '''
   state_index=5'(sample%28);
   window_index_shift_q=5'(sample/16);
   incoming_pixel_select=10'b1<<(sample%10);
   if(sample[3:0]==0)begin
     state_index=$clog2(conv_im2col_frontend_pkg::STREAM);
     row_last_q=0;row_base_valid=1;geometry_tile=0;
     next_row_padding=0;next_row_word_hit=0;wr_ready=1;
     narrow_output=0;word_output_q=0;past_active_q=1;
     column_lane_allowed_q=1;active_lane_allowed_q='1;group_lane_allowed='1;
   end
   if(sample[3:0]==1)begin
     state_index=$clog2(conv_im2col_frontend_pkg::FETCH);
     current_word_hit=0;
   end
''' + inject_unknowns(widths) + '''
   #1;
   if(equivalent!==1'b1)$fatal(1,"Metadata mismatch sample=%0d state=%0d actual=%h expected=%h",sample,state_index,actual_value,expected_value);
   if(range_exclusive===1'b0)$fatal(1,"Column and row request ranges overlap");
   if(observed)requests++;
   if(dut.request_row_metadata_context===1'b1)static_rows++;
''' + record_coverage(widths) + '''
   if(state_index<28)seen_state[state_index]=1'b1;
   checks++;
  end
''' + check_coverage(width) + '''
  if(seen_state!=='1)$fatal(1,"Incomplete frontend state coverage");
  $display("REQUEST_METADATA_STATE_COVERAGE state_encodings=28");
  if(requests<40)$fatal(1,"Insufficient valid request checks");
  $display("REQUEST_METADATA_FOUR_STATE_PASS checks=%0d requests=%0d static_rows=%0d",checks,requests,static_rows);
  $finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    refs = parser.add_mutually_exclusive_group(required=True)
    refs.add_argument("--reference-ref")
    refs.add_argument("--reference-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    parser.add_argument("--jobs", type=int, default=2, help="Concurrent four-state simulations; formal partitions run sequentially")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / FRONTEND).read_text()
    stream = (root / STREAM).read_text()
    geometry_file = root / "rtl/npu/conv/conv_im2col_geometry.sv"
    geometry = geometry_file.read_text()
    reference = read_reference_file(root, args.reference_ref, str(FRONTEND), text=True) \
        if args.reference_ref else args.reference_file.read_text()
    packages = [root / "rtl/npu/conv/conv_im2col_pkg.sv", root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv",
                root / "rtl/common/onehot_mux.sv"]
    tracked = [root / FRONTEND, root / STREAM, geometry_file, *packages, Path(__file__).resolve(),
               Path(__file__).with_name("check_request_qualification.py")]
    hashes = {str(path): digest(path) for path in tracked}
    address_verification = None
    if "begin : g_parallel_request_address" in current:
        address_out = out / "address_selection"
        subprocess.run([sys.executable, str(root / "test/conv_frontend/tools/check_request_address_selection.py"),
                        "--source-root", str(root), "--out", str(address_out),
                        "--iverilog", args.iverilog, "--vvp", args.vvp], check=True)
        address_report = address_out / "summary.json"
        if not json.loads(address_report.read_text())["passed"]:
            raise RuntimeError(str(address_report))
        address_verification = {"summary": str(address_report), "sha256": digest(address_report)}
    selected = out / "selection_model.sv"
    selected.write_text(selection_model(current, reference, geometry).replace("always_comb", "always @*"))
    mapping = out / "mapping"
    mapping.mkdir(exist_ok=True)
    mapping_cases = {}
    for name, source in (("reference", reference), ("candidate", current)):
        generated = mapping / (name + ".sv")
        generated.write_text(mapping_model(source))
        mapping_cases[name] = {"top": "metadata_mapping", "options": ["-D", "SYNTHESIS=1"],
                               "sources": [str(packages[0]), str(generated)],
                               "configuration": "Production request metadata selection with its existing register write enable"}
    (mapping / "cases.json").write_text(json.dumps(mapping_cases, indent=2) + "\n")
    metadata_formal = []
    for descriptor in (0, 1):
        name = f"selection_descriptor{descriptor}"
        ys, formal = out / (name + ".ys"), out / (name + ".formal.log")
        shifts = range(32) if not descriptor else (None,)
        commands = []
        for shift in shifts:
            commands.append("design -load prepared")
            if shift is not None:
                commands += [f"connect -set window_index_shift_q 5'd{shift}", "opt -full"]
            commands.append("sat -verify -prove equivalent 1 -show-inputs -show-outputs")
        ys.write_text("read_slang --top proof " + f"-GREGISTER_DESCRIPTOR={descriptor} " +
                      shlex.join(map(str, [*packages, selected])) +
                      "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
                      "prep -top proof -flatten\ncheck -assert\ndesign -save prepared\n" +
                      "\n".join(commands) + "\n")
        with formal.open("w") as output:
            result = subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(ys)],
                                    stdout=output, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode or formal.read_text().count("SAT proof finished - no model found: SUCCESS!") != len(shifts):
            raise RuntimeError(str(formal))
        tb, binary, build, simulation = (out / (name + suffix) for suffix in
                                          (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(selection_four_state_test(descriptor))
        with build.open("w") as output:
            subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                            *map(str, [*packages, selected, tb])], stdout=output, stderr=subprocess.STDOUT, check=True)
        with simulation.open("w") as output:
            subprocess.run([args.vvp, str(binary)], stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
        if f"REQUEST_SELECTION_FOUR_STATE_PASS checks={FOUR_STATE_SAMPLES}" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        metadata_formal.append({"register_descriptor": descriptor, "formal_partitions": len(shifts),
                                "formal_sha256": digest(formal), "passed": True,
                                "four_state_checks": FOUR_STATE_SAMPLES,
                                "four_state_coverage": {"input_bits_with_x_and_z": sum(INPUTS.values()) + 36,
                                    "shift_context_pairs": 512, "pixel_candidates": 10,
                                    "unknown_source_controls": 8, "zero_and_multiple_selections": True},
                                "four_state_sha256": digest(simulation)})
        print("REQUEST_SELECTION_FORMAL_PASS", name, "partitions=" + str(len(shifts)), flush=True)

    simulations = []
    for lanes in (8, 16):
        generated = out / f"model_lanes{lanes}.sv"
        generated.write_text(model(current, reference, stream, geometry, lanes).replace("always_comb", "always @*"))
        for descriptor, row, request in itertools.product((0, 1), repeat=3):
            name = f"lanes{lanes}_descriptor{descriptor}_row{row}_request{request}"
            ys, formal = out / (name + ".ys"), out / (name + ".formal.log")
            commands = ["sat -verify -prove range_exclusive 1 -show-inputs -show-outputs"]
            ys.write_text("read_slang --top proof " +
                          f"-GREGISTER_DESCRIPTOR={descriptor} -GREGISTER_ROW_ADDRESS={row} -GREGISTER_CACHE_REQUEST={request} " +
                          shlex.join(map(str, [*packages, generated])) +
                          "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
                          "prep -top proof -flatten\ncheck -assert\n" + "\n".join(commands) + "\n")
            with formal.open("w") as output:
                result = subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(ys)],
                                        stdout=output, stderr=subprocess.STDOUT, timeout=300)
            if result.returncode or formal.read_text().count("SAT proof finished - no model found: SUCCESS!") != len(commands):
                raise RuntimeError(str(formal))
            tb, binary, build, simulation = (out / (name + suffix) for suffix in (".sv", ".vvp", ".build.log", ".four_state.log"))
            tb.write_text(four_state_test(lanes, descriptor, row, request))
            with build.open("w") as output:
                subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary), *map(str, [*packages, generated, tb])],
                               stdout=output, stderr=subprocess.STDOUT, check=True)
            simulations.append((name, binary, simulation,
                {"lanes": lanes, "register_descriptor": descriptor, "register_row_address": row,
                 "register_cache_request": request, "formal_passed": True, "formal_partitions": len(commands),
                 "metadata_formal_configuration": f"selection_descriptor{descriptor}",
                 "formal_sha256": digest(formal)}))
            print("REQUEST_METADATA_FORMAL_PASS", name, "partitions=" + str(len(commands)), flush=True)

    def simulate(specification):
        name, binary, simulation, row = specification
        with simulation.open("w") as output:
            subprocess.run([args.vvp, str(binary)], stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
        match = re.search(r"PASS checks=(\d+) requests=(\d+) static_rows=(\d+)", simulation.read_text())
        if match is None or int(match[1]) != FOUR_STATE_SAMPLES:
            raise RuntimeError(str(simulation))
        row.update(four_state_checks=int(match[1]), valid_requests=int(match[2]), static_row_selections=int(match[3]),
                   four_state_coverage={"input_bits_with_x_and_z": sum(inputs(row["lanes"]).values()),
                       "shifts": 32, "pixel_candidates": 10, "state_encodings": 28},
                   simulation_sha256=digest(simulation))
        print("REQUEST_METADATA_FOUR_STATE_PASS", name, "requests=" + match[2], flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        cases = list(executor.map(simulate, simulations))
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "source_sha256": hashes, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(), "cases": cases,
              "metadata_formal": metadata_formal, "address_selection": address_verification,
              "local_mapping_cases": str(mapping / "cases.json"),
              "configuration": {"size": 16, "line_bytes": 128},
              "metadata_bits": sum(FIELDS.values()), "domain":
              "Formal metadata checks cover independent descriptor, row, tap and stream qualifications, arbitrary metadata and all pixel selections. Four-state checks compare all fields on every sample, cover all 32 shifts and 16 source combinations, inject X and Z at every input bit, and cover every frontend state and both lane counts with all eight register configurations",
              "range_property": "The source expressions prove column_after_chunk and chunk_reaches_end are mutually exclusive"}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
