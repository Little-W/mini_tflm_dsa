#!/usr/bin/env python3
"""从实际映射图统计前端位置寄存器到行尾和通道范围状态的路径。"""
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
    parser.add_argument("--helper-proof", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"]:
        raise RuntimeError("Row-end proof must pass before measurement")
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
        queries = {
            "last_p_to_row_wrap": (r"g_im2col\.u_frontend\.last_p(?: |$)", r"g_im2col\.u_frontend\.row_wrap_q$"),
            "p0_to_row_wrap": (r"g_im2col\.u_frontend\.p0(?: |$)", r"g_im2col\.u_frontend\.row_wrap_q$"),
            "frontend_to_row_wrap": (r"g_im2col\.u_frontend\.", r"g_im2col\.u_frontend\.row_wrap_q$"),
            "q0_to_group_range": (r"g_im2col\.u_frontend\.q0(?: |$)", r"g_im2col\.u_frontend\.group_range_q(?: |$)"),
        }
        paths = {}
        for name, (expression, sink_expression) in queries.items():
            roots = re.compile(expression)
            sinks = re.compile(sink_expression)
            paths[name] = connected_paths(module, limit=20, group_limit=20,
                root_filter=lambda n, c, p: bool(roots.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n, c, p: bool(sinks.search(c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[name]["graph_complete"]:
                raise RuntimeError("Incomplete mapped dependency graph")
        result[label] = dict(configuration=summary["configuration"], resources=summary["resources"],
            longest_register_path_cells=summary["paths"]["longest_register_path_cells"],
            source_sha256=summary["source_sha256"], mapped_sha256=digest(folder / "mapped.json"),
            pre_lut_sha256=digest(folder / "pre_lut.il"), targeted_paths=paths)
    helper_proof = json.loads(args.helper_proof.read_text()) if args.helper_proof else None
    allowed = {"rtl/npu/conv/conv_im2col_frontend.sv"}
    if helper_proof:
        helper = "rtl/common/add_equal.sv"
        if not helper_proof["passed"] or helper_proof["source_sha256"] != result["current"]["source_sha256"][helper] or \
                helper_proof["reference_sha256"] != result["reference"]["source_sha256"][helper]:
            raise RuntimeError("Helper proof and synthesized sources differ")
        allowed.add(helper)
    for path, current_hash in result["current"]["source_sha256"].items():
        if path not in allowed and result["reference"]["source_sha256"].get(path) != current_hash:
            raise RuntimeError("Additional synthesized source differences require verification")
    report = dict(passed=True, reference_commit=proof["reference_commit"],
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"),
        dsp_dependency_test_sha256=digest(ROOT / "scripts/fpga/test_dsp_alu_bit_dependencies.py"), cases=result)
    if helper_proof:
        report["helper_proof"] = helper_proof
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for label, row in result.items():
        print(label, {key: value["longest_register_path_cells"] for key, value in row["targeted_paths"].items()})


if __name__ == "__main__":
    main()
