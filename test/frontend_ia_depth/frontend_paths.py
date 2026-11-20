#!/usr/bin/env python3
"""核对前端、窗口队列、缓存和预测器的指定实际组合路径。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def content(path):
    return path.read_bytes() if path.exists() else gzip.decompress(path.with_suffix(path.suffix + ".gz").read_bytes())


class OriginFile:
    def __init__(self, path):
        self.path = path

    def open(self):
        return self.path.open() if self.path.exists() else gzip.open(
            self.path.with_suffix(self.path.suffix + ".gz"), "rt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--joint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    frontend = r"g_im2col\.u_frontend\."
    cfg = frontend + r"g_next_use\.u_predictor\.(?:cfg_busy|cfg_phase)(?: |$)"
    queries = {
        "predictor_cfg_to_tap_wrap": (cfg, frontend + r"tap_wrap_q(?: |$)"),
        "predictor_cfg_to_tap0": (cfg, frontend + r"tap0(?: |$)"),
        "predictor_cfg_to_incoming_word": (cfg, frontend + r"(?:u_incoming_word\.i_a|row_base_addr)(?: |$)"),
        "active_remaining_to_group_range": (frontend + r"active_remaining(?: |$)", frontend + r"group_range_q(?: |$)"),
        "active_remaining4_to_group_range": (frontend + r"active_remaining \[4\]$", frontend + r"group_range_q(?: |$)"),
        "active_remaining_to_state": (frontend + r"active_remaining(?: |$)", frontend + r"state(?: |$)"),
        "input_s16_to_state": (frontend + r"c \[2\]$", frontend + r"state(?: |$)"),
        "group_minus_two_to_state": (frontend + r"group_minus_two_q(?: |$)", frontend + r"state(?: |$)"),
    }
    report = {}
    for label in ("reference", "current"):
        folder = args.joint / label
        summary = json.loads((folder / "summary.json").read_text())
        if not summary["cache_included"] or not summary["predictor_included"]:
            raise RuntimeError("Joint synthesis scope is incomplete")
        mapped = content(folder / "mapped.json")
        if hashlib.sha256(mapped).hexdigest() != summary["mapped_sha256"]:
            raise RuntimeError("Mapped source differs from joint summary")
        if hashlib.sha256(content(folder / "pre_lut.il")).hexdigest() != summary["pre_lut_sha256"]:
            raise RuntimeError("Register origin source differs from joint summary")
        module = json.loads(mapped)["modules"]["axi_dual_block_dma"]
        for name, value in register_origins(OriginFile(folder / "pre_lut.il")).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
        removed = {item["cell"] for item in summary["interface_boundaries"]}
        module["cells"] = {name: cell for name, cell in module["cells"].items()
                           if name not in removed and cell["type"] != "$scopeinfo"}
        paths = {}
        for name, (start, end) in queries.items():
            a, b = re.compile(start), re.compile(end)
            paths[name] = connected_paths(module, limit=4, group_limit=4,
                root_filter=lambda n,c,p: bool(a.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n,c,p: p == "D" and bool(b.search(
                    c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[name]["graph_complete"]:
                raise RuntimeError("Joint frontend graph is incomplete")
        report[label] = dict(resources=summary["resources"], source_sha256=summary["source_sha256"],
                             paths=paths, complete_max=summary["paths"]["longest_register_path_cells"],
                             mapped_sha256=summary["mapped_sha256"], pre_lut_sha256=summary["pre_lut_sha256"])
        print(label, {name: item["longest_register_path_cells"] for name,item in paths.items()}, flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
