#!/usr/bin/env python3
"""比较完整向量模块中输出偏移和舍入值到结果存储的实际映射路径。"""
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


def origin(cell):
    return cell.get("attributes", {}).get("fpga_register_origin", "")


def config_bit(cell):
    match = re.fullmatch(r"(?:c|u_config_check\.cfg) \[(\d+)\]", origin(cell))
    return int(match[1]) if match else -1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"]:
        raise RuntimeError("Arithmetic proof is incomplete")
    cases = {}
    sources = {}
    for label, folder, expected in (("reference", args.reference, proof["reference_sha256"]),
                                    ("current", args.current, proof["source_sha256"])):
        manifest = json.loads((folder / "manifest.json").read_text())
        sources[label] = {Path(name).name: value for name, value in manifest["sources_sha256"].items()}
        if sources[label]["vector_engine.sv"] != expected:
            raise RuntimeError("Proof and synthesis use different source files")
        module = json.loads((folder / "mapped.json").read_text())["modules"]["vector_engine"]
        for name, value in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value
        roots = {
            "output_offset_bit10": lambda n, c, p: config_bit(c) == 654,
            "output_offset": lambda n, c, p: 644 <= config_bit(c) <= 675,
            "rounded_value": lambda n, c, p: origin(c).startswith("q_rounded "),
        }
        paths = {}
        sink = lambda n, c, p: p == "D" and bool(re.search(r"^(?:writeback_words|result_buf)(?: |\[)", origin(c)))
        for name, root in roots.items():
            paths[name] = connected_paths(module, limit=30, group_limit=30,
                root_filter=root, sink_filter=sink)
            if not paths[name]["graph_complete"] or paths[name]["longest_register_path_cells"] <= 0:
                raise RuntimeError("Incomplete result path: " + name)
        metrics = json.loads((folder / "metrics.json").read_text())
        if not metrics["paths"]["graph_complete"]:
            raise RuntimeError("Incomplete mapped graph")
        cases[label] = dict(configuration=manifest["configuration"], source_sha256=expected,
            resources=metrics["resources"], longest_register_path_cells=metrics["paths"]["longest_register_path_cells"],
            paths=paths, mapped_sha256=digest(folder / "mapped.json"),
            pre_lut_sha256=digest(folder / "pre_lut.il"), manifest_sha256=digest(folder / "manifest.json"))
        print(label, metrics["resources"]["logic_lut_cells"],
              {name: value["longest_register_path_cells"] for name, value in paths.items()}, flush=True)
    for name, value in sources["current"].items():
        if name != "vector_engine.sv" and value != sources["reference"].get(name):
            raise RuntimeError("Additional source changes require verification: " + name)
    report = dict(passed=True, reference_commit=proof["reference_commit"], cases=cases,
        unchanged_other_synthesis_sources=True, metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"),
        proof_sha256=digest(args.proof))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
