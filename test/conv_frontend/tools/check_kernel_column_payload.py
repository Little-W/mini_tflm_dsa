#!/usr/bin/env python3
"""验证卷积核列数据预选的完整写入条件、数值和四态语义。"""
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

from check_state_context import Statements, assignment, digest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")
INPUTS = {
    "state_index": 5, "rst_n": 1, "cfg_valid": 1, "cfg_ready": 1,
    "tile_valid": 1, "tile_prepared_valid": 1, "error": 1,
    "tile_ready_static": 1, "wr_ready": 1, "cache_rsp_valid": 1,
    "cache_rsp_error": 1, "row_last_q": 1, "chunk_reaches_end": 1,
    "past_active_q": 1, "active_after_chunk": 1, "group_end_o_equal": 1,
    "coordinate_address_valid": 1, "tap_wrap": 1,
    "commit_invalid": 1, "commit_fast": 1, "commit_kernel_x": 16,
    "kernel_shape_o_valid": 1, "kernel_w": 16, "tap0": 32,
    "k_decode_value": 6, "kernel_decode_column": 16,
    "decode_index": 32, "decode_inner": 32, "kx_q": 16, "kx0_q": 16,
}


def selected_updates(source, prefix, normalize=False):
    first = source.index("  // 保存前端配置、描述符和坐标状态。")
    body = source[first:source.index("  // 解码计数与坐标运算", first)]
    values = []

    def selected(statement):
        match = re.fullmatch(r"kx_q\s*<=\s*(.*);", statement, re.S)
        if match is None:
            return ""
        values.append(match[1].strip())
        value = "selected_value" if normalize else match[1]
        return f"begin {prefix}_value = {value}; {prefix}_site = 4'd{len(values)}; end"

    updates = Statements(body[body.index("begin"):], select_assignment=selected).statement()
    if len(values) != 10:
        raise ValueError(f"Expected all 10 kernel column assignments, found {len(values)}")
    return updates, values


def declarations(direction=""):
    return [f"{direction}logic" + (f" [{width-1}:0]" if width > 1 else "") + " " + name
            for name, width in INPUTS.items()]


def model(current, reference):
    actual, values = selected_updates(current, "actual")
    expected, reference_values = selected_updates(reference, "expected")
    if selected_updates(current, "value", True)[0] != selected_updates(reference, "value", True)[0]:
        raise ValueError("Kernel column write conditions changed")
    if values[0] != reference_values[0] or values[1:] != ["kernel_column_payload"] * 9:
        raise ValueError("Expected the original reset and nine kernel column payload writes")
    first = current.index("  // 卷积核列数据按运行阶段预选")
    last = current.index("  // 数据来源由运行阶段提前选择", first)
    control_names = (
        "wr_valid", "wr_last", "finishing_tile", "tile_ready_context", "tile_ready",
        "stream_response_error", "stream_output_accept", "stream_operation_accept",
        "tile_admission_ready", "descriptor_commit_eligible", "descriptor_state_context",
        "descriptor_payload_context")
    if any(assignment(current, name) != assignment(reference, name) for name in control_names):
        raise ValueError("Shared kernel column update controls changed")
    controls = "\n".join(assignment(current, name) for name in control_names)
    ports = declarations("input ") + ["output logic equivalent", "output logic [15:0] actual_value,expected_value",
                                      "output logic [3:0] actual_site,expected_site"]
    return "module proof #(parameter bit REGISTER_DESCRIPTOR=0)(\n" + ",\n".join(ports) + ''');
  import conv_im2col_frontend_pkg::*;
  logic [26:0] state;
  logic wr_valid,wr_last,finishing_tile,tile_ready_context,tile_ready,tile_commit;
  logic stream_response_error,stream_output_accept,stream_operation_accept;
  logic tile_admission_ready,descriptor_commit_eligible,descriptor_state_context;
  logic descriptor_payload_context;
  logic [15:0] kernel_column_payload;
  wire cache_rsp_success=cache_rsp_valid&&!cache_rsp_error;
  wire cache_rsp_failure=cache_rsp_valid&&cache_rsp_error;
  wire [31:0] kx=32'(kx_q),kx0=32'(kx0_q);
  typedef struct packed {logic invalid,fast;logic [15:0] kernel_x;} tile_t;
  typedef struct packed {logic [15:0] kernel_w;} config_t;
  tile_t committing_tile;
  config_t c;
  assign committing_tile={commit_invalid,commit_fast,commit_kernel_x};
  assign c.kernel_w=kernel_w;
  assign state=27'b1<<state_index;
  assign tile_commit=REGISTER_DESCRIPTOR ?
      tile_prepared_valid&&!error&&(state[$clog2(IDLE)]||finishing_tile) : tile_valid&&tile_ready;
''' + controls + "\n" + current[first:last] + "\n" + \
        "always_comb begin\nactual_value=kx_q;actual_site=0;\n" + actual + "\nend\n" + \
        "always_comb begin\nexpected_value=kx_q;expected_site=0;\n" + expected + "\nend\n" + \
        "assign equivalent=({actual_site,actual_value}==={expected_site,expected_value});\nendmodule\n"


def four_state_test(registered):
    width = sum(INPUTS.values())
    padded = (width + 31)//32*32
    return "module tb;\nimport conv_im2col_frontend_pkg::*;\n" + ";\n".join(declarations()) + ''';
 logic equivalent;
 logic [15:0] actual_value,expected_value;
 logic [3:0] actual_site,expected_site;
 integer checks=0,changes=0;
 integer site_hits[0:10];
''' + f"logic[{padded-1}:0]pattern;\nproof #(.REGISTER_DESCRIPTOR({registered})) dut(.*);\n" + '''
 initial begin
  for(integer site=0;site<=10;site++)site_hits[site]=0;
  for(integer sample=0;sample<65536;sample++)begin
''' + f"for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;\n" + \
        f"if(sample%3==0)pattern[(sample/3)%{width}]=1'bx;\n" + \
        f"if(sample%5==0)pattern[(sample/5)%{width}]=1'bz;\n" + \
        "{" + ",".join(INPUTS) + "}=pattern;\n" + '''
   state_index=5'(sample%32);
   if(sample[2:0]!=3'b111)begin rst_n=1;cfg_valid=0;end
   if(sample%3==0)decode_index=tap0;
   if(sample%5==0)begin kernel_w=16'd3;tap0=sample%9;end
   if(sample%127==0)state_index=5'bxxxxx;
   if(sample<10)begin
    rst_n=1;cfg_valid=0;tile_valid=0;tile_prepared_valid=0;
    error=0;wr_ready=1;cache_rsp_valid=1;cache_rsp_error=0;
    row_last_q=0;chunk_reaches_end=0;past_active_q=0;
    active_after_chunk=1;group_end_o_equal=1;coordinate_address_valid=1;
    tap_wrap=0;commit_invalid=0;commit_fast=1;tile_ready_static=1;
    state_index=5'($clog2(STREAM));kernel_shape_o_valid=0;
    case(sample)
     0:rst_n=0;
     1:begin state_index=5'($clog2(IDLE));tile_valid=1;tile_prepared_valid=1;end
     2:chunk_reaches_end=1;
     3:tap_wrap=1;
     4:;
     5:begin coordinate_address_valid=0;tap_wrap=1;end
     6:coordinate_address_valid=0;
     7:begin state_index=5'($clog2(K_DECODE));kernel_shape_o_valid=1;end
     8:begin state_index=5'($clog2(K_DECODE));kernel_w=16'd3;tap0=32'd5;end
     9:begin state_index=5'($clog2(K_WAIT));decode_index=tap0;end
    endcase
   end
   #1;
   if(equivalent!==1'b1)$fatal(1,"Kernel column mismatch sample=%0d state=%0d actual=%h expected=%h site=%0d/%0d",
       sample,state_index,actual_value,expected_value,actual_site,expected_site);
   if(sample<10 && expected_site!=sample+1)$fatal(1,"Directed kernel column site coverage failed");
   site_hits[expected_site]++;
   if(actual_value!==kx_q)changes++;
   checks++;
  end
  for(integer site=0;site<=10;site++)begin
   if(site_hits[site]==0)$fatal(1,"Uncovered kernel column update site %0d",site);
   $display("KERNEL_COLUMN_SITE site=%0d hits=%0d",site,site_hits[site]);
  end
  if(changes<1000)$fatal(1,"Insufficient kernel column updates");
  $display("KERNEL_COLUMN_FOUR_STATE_PASS checks=%0d changes=%0d",checks,changes);$finish;
 end
endmodule
'''


def run(command, log, timeout=120):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    reference = parser.add_mutually_exclusive_group(required=True)
    reference.add_argument("--reference-ref")
    reference.add_argument("--reference-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, package = root/SOURCE, root/"rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    original = read_reference_file(root, args.reference_ref, str(SOURCE), text=True) \
        if args.reference_ref else args.reference_file.read_text()
    generated = out/"model.sv"
    generated.write_text(model(source.read_text(), original).replace("always_comb", "always @*"))
    tracked = (source, package, generated, Path(__file__).resolve(), Path(__file__).with_name("check_state_context.py"))
    hashes = {str(path): digest(path) for path in tracked}
    rows = []
    for registered in (0, 1):
        name = f"descriptor{registered}"
        ys, log = out/(name+".ys"), out/(name+".formal.log")
        ys.write_text(f"read_slang --top proof -GREGISTER_DESCRIPTOR={registered} "+shlex.join(map(str,(package,generated)))+
                      "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", ys), log)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        print("KERNEL_COLUMN_FORMAL_PASS", name, flush=True)
        tb, binary, build, simulation = (out/(name+suffix) for suffix in
                                         (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(four_state_test(registered))
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary, package, generated, tb), build)
        run((shutil.which("vvp") or "vvp", binary), simulation)
        match = re.search(r"PASS checks=(\d+) changes=(\d+)", simulation.read_text())
        hits = {int(site): int(count) for site, count in
                re.findall(r"KERNEL_COLUMN_SITE site=(\d+) hits=(\d+)", simulation.read_text())}
        if match is None or int(match[1]) != 65536 or len(hits) != 11 or not all(hits.values()):
            raise RuntimeError(str(simulation))
        rows.append({"register_descriptor": registered, "formal_passed": True,
                     "four_state_checks": int(match[1]), "changed_values": int(match[2]), "site_hits": hits,
                     "formal_log_sha256": digest(log), "simulation_log_sha256": digest(simulation)})
        print("KERNEL_COLUMN_FOUR_STATE_PASS", name, flush=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "source_sha256": hashes, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(original.encode()).hexdigest(), "cases": rows,
              "payload_bits": 16, "assignment_sites": 10, "update_structure_preserved": True,
              "domain": "All 27 one-hot states and the zero state; arbitrary data, reset, configuration, descriptor and stream controls"}
    (out/"summary.json").write_text(json.dumps(report, indent=2)+"\n")
    print("KERNEL_COLUMN_PASS", flush=True)


if __name__ == "__main__":
    main()
