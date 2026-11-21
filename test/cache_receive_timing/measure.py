#!/usr/bin/env python3
"""在相同 xc7 设置下测量完整窗口缓存与接口组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from support import ROOT, SOURCE, REFERENCE, PARAMETERS, check_sources, prepare_inputs

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def boundary_paths(folder):
    metrics = json.loads((folder / "metrics.json").read_text())
    module = json.loads((folder / "mapped.json").read_text())["modules"]["conv_windowed_cache"]
    for name, origin in register_origins(folder / "pre_lut.il").items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin

    def origin(cell):
        return cell.get("attributes", {}).get("fpga_register_origin", "")

    def selected_path(paths):
        selected = paths["register_to_register_paths"]
        return {"cells": paths["longest_register_path_cells"],
                "path": selected[0] if selected else None}

    report = {"resources": metrics["resources"],
              "maximum_register_depth": metrics["paths"]["longest_register_path_cells"],
              "inputs": {}, "outputs": {}}
    # 仅在分析对象中增加端点标记，映射网表和综合结果保持原样。
    # 输入标记将模块端口作为路径起点；输出标记不计入组合逻辑级数。
    for input_name in ("req_addr", "req_valid", "req_window_retire",
                       "prefetch_addr", "prefetch_ref_addr"):
        root = "$input$" + input_name
        module["cells"][root] = {"type": "FDRE",
            "connections": {"Q": module["ports"][input_name]["bits"]},
            "port_directions": {"Q": "output"},
            "attributes": {"fpga_register_origin": input_name}}
        entries = {}
        for target in ("work_request [0]", "work_request", "word_matches_q",
                       "offer_next_range_q", "offer_next_addr_q"):
            paths = connected_paths(module, limit=1, group_limit=1,
                root_filter=lambda name, cell, port: name == root,
                sink_filter=lambda name, cell, port: port == "D" and
                    (origin(cell) == target if target.endswith("]") else target in origin(cell)))
            entries[target] = selected_path(paths)
        del module["cells"][root]
        report["inputs"][input_name] = entries
    for output_name in ("cfg_ready", "req_ready", "rsp_valid", "rsp_data", "rsp_error",
                        "arvalid", "araddr", "rready"):
        sink = "$output$" + output_name
        module["cells"][sink] = {"type": "FDRE",
            "connections": {"D": module["ports"][output_name]["bits"]},
            "port_directions": {"D": "input"},
            "attributes": {"fpga_register_origin": output_name}}
        paths = connected_paths(module, limit=1, group_limit=1,
            sink_filter=lambda name, cell, port: name == sink)
        del module["cells"][sink]
        report["outputs"][output_name] = selected_path(paths)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, default=ROOT / "build/cache_receive_timing/measurement")
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--read-width", type=int, default=PARAMETERS["READ_WIDTH"])
    parser.add_argument("--line-bytes", type=int, default=PARAMETERS["LINE_BYTES"])
    parser.add_argument("--sets", type=int, default=PARAMETERS["SETS"])
    parser.add_argument("--depths", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--labels", choices=["reference", "current"], nargs="+", default=["reference", "current"])
    args = parser.parse_args()
    parameters = {**PARAMETERS, "SETS": args.sets,
                  "READ_WIDTH": args.read_width, "LINE_BYTES": args.line_bytes}
    out = args.out.resolve()
    source_root, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    cases = {}
    for label, path in paths.items():
        if label not in args.labels:
            continue
        for depth in args.depths:
            name = f"{label}_d{depth}"
            cases[name] = {
                "top": "conv_windowed_cache",
                "options": ["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"] +
                    [f"-G{name}={value}" for name, value in parameters.items()] +
                    [f"-GDEMAND_DEPTH={depth}"],
                "sources": [str(item.relative_to(source_root)) for item in [path] + helpers],
                "configuration": f"完整窗口缓存，{args.sets}组、2路、{args.line_bytes}字节缓存行、64位AXI、{args.read_width}位读取、{depth}项需求队列",
            }
    config = out / "cases.json"
    config.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(source_root), "--case-config", str(config),
               "--cases", *cases, "--out", str(out / "synthesis")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    check_sources(manifest)
    synthesis = json.loads((out / "synthesis/summary.json").read_text())
    report = {"inputs": manifest, "parameters": parameters, "tool": synthesis["tool"],
              "part": synthesis["part"], "family": synthesis["family"],
              "method": "synth_xilinx -top conv_windowed_cache -family xc7 -noiopad -noclkbuf -flatten",
              "scope": "完整缓存独立综合；输入、输出路径计数不包括模块外部逻辑",
              "cases": {}}
    details = {}
    for name in cases:
        details[name] = boundary_paths(out / "synthesis" / name)
        row = details[name]
        report["cases"][name] = {
            "resources": row["resources"], "maximum_register_depth": row["maximum_register_depth"],
            "inputs": {port: {target: entry["cells"] for target, entry in targets.items()}
                       for port, targets in row["inputs"].items()},
            "outputs": {port: entry["cells"] for port, entry in row["outputs"].items()},
        }
        print(name, json.dumps(report["cases"][name], ensure_ascii=False), flush=True)
    (out / "boundary_paths.json").write_text(json.dumps(details, indent=2) + "\n")
    (out / "measurement.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(out / "measurement.json")


if __name__ == "__main__":
    main()
