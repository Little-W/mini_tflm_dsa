#!/usr/bin/env python3
"""Verify every output lane of the parallel convolution response formatter."""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source: str, name: str) -> str:
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise ValueError(name)
    return match.group()


def model(source: str) -> str:
    helper_names = (
        "conv_im2col_sample_sum_group", "conv_im2col_sample_sum_carry",
        "conv_im2col_sample_sum_select", "conv_im2col_sample_sum",
        "conv_im2col_formatter_reduce", "conv_im2col_formatter_mux",
    )
    helper_blocks = []
    for name in helper_names:
        found = re.search(r"\bmodule\s+" + re.escape(name) + r"\b.*?endmodule", source, re.S)
        if found is not None:
            attribute = re.search(r"\(\*[^\n]*keep_hierarchy[^\n]*\*\)\s*$",
                                  source[:found.start()])
            helper_blocks.append((attribute.group() if attribute else "") + found.group())
    helpers = "\n\n".join(helper_blocks)
    first = source.index("  for (genvar data_lane = 0; data_lane < p_lanes; data_lane++) begin : g_signed_byte_offset")
    last = source.index("  assign stream_word =", first)
    correction = source[first:last]
    first = source.index("  if (p_lanes <= 16 && p_cache_read_bytes <= 16) begin : g_parallel_formatter")
    last = source.index("  always_comb begin\n    channel_update =", first)
    selection = source[first:last]
    header = '''module formatter #(parameter int p_lanes=8,p_cache_read_bytes=8,
 localparam int p_cache_read_width=8*p_cache_read_bytes,p_word_shift=$clog2(p_cache_read_bytes))(
 input logic[p_cache_read_width-1:0] i_cache_rsp_data,i_word_buf,
 input logic signed[15:0] input_offset,
 input logic input_s16,state_stream,state_wait,
 input logic[31:0] o_addr,
 input logic[p_lanes-1:0] o_wr_mask,
 output logic[p_lanes-1:0][15:0] o_wr_data
);
 import conv_im2col_frontend_pkg::*;
 typedef struct packed {logic signed[15:0]input_offset;logic input_s16;} config_t;
 config_t i_c;
 logic[21:0]i_state;
 logic stream_context;
 logic[p_cache_read_width-1:0]stream_word,selected_word;
 logic[p_lanes-1:0][7:0]selected_s8_byte;
 logic[p_lanes-1:0][8:0]corrected_s8_sum;
 logic[p_lanes-1:0][15:0]corrected_s8_value;
 always_comb begin
  i_state='0;
  i_state[$clog2(STREAM)]=state_stream;
  i_state[$clog2(WAIT_WORD)]=state_wait;
 end
 assign i_c.input_offset=input_offset;
 assign i_c.input_s16=input_s16;
'''
    return helpers + "\n\n" + header + correction + "\n".join(assignment(source, name) for name in (
        "stream_context", "stream_word", "selected_word")) + "\n" + selection + '''endmodule

module proof #(parameter int p_lanes=8,p_cache_read_bytes=8,
 localparam int WIDTH=8*p_cache_read_bytes,SHIFT=$clog2(p_cache_read_bytes))(
 input logic[WIDTH-1:0] i_cache_rsp_data,i_word_buf,
 input logic signed[15:0] input_offset,
 input logic input_s16,state_stream,state_wait,
 input logic[31:0] o_addr,
 input logic[p_lanes-1:0] o_wr_mask,
 output logic equivalent
);
 logic[p_lanes-1:0][15:0] o_wr_data,expected;
 logic[WIDTH-1:0] reference_word;
 logic[p_lanes-1:0][8:0] reference_sum;
 logic[p_lanes-1:0] lane_equal;
 formatter #(.p_lanes(p_lanes),.p_cache_read_bytes(p_cache_read_bytes)) dut(.*);
 assign reference_word=(state_wait?i_cache_rsp_data:i_word_buf)>>(8*o_addr[SHIFT-1:0]);
 for(genvar lane=0;lane<p_lanes;lane++)begin:g_reference
  logic[7:0]sample;
  logic unused_carry;
  assign sample=8'(reference_word>>(8*lane));
  assign reference_sum[lane]={sample[7],sample}+input_offset[8:0];
  always_comb begin
   expected[lane]='0;
   if((state_stream||state_wait)&&o_wr_mask[lane])begin
    if(input_s16)expected[lane]=$signed(16'(reference_word>>(16*lane)));
    else expected[lane]=$signed({{7{reference_sum[lane][8]}},reference_sum[lane]});
   end
  end
  assign lane_equal[lane]=o_wr_data[lane]===expected[lane];
 end
 assign equivalent=&lane_equal;
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / "rtl/npu/conv/conv_im2col_stream.sv"
    package = root / "rtl/npu/conv/conv_im2col_frontend_pkg.sv"
    helper = root / "rtl/common/parallel_prefix_add.sv"
    mux_helper = root / "rtl/common/onehot_mux.sv"
    inputs = (source, package, helper, mux_helper)
    hashes = {str(path): digest(path) for path in inputs}
    generated = out / "model.sv"
    generated.write_text(model(source.read_text()))
    proofs, simulations = [], []
    cases = ((1,4),(2,4),(4,4),(8,4),(8,8),(16,8),(16,16),(20,16))
    for lanes, byte_count in cases:
        name = f"lanes{lanes}_bytes{byte_count}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(
            f"read_slang --top proof -Gp_lanes={lanes} -Gp_cache_read_bytes={byte_count} " +
            shlex.join(map(str, (package, helper, mux_helper, generated))) +
            "\nprep -top proof -flatten\ncheck -assert\n" +
            "".join(f"sat -verify -set o_addr[{byte_count.bit_length()-2}:0] {position} "
                    "-prove equivalent 1 -show-inputs -show-outputs\n"
                    for position in range(byte_count)))
        with log.open("w") as handle:
            run = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                  "--worker", str(script)], stdout=handle,
                                 stderr=subprocess.STDOUT, timeout=300)
        if run.returncode or log.read_text().count("SAT proof finished - no model found: SUCCESS!") != byte_count:
            raise RuntimeError(str(log))
        proofs.append({"lanes": lanes, "cache_read_bytes": byte_count,
                       "byte_positions_proven": list(range(byte_count)),
                       "passed": True, "log_sha256": digest(log)})
        print("RETURN_FORMATTER_FORMAL_PASS", name, flush=True)
    for lanes, byte_count in cases:
        name = f"lanes{lanes}_bytes{byte_count}"
        total = 16*byte_count + 16 + 3 + 32 + lanes
        sample_count = max(1024, 2*total + 8*byte_count)
        tb = out / (name + "_four_state.sv")
        tb.write_text(f'''module tb;
 localparam int BYTES={byte_count},LANES={lanes},BITS={total};
 logic[BYTES*8-1:0]i_cache_rsp_data,i_word_buf;
 logic signed[15:0]input_offset;
 logic input_s16,state_stream,state_wait;
 logic[31:0]o_addr;
 logic[LANES-1:0]o_wr_mask;
 logic equivalent;
 logic[BITS-1:0]pattern;
 integer checks=0;
 proof #(.p_lanes(LANES),.p_cache_read_bytes(BYTES)) dut(.*);
 initial begin
  for(integer sample=0;sample<{sample_count};sample++)begin
   for(integer bit_index=0;bit_index<BITS;bit_index++)pattern[bit_index]=$urandom_range(0,1);
   if(sample<2*BITS)pattern[sample/2]=(sample%2==0)?1'bx:1'bz;
   {{i_cache_rsp_data,i_word_buf,input_offset,input_s16,state_stream,state_wait,o_addr,o_wr_mask}}=pattern;
   if(sample>=2*BITS)begin
    o_addr=(sample-2*BITS)%BYTES;
    {{input_s16,state_stream,state_wait}}=3'((sample-2*BITS)/BYTES);
   end
   #1;
   if(equivalent!==1'b1)$fatal(1,"Return formatter mismatch sample=%0d",sample);
   checks++;
  end
  $display("RETURN_FORMATTER_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
        binary, build, run_log = (out / (name + suffix) for suffix in (".vvp", ".build.log", ".four_state.log"))
        with build.open("w") as handle:
            subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),
                            *map(str,(package,helper,mux_helper,generated,tb))], stdout=handle,
                           stderr=subprocess.STDOUT, check=True)
        with run_log.open("w") as handle:
            subprocess.run([args.vvp,str(binary)], stdout=handle,
                               stderr=subprocess.STDOUT, check=True, timeout=600)
        if f"PASS checks={sample_count}" not in run_log.read_text():
            raise RuntimeError(str(run_log))
        simulations.append({"lanes": lanes, "cache_read_bytes": byte_count,
                            "checks": sample_count, "passed": True,
                            "all_input_bits_x_z": True,
                            "all_known_format_source_positions": True,
                            "log_sha256": digest(run_log)})
        binary.unlink()
    if hashes != {str(path): digest(path) for path in inputs}:
        raise RuntimeError("Source changed during verification")
    report = {"passed": True, "source_sha256": hashes, "formal_cases": proofs,
              "four_state_cases": simulations,
              "domain": "All input data, offsets, byte positions, masks, formats and source selections",
              "property": "All public data lanes match, including inactive lanes and cycles"}
    (out / "summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print("RETURN_FORMATTER_PASS",flush=True)


if __name__ == "__main__":
    main()
