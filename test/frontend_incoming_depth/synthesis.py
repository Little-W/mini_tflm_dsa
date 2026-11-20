#!/usr/bin/env python3
"""测量实际通道范围、描述符选择与快速接收表达式的寄存器路径。"""
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
import open_fpga_synth as flow
from remap_fpga_luts import physical_cost_library, mapping_commands
from netlist_metrics import connected_paths, register_origins, resources

INPUTS = (("win_busy", 1), ("win_frontend_p0", 32), ("win_frontend_q0", 32),
          ("p0_q", 32), ("q0_q", 32), ("dma_rows_q", 5),
          ("ch0_q", 16), ("cols_q", 5), ("group_c", 16),
          ("p0", 32), ("q0", 32), ("next_group_q", 33), ("rows_q", 5),
          ("windowed", 1), ("row_base_valid", 1), ("coordinate_address_valid", 1),
          ("row_base_addr", 32), ("word_addr", 32), ("addr", 32),
          ("tap_wrap_bytes", 32), ("tap_step_bytes", 32), ("incoming_tap_wrap", 1),
          ("finishing_tile", 1), ("state", 5), ("word_valid", 1))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin_contains(word):
    return lambda name, cell, port: word in cell.get("attributes", {}).get("fpga_register_origin", "")


def run(script, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
            cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


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
        raise RuntimeError("The measured frontend differs from the proved source")
    dma_path = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv"
    dma = dma_path.read_text()
    if dma != subprocess.check_output(["git", "show", proof["reference_commit"] + ":rtl/npu/dma/axi_dual_block_dma.sv"], cwd=ROOT, text=True):
        raise RuntimeError("The actual DMA field selection changed")
    selections = "\n".join(re.findall(r"    assign frontend_i_tile_(?:p0|q0|rows)\s*=.*?;", dma, re.S))
    if len(re.findall(r"\bassign\b", selections)) != 3:
        raise RuntimeError("Expected three actual descriptor selections")
    selections = selections.replace(" : rows_q;", " : dma_rows_q;")
    declarations = "\n".join(f"logic [{width}-1:0] {name};" for name, width in INPUTS)
    updates = "\n".join(f"{name} <= i_{name};" for name, width in INPUTS)
    tool = runpy.run_path(str(ROOT / "test/frontend_incoming_depth/formal.py"))
    cases = {}
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label in ("reference", "current"):
            folder = out / label
            folder.mkdir(exist_ok=True)
            wrapper = "module incoming_registered(input logic clk,\n" + ",\n".join(
                f"input logic [{width}-1:0] i_{name}" for name, width in INPUTS) + """,
output logic o_group_fits,o_fast,o_q_fast,o_word_equal,o_live_equal,o_word_hit);
localparam int CONV_RW=5;
logic win_payload_select;
logic [31:0] frontend_i_tile_p0,frontend_i_tile_q0;
logic [4:0] frontend_i_tile_rows;
logic [6:0] result;
""" + declarations + "\nassign win_payload_select=win_busy;\n" + selections + \
                "\nalways_ff @(posedge clk) begin\n" + updates + \
                "\no_group_fits<=result[5];\no_fast<=result[4];\no_q_fast<=result[3];\no_word_equal<=result[2];\no_live_equal<=result[1];\no_word_hit<=result[0];\nend\n"
            connections = []
            for name, width in tool["PORTS"]:
                value = "frontend_i_" + name if name in ("tile_p0", "tile_q0", "tile_rows") else name
                connections.append("." + name + "(" + value + ")")
            wrapper += label + "_incoming #(.p_cfg_idle_use_lut(1'b1)) u_incoming (" + \
                ",".join(connections + [".observed(result)"]) + ");\nendmodule\n"
            source = folder / "registered.sv"
            source.write_text((proof_dir / (label + "_incoming.sv")).read_text() + wrapper)
            import pyosys
            options, primitives = flow.primitive_models(folder, [str(source), str(ROOT / "rtl/common/add_equal.sv")],
                Path(pyosys.__file__).parent / "share/xilinx")
            mapped, pre_lut, script = folder / "mapped.json", folder / "pre_lut.il", folder / "pre_lut.ys"
            script.write_text("read_slang --keep-hierarchy --top incoming_registered " + options + " " +
                " ".join(shlex.quote(str(path)) for path in (source, ROOT / "rtl/common/add_equal.sv")) +
                "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nhierarchy -check -top incoming_registered\n"
                "synth_xilinx -top incoming_registered -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n"
                "write_rtlil " + shlex.quote(str(pre_lut)) + "\n")
            run(script, folder / "pre_lut.log")
            raw, library = folder / "native.lut", folder / "physical.lut"
            prepare = folder / "library.ys"
            prepare.write_text("read_verilog -lib -specify +/xilinx/cells_sim.v\nadd -mod library_top\n"
                "abc9_ops -prep_lut 0\nabc9_ops -write_lut " + shlex.quote(str(raw)) + "\n")
            run(prepare, folder / "library.log")
            library_info = physical_cost_library(raw, library, 8)
            script = folder / "mapping.ys"
            script.write_text(mapping_commands("incoming_registered", pre_lut, folder, "physical-cost", 6667, 300, library))
            log = folder / "mapping.log"
            run(script, log)
            if "Networks are equivalent." not in log.read_text():
                raise RuntimeError("ABC9 did not verify mapping")
            module = json.loads(mapped.read_text())["modules"]["incoming_registered"]
            for name, value in register_origins(pre_lut).items():
                if name in module["cells"]:
                    module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
            for name in list(module["cells"]):
                if module["cells"][name]["type"] == "$scopeinfo":
                    del module["cells"][name]
            paths = {"all": connected_paths(module, limit=8, group_limit=8)}
            for selector in ("ch0_q", "cols_q", "group_c", "win_busy", "row_base_addr", "word_addr", "addr", "tap_wrap_bytes", "tap_step_bytes"):
                for endpoint in ("o_group_fits", "o_fast", "o_q_fast", "o_word_equal", "o_live_equal", "o_word_hit"):
                    paths[selector + "_to_" + endpoint] = connected_paths(module, limit=2, group_limit=2,
                        root_filter=origin_contains(selector), sink_filter=origin_contains(endpoint))
            if not all(value["graph_complete"] for value in paths.values()):
                raise RuntimeError("Incomplete mapped dependency graph")
            row = dict(resources=resources(module["cells"]), paths=paths,
                source_sha256=digest(source), mapped_sha256=digest(mapped), pre_lut_sha256=digest(pre_lut),
                log_sha256=digest(log), primitive_models=primitives, library=library_info, abc9_equivalent=True)
            cases[label] = row
            (folder / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
            print(label, row["resources"]["logic_lut_cells"],
                {name: value["longest_register_path_cells"] for name, value in paths.items()}, flush=True)
    report = dict(passed=True, reference_commit=proof["reference_commit"],
        source_sha256=proof["source_sha256"], reference_sha256=proof["reference_sha256"],
        dma_sha256=digest(dma_path), proof_summary_sha256=digest(proof_dir / "summary.json"),
        actual_dma_field_selection=True, RW=5, TILE_COUNT_W=5, CACHE_POLICY=3,
        boundary="registered descriptor and complete group range inputs to fast predicate outputs",
        mapping=dict(mode="physical-cost", max_lut_inputs=8, delay_target_ps=6667, wire_delay_ps=300),
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
