#!/usr/bin/env python3
"""验证窗口和行切换的列范围判断、定宽溢出及四态语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/conv/conv_im2col_stream.sv")
FOUR_STATE_CASES = 16384


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def group_region(source):
    first = source.index("  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range")
    return source[first:source.index("  assign o_incoming_tap_wrap", first)]


def range_module(name, body):
    return f"""module {name} #(parameter int p_size=16,p_rw=$clog2(p_size+1),
 localparam int p_tile_count_w=$clog2(p_size+1))(
 input logic[15:0]group_c,i_window_next_ch,i_ch0_q,
 input logic[16:0]i_window_group_remaining_q,
 input logic[p_rw-1:0]i_tile_cols,
 output logic[1:0]o_incoming_tile_group_fits);
 typedef struct packed{{logic[15:0]group_c;}} config_t;
 config_t i_c;
 wire[16:0]o_initial_group_remaining={{1'b0,group_c}}-{{1'b0,i_ch0_q}};
 assign i_c.group_c=group_c;
 {body}
endmodule
"""


def model(current, reference):
    current_body, reference_body = group_region(current), group_region(reference)
    first = current_body.index("    end else if (p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_short_remaining")
    last = current_body.index("    end else if (p_tile_count_w < 16) begin : g_split", first)
    if current_body[:first] + current_body[last:] != reference_body:
        raise ValueError("Existing saved-range and wide-column branches changed")
    return range_module("candidate", current_body) + range_module("reference", reference_body) + """
module proof #(parameter int p_size=16,p_rw=$clog2(p_size+1))(
 input logic[15:0]group_c,i_window_next_ch,i_ch0_q,
 input logic[16:0]i_window_group_remaining_q,
 input logic[p_rw-1:0]i_tile_cols,
 output logic[1:0]actual,expected,output logic equivalent);
 candidate #(.p_size(p_size),.p_rw(p_rw)) u_candidate(.*,.o_incoming_tile_group_fits(actual));
 reference #(.p_size(p_size),.p_rw(p_rw)) u_reference(.*,.o_incoming_tile_group_fits(expected));
 assign equivalent=actual===expected;
endmodule
"""


def four_state_test(size, width):
    return f"""module tb;
 localparam int p_size={size},p_rw={width},p_tile_count_w=$clog2(p_size+1);
 logic[15:0]group_c,i_window_next_ch,i_ch0_q;
 logic[16:0]i_window_group_remaining_q;
 logic[p_rw-1:0]i_tile_cols;
 logic[1:0]actual,expected;
 logic equivalent;
 proof #(.p_size(p_size),.p_rw(p_rw)) dut(.*);
 initial begin
  for(integer sample=0;sample<{FOUR_STATE_CASES};sample++)begin
   group_c=16'($urandom);i_window_next_ch=16'($urandom);i_ch0_q=16'($urandom);
   i_window_group_remaining_q=17'($urandom);i_tile_cols=p_rw'($urandom);
   if(sample%2==0)i_ch0_q=group_c-16'(p_tile_count_w'($urandom));
   if(sample%4==0)i_ch0_q=group_c+16'(p_tile_count_w'($urandom));
   if(sample%8==0 && p_tile_count_w<16)begin
    i_ch0_q=(i_ch0_q>>p_tile_count_w)<<p_tile_count_w;
    i_ch0_q|=(16'd1<<p_tile_count_w)-16'd1;
    group_c=i_ch0_q+16'd1;i_tile_cols=p_rw'(sample%3);
   end
   if(sample%17==0)begin group_c=0;i_ch0_q=16'hffff;i_window_next_ch=0;end
   if(sample%19==0)begin group_c=16'hffff;i_ch0_q=16'hffff;i_window_next_ch=0;end
   if(sample%23==0)i_tile_cols=0;
   if(sample%29==0)i_tile_cols='1;
   if(sample%31==0)i_tile_cols=p_rw'(32'd1<<p_tile_count_w);
   if(sample%3==0)group_c[(sample/3)%16]=1'bx;
   if(sample%5==0)i_ch0_q[(sample/5)%16]=1'bz;
   if(sample%7==0)i_tile_cols[(sample/7)%p_rw]=1'bx;
   if(sample%11==0)i_window_group_remaining_q[(sample/11)%17]=1'bz;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Tile group mismatch size=%0d rw=%0d sample=%0d actual=%b expected=%b",
       p_size,p_rw,sample,actual,expected);
  end
  $display("TILE_GROUP_FOUR_STATE_PASS checks={FOUR_STATE_CASES}");$finish;
 end
endmodule
"""


def run(command, log):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=120)


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
    source, helper = root/SOURCE, root/"rtl/common/add_equal.sv"
    original = read_reference_file(root, args.reference_ref, str(SOURCE), text=True) \
        if args.reference_ref else args.reference_file.read_text()
    generated = out/"model.sv"
    generated.write_text(model(source.read_text(), original).replace("always_comb", "always @*"))
    tracked = (source, helper, generated, Path(__file__).resolve())
    hashes = {str(path): digest(path) for path in tracked}
    cases = [(size, size.bit_length()) for size in (1,2,3,4,7,8,16,31,255,256,32767,32768,65535,65536)]
    cases += [(16,1),(16,6),(16,17),(256,16)]
    rows = []
    for size, width in cases:
        name = f"size{size}_columns{width}"
        script, log = out/(name+".ys"), out/(name+".formal.log")
        script.write_text(f"read_slang -D SYNTHESIS=1 --top proof -Gp_size={size} -Gp_rw={width} "+
                          shlex.join(map(str,(helper,generated)))+
                          "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script), log)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb, binary, build, simulation = (out/(name+suffix) for suffix in
                                         (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(four_state_test(size, width))
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary, helper, generated, tb), build)
        run((shutil.which("vvp") or "vvp", binary), simulation)
        if f"TILE_GROUP_FOUR_STATE_PASS checks={FOUR_STATE_CASES}" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        rows.append({"size": size, "column_input_width": width, "formal_passed": True,
                     "four_state_checks": FOUR_STATE_CASES, "formal_log_sha256": digest(log),
                     "simulation_log_sha256": digest(simulation)})
        print("TILE_GROUP_PASS", name, flush=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "source_sha256": hashes, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(original.encode()).hexdigest(), "cases": rows,
              "source_count": 2, "saved_range_and_wide_column_branches_preserved": True,
              "domain": "Arbitrary channels, group limits, stored window remainder and column values, including unsigned overflow"}
    (out/"summary.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
