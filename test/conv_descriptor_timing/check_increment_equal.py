#!/usr/bin/env python3
"""Check modular increment equality and its four-state comparison semantics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"](
    [ROOT / "rtl/common/increment_equal.sv", ROOT / "rtl/common/add_equal.sv"], ROOT)


def run(command, log):
    with log.open("w") as handle:
        subprocess.run(list(map(str, command)), stdout=handle, stderr=subprocess.STDOUT,
                       check=True, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    simulation_sources = []
    for source in SOURCES:
        local_source = out / source.name
        local_source.write_text(source.read_text().replace(
            "parameter int unsigned", "parameter integer").replace(
            "localparam int unsigned", "localparam integer"))
        simulation_sources.append(local_source)
    rows = []
    for width in (1, 2, 3, 4, 5, 6, 8, 11, 16, 17, 29, 32, 64):
        case = out / f"width{width}"
        case.mkdir(exist_ok=True)
        model = case / "proof.sv"
        model.write_text(f"""module proof(input logic[{width-1}:0]a,target,
 output logic actual,kept,expected,reference_equal,equivalent);
 increment_equal #(.p_width({width})) dut(.i_a(a),.i_target(target),.o_equal(actual));
 increment_equal #(.p_width({width}),.p_preserve_pairs(1'b1)) kept_dut(.i_a(a),.i_target(target),.o_equal(kept));
 add_equal #(.p_width({width}),.p_preserve_bits(1'b1),.p_keep_bits(1'b0)) reference_dut(.i_a(a),.i_b({width}'b0),
   .i_target(target),.i_carry_in(1'b1),.o_equal(reference_equal));
 assign expected=({width}'(a+{width}'d1)==target);
 assign equivalent=(actual===expected)&&(actual===reference_equal)&&(kept===reference_equal);
endmodule
""")
        script = case / "proof.ys"
        script.write_text("read_slang -USYNTHESIS -UXILINX_FPGA --top proof " + shlex.join(map(str, (*SOURCES, model))) +
                         "\nprep -top proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run((sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script), case / "formal.log")
        bench = case / "tb.sv"
        bench.write_text(f"""module tb;
 logic[{width-1}:0]a,target;
 logic actual,kept,expected,reference_equal,equivalent;
 proof dut(.*);
 initial begin
  for(integer sample=0;sample<16384;sample++)begin
   a={width}'($urandom);target={width}'($urandom);
   if(sample%2==0)target={width}'(a+{width}'d1);
   if(sample%3==0)a[(sample/3)%{width}]=1'bx;
   if(sample%5==0)target[(sample/5)%{width}]=1'bz;
   #1;
   if(actual!==reference_equal||kept!==reference_equal)$fatal(1,"Increment comparison differs at sample %0d",sample);
  end
  $display("INCREMENT_EQUAL_PASS checks=16384");$finish;
 end
endmodule
""")
        simulator = case / "simulation.vvp"
        run((shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", simulator,
             *simulation_sources, model, bench), case / "build.log")
        run((shutil.which("vvp") or "vvp", simulator), case / "run.log")
        if "INCREMENT_EQUAL_PASS checks=16384" not in (case / "run.log").read_text():
            raise RuntimeError(f"Missing simulation result for width {width}")
        rows.append({"width": width, "all_input_proof": True, "preserve_pair_modes": [False, True],
                     "four_state_samples": 16384, "four_state_comparisons": 32768})
        print("INCREMENT_EQUAL_PASS", width, flush=True)
    (out / "summary.json").write_text(json.dumps({"passed": True,
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in SOURCES}, "cases": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
