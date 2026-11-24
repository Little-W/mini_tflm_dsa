#!/usr/bin/env python3
"""Verify address and byte-range selection at every enabled stream write."""
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
    statements = "\n".join(assignment(source, name) for name in (
        "o_incoming_context", "active_select_commit", "address_stream_write", "address_column_advance",
        *[f"address_update_select[{index}]" for index in range(5)]))
    first = source.index("  if (!p_register_descriptor) begin : g_early_address_data")
    last = source.index("  always_ff @(posedge i_clk", first)
    available = assignment(source, "next_available[byte_index]").replace("byte_index", "0")
    return '''module proof #(parameter bit p_register_descriptor=0)(
 input logic[4:0]state_index,
 input logic i_tile_valid,i_wr_ready,i_cache_rsp_valid,i_cache_rsp_error,
 input logic o_chunk_reaches_end,i_row_last_q,admission_ready,registered_commit,
 input logic invalid,fast,i_past_active_q,o_active_after_chunk,
 input logic i_row_base_valid,i_geometry_tile,o_group_end_o_equal,i_coordinate_address_valid,
 input logic[4:0][31:0]candidate,
 output logic equivalent,update_enable,
 output logic[31:0]actual,expected,
 output logic actual_available,expected_available
);
 import conv_im2col_frontend_pkg::*;
 logic[$bits(st_t)-1:0]i_state;
 logic i_wr_valid,i_wr_last,i_tile_commit,i_tile_ready;
 logic o_incoming_context,active_select_commit,address_stream_write,address_column_advance;
 logic[4:0]address_update_select;
 logic[31:0]address_update_value,i_next_row_addr,i_next_tap_addr,next_byte_addr,i_channel_addr;
 logic[0:0][4:0]source_available;
 logic[0:0]next_available;
 for(genvar source=0;source<5;source++)begin
  assign source_available[0][source]=candidate[source][0];
 end
 typedef struct packed {logic invalid,fast;logic[31:0]address;} tile_t;
 tile_t committing_tile;
 assign committing_tile={invalid,fast,candidate[0]};
 assign i_next_row_addr=candidate[1];assign i_next_tap_addr=candidate[2];
 assign next_byte_addr=candidate[3];assign i_channel_addr=candidate[4];
 assign i_state=$bits(st_t)'(1)<<state_index;
 assign i_wr_valid=i_state[$clog2(STREAM)]||i_state[$clog2(ZERO_STREAM)]||
   (i_state[$clog2(WAIT_WORD)]&&i_cache_rsp_valid&&!i_cache_rsp_error);
 assign i_wr_last=i_row_last_q&&o_chunk_reaches_end;
 assign i_tile_ready=(i_state[$clog2(IDLE)]||(i_wr_valid&&i_wr_ready&&i_wr_last))&&admission_ready;
 assign i_tile_commit=p_register_descriptor?registered_commit:i_tile_valid&&i_tile_ready;
''' + statements + "\n" + source[first:last] + available + '''
 assign actual=address_update_value;
 assign expected=({32{address_update_select[0]}}&candidate[0])|
  ({32{address_update_select[1]}}&candidate[1])|
  ({32{address_update_select[2]}}&candidate[2])|
  ({32{address_update_select[3]}}&candidate[3])|
  ({32{address_update_select[4]}}&candidate[4]);
 assign update_enable=|address_update_select;
 assign actual_available=next_available[0];
 assign expected_available=i_tile_commit?source_available[0][0]:
  i_state[$clog2(ADDRESS_CHANNEL)]?source_available[0][4]:
  o_chunk_reaches_end?source_available[0][1]:
  (o_group_end_o_equal&&i_coordinate_address_valid)?source_available[0][2]:
  source_available[0][3];
 assign equivalent=!update_enable||(actual==expected && actual_available==expected_available);
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
    hashes = {str(path): digest(path) for path in (source, package)}
    generated = out / "model.sv"
    generated.write_text(model(source.read_text()))
    cases = []
    for registered in (0, 1):
        name = f"registered{registered}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(f"read_slang --top proof -Gp_register_descriptor={registered} " +
                         shlex.join(map(str, (package, generated))) +
                         "\nprep -top proof -flatten\ncheck -assert\n"
                         "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as handle:
            run = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                  "--worker", str(script)], stdout=handle,
                                 stderr=subprocess.STDOUT, timeout=120)
        if run.returncode or "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb = out / (name + "_four_state.sv")
        tb.write_text('''module tb;
 logic[4:0]state_index;
 logic i_tile_valid,i_wr_ready,i_cache_rsp_valid,i_cache_rsp_error;
 logic o_chunk_reaches_end,i_row_last_q,admission_ready,registered_commit;
 logic invalid,fast,i_past_active_q,o_active_after_chunk;
 logic i_row_base_valid,i_geometry_tile,o_group_end_o_equal,i_coordinate_address_valid;
 logic[4:0][31:0]candidate;
 logic equivalent,update_enable;
 logic[31:0]actual,expected;
 logic actual_available,expected_available;
 logic[175:0]pattern;
 integer checks=0,enabled=0;
 proof #(.p_register_descriptor(''' + str(registered) + ''')) dut(.*);
 initial begin
  for(integer sample=0;sample<32768;sample++)begin
   state_index=5'(sample%32);
   for(integer bit_index=0;bit_index<176;bit_index++)pattern[bit_index]=$urandom_range(0,1);
   if(sample%3==0)pattern[(sample/3)%176]=1'bx;
   if(sample%5==0)pattern[(sample/5)%176]=1'bz;
   {i_tile_valid,i_wr_ready,i_cache_rsp_valid,i_cache_rsp_error,
    o_chunk_reaches_end,i_row_last_q,admission_ready,registered_commit,
    invalid,fast,i_past_active_q,o_active_after_chunk,
    i_row_base_valid,i_geometry_tile,o_group_end_o_equal,i_coordinate_address_valid,candidate}=pattern;
   #1;
   if(update_enable)begin
    if(actual!==expected || actual_available!==expected_available)
     $fatal(1,"Enabled address or byte-range mismatch sample=%0d",sample);
    enabled++;
   end
   checks++;
  end
  if(enabled<500)$fatal(1,"Insufficient enabled writes");
  $display("STREAM_ADDRESS_CONTEXT_FOUR_STATE_PASS checks=%0d enabled=%0d",checks,enabled);$finish;
 end
endmodule
''')
        binary, build, run_log = (out / (name + suffix) for suffix in (".vvp", ".build.log", ".four_state.log"))
        with build.open("w") as handle:
            subprocess.run([args.iverilog,"-g2012","-s","tb","-o",str(binary),
                            *map(str,(package,generated,tb))], stdout=handle,
                           stderr=subprocess.STDOUT, check=True)
        with run_log.open("w") as handle:
            subprocess.run([args.vvp,str(binary)],stdout=handle,stderr=subprocess.STDOUT,
                           check=True,timeout=60)
        match = re.search(r"PASS checks=(\d+) enabled=(\d+)",run_log.read_text())
        if match is None or int(match[1]) != 32768:
            raise RuntimeError(str(run_log))
        cases.append({"register_descriptor": registered, "passed": True,
                      "four_state_checks": int(match[1]), "enabled_writes": int(match[2]),
                      "formal_log_sha256": digest(log), "four_state_log_sha256": digest(run_log)})
    if hashes != {str(path): digest(path) for path in (source, package)}:
        raise RuntimeError("Source changed during verification")
    report = {"passed": True, "source_sha256": hashes, "cases": cases,
              "assumptions": ["One-hot or zero state", "Frontend write valid, last and tile-ready definitions"],
              "property": "Every enabled address write stores the same complete address and byte-range candidate"}
    (out / "summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print("STREAM_ADDRESS_CONTEXT_PASS",flush=True)


if __name__ == "__main__":
    main()
