#!/usr/bin/env python3
"""检查完整设计及窗口选择区域的实际寄存器连接路径。"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def identity(name, cell):
    attributes = cell.get("attributes", {})
    return " ".join((name, attributes.get("hdlname", ""),
        attributes.get("fpga_register_origin", "")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--top", default="soc_top")
    parser.add_argument("--scope", choices=("soc", "window-decode"), default="soc")
    parser.add_argument("--reference-report", type=Path)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    design = json.loads(args.mapped.read_text())
    module = design["modules"][args.top]
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    module["cells"] = {name: cell for name, cell in module["cells"].items()
        if cell["type"] != "$scopeinfo"}
    reports = {}
    targets = {
        "descriptor_q0_to_demand_word_matches": "demand_word_matches_q",
        "descriptor_q0_to_work_word_matches": "work_word_matches_q",
    }
    scopes = ("descriptor_q0", "descriptor_queue", "frontend", *targets) if args.scope == "soc" else (
        "tile_q0", "p0", "tile_p0", "window_next_ix", "window_next_iy", "row_base_ix")
    for scope in scopes:
        def source(name, cell, port):
            if args.scope == "window-decode":
                origin = cell.get("attributes", {}).get("fpga_register_origin", "")
                return origin == scope or origin.startswith(scope + " [")
            value = identity(name, cell)
            if scope.startswith("descriptor_q0"):
                return "u_window_queue" in value and "g_descriptor[1]" in value and (
                    scope not in targets or cell["type"].startswith("RAMB"))
            if scope == "descriptor_queue":
                return "u_window_queue" in value
            return "g_im2col.u_frontend" in value

        def destination(name, cell, port):
            if args.scope == "window-decode":
                return True
            if scope in targets:
                origin = cell.get("attributes", {}).get("fpga_register_origin", "")
                return port == "D" and origin.endswith("." + targets[scope])
            return "g_im2col.u_frontend" in identity(name, cell)

        paths = connected_paths(module, limit=16, group_limit=16,
            root_filter=source, sink_filter=destination)
        if not paths["graph_complete"]:
            raise RuntimeError("图像前端的组合连接分析不完整: " + scope)
        if not paths["register_to_register_paths"] and scope not in targets:
            raise RuntimeError("找不到指定范围内的寄存器路径: " + scope)
        if scope in targets:
            paths["selected_endpoint_register_count"] = sum(
                destination(name, cell, "D") for name, cell in module["cells"].items())
        reports[scope] = paths
        print(scope, paths["longest_register_path_cells"], flush=True)
    summary = {}
    for scope, paths in reports.items():
        selected = paths["register_to_register_paths"]
        first = selected[0] if selected else None
        summary[scope] = dict(path_exists=bool(selected),
            longest_combinational_cells=first["combinational_cells"] if first else None,
            startpoint=first["startpoint"] if first else None,
            endpoint=first["endpoint"] if first else None,
            cell_types=dict(collections.Counter(step["type"] for step in first["path"])) if first else {})
        if scope in targets:
            summary[scope]["target_register"] = targets[scope]
            summary[scope]["target_port"] = "D"
            summary[scope]["selected_endpoint_register_count"] = paths["selected_endpoint_register_count"]
    result = dict(top=args.top, mapped_sha256=digest(args.mapped),
        pre_lut_sha256=digest(args.pre_lut), paths=reports,
        analysis_script_sha256=digest(Path(__file__)), summary=summary,
        scope=("完整设计网表中描述符队列及图像前端的实际寄存器连接" if args.scope == "soc" else
            "窗口选择区域中输入寄存器至输出寄存器的实际连接"),
        placed_routed_timing_measured=False)
    if args.reference_report:
        reference = json.loads(args.reference_report.read_text())
        if reference["analysis_script_sha256"] != result["analysis_script_sha256"]:
            raise RuntimeError("两个网表必须使用同一版本的路径分析脚本")
        result["comparison"] = {}
        for scope, current in summary.items():
            previous = reference["summary"][scope]
            reduction = previous["longest_combinational_cells"] - current["longest_combinational_cells"] \
                if previous["path_exists"] and current["path_exists"] else None
            result["comparison"][scope] = dict(reference=previous, current=current,
                combinational_cell_reduction=reduction)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps({key: value for key, value in result.items() if key != "paths"},
            indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
