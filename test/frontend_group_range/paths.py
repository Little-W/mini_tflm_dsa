#!/usr/bin/env python3
"""从实际映射图统计组内范围来源到前端描述符状态的寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


BOUNDARIES = ("axi_linear_block_dma", "conv_read_cache", "conv_next_use_predictor",
              "conv_axi_read_guard", "axi_write_page_guard", "conv_axi_read_mux")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"]:
        raise RuntimeError("Range state proof must pass before measurement")
    result = {}
    for label, folder, expected in (("reference", args.reference, proof["reference_sha256"]),
                                    ("current", args.current, proof["source_sha256"])):
        summary = json.loads((folder / "summary.json").read_text())
        if summary["source_sha256"]["rtl/npu/conv/conv_im2col_frontend.sv"] != expected:
            raise RuntimeError("Formal and synthesized sources differ")
        module = json.loads((folder / "mapped.json").read_text())["modules"]["axi_dual_block_dma"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        module["cells"] = {name: cell for name, cell in module["cells"].items()
                           if cell["type"] != "$scopeinfo" and not cell["type"].startswith(BOUNDARIES)}
        sinks = re.compile(r"g_im2col\.u_frontend\.(?:state|tap0|tap_wrap_q|ix|iy|request_index_q)(?: |$)")
        queries = {
            "group_bit_10_to_descriptor": r"g_im2col\.u_frontend\.c \[206\]$",
            "group_configuration_to_descriptor": r"g_im2col\.u_frontend\.c \[(?:19[6-9]|20[0-9]|21[01])\]$",
            "group_range_register_to_descriptor": r"g_im2col\.u_frontend\.group_range_q(?: |$)",
            "second_last_channel_to_descriptor": r"g_im2col\.u_frontend\.group_minus_two_q(?: |$)",
        }
        paths = {}
        for name, expression in queries.items():
            roots = re.compile(expression)
            paths[name] = connected_paths(module, limit=20, group_limit=20,
                root_filter=lambda n, c, p: bool(roots.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n, c, p: bool(sinks.search(c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[name]["graph_complete"]:
                raise RuntimeError("Incomplete mapped dependency graph")
        result[label] = dict(configuration=summary["configuration"], resources=summary["resources"],
            longest_register_path_cells=summary["paths"]["longest_register_path_cells"],
            source_sha256=summary["source_sha256"], mapped_sha256=digest(folder / "mapped.json"),
            pre_lut_sha256=digest(folder / "pre_lut.il"), targeted_paths=paths)
    for path, current_hash in result["current"]["source_sha256"].items():
        if path != "rtl/npu/conv/conv_im2col_frontend.sv" and result["reference"]["source_sha256"].get(path) != current_hash:
            raise RuntimeError("Additional synthesized source differences require verification")
    report = dict(passed=True, reference_commit=proof["reference_commit"],
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"),
        dsp_dependency_test_sha256=digest(ROOT / "scripts/fpga/test_dsp_alu_bit_dependencies.py"), cases=result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for label, row in result.items():
        print(label, {key: value["longest_register_path_cells"] for key, value in row["targeted_paths"].items()})


if __name__ == "__main__":
    main()
