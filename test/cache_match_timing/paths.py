#!/usr/bin/env python3
"""检查完整窗口缓存中连接到字地址匹配寄存器的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins, resources


def identity(name, cell):
    attributes = cell.get("attributes", {})
    return " ".join((name, attributes.get("hdlname", ""),
        attributes.get("fpga_register_origin", "")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reports = {}
    for folder in args.case_dir:
        mapped = folder / "mapped.json"
        module = json.loads(mapped.read_text())["modules"]["conv_windowed_cache"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        module["cells"] = {name: cell for name, cell in module["cells"].items()
            if cell["type"] != "$scopeinfo"}
        report = dict(resources=resources(module["cells"]),
            mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest())
        report["register_paths"] = connected_paths(module, limit=4, group_limit=4)

        def destination(name, cell, port):
            return "word_matches_q" in identity(name, cell)

        report["match_register_paths"] = connected_paths(module, limit=4, group_limit=4,
            sink_filter=destination)
        port_reports = {}
        for port in ("req_valid", "req_addr"):
            # 在连接分析中把输入端口作为零级起点，资源统计仍使用完整原始网表。
            # 此节点仅存在于 Python 分析对象，不写入 RTL 或综合网表。
            marker = "$analysis_input$" + port
            module["cells"][marker] = dict(type="FDRE", port_directions={"Q": "output"},
                connections={"Q": module["ports"][port]["bits"]}, attributes={})
            paths = connected_paths(module, limit=4, group_limit=4,
                root_filter=lambda name, cell, pin: name == marker, sink_filter=destination)
            del module["cells"][marker]
            if not paths["graph_complete"]:
                raise RuntimeError("缓存端口的连接分析不完整: " + port)
            selected = paths["register_to_register_paths"]
            for path in selected:
                path["startpoint"].update(cell=None, type="input_port", port=port,
                    detail="模块输入端口", register_origin=None)
            port_reports[port] = dict(longest_combinational_cells=paths["longest_register_path_cells"],
                paths=selected, graph_complete=True)
        report["input_to_match_register_paths"] = port_reports
        for name in ("register_paths", "match_register_paths"):
            if not report[name]["graph_complete"]:
                raise RuntimeError("缓存寄存器连接分析不完整: " + folder.name)
        reports[folder.name] = report
        print(folder.name, "LUT", report["resources"]["logic_lut_cells"],
            "match_cells", report["match_register_paths"]["longest_register_path_cells"],
            "req_valid_cells", port_reports["req_valid"]["longest_combinational_cells"], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dict(cases=reports, placed_routed_timing_measured=False),
        indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
