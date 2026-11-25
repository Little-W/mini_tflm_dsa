#!/usr/bin/env python3
"""检查五路地址步进的完整模加法和四态结果。"""
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


ROOT = Path(__file__).resolve().parents[2]


def model(source: str) -> str:
    first = source.index("  for (genvar source = 0; source < 5; source++) begin : g_movement_sum")
    last = source.index("  // 配置阶段保存乘积", first)
    helper = re.search(r"module conv_geometry_movement_add\b.*?endmodule", source, re.S)
    if helper is None:
        raise ValueError("缺少地址加法模块")
    return """module comparison(
input logic [4:0][31:0] movement_i_a, movement_step_delta, movement_wrap_delta,
input logic [4:0] movement_wrap_select,
output logic equivalent);
logic [4:0][31:0] movement_i_b, movement_o_sum, reference_sum;
for (genvar index=0; index<5; index++) begin : g_reference
  assign movement_i_b[index]=movement_wrap_select[index] ?
      movement_wrap_delta[index] : movement_step_delta[index];
  assign reference_sum[index]=movement_i_a[index]+movement_i_b[index];
end
""" + source[first:last] + """
`ifdef SYNTHESIS
assign equivalent=movement_o_sum==reference_sum;
`else
assign equivalent=movement_o_sum===reference_sum;
`endif
endmodule
""" + helper.group(0) + "\n"


BENCH = """module tb;
logic [484:0] stimulus, known_stimulus;
wire [4:0][31:0] movement_i_a=stimulus[159:0];
wire [4:0][31:0] movement_step_delta=stimulus[319:160];
wire [4:0][31:0] movement_wrap_delta=stimulus[479:320];
wire [4:0] movement_wrap_select=stimulus[484:480];
wire equivalent;
integer checks=0;
comparison dut(.*);
task automatic check;
  #1;
  if(equivalent!==1'b1)$fatal(1,"Movement sum mismatch stimulus=%h",stimulus);
  checks++;
endtask
initial begin
  stimulus='0;check();stimulus='1;check();
  for(int trial=0; trial<32; trial++)begin
    for(int bit_index=0; bit_index<485; bit_index++)
      stimulus[bit_index]=1'($urandom());
    known_stimulus=stimulus;check();
    for(int bit_index=0; bit_index<485; bit_index++)begin
      stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
      stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
    end
    stimulus='x;check();stimulus='z;check();
  end
  $display("MOVEMENT_SUMS_PASS checks=%0d",checks);$finish;
end
endmodule
"""


def run(command, log: Path, timeout: int):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / "rtl/npu/conv/conv_im2col_geometry.sv",
               root / "rtl/common/parallel_prefix_add.sv"]
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sources}
    comparison = out / "comparison.sv"
    comparison.write_text(model(sources[0].read_text()))
    proof = out / "proof.ys"
    proof.write_text("read_slang --top comparison -D SYNTHESIS=1 " +
                     shlex.join(map(str, [sources[1], comparison])) + "\n" +
                     "prep -top comparison -flatten\ncheck -assert\n" +
                     "sat -set-def-inputs -prove equivalent 1 -verify\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", proof],
        out / "proof.log", 180)
    simulation_helper = out / sources[1].name
    simulation_helper.write_text(sources[1].read_text().replace(
        "parameter int unsigned", "parameter integer").replace(
        "localparam int unsigned", "localparam integer"))
    bench = out / "bench.sv"
    bench.write_text(BENCH)
    executable = out / "simulation.vvp"
    run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", executable,
         simulation_helper, comparison, bench], out / "build.log", 60)
    run([shutil.which("vvp") or "vvp", executable], out / "run.log", 180)
    result = (out / "run.log").read_text().strip()
    if "MOVEMENT_SUMS_PASS checks=31138" not in result:
        raise AssertionError(result)
    unchanged = hashes == {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sources}
    if not unchanged:
        raise RuntimeError("验证期间源文件发生变化")
    report = dict(passed=True, formal_passed=True, four_state_passed=True,
                  source_sha256=hashes, sources_unchanged=True, address_width=32,
                  input_assumptions=[], added_state_bits=0, simulation=result)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    main()
