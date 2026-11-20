#!/usr/bin/env python3
"""测量实际 DMA 字段选择至前端状态更新的物理成本映射。"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
import open_fpga_synth as flow
from remap_fpga_luts import physical_cost_library, mapping_commands
from netlist_metrics import connected_paths, register_origins, resources


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(script, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def origin_contains(value):
    return lambda name, cell, port: value in cell.get("attributes", {}).get("fpga_register_origin", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    parser.add_argument("--max-lut-inputs", type=int, choices=(6, 8), default=6)
    parser.add_argument("--wire-delays", type=int, nargs="+", default=[700, 300])
    args = parser.parse_args()
    out, proof_path = args.out.resolve(), args.proof.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = json.loads(proof_path.read_text())
    selected = runpy.run_path(str(ROOT / "test/frontend_delta_select/formal.py"))
    local = runpy.run_path(str(ROOT / "test/frontend_delta_select/local_model.py"))
    reference, current, _ = selected["sources"](proof["reference_commit"])
    if not proof["passed"] or sha(ROOT / selected["SOURCE"]) != proof["source_sha256"]:
        raise RuntimeError("综合源码与形式证明不一致")
    dma_path, helper_path = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv", ROOT / "rtl/common/add_equal.sv"
    for path in (dma_path, helper_path):
        fixed = subprocess.check_output(["git", "show", proof["reference_commit"] + ":" + str(path.relative_to(ROOT))], cwd=ROOT)
        if fixed != path.read_bytes():
            raise RuntimeError("公共数据选择或比较模块与参考版本不一致")
    dma, model = dma_path.read_text(), proof_path.parent / "official_lut6.v"
    state_unchanged = local["state_body"](reference) == local["state_body"](current)
    if not state_unchanged:
        raise RuntimeError("实际状态更新过程有额外变化")
    commands = []
    for label, text in (("reference", reference), ("current", current)):
        path = out / (label + "_comb.sv")
        path.write_text(local["unit"](text, dma, registered=False).replace("module delta_path(", "module " + label + "("))
        commands += ["read_slang --top " + label + " " + " ".join(shlex.quote(str(p)) for p in (path, helper_path, model)),
                     "prep -top " + label + " -flatten", "opt -full", "design -stash " + label]
    commands += ["design -copy-from reference reference", "design -copy-from current current",
                 "miter -equiv -flatten reference current comparison", "hierarchy -top comparison", "opt -full",
                 "sat -verify -prove trigger 0 -show-inputs -show-outputs"]
    script, log = out / "state_comparison.ys", out / "state_comparison.log"
    script.write_text("\n".join(commands) + "\n")
    run(script, log)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("实际状态组合比较未完成")
    state_formal = dict(passed=True, input_bits=sum(width for _, width in local["INPUTS"]), output_bits=8,
                        inputs_constrained=False, state_process_unchanged=state_unchanged,
                        script_sha256=sha(script), log_sha256=sha(log))
    print("actual_state_comparison: passed", flush=True)
    cases = {}
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label, text in (("reference", reference), ("current", current)):
            folder = out / label
            folder.mkdir(exist_ok=True)
            source = folder / "registered.sv"
            source.write_text(local["unit"](text, dma))
            import pyosys
            options, primitives = flow.primitive_models(folder, [str(source), str(helper_path)],
                                                        Path(pyosys.__file__).parent / "share/xilinx")
            pre_lut, script = folder / "pre_lut.il", folder / "pre_lut.ys"
            script.write_text("read_slang --keep-hierarchy --top delta_path " + options + " " +
                              " ".join(shlex.quote(str(path)) for path in (source, helper_path)) +
                              "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nhierarchy -check -top delta_path\n"
                              "synth_xilinx -top delta_path -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n"
                              "write_rtlil " + shlex.quote(str(pre_lut)) + "\n")
            run(script, folder / "pre_lut.log")
            raw = folder / "native.lut"
            script = folder / "library.ys"
            script.write_text("read_verilog -lib -specify +/xilinx/cells_sim.v\nadd -mod library_top\n"
                              "abc9_ops -prep_lut 0\nabc9_ops -write_lut " + shlex.quote(str(raw)) + "\n")
            run(script, folder / "library.log")
            for wire_delay in args.wire_delays:
                maximum = args.max_lut_inputs
                mapped_dir = folder / ("max" + str(maximum) + "_wire" + str(wire_delay))
                mapped_dir.mkdir(exist_ok=True)
                library = mapped_dir / "physical.lut"
                library_info = physical_cost_library(raw, library, maximum)
                script, log = mapped_dir / "mapping.ys", mapped_dir / "mapping.log"
                script.write_text(mapping_commands("delta_path", pre_lut, mapped_dir, "physical-cost", 6667, wire_delay, library))
                run(script, log)
                if "Networks are equivalent." not in log.read_text():
                    raise RuntimeError("ABC9 映射等价检查未完成")
                mapped = mapped_dir / "mapped.json"
                module = json.loads(mapped.read_text())["modules"]["delta_path"]
                for name, value in register_origins(pre_lut).items():
                    if name in module["cells"]:
                        module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
                for name in list(module["cells"]):
                    if module["cells"][name]["type"] == "$scopeinfo":
                        del module["cells"][name]
                paths = {"all": connected_paths(module, limit=8, group_limit=12)}
                for origin in ("win_busy", "win_frontend_q0", "q0", "tap_wrap_bytes", "tap_step_bytes"):
                    for endpoint in ("o_state", "o_word_equal", "o_live_equal", "o_word_hit"):
                        paths[origin + "_to_" + endpoint] = connected_paths(module, limit=2, group_limit=2,
                            root_filter=origin_contains(origin), sink_filter=origin_contains(endpoint))
                if not all(value["graph_complete"] for value in paths.values()):
                    raise RuntimeError("映射图含未识别组合单元")
                row = dict(resources=resources(module["cells"]), paths=paths,
                           source_sha256=sha(source), mapped_sha256=sha(mapped), pre_lut_sha256=sha(pre_lut),
                           mapping_log_sha256=sha(log), primitive_models=primitives, library=library_info,
                           abc9_equivalent=True, max_lut_inputs=maximum, wire_delay_ps=wire_delay,
                           directory=str(mapped_dir))
                cases[label + "_max" + str(maximum) + "_wire" + str(wire_delay)] = row
                (mapped_dir / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
                print(label, maximum, wire_delay, row["resources"]["logic_lut_cells"],
                      {key: paths[key]["longest_register_path_cells"] for key in
                       ("all", "win_busy_to_o_state", "win_busy_to_o_live_equal", "win_busy_to_o_word_hit")}, flush=True)
    if sha(ROOT / selected["SOURCE"]) != proof["source_sha256"]:
        raise RuntimeError("测量期间前端源码发生变化")
    report = dict(passed=True, reference_commit=proof["reference_commit"], source_sha256=proof["source_sha256"],
                  reference_sha256=proof["reference_sha256"], dma_sha256=sha(dma_path), add_equal_sha256=sha(helper_path),
                  proof_sha256=sha(proof_path), state_formal=state_formal, cases=cases,
                  boundary="实际 DMA 描述符字段选择、完整组内比较和数据字匹配，至实际前端全部状态位的组合次值；其他状态条件在列明的寄存输入处截断",
                  input_registers=list(local["INPUTS"]), actual_state_update=True, actual_dma_field_selection=True,
                  parameters=dict(SIZE=16, LANES=4, RW=5, TILE_COUNT_W=5, CACHE_POLICY=3),
                  mapping=dict(mode="physical-cost", max_lut_inputs=args.max_lut_inputs, delay_target_ps=6667,
                               wire_delay_ps=args.wire_delays),
                  source_model_sha256=sha(ROOT / "test/frontend_delta_select/local_model.py"),
                  metrics_tool_sha256=sha(ROOT / "scripts/fpga/netlist_metrics.py"))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
