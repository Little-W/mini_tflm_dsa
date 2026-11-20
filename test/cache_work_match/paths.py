#!/usr/bin/env python3
"""测量缓存保存字比较到预取及选择状态的实际连接路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


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
        raise RuntimeError("Work-word match proof must pass")
    cases = {}
    for label, folder, expected in (("reference", args.reference, proof["reference_sha256"]),
                                    ("current", args.current, proof["source_sha256"])):
        summary = json.loads((folder / "summary.json").read_text())
        sources = {Path(path).name: sha for path, sha in summary["source_sha256"].items()}
        if sources["conv_read_cache.sv"] != expected:
            raise RuntimeError("Formal and mapped sources differ")
        module = json.loads((folder / "mapped.json").read_text())["modules"]["conv_windowed_cache"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        results = {}
        for key, source in (
            ("snapshot_word_to_control", r"^lookup_snapshot_word(?: |$)"),
            ("work_word_match_to_control", r"^work_word_matches_q$"),
            ("demand_word_match_to_control", r"^demand_word_matches_q$"),
            ("work_request_to_control", r"^work_request(?: |$)"),
            ("all_registers_to_control", r".")):
            root = re.compile(source)
            results[key] = connected_paths(module, limit=10, group_limit=10,
                root_filter=lambda n, c, p: bool(root.search(c.get("attributes", {}).get("fpga_register_origin", ""))),
                sink_filter=lambda n, c, p: c.get("attributes", {}).get("fpga_register_origin") in (
                    "pf_hit_checked", "lookup_snapshot_valid", "select_stage_valid"))
            if not results[key]["graph_complete"]:
                raise RuntimeError("Incomplete mapped path graph")
        cases[label] = dict(configuration=summary["configuration"], source_sha256=sources,
            resources=summary["resources"],
            longest_register_path_cells=summary["connected_path_metrics"]["longest_register_path_cells"],
            maximum_resident_kib=summary["maximum_resident_kib"],
            mapped_sha256=digest(folder / "mapped.json"), pre_lut_sha256=digest(folder / "pre_lut.il"),
            targeted_paths=results)
    for name, sha in cases["current"]["source_sha256"].items():
        if name != "conv_read_cache.sv" and cases["reference"]["source_sha256"].get(name) != sha:
            raise RuntimeError("Additional mapped source differences require verification")
    report = dict(passed=True, reference_commit=proof["reference"],
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"), cases=cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for label, case in cases.items():
        print(label, {key: value["longest_register_path_cells"] for key, value in case["targeted_paths"].items()})


if __name__ == "__main__":
    main()
