#!/usr/bin/env python3
"""Verify every saved group-range value with independent source candidates."""
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
SOURCE = Path("rtl/npu/conv/conv_im2col_stream.sv")
PORTS = """
 input logic [4:0] state_index,
 input logic [31:0] i_q0, i_decode_index,
 input logic [15:0] group_c,
 input logic i_group_shape_o_valid, i_cfg_valid, i_cfg_ready, i_tile_commit,
 input logic invalid, fast, i_wr_valid, range_stream_allowed,
 input logic i_tile_valid, i_wr_last, i_tile_admission_ready,
 input logic [5:0][WIDTH-1:0] o_group_range_next,
 input logic [WIDTH-1:0] group_range_cfg, group_transfer_range, channel_range,
 input logic o_chunk_reaches_end
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection_module(source, name):
    first = source.index("  // 译码选择保持状态优先次序")
    last = source.index("  always_ff @(posedge i_clk", first)
    body = source[first:last]
    return model_module(body, name)


def model_module(body, name):
    return f"""module {name} #(parameter int p_lanes=8,
 parameter bit p_register_descriptor=0,
 localparam int p_saved_group_lanes=p_lanes<=4?4:(1<<$clog2(p_lanes)),
 localparam int WIDTH=p_saved_group_lanes+1)(
{PORTS},
 output logic [WIDTH-1:0] result,
 output logic update_enable
);
 import conv_im2col_frontend_pkg::*;
 typedef struct packed {{logic[15:0] group_c;}} config_t;
 config_t i_c;
 typedef struct packed {{logic invalid,fast;logic[WIDTH-1:0] channel_range;}} tile_t;
 tile_t committing_tile;
 logic range_decode_write,range_commit_context;
 logic[26:0] i_state;
 logic o_incoming_context;
 logic[3:0] range_decode_select,range_update_select;
 logic[WIDTH-1:0] range_decode_value,range_update_value,group_range_stream_value;
 assign group_range_stream_value=o_chunk_reaches_end?o_group_range_next[1]:group_transfer_range;
 assign i_c.group_c=group_c;
 assign committing_tile={{invalid,fast,channel_range}};
 assign i_state=27'b1<<state_index;
 assign o_incoming_context=!p_register_descriptor && i_tile_valid &&
  (i_state[$clog2(IDLE)] ||
   ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]) && i_wr_last));
{body}
 assign result=range_update_value;
 assign update_enable=|range_update_select;
endmodule
"""


def priority_reference():
    return model_module("""
 always_comb begin
  range_decode_write=1'b0;
  range_decode_value=o_group_range_next[4];
  unique case(1'b1)
   i_state[$clog2(P_DECODE)],i_state[$clog2(P_START)],i_state[$clog2(P_WAIT)]:;
   i_state[$clog2(Q_DECODE)]:begin
   if(i_q0==32'd0)begin
    range_decode_write=1'b1;
    range_decode_value=o_group_range_next[0];
   end else if(i_group_shape_o_valid)begin
    range_decode_write=1'b1;
    range_decode_value=o_group_range_next[2];
   end else if(group_c==16'd3 && i_q0<32'd27)begin
    range_decode_write=1'b1;
    range_decode_value=o_group_range_next[3];
   end
   end
   i_state[$clog2(Q_START)]:;
   i_state[$clog2(Q_WAIT)]:begin
    if(i_decode_index==i_q0)range_decode_write=1'b1;
   end
   default:;
  endcase
 end
 assign range_update_select={
  !i_tile_commit && i_wr_valid && range_stream_allowed,
  i_tile_commit && !invalid && fast,
  i_cfg_valid && i_cfg_ready,
  range_decode_write};
 assign range_commit_context=p_register_descriptor ? range_update_select[2] :
  o_incoming_context && i_tile_admission_ready;
 always_comb begin
  range_update_value=group_range_stream_value;
  unique case(1'b1)
   range_update_select[1]:range_update_value=group_range_cfg;
   range_commit_context:range_update_value=channel_range;
   range_update_select[0]:range_update_value=range_decode_value;
   default:;
  endcase
 end
""", "reference")


def proof_module():
    return f"""module proof #(parameter int p_lanes=8,
 parameter bit p_register_descriptor=0,
 localparam int WIDTH=(p_lanes<=4?4:(1<<$clog2(p_lanes)))+1)(
{PORTS}, output logic equivalent,
 output logic[WIDTH-1:0] actual,expected,
 output logic actual_update,expected_update
);
 import conv_im2col_frontend_pkg::*;
 logic[26:0]state_mask;
 logic stream_phase,write_valid,descriptor_commit;
 assign state_mask=27'b1<<state_index;
 assign stream_phase=state_mask[$clog2(WAIT_WORD)]||state_mask[$clog2(STREAM)]||
  state_mask[$clog2(ZERO_STREAM)];
 assign write_valid=i_wr_valid&&stream_phase;
 assign descriptor_commit=p_register_descriptor?i_tile_commit:
  i_tile_commit&&i_tile_valid&&i_tile_admission_ready&&
  (state_mask[$clog2(IDLE)]||(stream_phase&&i_wr_last));
 current #(.p_lanes(p_lanes),.p_register_descriptor(p_register_descriptor))
  u_current(.result(actual),.update_enable(actual_update),
   .i_wr_valid(write_valid),.i_tile_commit(descriptor_commit),.*);
 reference #(.p_lanes(p_lanes),.p_register_descriptor(p_register_descriptor))
  u_reference(.result(expected),.update_enable(expected_update),
   .i_wr_valid(write_valid),.i_tile_commit(descriptor_commit),.*);
 assign equivalent=actual_update==expected_update && (!actual_update||actual==expected);
endmodule
"""


def four_state(lanes, descriptor):
    declarations = PORTS.replace(" input ", " ").strip().rstrip(",")
    declarations = re.sub(r",\s*logic", ";\n logic", declarations) + ";"
    names = """state_index,i_q0,i_decode_index,group_c,i_group_shape_o_valid,
 i_cfg_valid,i_cfg_ready,i_tile_commit,invalid,fast,i_wr_valid,range_stream_allowed,
 i_tile_valid,i_wr_last,i_tile_admission_ready,o_group_range_next,
 group_range_cfg,group_transfer_range,channel_range,o_chunk_reaches_end"""
    return f"""module tb;
 localparam int p_lanes={lanes},WIDTH=(p_lanes<=4?4:(1<<$clog2(p_lanes)))+1;
{declarations}
 logic equivalent,actual_update,expected_update;
 logic[WIDTH-1:0] actual,expected;
 logic[$bits({{{names}}})-1:0] pattern;
 proof #(.p_lanes(p_lanes),.p_register_descriptor({descriptor})) dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   for(integer bit_index=0;bit_index<$bits(pattern);bit_index++)
    pattern[bit_index]=$urandom_range(0,1);
   if(sample%3==0)pattern[(sample/3)%$bits(pattern)]=1'bx;
   if(sample%5==0)pattern[(sample/5)%$bits(pattern)]=1'bz;
   {{{names}}}=pattern;
   state_index=5'(sample%32);
   #1;
   if(actual_update!==expected_update || (actual_update && actual!==expected))
    $fatal(1,"Group-range data selection differs at sample %0d",sample);
  end
  $display("RANGE_DATA_CHOICE_FOUR_STATE_PASS checks=65536");$finish;
 end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", help="Optional Git reference instead of the priority reference function")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stream = root / SOURCE
    package = root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    helper = root / "rtl/common/onehot_mux.sv"
    hashes = {str(path): digest(path) for path in (stream, package, helper)}
    if args.reference_ref:
        reference = read_reference_file(ROOT, args.reference_ref, SOURCE, text=True)
        reference_model = selection_module(reference, "reference")
    else:
        reference_model = priority_reference()
    model = out / "model.sv"
    model.write_text(reference_model +
                     selection_module(stream.read_text(), "current") + proof_module())
    rows = []
    for descriptor in (0, 1):
        for lanes in (4, 8, 16):
            case = f"lanes{lanes}_descriptor{descriptor}"
            script, log = out / (case + ".ys"), out / (case + ".log")
            script.write_text(f"read_slang --top proof -Gp_lanes={lanes} -Gp_register_descriptor={descriptor} " +
                shlex.join(map(str, (package, helper, model))) + "\nprep -top proof -flatten\ncheck -assert\n" +
                "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with log.open("w") as handle:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], stdout=handle, stderr=subprocess.STDOUT,
                               timeout=120, check=True)
            if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
                raise RuntimeError(str(log))
            tb, binary = out / (case + "_four_state.sv"), out / (case + ".vvp")
            tb.write_text(four_state(lanes, descriptor))
            with (out / (case + "_build.log")).open("w") as handle:
                subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                                *map(str, (package, helper, model, tb))], stdout=handle,
                               stderr=subprocess.STDOUT, check=True)
            simulation = out / (case + "_four_state.log")
            with simulation.open("w") as handle:
                subprocess.run([args.vvp, str(binary)], stdout=handle, stderr=subprocess.STDOUT,
                               timeout=90, check=True)
            if "PASS checks=65536" not in simulation.read_text():
                raise RuntimeError(str(simulation))
            rows.append({"lanes": lanes, "register_descriptor": descriptor, "passed": True,
                         "four_state_checks": 65536, "proof_sha256": digest(log),
                         "four_state_log_sha256": digest(simulation)})
            print("RANGE_DATA_CHOICE_PASS", lanes, descriptor, flush=True)
    if hashes != {str(path): digest(path) for path in (stream, package, helper)}:
        raise RuntimeError("Source changed during verification")
    result = {"passed": True, "reference_ref": args.reference_ref,
              "reference_model": "Configuration, descriptor, decode, and stream priority",
              "source_sha256": hashes,
              "property": "Update enable and every saved range value are identical",
              "input_assumptions": ["One-hot or zero operation state",
                                    "Output writes occur in WAIT_WORD, STREAM, or ZERO_STREAM",
                                    "Direct descriptor commits require an offered descriptor, static admission, and IDLE or the final output phase"],
              "incoming_context": "Actual descriptor offer, operation state, and final output phase",
              "cases": rows}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
