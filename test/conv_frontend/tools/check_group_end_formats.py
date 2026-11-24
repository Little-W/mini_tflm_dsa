#!/usr/bin/env python3
"""验证各数据格式的组末判断与完整通道掩码选择等价。"""
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
SAMPLES = 4096


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def region(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def unit(name, source):
    body = region(source, "  if (p_lanes <= 16) begin : g_group_end_by_lane", "  end else begin : g_group_end_wide") + "  end\n"
    return f'''module {name} #(parameter int p_lanes=8,parameter bit p_contiguous_chunk=0)(
 input logic [p_lanes-1:0] lane_context_allowed,word_lane_s8,word_lane_s16,
 input logic [p_lanes:0] column_lane_allowed_q,group_range_q,
 input logic i_word_output_q,input_s16,output logic o_group_end_o_equal);
 typedef struct packed {{logic input_s16;}} cfg_t;
 cfg_t i_c;
 logic [p_lanes-1:0] o_chunk_lane_allowed;
 logic [p_lanes:0] o_chunk_selected;
 assign i_c.input_s16=input_s16;
 assign o_chunk_lane_allowed=lane_context_allowed & column_lane_allowed_q[p_lanes-1:0] &
     ({{p_lanes{{!i_word_output_q}}}} | (input_s16 ? word_lane_s16 : word_lane_s8));
 assign o_chunk_selected[0]=p_contiguous_chunk ? !o_chunk_lane_allowed[0] : !(|o_chunk_lane_allowed);
 for(genvar step=1;step<=p_lanes;step++) begin:g_selection
   if(step==p_lanes)assign o_chunk_selected[step]=o_chunk_lane_allowed[step-1];
   else if(p_contiguous_chunk)assign o_chunk_selected[step]=o_chunk_lane_allowed[step-1]&&!o_chunk_lane_allowed[step];
   else assign o_chunk_selected[step]=o_chunk_lane_allowed[step-1]&&!(|o_chunk_lane_allowed[p_lanes-1:step]);
 end
''' + body + "endmodule\n"


def model(current, reference):
    helper = region(current, "// 输入掩码先形成各个有效长度", "`default_nettype wire")
    return helper + unit("candidate", current) + unit("reference", reference) + '''
module proof #(parameter int p_lanes=8,parameter bit p_contiguous_chunk=0)(
 input logic [p_lanes-1:0] lane_context_allowed,word_lane_s8,word_lane_s16,
 input logic [p_lanes:0] column_lane_allowed_q,group_range_q,
 input logic i_word_output_q,input_s16,output logic equivalent,actual,expected);
 candidate #(.p_lanes(p_lanes),.p_contiguous_chunk(p_contiguous_chunk)) u_candidate(.*,.o_group_end_o_equal(actual));
 reference #(.p_lanes(p_lanes),.p_contiguous_chunk(p_contiguous_chunk)) u_reference(.*,.o_group_end_o_equal(expected));
 assign equivalent=actual===expected;
endmodule
'''


def bench(lanes, contiguous):
    width = 5 * lanes + 4
    padded = (width + 31) // 32 * 32
    return f'''module tb;
 localparam int p_lanes={lanes};
 logic [p_lanes-1:0] lane_context_allowed,word_lane_s8,word_lane_s16;
 logic [p_lanes:0] column_lane_allowed_q,group_range_q;
 logic i_word_output_q,input_s16,equivalent,actual,expected;
 logic [{padded-1}:0] pattern;
 proof #(.p_lanes(p_lanes),.p_contiguous_chunk({contiguous})) dut(.*);
 initial begin
  for(integer sample=0;sample<{SAMPLES};sample++)begin
   for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
   if(sample%3==0)pattern[(sample/3)%{width}]=1'bx;
   if(sample%5==0)pattern[(sample/5)%{width}]=1'bz;
   {{lane_context_allowed,word_lane_s8,word_lane_s16,column_lane_allowed_q,group_range_q,
     i_word_output_q,input_s16}}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"Group end differs lanes=%0d contiguous=%0d sample=%0d",p_lanes,{contiguous},sample);
  end
  $display("GROUP_END_FORMATS_FOUR_STATE_PASS checks={SAMPLES}");$finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, helper = root / SOURCE, root / "rtl/common/onehot_mux.sv"
    reference = read_reference_file(root, args.reference_ref, str(SOURCE), text=True)
    generated = out / "model.sv"
    generated.write_text(model(source.read_text(), reference).replace("always_comb", "always @*"))
    tracked = [source, helper, generated, Path(__file__).resolve()]
    hashes = {str(p): digest(p) for p in tracked}
    rows = []
    for lanes in (1, 4, 8, 16):
        for contiguous in (0, 1):
            name = f"lanes{lanes}_contiguous{contiguous}"
            script, formal, testbench, binary, build, simulation = (out / (name + suffix) for suffix in
                (".ys", ".formal.log", ".sv", ".vvp", ".build.log", ".four_state.log"))
            script.write_text(f"read_slang --top proof -Gp_lanes={lanes} -Gp_contiguous_chunk={contiguous} " +
                shlex.join(map(str, (helper, generated))) +
                "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
                "prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
            with formal.open("w") as output:
                subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                    stdout=output, stderr=subprocess.STDOUT, check=True, timeout=120)
            if "SAT proof finished - no model found: SUCCESS!" not in formal.read_text():
                raise RuntimeError(str(formal))
            testbench.write_text(bench(lanes, contiguous))
            with build.open("w") as output:
                subprocess.run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                    *map(str, (helper, generated, testbench))], stdout=output, stderr=subprocess.STDOUT, check=True)
            with simulation.open("w") as output:
                subprocess.run([shutil.which("vvp") or "vvp", str(binary)], stdout=output,
                    stderr=subprocess.STDOUT, check=True, timeout=120)
            if f"GROUP_END_FORMATS_FOUR_STATE_PASS checks={SAMPLES}" not in simulation.read_text():
                raise RuntimeError(str(simulation))
            rows.append({"lanes": lanes, "contiguous": bool(contiguous), "passed": True,
                "formal_partitions": 1, "four_state_checks": SAMPLES,
                "formal_sha256": digest(formal), "four_state_sha256": digest(simulation)})
            print("GROUP_END_FORMATS_PASS", name, flush=True)
    if hashes != {str(p): digest(p) for p in tracked}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps({"passed": True, "source_sha256": hashes,
        "reference_ref": args.reference_ref, "cases": rows,
        "domain": "Arbitrary lane, column, group and byte-coverage masks, including noncontiguous masks; all binary combinations are proved. Four-state tests inject X and Z into control and mask inputs."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
