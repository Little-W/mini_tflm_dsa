#!/usr/bin/env python3
"""检查完整设计及窗口选择区域的实际寄存器连接路径。"""
import argparse
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
    scopes = ("descriptor_q0", "descriptor_queue", "frontend") if args.scope == "soc" else (
        "tile_q0", "p0", "tile_p0", "window_next_ix", "window_next_iy", "row_base_ix")
    for scope in scopes:
        def source(name, cell, port):
            if args.scope == "window-decode":
                origin = cell.get("attributes", {}).get("fpga_register_origin", "")
                return origin == scope or origin.startswith(scope + " [")
            value = identity(name, cell)
            if scope == "descriptor_q0":
                return "u_window_queue" in value and "g_descriptor[1]" in value
            if scope == "descriptor_queue":
                return "u_window_queue" in value
            return "g_im2col.u_frontend" in value

        def destination(name, cell, port):
            if args.scope == "window-decode":
                return True
            return "g_im2col.u_frontend" in identity(name, cell)

        paths = connected_paths(module, limit=16, group_limit=16,
            root_filter=source, sink_filter=destination)
        if not paths["graph_complete"]:
            raise RuntimeError("图像前端的组合连接分析不完整: " + scope)
        if not paths["register_to_register_paths"]:
            raise RuntimeError("找不到指定范围内的寄存器路径: " + scope)
        reports[scope] = paths
        print(scope, paths["longest_register_path_cells"], flush=True)
    result = dict(top=args.top, mapped_sha256=digest(args.mapped),
        pre_lut_sha256=digest(args.pre_lut), paths=reports,
        scope=("完整设计网表中描述符队列及图像前端的实际寄存器连接" if args.scope == "soc" else
            "窗口选择区域中输入寄存器至输出寄存器的实际连接"),
        placed_routed_timing_measured=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
