#!/usr/bin/env python3
"""从实际映射图统计前端解码寄存器到写入数据端口的组合级数。"""
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


def output_endpoints(module, names):
    """仅增加测量终点，保留生产输出端口之前的全部连接。"""
    next_bit = 1 + max(bit for cell in module["cells"].values()
                       for bits in cell["connections"].values() for bit in bits if isinstance(bit, int))
    for name in names:
        port = module["ports"][name]
        if port["direction"] != "output":
            raise RuntimeError("Data endpoint must be an output port")
        for index, bit in enumerate(port["bits"]):
            endpoint = f"output_endpoint.{name}[{index}]"
            module["cells"][endpoint] = dict(type="FDRE",
                attributes=dict(fpga_register_origin=endpoint),
                parameters={}, port_directions=dict(C="input", CE="input", R="input", D="input", Q="output"),
                connections=dict(C=["0"], CE=["1"], R=["0"], D=[bit], Q=[next_bit]))
            next_bit += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"]:
        raise RuntimeError("Byte selection proof must pass before measurement")
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
        output_endpoints(module, ("wr_data", "win_rsp_data"))
        queries = {
            "q_decode_to_write_data": r"g_im2col\.u_frontend\.q0(?: |$)",
            "tap_decode_to_write_data": r"g_im2col\.u_frontend\.tap0(?: |$)",
            "frontend_state_to_write_data": r"g_im2col\.u_frontend\.state(?: |$)",
            "frontend_to_write_data": r"g_im2col\.u_frontend\.",
        }
        paths = {}
        for name, expression in queries.items():
            roots = re.compile(expression)
            paths[name] = connected_paths(module, limit=20, group_limit=20,
                root_filter=lambda n, c, p: bool(roots.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n, c, p: n.startswith("output_endpoint.") and p == "D")
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
        scope="Register outputs to actual DMA write data ports; measurement endpoint registers add no combinational cells",
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"),
        dsp_dependency_test_sha256=digest(ROOT / "scripts/fpga/test_dsp_alu_bit_dependencies.py"), cases=result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for label, row in result.items():
        print(label, {key: value["longest_register_path_cells"] for key, value in row["targeted_paths"].items()})


if __name__ == "__main__":
    main()
