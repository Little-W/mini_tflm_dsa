#!/usr/bin/env python3
"""验证并行无符号比较的全部二态输入和逐位四态输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/common/parallel_unsigned_compare.sv"
WIDTHS = (1, 2, 3, 7, 16, 27, 35, 64)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(width):
    return f'''module proof(input logic [{width-1}:0] i_a,i_b,
output logic equivalent,output logic [1:0] actual,expected);
parallel_unsigned_compare #(.p_width({width})) dut(
 .i_a,.i_b,.o_less(actual[1]),.o_equal(actual[0]));
assign expected={{i_a<i_b,i_a==i_b}};
assign equivalent=actual===expected;
endmodule
'''


def bench(width):
    padded = (2 * width + 31) // 32 * 32
    return f'''module tb;
logic [{width-1}:0] i_a,i_b,known_a,known_b;
logic [{padded-1}:0] pattern;
wire equivalent;wire [1:0] actual,expected;
integer checks=0;
proof dut(.*);
task automatic check_value;
 #1;
 if(equivalent!==1'b1)$fatal(1,"Comparison mismatch width={width} actual=%b expected=%b",actual,expected);
 checks++;
endtask
initial begin
 for(integer sample=0;sample<2048;sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
  {{i_a,i_b}}=pattern;check_value();
  if(sample%8==0)begin
   i_b=i_a;check_value();
   i_b=i_a+{width}'(1);check_value();
   i_b=i_a-{width}'(1);check_value();
  end
 end
 for(integer trial=0;trial<8;trial++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
  {{known_a,known_b}}=pattern;
  if(trial==0)begin known_a='0;known_b='0;end
  if(trial==1)begin known_a='1;known_b='1;end
  for(integer bit_index=0;bit_index<{2*width};bit_index++)begin
   {{i_a,i_b}}={{known_a,known_b}};
   if(bit_index<{width})i_b[bit_index]=1'bx;else i_a[bit_index-{width}]=1'bx;
   check_value();
   {{i_a,i_b}}={{known_a,known_b}};
   if(bit_index<{width})i_b[bit_index]=1'bz;else i_a[bit_index-{width}]=1'bz;
   check_value();
  end
 end
 i_a='x;i_b='x;check_value();
 i_a='z;i_b='z;check_value();
 $display("PARALLEL_COMPARE_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / SOURCE
    hashes = {SOURCE: digest(source), "verification_script": digest(Path(__file__))}
    simulation_source = out / "parallel_unsigned_compare.sv"
    simulation_source.write_text(source.read_text().replace("parameter int unsigned", "parameter integer").replace(
        "localparam int unsigned", "localparam integer"))
    rows = []
    for width in WIDTHS:
        generated, testbench, script, formal, binary, build, simulation = (
            out / (f"width{width}" + suffix) for suffix in
            (".sv", ".tb.sv", ".ys", ".formal.log", ".vvp", ".build.log", ".four_state.log"))
        generated.write_text(model(width))
        script.write_text("read_slang --top proof " + shlex.join(map(str, (source, generated))) +
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
            "prep -top proof -flatten\ncheck -assert\n" +
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with formal.open("w") as output:
            subprocess.run([sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=120)
        if formal.read_text().count("SAT proof finished - no model found: SUCCESS!") != 1:
            raise RuntimeError(str(formal))
        testbench.write_text(bench(width))
        with build.open("w") as output:
            subprocess.run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                *map(str, (simulation_source, generated, testbench))], stdout=output,
                stderr=subprocess.STDOUT, check=True, timeout=120)
        with simulation.open("w") as output:
            subprocess.run([shutil.which("vvp") or "vvp", str(binary)], stdout=output,
                stderr=subprocess.STDOUT, check=True, timeout=120)
        checks = 2818 + 32 * width
        if f"PARALLEL_COMPARE_FOUR_STATE_PASS checks={checks}" not in simulation.read_text():
            raise RuntimeError(str(simulation))
        rows.append({"width": width, "formal_partitions": 1, "simulation_checks": checks,
            "unknown_input_bit_checks": 32 * width, "passed": True,
            "formal_sha256": digest(formal), "four_state_sha256": digest(simulation)})
        print("PARALLEL_COMPARE_PASS", "width=" + str(width), flush=True)
    if hashes != {SOURCE: digest(source), "verification_script": digest(Path(__file__))}:
        raise RuntimeError("Sources changed during verification")
    (out / "summary.json").write_text(json.dumps({"passed": True, "source_sha256": hashes,
        "cases": rows, "domain": "All binary values are proved against the unsigned SystemVerilog operators. Simulation includes equality and adjacent values, and injects X and Z into every input bit."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
