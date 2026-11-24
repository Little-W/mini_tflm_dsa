#!/usr/bin/env python3
"""验证描述符候选通道范围的低位阈值比较及四态语义。"""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_region(source):
    first = source.index("    for (genvar source = 0; source < 2; source++) begin : g_candidate",
                         source.index("begin : g_saved_group_range"))
    last = source.index("    always_comb begin\n      accepted_fits =", first)
    return source[first:last]


def unchanged_logic(source):
    first = source.index("  if (!p_register_descriptor && p_tile_count_w < 16) begin : g_saved_group_range")
    last = source.index("  // 像素候选以四位分组并行求进位", first)
    return source[first:last].replace(candidate_region(source), "CANDIDATE_RANGE\n").replace(
        "    logic [1:0][16:0] candidate_end;\n", "")


def candidate_module(name, body):
    end_declaration = "logic [1:0][16:0] candidate_end;" if "candidate_end[source]" in body else ""
    return f"""module {name} #(parameter int p_tile_count_w=5)(
 input logic [15:0] group_c,i_ch0_q,o_window_next_ch,
 input logic [p_tile_count_w-1:0] prepared_columns,
 output logic [1:0] candidate_fits);
 typedef struct packed {{logic [15:0] group_c;}} config_t;
 config_t i_c;
 logic [1:0][15:0] candidate_channel;
 {end_declaration}
 assign i_c.group_c=group_c;
 assign candidate_channel={{o_window_next_ch,i_ch0_q}};
 {body}
endmodule
"""


def model(current, reference):
    if unchanged_logic(current) != unchanged_logic(reference):
        raise ValueError("Saved group qualification outside the candidate comparison changed")
    return candidate_module("candidate", candidate_region(current)) + \
        candidate_module("reference", candidate_region(reference)) + """
module proof #(parameter int p_tile_count_w=5)(
 input logic [15:0] group_c,i_ch0_q,o_window_next_ch,
 input logic [p_tile_count_w-1:0] prepared_columns,
 output logic [1:0] actual,expected,
 output logic equivalent);
 candidate #(.p_tile_count_w(p_tile_count_w)) u_candidate (
   .group_c,.i_ch0_q,.o_window_next_ch,.prepared_columns,.candidate_fits(actual));
 reference #(.p_tile_count_w(p_tile_count_w)) u_reference (
   .group_c,.i_ch0_q,.o_window_next_ch,.prepared_columns,.candidate_fits(expected));
 assign equivalent=actual===expected;
endmodule
"""


def four_state_test(width):
    return f"""module tb;
 localparam int p_tile_count_w={width};
 logic [15:0] group_c,i_ch0_q,o_window_next_ch;
 logic [p_tile_count_w-1:0] prepared_columns;
 logic [1:0] actual,expected;
 logic equivalent;
 integer known_checks=0,unknown_checks=0;
 proof #(.p_tile_count_w(p_tile_count_w)) dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   group_c=16'($urandom);i_ch0_q=16'($urandom);o_window_next_ch=16'($urandom);
   prepared_columns=p_tile_count_w'($urandom);
   if(sample%2==0)begin
    i_ch0_q=group_c-16'(p_tile_count_w'($urandom));
    o_window_next_ch=group_c+16'(p_tile_count_w'($urandom));
   end
   if(sample%17==0)begin group_c=0;i_ch0_q=16'hffff;o_window_next_ch=0;end
   if(sample%19==0)begin group_c=16'hffff;i_ch0_q=16'hffff;o_window_next_ch=0;end
   if(sample%23==0)prepared_columns=0;
   if(sample%29==0)prepared_columns='1;
   if(sample%3==0)group_c[(sample/3)%16]=1'bx;
   if(sample%5==0)i_ch0_q[(sample/5)%16]=1'bz;
   if(sample%7==0)prepared_columns[(sample/7)%p_tile_count_w]=1'bx;
   if(sample%11==0)o_window_next_ch[(sample/11)%16]=1'bz;
   #1;
   if(equivalent!==1'b1)$fatal(1,"Group range mismatch width=%0d sample=%0d actual=%b expected=%b",
       p_tile_count_w,sample,actual,expected);
   if((^expected)===1'bx)unknown_checks++;else known_checks++;
  end
  if(known_checks<1000 || unknown_checks<1000)$fatal(1,"Insufficient group range coverage");
  $display("DESCRIPTOR_GROUP_RANGE_FOUR_STATE_PASS checks=65536 known=%0d unknown=%0d",known_checks,unknown_checks);
  $finish;
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
    rows = []
    for width in range(1, 16):
        name = f"columns{width}"
        script, log = out/(name+".ys"), out/(name+".formal.log")
        script.write_text(f"read_slang -D SYNTHESIS=1 --top proof -Gp_tile_count_w={width} "+
                          shlex.join(map(str,(helper,generated)))+
                          "\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker", script), log)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(str(log))
        tb, binary, build, simulation = (out/(name+suffix) for suffix in
                                         (".sv", ".vvp", ".build.log", ".four_state.log"))
        tb.write_text(four_state_test(width))
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", binary, helper, generated, tb), build)
        run((shutil.which("vvp") or "vvp", binary), simulation)
        match = re.search(r"PASS checks=(\d+) known=(\d+) unknown=(\d+)", simulation.read_text())
        if match is None or int(match[1]) != 65536:
            raise RuntimeError(str(simulation))
        rows.append({"tile_count_width": width, "formal_passed": True,
                     "four_state_checks": int(match[1]), "known_checks": int(match[2]),
                     "unknown_checks": int(match[3]), "formal_log_sha256": digest(log),
                     "simulation_log_sha256": digest(simulation)})
        print("DESCRIPTOR_GROUP_RANGE_PASS", name, flush=True)
    if hashes != {str(path): digest(path) for path in tracked}:
        raise RuntimeError("Sources changed during verification")
    report = {"passed": True, "source_sha256": hashes, "reference_ref": args.reference_ref,
              "reference_sha256": hashlib.sha256(original.encode()).hexdigest(), "cases": rows,
              "candidate_count": 2, "saved_group_update_logic_preserved": True,
              "domain": "All 16-bit channel/group values and all column values for tile-count widths 1 through 15"}
    (out/"summary.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
