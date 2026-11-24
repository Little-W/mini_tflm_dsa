#!/usr/bin/env python3
"""Verify grouped subtraction against the complete SystemVerilog subtraction result."""
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
SOURCE = ROOT / "rtl/common/borrow_select_subtract.sv"

def run(command, log):
    with log.open("w") as handle:
        subprocess.run(list(map(str, command)), stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=120)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for width in (1, 2, 3, 4, 5, 6, 7, 8, 16):
        case = out / f"width{width}"
        case.mkdir(exist_ok=True)
        model = case / "proof.sv"
        model.write_text(f"""module proof(input logic[{width-1}:0]a,b,
 output logic[{width}:0]actual,expected,output logic equivalent);
 borrow_select_subtract #(.p_width({width})) dut(.i_a(a),.i_b(b),.o_difference(actual));
 assign expected={{1'b0,a}}-{{1'b0,b}};
 assign equivalent=actual===expected;
endmodule
""")
        script = case / "proof.ys"
        script.write_text("read_slang --top proof " + shlex.join(map(str, (SOURCE, model))) +
                         "\nprep -top proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script), case / "formal.log")
        bench = case / "tb.sv"
        bench.write_text(f"""module tb;
 logic[{width-1}:0]a,b;
 logic[{width}:0]actual,expected;
 logic equivalent;
 proof dut(.*);
 initial begin
  for(integer sample=0;sample<16384;sample++)begin
   a={width}'($urandom);b={width}'($urandom);
   if(sample%3==0)a[(sample/3)%{width}]=1'bx;
   if(sample%5==0)b[(sample/5)%{width}]=1'bz;
   #1;
   if(actual!==expected)$fatal(1,"Subtraction differs at sample %0d",sample);
  end
  $display("BORROW_SELECT_PASS checks=16384");$finish;
 end
endmodule
""")
        simulator = case / "simulation.vvp"
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", simulator,
             SOURCE, model, bench), case / "build.log")
        run((shutil.which("vvp") or "vvp", simulator), case / "run.log")
        if "BORROW_SELECT_PASS checks=16384" not in (case / "run.log").read_text():
            raise RuntimeError(f"Missing simulation result for width {width}")
        rows.append({"width": width, "all_input_proof": True, "four_state_samples": 16384})
        print("BORROW_SELECT_PASS", width, flush=True)
    (out / "summary.json").write_text(json.dumps({"passed": True,
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "cases": rows}, indent=2) + "\n")

if __name__ == "__main__":
    main()
