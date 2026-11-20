#!/usr/bin/env python3
"""测量队列占用选择到实际前端范围和接收资格输出的组合路径。"""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
import open_fpga_synth
from netlist_metrics import connected_paths, register_origins, resources

INPUTS = (("queue_count", 3), ("win_frontend_p0", 32), ("win_frontend_q0", 32),
          ("p0_q", 32), ("q0_q", 32), ("dma_rows_q", 5),
          ("position_count", 32), ("position_high_minus_one_q", 27),
          ("p0", 32), ("q0", 32), ("next_group_q", 33), ("rows_q", 5),
          ("windowed", 1), ("row_base_valid", 1),
          ("coordinate_address_valid", 1), ("incoming_group_fits", 1))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin_contains(word):
    return lambda name, cell, port: word in cell.get("attributes", {}).get("fpga_register_origin", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()
    out, proof_dir = args.out.resolve(), args.proof.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = json.loads((proof_dir / "summary.json").read_text())
    if not proof["passed"] or digest(ROOT / "rtl/npu/conv/conv_im2col_frontend.sv") != proof["source_sha256"]:
        raise RuntimeError("The measured frontend must match the completed proof")
    dma_path = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv"
    dma = dma_path.read_text()
    reference_dma = read_rtl_source(proof["reference_commit"] +
        ":rtl/npu/dma/axi_dual_block_dma.sv", cwd=ROOT, text=True)
    if dma != reference_dma:
        raise RuntimeError("The DMA field selection must match the fixed source")
    selections = "\n".join(re.findall(r"    assign frontend_i_tile_(?:p0|q0|rows)\s*=.*?;", dma, re.S))
    if len(re.findall(r"\bassign\b", selections)) != 3:
        raise RuntimeError("Expected three actual descriptor selections")
    selections = selections.replace(" : rows_q;", " : dma_rows_q;")
    declarations = "\n".join(f"logic [{width}-1:0] {name};" for name, width in INPUTS)
    updates = "\n".join(f"{name} <= i_{name};" for name, width in INPUTS)
    tool = runpy.run_path(str(ROOT / "test/frontend_tile_input_depth/formal.py"))
    cases = {}
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label in ("reference", "current"):
            folder = out / label
            folder.mkdir(exist_ok=True)
            selected = "assign win_busy = queue_count != 3'd0;\n" if label == "reference" else \
                "always_ff @(posedge clk) win_busy <= i_queue_count != 3'd0;\n"
            wrapper = "module tile_input_registered(input logic clk,\n" + ",\n".join(
                f"input logic [{width}-1:0] i_{name}" for name, width in INPUTS) + """,
output logic o_range, o_fast, o_q_fast,
output logic [2:0] o_queue_count);
localparam int CONV_RW=5;
logic win_busy,win_payload_select;
logic [31:0] frontend_i_tile_p0,frontend_i_tile_q0;
logic [4:0] frontend_i_tile_rows;
logic range_result;
logic [1:0] fast_result;
""" + declarations + "\n" + selected + "assign win_payload_select = win_busy;\n" + selections + \
                "\nassign o_queue_count=queue_count;\nalways_ff @(posedge clk) begin\n" + updates + \
                "\no_range<=range_result;\no_fast<=fast_result[1];\no_q_fast<=fast_result[0];\nend\n"
            for kind in ("range", "fast"):
                port_list = tool["RANGE_PORTS"] if kind == "range" else tool["FAST_PORTS"]
                connections = []
                for name, width in port_list:
                    value = "frontend_i_" + name if name in ("tile_p0", "tile_q0", "tile_rows") else name
                    connections.append("." + name + "(" + value + ")")
                connections.append(".observed(" + kind + "_result)")
                wrapper += label + "_" + kind + " #(.p_cfg_idle_use_lut(1'b1)) u_" + kind + \
                    " (" + ",".join(connections) + ");\n"
            wrapper += "endmodule\n"
            source = folder / "registered.sv"
            source.write_text((proof_dir / (label + "_range.sv")).read_text() +
                (proof_dir / (label + "_fast.sv")).read_text() + wrapper)
            import pyosys
            options, primitives = open_fpga_synth.primitive_models(folder, [str(source)],
                Path(pyosys.__file__).parent / "share/xilinx")
            mapped, pre_lut, script = folder / "mapped.json", folder / "pre_lut.il", folder / "run.ys"
            script.write_text("read_slang --keep-hierarchy --top tile_input_registered " + options + " " +
                shlex.quote(str(source)) + "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
                "hierarchy -check -top tile_input_registered\n" +
                "synth_xilinx -top tile_input_registered -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
                "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
                "synth_xilinx -top tile_input_registered -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
                "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
            log = folder / "synthesis.log"
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                    "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            module = json.loads(mapped.read_text())["modules"]["tile_input_registered"]
            for name, value in register_origins(pre_lut).items():
                if name in module["cells"]:
                    module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
            for name in list(module["cells"]):
                if module["cells"][name]["type"] == "$scopeinfo":
                    del module["cells"][name]
            paths = {"all": connected_paths(module, limit=6, group_limit=6)}
            selector = "queue_count" if label == "reference" else "win_busy"
            for endpoint in ("o_range", "o_fast", "o_q_fast"):
                paths[endpoint] = connected_paths(module, limit=4, group_limit=4,
                    root_filter=origin_contains(selector), sink_filter=origin_contains(endpoint))
            if not all(value["graph_complete"] for value in paths.values()):
                raise RuntimeError("The mapped bit dependency graph must be complete")
            row = dict(resources=resources(module["cells"]), paths=paths,
                source_sha256=digest(source), mapped_sha256=digest(mapped), pre_lut_sha256=digest(pre_lut),
                log_sha256=digest(log), primitive_models=primitives)
            cases[label] = row
            (folder / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
            print(label, row["resources"]["logic_lut_cells"],
                {name: value["longest_register_path_cells"] for name, value in paths.items()}, flush=True)
    report = dict(passed=True, reference_commit=proof["reference_commit"],
        source_sha256=proof["source_sha256"], reference_sha256=proof["reference_sha256"],
        dma_sha256=digest(dma_path), proof_summary_sha256=digest(proof_dir / "summary.json"),
        actual_dma_field_selection=True, RW=5, CACHE_POLICY=3,
        boundary="registered descriptor and frontend context to range/fast predicate outputs",
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
