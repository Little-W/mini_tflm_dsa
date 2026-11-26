#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""检查向量舍入的全部寄存配置、四态传播与完整模块映射结果。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import runpy
import os
from pathlib import Path
import signal
import shlex
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_round_shift.sv")
DEPENDENCIES = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log: Path, timeout: int = 180) -> int:
    """执行独立检查，并限制单个进程的常驻内存。"""
    peak = 0
    started = time.monotonic()
    with log.open("w") as stream:
        process = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                try:
                    fields = [line.split()[1] for line in
                              Path(f"/proc/{process.pid}/status").read_text().splitlines()
                              if line.startswith("VmRSS:")]
                    rss = int(fields[0]) if fields else 0
                    peak = max(peak, rss)
                    if rss > 270000:
                        raise RuntimeError(f"Resident memory exceeds 270000 KiB: {log}")
                except FileNotFoundError:
                    pass
                if time.monotonic() - started > timeout:
                    raise TimeoutError(str(log))
                time.sleep(0.02)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait()
            raise
    return peak


def bench(samples: int) -> str:
    return f"""module tb;
logic clk;
logic signed [63:0] value;
logic [5:0] amount;
logic [3:0][63:0] actual, expected, actual_floor, expected_floor;
for (genvar mode_index=0; mode_index<4; mode_index++) begin:g_mode
  round_reference #(.REGISTER_INPUT(mode_index/2), .REGISTER_MIDDLE(mode_index%2))
    a(clk, value, amount, expected[mode_index], expected_floor[mode_index]);
  round_direct #(.REGISTER_INPUT(mode_index/2), .REGISTER_MIDDLE(mode_index%2))
    b(clk, value, amount, actual[mode_index], actual_floor[mode_index]);
end
initial begin
  clk=0; value=0; amount=0;
  for (integer sample=0; sample<{samples}; sample++) begin
    clk=0; value={{$urandom,$urandom}}; amount=$urandom;
    if (sample%13==0) value[sample%64]=1'bx;
    if (sample%23==0) value[(sample*17)%64]=1'bz;
    if (sample%17==0) amount[sample%6]=1'bx;
    if (sample%29==0) amount[sample%6]=1'bz;
    #2; clk=1; #1;
    if ({{actual,actual_floor}}!=={{expected,expected_floor}})
      $fatal(1,"Round comparison sample=%0d",sample);
  end
  $display("ROUND_COMPARE_PASS configurations=4 samples={samples}");
  $finish;
end
endmodule
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-source-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=8192)
    args = parser.parse_args()
    root, reference_root, out = (args.source_root.resolve(),
                                 args.reference_source_root.resolve(), args.out.resolve())
    out.mkdir(parents=True, exist_ok=True)
    paths = {"reference": reference_root/SOURCE, "candidate": root/SOURCE}
    hashes = {name: digest(path) for name, path in paths.items()}
    tops = {"reference": "round_reference", "candidate": "round_direct"}
    sources = {}
    for name, path in paths.items():
        target = out/(tops[name]+".sv")
        original = path.read_text()
        declaration = "module vector_round_shift #("
        if original.count(declaration) != 1:
            raise ValueError(f"Expected one vector_round_shift declaration: {path}")
        target.write_text(original.replace(declaration, "module "+tops[name]+" #("))
        sources[name] = target
    worker = [sys.executable, ROOT/"scripts/fpga/open_fpga_synth.py", "--worker"]
    formal, memory = [], {}
    for registered_input in (0, 1):
        for registered_middle in (0, 1):
            name = f"proof_{registered_input}_{registered_middle}"
            options = (f"-GREGISTER_INPUT={registered_input} "
                       f"-GREGISTER_MIDDLE={registered_middle}")
            script = out/(name+".ys")
            script.write_text(
                f"read_slang --top round_reference {options} {shlex.join(map(str, DEPENDENCIES([sources['reference']], root)))}\n"
                "prep -top round_reference -flatten\nrename round_reference gold\ndesign -stash gold\n"
                f"read_slang --top round_direct {options} {shlex.join(map(str, DEPENDENCIES([sources['candidate']], root)))}\n"
                "prep -top round_direct -flatten\nrename round_direct gate\n"
                "design -copy-from gold -as gold gold\nequiv_make gold gate equiv\n"
                "hierarchy -top equiv\nequiv_simple -seq 3\nequiv_induct -seq 3\nequiv_status -assert\n")
            memory[name] = run([*worker, script], out/(name+".log"))
            formal.append({"REGISTER_INPUT": registered_input,
                           "REGISTER_MIDDLE": registered_middle, "equivalent": True})
    simulation_sources = []
    for name, source in sources.items():
        target = out/(tops[name]+"_simulation.sv")
        target.write_text(source.read_text().replace("always_comb", "always @*"))
        simulation_sources.append(target)
    testbench, executable = out/"tb.sv", out/"comparison.vvp"
    testbench.write_text(bench(args.samples))
    run(["iverilog", "-g2012", "-s", "tb", "-o", executable,
         *DEPENDENCIES(simulation_sources, root), testbench], out/"simulation_build.log")
    run(["vvp", executable], out/"simulation_run.log")
    if "ROUND_COMPARE_PASS" not in (out/"simulation_run.log").read_text():
        raise RuntimeError("Four-state comparison did not complete")
    specification = importlib.util.spec_from_file_location(
        "complete_paths", ROOT/"test/conv_frontend/tools/measure_complete_paths.py")
    measurement = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(measurement)
    mapping = {}
    for name, source in sources.items():
        top, mapped = tops[name], out/(name+"_mapped.json")
        script = out/(name+"_mapping.ys")
        script.write_text(
            f"read_slang --top {top} -GREGISTER_INPUT=1 -GREGISTER_MIDDLE=1 {shlex.join(map(str, DEPENDENCIES([source], root)))}\n"
            f"synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -abc9\n"
            f"check -assert\nwrite_json {mapped}\nstat\n")
        memory[name+"_mapping"] = run([*worker, script], out/(name+"_mapping.log"))
        module = json.loads(mapped.read_text())["modules"][top]
        # 层次名称记录没有电路端口，不参与组合连接图。
        module["cells"] = {key: cell for key, cell in module["cells"].items()
                           if cell["type"] != "$scopeinfo"}
        report = measurement.measure(module, path_limit=8)
        if not report["graph_complete"]:
            raise RuntimeError(f"Incomplete mapped graph: {name}")
        (out/(name+"_metrics.json")).write_text(json.dumps(report, indent=2)+"\n")
        mapping[name] = {"resources": report["resources"],
                         "maximum_combinational_cells": {
                             key: value["maximum_combinational_cells"]
                             for key, value in report["path_groups"].items()},
                         "graph_complete": True, "mapped_sha256": digest(mapped)}
    if any(digest(paths[name]) != value for name, value in hashes.items()):
        raise RuntimeError("RTL source changed during validation")
    result = {"passed": True, "source_file": str(SOURCE), "source_sha256": hashes,
              "formal": formal, "four_state_samples_per_configuration": args.samples,
              "four_state_configuration_count": 4, "mapping": mapping,
              "peak_rss_kib": memory, "script_sha256": digest(Path(__file__))}
    (out/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print("VECTOR_ROUNDING_AREA_PASS", str(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
