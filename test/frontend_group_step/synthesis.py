#!/usr/bin/env python3
"""测量实际分组增量比较的面积及有效通道到范围输出的路径。"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
import open_fpga_synth
from netlist_metrics import connected_paths, register_origins, resources


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--range-output", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = json.loads((args.proof / "summary.json").read_text())
    if not proof["passed"]:
        raise RuntimeError("Complete formal proof is required")
    rtl = (ROOT / "rtl/npu/conv/conv_im2col_frontend.sv").read_text()
    if digest(ROOT / "rtl/npu/conv/conv_im2col_frontend.sv") != proof["source_sha256"]:
        raise RuntimeError("The frontend differs from the proved source")
    proof_tools = runpy.run_path(str(ROOT / "test/frontend_group_step/formal.py"))
    range_expression = proof_tools["extract_range"](rtl)
    result_logic = "assign calc_result = calc_observed[7:4];\n" if args.range_output else "assign calc_result = calc_observed[3:0];\n"
    ports = proof_tools["PORTS"]
    declarations, updates, connections = [], [], []
    for name, width in ports:
        saved = name + "_saved"
        declarations.append("logic [" + width + "-1:0] " + saved + ";")
        updates.append(saved + " <= " + name + ";")
        connections.append("." + name + "(" + saved + ")")
    cases = {}
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label in ("reference", "current"):
            folder = out / label
            folder.mkdir(exist_ok=True)
            source = folder / "registered.sv"
            source.write_text((args.proof / (label + ".sv")).read_text() + """
module range_registered #(parameter int LANES=4)(
input logic clk,
""" + ",\n".join("input logic [" + width + "-1:0] " + name for name, width in ports) + """,
output logic [3:0] o_observed);
""" + "\n".join(declarations) + "\nlogic [7:0] calc_observed;\nlogic [3:0] calc_result;\n" + result_logic +
                "always_ff @(posedge clk) begin\n" + "\n".join(updates) +
                "\no_observed <= calc_result;\nend\n" + label +
                "_range #(.LANES(LANES), .p_cfg_idle_use_lut(1'b1)) u_calc (" +
                ",".join(connections) + ",.observed(calc_observed));\nendmodule\n")
            import pyosys
            source_paths = [args.proof.resolve() / "add_equal.sv", source]
            options, primitives = open_fpga_synth.primitive_models(folder, list(map(str, source_paths)),
                Path(pyosys.__file__).parent / "share/xilinx")
            mapped, pre_lut, script = folder / "mapped.json", folder / "pre_lut.il", folder / "run.ys"
            top = "range_registered"
            script.write_text("read_slang --keep-hierarchy --top " + top + " " + options + " " +
                " ".join(shlex.quote(str(path)) for path in source_paths) + "\n" +
                "read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                "hierarchy -check -top " + top + "\n" +
                "synth_xilinx -top " + top + " -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
                "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
                "synth_xilinx -top " + top + " -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
                "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
            log = folder / "synthesis.log"
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            module = json.loads(mapped.read_text())["modules"][top]
            for name, origin in register_origins(pre_lut).items():
                if name in module["cells"]:
                    module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
            for name in list(module["cells"]):
                if module["cells"][name]["type"] == "$scopeinfo":
                    del module["cells"][name]
            all_paths = connected_paths(module, limit=6, group_limit=6)
            mask_paths = connected_paths(module, limit=4, group_limit=4,
                root_filter=lambda n, c, p: "chunk_lane_allowed_saved" in c.get("attributes", {}).get("fpga_register_origin", ""))
            if not all_paths["graph_complete"] or not mask_paths["graph_complete"]:
                raise RuntimeError("Incomplete mapped graph")
            row = dict(resources=resources(module["cells"]), all_paths=all_paths,
                mask_paths=mask_paths, source_sha256=digest(source), mapped_sha256=digest(mapped),
                pre_lut_sha256=digest(pre_lut), log_sha256=digest(log), primitive_models=primitives)
            cases[label] = row
            (folder / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
            print(label, row["resources"]["logic_lut_cells"], all_paths["longest_register_path_cells"],
                  mask_paths["longest_register_path_cells"], flush=True)
    report = dict(passed=True, source_sha256=proof["source_sha256"], reference_sha256=proof["reference_sha256"],
        reference_commit=proof["reference_commit"], configuration=dict(LANES=4), cases=cases,
        outputs="group_range_next[5]" if args.range_output else "group_boundary_predicates",
        actual_range_expression=range_expression if args.range_output else None,
        proof_summary_sha256=digest(args.proof / "summary.json"),
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
