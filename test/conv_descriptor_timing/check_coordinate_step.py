#!/usr/bin/env python3
"""证明完整坐标模加法和十六位尺寸比较，并检查四态仿真结果。"""
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
SOURCES = (
    "rtl/common/parallel_prefix_add.sv",
    "rtl/common/add_equal.sv",
    "rtl/npu/conv/conv_coordinate_step.sv",
)


def comparison(width: int) -> str:
    return f"""module comparison (
input logic [{width - 1}:0] i_base, i_delta,
input logic [15:0] i_limit,
output logic equivalent
);
wire [{width - 1}:0] actual_sum, expected_sum;
wire actual_valid, expected_valid;
conv_coordinate_step #(.p_width({width})) u_step (
  .i_base, .i_delta, .i_limit, .o_sum(actual_sum), .o_valid(actual_valid)
);
assign expected_sum = i_base + i_delta;
assign expected_valid = expected_sum < {width}'(i_limit);
`ifdef SYNTHESIS
assign equivalent = {{actual_sum, actual_valid}} == {{expected_sum, expected_valid}};
`else
assign equivalent = {{actual_sum, actual_valid}} === {{expected_sum, expected_valid}};
`endif
endmodule
"""


def simulation(width: int) -> str:
    bits = 2 * width + 16
    return comparison(width) + f"""module tb;
logic [{bits - 1}:0] stimulus, known_stimulus;
wire [{width - 1}:0] i_base = stimulus[{width - 1}:0];
wire [{width - 1}:0] i_delta = stimulus[{2 * width - 1}:{width}];
wire [15:0] i_limit = stimulus[{bits - 1}:{2 * width}];
wire equivalent;
integer checks = 0;
comparison dut (.*);
task automatic check;
  #1;
  if (equivalent !== 1'b1)
    $fatal(1, "coordinate mismatch width={width} stimulus=%h", stimulus);
  checks++;
endtask
initial begin
  stimulus = '0; check();
  stimulus = '1; check();
  for (int trial = 0; trial < 32; trial++) begin
    for (int bit_index = 0; bit_index < {bits}; bit_index++)
      stimulus[bit_index] = 1'($urandom());
    known_stimulus = stimulus; check();
    for (int bit_index = 0; bit_index < {bits}; bit_index++) begin
      stimulus = known_stimulus; stimulus[bit_index] = 1'bx; check();
      stimulus = known_stimulus; stimulus[bit_index] = 1'bz; check();
    end
    stimulus = 'x; check();
    stimulus = 'z; check();
  end
  $display("COORDINATE_FOUR_STATE_PASS checks=%0d", checks);
  $finish;
end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default=shutil.which("iverilog") or "iverilog")
    parser.add_argument("--vvp", default=shutil.which("vvp") or "vvp")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [source_root / name for name in SOURCES]
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
              for name, path in zip(SOURCES, sources)}
    simulation_sources = []
    for source in sources:
        local = out / source.name
        local.write_text(source.read_text().replace("parameter int unsigned", "parameter integer"))
        simulation_sources.append(local)
    report = {"passed": False, "sources_sha256": hashes, "input_assumptions": [],
              "latency_cycles": 0, "limit_width": 16, "cases": []}
    for width in (17, 18, 32, 35, 64):
        folder = out / f"w{width}"
        folder.mkdir(exist_ok=True)
        formal = folder / "formal.sv"
        formal.write_text(comparison(width))
        proof = folder / "proof.ys"
        proof.write_text("read_slang --top comparison -D SYNTHESIS=1 " +
                         shlex.join(map(str, [*sources, formal])) + "\n" +
                         "prep -top comparison -flatten\ncheck -assert\n" +
                         "sat -set-def-inputs -prove equivalent 1 -verify\n")
        with (folder / "proof.log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(proof)], stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        bench = folder / "simulation.sv"
        bench.write_text(simulation(width))
        binary = folder / "run.vvp"
        with (folder / "build.log").open("w") as log:
            subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                            *map(str, simulation_sources), str(bench)], stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        with (folder / "run.log").open("w") as log:
            subprocess.run([args.vvp, str(binary)], stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        output = (folder / "run.log").read_text().strip()
        if "COORDINATE_FOUR_STATE_PASS" not in output:
            raise AssertionError(output)
        report["cases"].append({"coordinate_width": width, "formal_passed": True,
                                "four_state_passed": True, "simulation": output})
        print(f"COORDINATE_STEP_PASS width={width}", flush=True)
    report["sources_unchanged"] = hashes == {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in zip(SOURCES, sources)}
    if not report["sources_unchanged"]:
        raise RuntimeError("Coordinate sources changed during validation")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
