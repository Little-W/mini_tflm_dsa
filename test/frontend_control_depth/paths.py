#!/usr/bin/env python3
"""测量完整缓存、窗口队列与前端之间的实际控制路径。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins

SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
BOUNDARIES = ("axi_linear_block_dma", "conv_next_use_predictor", "conv_axi_read_guard",
              "axi_write_page_guard", "conv_axi_read_mux")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origins(folder, expected):
    source = folder / "pre_lut.il"
    if source.exists():
        if digest(source) != expected:
            raise RuntimeError("Register source file differs")
        return register_origins(source)
    with tempfile.TemporaryDirectory() as temporary:
        restored = Path(temporary) / "pre_lut.il"
        with gzip.open(source.with_suffix(".il.gz"), "rb") as stream, restored.open("wb") as target:
            shutil.copyfileobj(stream, target)
        if digest(restored) != expected:
            raise RuntimeError("Compressed register source file differs")
        return register_origins(restored)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"] or not proof["unchanged_outside_readiness_and_metadata"]:
        raise RuntimeError("Frontend control proof is incomplete")
    frontend = r"g_im2col\.u_frontend\."
    cache = frontend + r"u_cache\."
    queries = {
        "iy_to_retirement": (frontend + r"iy(?: |$)", cache + r".*work_request \[(?:4[2-9]|[56][0-9]|7[0-3])\]"),
        "iy_to_retirement_bit12": (frontend + r"iy(?: |$)", cache + r".*work_request \[54\]"),
        "cache_to_group_range": (cache, frontend + r"group_range_q(?: |$)"),
        "cache_to_request_index": (cache, frontend + r"request_index_q(?: |$)"),
        "fg_state_bit1_to_request_index": ("fg_state_bit1", frontend + r"request_index_q(?: |$)"),
        "fg_state_bit1_to_group_range": ("fg_state_bit1", frontend + r"group_range_q(?: |$)"),
        "fg_state_bit1_to_tap0": ("fg_state_bit1", frontend + r"tap0(?: |$)"),
        "cache_to_tap0": (cache, frontend + r"tap0(?: |$)"),
        "queue_count_to_state": (r"u_window_queue\.count(?: |$)", frontend + r"state(?: |$)"),
        "tap_wrap_to_state": (frontend + r"tap_wrap_q(?: |$)", frontend + r"state(?: |$)"),
    }
    cases = {}
    for label, folder, expected in (("reference", args.reference, proof["reference_sha256"]),
                                    ("current", args.current, proof["source_sha256"])):
        summary = json.loads((folder / "summary.json").read_text())
        if not summary["cache_included"] or summary["source_sha256"][SOURCE] != expected:
            raise RuntimeError("Joint synthesis scope or source differs")
        if digest(folder / "mapped.json") != summary["mapped_sha256"]:
            raise RuntimeError("Mapped source file differs")
        module = json.loads((folder / "mapped.json").read_text())["modules"]["axi_dual_block_dma"]
        for name, value in origins(folder, summary["pre_lut_sha256"]).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
        module["cells"] = {name: cell for name, cell in module["cells"].items()
            if cell["type"] != "$scopeinfo" and not cell["type"].startswith(BOUNDARIES)}
        fg_cells = [name for name, cell in module["cells"].items()
            if re.search(r"u_cache\.g_window\.u_window\.fg_state \[1\]$",
                         cell.get("attributes", {}).get("fpga_register_origin", ""))]
        if len(fg_cells) != 1:
            raise RuntimeError("Cache foreground state register is not uniquely identified")
        fg_bit1 = module["cells"][fg_cells[0]]["connections"]["Q"][0]
        paths = {}
        for name, (start, end) in queries.items():
            starts, ends = re.compile(start), re.compile(end)
            selected = (lambda n, c, p: fg_bit1 in c.get("connections", {}).get("Q", [])) if start == "fg_state_bit1" else \
                (lambda n, c, p: bool(starts.search(c.get("attributes", {}).get("fpga_register_origin", ""))))
            paths[name] = connected_paths(module, limit=6, group_limit=6,
                root_filter=selected,
                sink_filter=lambda n, c, p: p == "D" and bool(ends.search(c.get("attributes", {}).get("fpga_register_origin", ""))))
            if not paths[name]["graph_complete"]:
                raise RuntimeError("Incomplete joint path graph")
        cases[label] = dict(configuration=summary["configuration"], source_sha256=summary["source_sha256"],
            fg_state_bit1_cell=fg_cells[0], fg_state_bit1_net=fg_bit1,
            resources=summary["resources"], longest_register_path_cells=summary["paths"]["longest_register_path_cells"],
            paths=paths, mapped_sha256=summary["mapped_sha256"], pre_lut_sha256=summary["pre_lut_sha256"],
            summary_sha256=digest(folder / "summary.json"), maximum_resident_kib=summary["maximum_resident_kib"])
        print(label, summary["resources"]["logic_lut_cells"],
              {name: value["longest_register_path_cells"] for name, value in paths.items()}, flush=True)
    differences = {name for name, value in cases["current"]["source_sha256"].items()
                   if cases["reference"]["source_sha256"].get(name) != value}
    if differences != {SOURCE}:
        raise RuntimeError("Additional synthesized source changes require verification")
    result = dict(passed=True, reference_commit=proof["reference_commit"], cases=cases,
        unchanged_other_sources=True, metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"),
        proof_sha256=digest(args.proof))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
