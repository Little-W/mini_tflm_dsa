#!/usr/bin/env python3
"""Verify channel values and write events against the complete priority update."""
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
SOURCE = "rtl/npu/conv/conv_im2col_stream.sv"
PORTS = """
 input logic [4:0] state_index,
 input logic cache_valid,cache_error,wr_ready,row_last,chunk_end,group_end,
 input logic tile_valid,tile_admission_ready,descriptor_fast_valid,registered_accept,
 input logic group_shape_valid,
 input logic [31:0] q0,decode_index,decode_inner,incoming_channel,ch0,
 input logic [15:0] group_c,current_channel,next_channel,current_q_remainder,masked_channel,
 input logic [4:0] col_idx,active_cols,active_remaining,
 input logic [$clog2(p_lanes+1)-1:0] chunk_count
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_body(source):
    first = source.index("  always_comb begin\n    channel_update =")
    return source[first:source.index("  // 行切换", first)]


def model(reference, current):
    first = current.index("  // 通道数据按运行阶段预选")
    current_body = current[first:current.index("  always_ff @(posedge i_clk", first)]
    reference_body = update_body(reference).replace("channel_update", "reference_update")
    return f"""module proof #(parameter int p_lanes=8,parameter bit p_register_descriptor=0,
 localparam int p_tile_count_w=5)(
{PORTS},output logic[15:0]actual,expected,output logic equivalent);
 import conv_im2col_frontend_pkg::*;
 logic[26:0]i_state;
 wire i_cache_rsp_valid=cache_valid,i_cache_rsp_error=cache_error;
 wire i_wr_ready=wr_ready,i_row_last_q=row_last,o_chunk_reaches_end=chunk_end;
 wire o_group_end_o_equal=group_end,i_tile_admission_ready=tile_admission_ready;
 wire i_group_shape_o_valid=group_shape_valid;
 wire[31:0]i_q0=q0,i_decode_index=decode_index,i_decode_inner=decode_inner;
 wire[31:0]i_ch0=ch0;
wire[15:0]o_ch_q=current_channel,i_current_q_remainder=current_q_remainder;
 wire[4:0]i_col_idx=col_idx,i_active_cols_q=active_cols;
 wire[$clog2(p_lanes+1)-1:0]o_chunk_count=chunk_count;
 wire[5:0][15:0]o_group_range_channel={{48'd0,masked_channel,32'd0}};
 typedef struct packed{{logic[15:0]group_c;}}config_t;
 typedef struct packed{{logic[31:0]channel;}}tile_t;
 config_t i_c;
 tile_t committing_tile;
 logic[15:0]channel_update,channel_value,reference_update;
 assign i_c.group_c=group_c;
 assign committing_tile.channel=incoming_channel;
 assign i_state=27'b1<<state_index;
 wire stream_phase=i_state[$clog2(WAIT_WORD)]||i_state[$clog2(STREAM)]||i_state[$clog2(ZERO_STREAM)];
 wire i_wr_valid=i_state[$clog2(STREAM)]||i_state[$clog2(ZERO_STREAM)]||
     (i_state[$clog2(WAIT_WORD)]&&cache_valid&&!cache_error);
 wire wr_last=row_last&&chunk_end;
 wire o_incoming_context=!p_register_descriptor&&tile_valid&&
     (i_state[$clog2(IDLE)]||(stream_phase&&wr_last));
 wire i_channel_accept_fire=p_register_descriptor?registered_accept:
     tile_valid&&tile_admission_ready&&descriptor_fast_valid&&
     (i_state[$clog2(IDLE)]||(i_wr_valid&&wr_ready&&wr_last));
{reference_body}
{update_body(current)}
{current_body}
 always_comb begin
   actual=current_channel;
   if(channel_write_enable)actual=channel_store_value;
 end
 assign expected=i_channel_accept_fire?16'(incoming_channel):reference_update;
 assign equivalent=actual===expected;
endmodule
"""


def run(command, log, timeout=120):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / SOURCE
    package = root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    helper = root / "rtl/common/onehot_mux.sv"
    reference = read_reference_file(root, args.reference_ref, SOURCE, text=True)
    current = source.read_text()
    if update_body(reference) != update_body(current):
        raise ValueError("The priority update differs from the reference revision")
    generated = out / "channel_admission.sv"
    generated.write_text(model(reference, current).replace("always_comb", "always @*"))
    hashes = {str(p): digest(p) for p in (source, package, helper, generated)}
    rows = []
    for lanes in (4, 8, 16):
        for registered in (0, 1):
            name = f"lanes{lanes}_descriptor{registered}"
            script, log = out / (name + ".ys"), out / (name + ".formal.log")
            script.write_text(f"read_slang --top proof -Gp_lanes={lanes} -Gp_register_descriptor={registered} " +
                shlex.join(map(str, (package, helper, generated))) +
                "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            run((sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script), log)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            declarations = PORTS.replace(" input ", " ").strip().rstrip(",")
            declarations = declarations.replace(",\n logic", ";\n logic") + ";"
            bench = out / (name + ".sv")
            bench.write_text(f"""module tb;
 localparam int p_lanes={lanes};
 {declarations}
 logic[15:0]actual,expected;
 logic equivalent;
 logic[10:0]controls;
 proof #(.p_lanes(p_lanes),.p_register_descriptor({registered})) dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   state_index=5'(sample%32);
   controls=11'($urandom);
   q0=$urandom;decode_index=$urandom;decode_inner=$urandom;incoming_channel=$urandom;
   group_c=16'($urandom);ch0=16'($urandom);current_channel=16'($urandom);
   next_channel=16'($urandom);current_q_remainder=16'($urandom);masked_channel=16'($urandom);
   col_idx=5'($urandom);active_cols=5'($urandom);active_remaining=5'($urandom);
   chunk_count=$clog2(p_lanes+1)'($urandom);
   if(sample%4==0)q0=32'd0;
   if(sample%5==0)begin group_c=16'd3;q0=sample%27;end
   if(sample%6==0)decode_index=q0;
   if(sample%3==0)controls[(sample/3)%11]=1'bx;
   if(sample%7==0)controls[(sample/7)%11]=1'bz;
   if(sample%11==0)incoming_channel[(sample/11)%32]=1'bx;
   if(sample%13==0)current_channel[(sample/13)%16]=1'bz;
   if(sample%127==0)state_index=5'bxxxxx;
   {{cache_valid,cache_error,wr_ready,row_last,chunk_end,group_end,tile_valid,
     tile_admission_ready,descriptor_fast_valid,registered_accept,group_shape_valid}}=controls;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Channel update differs sample=%0d state=%0d actual=%h expected=%h",
      sample,state_index,actual,expected);
  end
  $display("CHANNEL_ADMISSION_PASS checks=65536");$finish;
 end
endmodule
""")
            binary = out / (name + ".vvp")
            run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary,
                 package, helper, generated, bench), out / (name + ".build.log"))
            simulation = out / (name + ".run.log")
            run((shutil.which("vvp") or "vvp", binary), simulation, timeout=180)
            if "CHANNEL_ADMISSION_PASS checks=65536" not in simulation.read_text():
                raise RuntimeError(str(simulation))
            rows.append({"lanes": lanes, "register_descriptor": registered, "formal_passed": True,
                         "four_state_checks": 65536, "formal_log_sha256": digest(log),
                         "simulation_log_sha256": digest(simulation)})
            print("CHANNEL_ADMISSION_PASS", name, flush=True)
    if hashes != {p: digest(Path(p)) for p in hashes}:
        raise RuntimeError("Source changed during verification")
    (out / "summary.json").write_text(json.dumps({"passed": True, "reference_ref": args.reference_ref,
        "source_sha256": hashes, "sources_unchanged": True,
        "input_model": "One-hot operation states and the connected frontend write/descriptor handshake equations",
        "cases": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
