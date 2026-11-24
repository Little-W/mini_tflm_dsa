#!/usr/bin/env python3
"""验证坐标及组地址预选在每个保存边沿保持完整数值与更新条件。"""
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
from check_stream_admission import normalize_stream_control

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
FIELDS = ("ix", "iy", "pixel_index", "tap_group_base", "row_group_base")
INPUTS = {
    "state_index": 5, "rst_n": 1, "cfg_valid": 1, "cfg_ready": 1,
    "tile_valid": 1, "tile_prepared_valid": 1, "error": 1,
    "tile_ready_static": 1, "wr_ready": 1, "cache_rsp_valid": 1,
    "cache_rsp_error": 1, "row_last_q": 1, "chunk_reaches_end": 1,
    "past_active_q": 1, "active_after_chunk": 1, "group_end_o_equal": 1,
    "coordinate_address_valid": 1, "row_base_valid": 1, "geometry_tile": 1,
    "row_coordinate_valid": 1, "col_idx": 5, "commit_invalid": 1, "commit_fast": 1,
    "commit_input_x": 33, "commit_input_y": 33, "commit_pixel": 32, "commit_group_address": 32,
    "ix": 33, "iy": 33, "pixel_index": 32, "tap_group_base": 32, "row_group_base": 32,
    "next_row_ix": 33, "next_row_iy": 33, "next_tap_ix": 33, "next_tap_iy": 33,
    "coordinate_padded_x": 33, "coordinate_padded_y": 33,
    "next_row_pixel": 32, "next_tap_pixel": 32, "next_row_group_base": 32,
    "next_tap_addr": 32, "pixel_product": 32, "group_base_addr": 32,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise ValueError(name)
    return match.group()


def selected_payload(source, prefix, normalize=False):
    start = source.index("  // 保存前端配置、描述符和坐标状态。")
    stop = source.index("  // 解码计数与坐标运算", start)
    body = source[start:stop]
    counts = dict.fromkeys(FIELDS, 0)

    def selected(text):
        match = re.fullmatch(r"(\w+)\s*<=\s*(.*);", text, re.S)
        if match is None or match[1] not in FIELDS:
            return ""
        counts[match[1]] += 1
        rhs = "selected_value" if normalize else match[2]
        return f"{prefix}_{match[1]} = {rhs};"

    parsed = Statements(body[body.index("begin"):], select_assignment=selected).statement()
    expected = {"ix": 7, "iy": 7, "pixel_index": 5, "tap_group_base": 5, "row_group_base": 4}
    if counts != expected:
        raise ValueError(f"Unexpected payload assignment coverage: {counts}")
    return parsed, counts


def declarations(direction=""):
    return [f"{direction}logic" + (f" [{width-1}:0]" if width > 1 else "") + " " + name
            for name, width in INPUTS.items()]


def model(current, reference):
    expected, counts = selected_payload(reference, "expected")
    actual, actual_counts = selected_payload(current, "actual")
    reference_shape, _ = selected_payload(reference, "value", normalize=True)
    comparable = normalize_stream_control(current) if 'assign stream_operation_accept =' in current else current
    candidate_shape, _ = selected_payload(comparable, "value", normalize=True)
    if reference_shape != candidate_shape or counts != actual_counts:
        raise ValueError("Payload update conditions changed")
    first = current.index("  // 数据来源由运行阶段提前选择")
    last = current.index("  // 请求地址、窗口索引和有效位同时寄存", first)
    controls = "\n".join(assignment(current, name) for name in
                         ("wr_valid", "wr_last", "finishing_tile", "tile_ready_context", "tile_ready"))
    if 'assign stream_operation_accept =' in current:
        controls += '\n' + '\n'.join(assignment(current, name) for name in (
            'stream_response_error', 'stream_output_accept', 'stream_operation_accept',
            'tile_admission_ready', 'descriptor_commit_eligible', 'descriptor_state_context'))
    ports = declarations("input ") + ["output logic equivalent", "output logic [161:0] actual_value, expected_value"]
    state = "\n".join("  logic " + ("[32:0]" if name in ("ix", "iy") else "[31:0]") +
                       f" actual_{name}, expected_{name};" for name in FIELDS)
    default_actual = "\n".join(f"actual_{name}={name};" for name in FIELDS)
    default_expected = "\n".join(f"expected_{name}={name};" for name in FIELDS)
    return "module proof #(parameter bit REGISTER_DESCRIPTOR=0)(\n" + ",\n".join(ports) + ''');
  import conv_im2col_frontend_pkg::*;
  localparam int COORD_W=33;
  logic [26:0] state;
  logic wr_valid,wr_last,finishing_tile,tile_ready_context,tile_ready,tile_commit;
  logic stream_response_error,stream_output_accept,stream_operation_accept;
  logic tile_admission_ready,descriptor_commit_eligible,descriptor_state_context;
  wire cache_rsp_success=cache_rsp_valid&&!cache_rsp_error;
  wire cache_rsp_failure=cache_rsp_valid&&cache_rsp_error;
  logic descriptor_payload_context;
  logic [1:0][COORD_W-1:0] coordinate_payload;
  logic [31:0] pixel_payload,tap_group_payload,row_group_payload;
  typedef struct packed {
    logic invalid,fast;
    logic [32:0] input_x,input_y;
    logic [31:0] pixel,group_address;
  } tile_t;
  tile_t committing_tile;
  assign committing_tile={commit_invalid,commit_fast,commit_input_x,commit_input_y,commit_pixel,commit_group_address};
  assign state=27'b1<<state_index;
  assign tile_commit=REGISTER_DESCRIPTOR ?
      tile_prepared_valid&&!error&&(state[$clog2(IDLE)]||finishing_tile) : tile_valid&&tile_ready;
''' + state + "\n" + controls + "\n" + current[first:last] + "\n" + \
        "always_comb begin\n" + default_actual + "\n" + actual + "\nend\n" + \
        "always_comb begin\n" + default_expected + "\n" + expected + "\nend\n" + \
        "assign actual_value={" + ",".join("actual_"+name for name in FIELDS) + "};\n" + \
        "assign expected_value={" + ",".join("expected_"+name for name in FIELDS) + "};\n" + \
        "assign equivalent=actual_value===expected_value;\nendmodule\n"


def four_state_test(registered):
    width = sum(INPUTS.values())
    padded = (width + 31)//32*32
    return "module tb;\n" + ";\n".join(declarations()) + ''';
 logic equivalent;
 logic[161:0]actual_value,expected_value;
 integer checks=0,changes=0;
''' + f"logic[{padded-1}:0]pattern;\nproof #(.REGISTER_DESCRIPTOR({registered})) dut(.*);\n" + '''
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
''' + f"for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;\n" + \
        f"if(sample%3==0)pattern[(sample/3)%{width}]=1'bx;\n" + \
        f"if(sample%5==0)pattern[(sample/5)%{width}]=1'bz;\n" + \
        "{" + ",".join(INPUTS) + "}=pattern;\n" + '''
   state_index=5'(sample%28);
   if(sample[2:0]!=3'b111)begin rst_n=1;cfg_valid=0;end
   #1;
   if(equivalent!==1'b1)$fatal(1,"Payload mismatch sample=%0d state=%0d actual=%h expected=%h",sample,state_index,actual_value,expected_value);
   if(actual_value!=={ix,iy,pixel_index,tap_group_base,row_group_base})changes++;
   checks++;
  end
  if(changes<1000)$fatal(1,"Insufficient payload updates");
  $display("PAYLOAD_CONTEXT_FOUR_STATE_PASS checks=%0d changes=%0d",checks,changes);$finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--reference-ref")
    reference.add_argument("--reference-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = Path("rtl/npu/conv/conv_im2col_frontend.sv")
    source, package = root/relative, root/"rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    if args.reference_ref:
        original = read_reference_file(root, args.reference_ref, str(relative), text=True)
    else:
        original = args.reference_file.read_text()
    generated = out/"model.sv"
    generated.write_text(model(source.read_text(), original).replace("always_comb", "always @*"))
    tracked = [source, package, generated, Path(__file__).resolve(), Path(__file__).with_name("check_state_context.py")]
    hashes = {str(path): digest(path) for path in tracked}
    rows = []
    for registered in (0, 1):
        name = f"descriptor{registered}"
        ys, log = out/(name+".ys"), out/(name+".formal.log")
        ys.write_text(f"read_slang --top proof -GREGISTER_DESCRIPTOR={registered} "+shlex.join(map(str,(package,generated)))+
                      "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as output:
            result = subprocess.run([sys.executable, str(ROOT/"scripts/fpga/open_fpga_synth.py"), "--worker", str(ys)],
                                    stdout=output, stderr=subprocess.STDOUT, timeout=120)
        if result.returncode or "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        print("PAYLOAD_CONTEXT_FORMAL_PASS",name,flush=True)
        tb, binary, build, simulation = (out/(name+suffix) for suffix in
                                         (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(four_state_test(registered))
        with build.open("w") as output:
            subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),*map(str,(package,generated,tb))],
                           stdout=output,stderr=subprocess.STDOUT,check=True)
        with simulation.open("w") as output:
            subprocess.run([args.vvp,str(binary)],stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
        match = re.search(r"PASS checks=(\d+) changes=(\d+)",simulation.read_text())
        if match is None or int(match[1]) != 65536:
            raise RuntimeError(str(simulation))
        rows.append({"register_descriptor":registered,"formal_passed":True,"four_state_checks":int(match[1]),
                     "changed_payloads":int(match[2]),"formal_log_sha256":digest(log),"simulation_log_sha256":digest(simulation)})
        print("PAYLOAD_CONTEXT_FOUR_STATE_PASS",name,flush=True)
    if hashes != {str(path):digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed":True,"source_sha256":hashes,"reference_ref":args.reference_ref,
              "reference_sha256":hashlib.sha256(original.encode()).hexdigest(),"cases":rows,
              "payload_bits":162,"assignment_sites":28,"update_structure_preserved":True,
              "domain":"All 27 one-hot states and the zero state; arbitrary payloads, reset, configuration, descriptor and stream backpressure inputs"}
    (out/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print("PAYLOAD_CONTEXT_PASS",flush=True)


if __name__ == "__main__":
    main()
