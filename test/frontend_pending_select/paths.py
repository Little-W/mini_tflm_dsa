#!/usr/bin/env python3
"""统计描述符来源到前端解码寄存器的实际映射路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
sys.path.insert(0, str(ROOT / "test"))
from netlist_metrics import connected_paths, register_origins
from frontend_ia_depth.frontend_paths import content, OriginFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=("reference", "current"),
                        default=["reference", "current"])
    args = parser.parse_args()
    frontend = r"g_im2col\.u_frontend\."
    queries = {}
    for label, start in {"pending": r"^conv_pending$", "count": r"^u_window_queue\.count(?: |$)"}.items():
        for register in ("tap0", "ky_q", "ky0_q"):
            queries[label + "_to_" + register] = (start, frontend + register + r"(?: |$)")
        queries[label + "_to_frontend"] = (start, frontend)
    for register in ("tap0", "ky_q", "ky0_q"):
        queries["all_to_" + register] = (r".", frontend + register + r"(?: |$)")
    report = {}
    for label in args.cases:
        folder = args.joint / label
        summary = json.loads((folder / "summary.json").read_text())
        if not summary["cache_included"] or not summary["predictor_included"]:
            raise RuntimeError("Joint synthesis scope is incomplete")
        mapped = content(folder / "mapped.json")
        pre_lut = content(folder / "pre_lut.il")
        if hashlib.sha256(mapped).hexdigest() != summary["mapped_sha256"] or \
                hashlib.sha256(pre_lut).hexdigest() != summary["pre_lut_sha256"]:
            raise RuntimeError("Netlist content differs from the synthesis summary")
        module = json.loads(mapped)["modules"]["axi_dual_block_dma"]
        for name, value in register_origins(OriginFile(folder / "pre_lut.il")).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
        excluded = {item["cell"] for item in summary["interface_boundaries"]}
        module["cells"] = {name: cell for name, cell in module["cells"].items()
                           if name not in excluded and cell["type"] != "$scopeinfo"}
        paths = {}
        for name, (start, end) in queries.items():
            a, b = re.compile(start), re.compile(end)
            paths[name] = connected_paths(module, limit=3, group_limit=3,
                root_filter=lambda n,c,p: bool(a.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n,c,p: p == "D" and bool(b.search(
                    c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[name]["graph_complete"]:
                raise RuntimeError("Joint graph is incomplete")
        report[label] = dict(resources=summary["resources"], source_sha256=summary["source_sha256"],
                             paths=paths, complete_max=summary["paths"]["longest_register_path_cells"],
                             complete_longest=summary["paths"]["distinct_register_path_groups"][:8],
                             mapped_sha256=summary["mapped_sha256"], pre_lut_sha256=summary["pre_lut_sha256"])
        print(label, {name: item["longest_register_path_cells"] for name,item in paths.items()}, flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
