#!/usr/bin/env python3
"""连接实际帧完成表达式和完整矩阵控制器，测量全部寄存器组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins

RTL = (
    "rtl/npu/control/npu_controller.sv",
    "rtl/npu/control/npu_ia_issue_select.sv",
    "rtl/npu/top/npu_frame_complete_select.sv",
    "rtl/npu/top/npu_matrix_engine.sv",
)
PARAMETERS = dict(REG_WIDTH=32, SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16, WEIGHT_WIDTH=16)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registered_connection(source: str, top: str, completion: str) -> str:
    """由控制器实际端口生成输入与输出寄存器，帧完成信号按生产连接接入。"""
    header = source[source.index("module npu_controller"):source.index("\n);", source.index("module npu_controller"))]
    ports = re.findall(
        r"^\s*(input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*(\[[^]]+\])?\s*(\w+)",
        header, re.M,
    )
    if len(ports) < 40:
        raise RuntimeError("控制器端口解析不完整")
    declarations = ["input logic clk, // 测量时钟", "input logic rst_n, // 控制器低有效复位",
                    "input logic [10:0] i_frame_controls, // 帧执行与完成输入"]
    internal = ["logic [10:0] frame_controls_q;", "logic frame_complete;"]
    updates = ["frame_controls_q <= i_frame_controls;"]
    connections = []
    for direction, width, name in ports:
        if name in ("clk", "rst_n"):
            connections.append(f".{name}({name})")
        elif name == "oa_calc_over":
            connections.append(".oa_calc_over(frame_complete)")
        elif name == "partial_sum_calc_over":
            connections.append(".partial_sum_calc_over(frame_controls_q[6])")
        elif direction == "input":
            declarations.append(f"input logic {width} i_{name}, // 控制器输入 {name}")
            internal.append(f"logic {width} {name}_q;")
            updates.append(f"{name}_q <= i_{name};")
            connections.append(f".{name}({name}_q)")
        else:
            declarations.append(f"output logic {width} o_{name}, // 保存控制器输出 {name}")
            internal.append(f"logic {width} {name};")
            updates.append(f"o_{name} <= {name};")
            connections.append(f".{name}({name})")
    declarations[-1] = declarations[-1].replace(", //", " //", 1)
    parameters = ", ".join(f"parameter int {name}={value}" for name, value in PARAMETERS.items())
    return (f"// 保存矩阵完成与控制器各输入、输出，统计连接后的完整组合路径。\n"
            f"module {top} #({parameters})(\n    " + "\n    ".join(declarations) + "\n);\n    " +
            "\n    ".join(internal) + "\n    always_ff @(posedge clk) begin\n        " +
            "\n        ".join(updates) + "\n    end\n    " +
            f"{completion} u_completion(.i_controls(frame_controls_q), .o_complete(frame_complete));\n    " +
            "npu_controller #(" + ", ".join(f".{name}({name})" for name in PARAMETERS) +
            ") u_controller(\n        " + ",\n        ".join(connections) + "\n    );\nendmodule\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="92f722e6")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip()
    completion_model = runpy.run_path(str(ROOT / "test/matrix_frame_complete/run.py"))["model"]
    production_hashes = {name: digest(ROOT / name) for name in RTL}
    cases = {}
    for label in ("reference", "current"):
        directory = out / label
        directory.mkdir(parents=True, exist_ok=True)
        sources = {}
        for relative in RTL:
            path = directory / Path(relative).name
            path.write_bytes(subprocess.check_output(["git", "show", reference + ":" + relative], cwd=ROOT)
                             if label == "reference" else (ROOT / relative).read_bytes())
            sources[Path(relative).name] = path
        top, completion = "frame_issue_registered_" + label, "completion_" + label
        wrapper = directory / "measure.sv"
        wrapper.write_text(completion_model(sources["npu_matrix_engine.sv"].read_text(), completion) +
                           registered_connection(sources["npu_controller.sv"].read_text(), top, completion))
        cases[label] = dict(top=top, options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"],
            sources=[str(wrapper), *[str(p) for name, p in sources.items() if name != "npu_matrix_engine.sv"]],
            configuration=PARAMETERS)
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config", case_file,
                    "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"], cwd=ROOT, check=True)
    report = dict(reference_commit=reference, source_sha256=production_hashes, parameters=PARAMETERS, cases={})
    for label, case in cases.items():
        cost = out / "mapped" / label
        subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py", "--source", out / "pre" / label,
                        "--out", cost, "--mode", "physical-cost", "--delay-target-ps", "6667",
                        "--wire-delay-ps", "300", "--max-lut-inputs", "8", "--discard-abc9-temporaries"],
                       cwd=ROOT, check=True)
        module = json.loads((cost / "mapped.json").read_text())["modules"][case["top"]]
        for name, origin in register_origins(out / "pre" / label / "pre_lut.il", case["top"]).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        def selected(name, cell, port):
            return cell.get("attributes", {}).get("fpga_register_origin", "") == "frame_controls_q [9]"
        paths = connected_paths(module, limit=8, group_limit=8, root_filter=selected)
        send_paths = connected_paths(module, limit=2, group_limit=2, root_filter=selected,
            sink_filter=lambda name, cell, port:
                cell.get("attributes", {}).get("fpga_register_origin", "") == "o_send_ia_trigger")
        all_paths = connected_paths(module, limit=16, group_limit=16)
        metrics = json.loads((cost / "metrics.json").read_text())
        synthesis = json.loads((cost / "summary.json").read_text())
        if not all_paths["graph_complete"] or not synthesis["functional_verification"]["passed"]:
            raise RuntimeError("综合映射验证或完整组合图检查未完成")
        report["cases"][label] = dict(resources=metrics["resources"],
            complete_paths=all_paths, command_active_paths=paths, command_active_to_send=send_paths,
            mapped_sha256=digest(cost / "mapped.json"))
        print(label, metrics["resources"]["logic_lut_cells"], all_paths["longest_register_path_cells"],
              "command_active", paths["longest_register_path_cells"], flush=True)
    if production_hashes != {name: digest(ROOT / name) for name in RTL}:
        raise RuntimeError("测量期间生产文件发生变化")
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
