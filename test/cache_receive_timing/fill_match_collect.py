#!/usr/bin/env python3
"""核对保存填充组号匹配状态的证明、依赖和实际映射结果。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from support import ROOT, SOURCE, digest

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def mapped_case(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    metrics = json.loads((folder / "metrics.json").read_text())
    module = json.loads((folder / "mapped.json").read_text())["modules"]["conv_windowed_cache"]
    for name, value in register_origins(folder / "pre_lut.il").items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value

    def origin(cell):
        return cell.get("attributes", {}).get("fpga_register_origin", "")

    entries, details = {}, {}
    for port in ("rsp_valid", "rsp_data"):
        sink = "$output$" + port
        module["cells"][sink] = {"type": "FDRE", "connections": {"D": module["ports"][port]["bits"]},
                                 "port_directions": {"D": "input"},
                                 "attributes": {"fpga_register_origin": port}}
        for source in ("lookup_snapshot_set", "lookup_fill_set_match_q"):
            key = source + "_to_" + port
            paths = connected_paths(module, limit=1, group_limit=1,
                root_filter=lambda name, cell, pin: source in origin(cell),
                sink_filter=lambda name, cell, pin: name == sink)
            entries[key] = paths["longest_register_path_cells"] if paths["register_to_register_paths"] else None
            details[key] = paths
        del module["cells"][sink]
    paths = connected_paths(module, limit=1, group_limit=1,
        sink_filter=lambda name, cell, pin: pin == "D" and "lookup_fill_set_match_q" in origin(cell))
    entries["match_register_data_input"] = paths["longest_register_path_cells"] if paths["register_to_register_paths"] else None
    details["match_register_data_input"] = paths
    return manifest, {"resources": metrics["resources"],
                      "maximum_register_depth": metrics["paths"]["longest_register_path_cells"],
                      "target_depths": entries}, details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal", type=Path, required=True)
    parser.add_argument("--reference-mapping", type=Path, required=True)
    parser.add_argument("--candidate-mapping", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.formal.read_text())
    if not proof["passed"] or proof["input_assumptions"]:
        raise RuntimeError("完整缓存证明未通过无约束检查")
    if len(proof["response_profiles"]) != 11 or len(proof["complete_cache_profiles"]) != 5:
        raise RuntimeError("完整缓存证明配置数量不符")
    if not all(row["passed"] for row in proof["response_profiles"] + proof["complete_cache_profiles"]):
        raise RuntimeError("缓存配置证明未完成")
    inputs = proof["inputs"]
    if digest(ROOT / SOURCE) != inputs["source_sha256"]:
        raise RuntimeError("当前缓存源码与证明不符")
    if digest(Path(__file__).resolve().parent / "fill_match_reference.sv") != inputs["reference_sha256"]:
        raise RuntimeError("保存的参考源码与证明不符")
    for name, expected in inputs["helper_sha256"].items():
        if digest(ROOT / name) != expected:
            raise RuntimeError("公共依赖与证明不符：" + name)
    rows, manifests, details = {}, {}, {}
    for label, folder in (("reference", args.reference_mapping), ("current", args.candidate_mapping)):
        manifest, rows[label], details[label] = mapped_case(folder)
        expected_source = inputs["reference_sha256" if label == "reference" else "source_sha256"]
        measured_sources = manifest["sources_sha256"]
        expected_helpers = inputs["helper_sha256"]
        for name, expected in expected_helpers.items():
            if measured_sources[name] != expected:
                raise RuntimeError("映射使用的公共依赖不符：" + name)
        measured_cache = [value for name, value in measured_sources.items() if name.endswith(str(SOURCE))]
        if measured_cache != [expected_source]:
            raise RuntimeError("映射使用的缓存源码不符")
        manifests[label] = manifest
    if manifests["reference"]["options"] != manifests["current"]["options"]:
        raise RuntimeError("两侧映射参数不同")
    report = {
        "passed": True,
        "source_sha256": {"reference": inputs["reference_sha256"], "current": inputs["source_sha256"]},
        "helper_sha256": inputs["helper_sha256"],
        "configuration": {option[2:].split("=", 1)[0]: int(option.split("=", 1)[1])
                          for option in manifests["current"]["options"] if option.startswith("-G")},
        "options": manifests["current"]["options"],
        "method": "synth_xilinx -top conv_windowed_cache -family xc7 -noiopad -noclkbuf -flatten",
        "proof": {"summary": str(args.formal), "summary_sha256": digest(args.formal),
                  "response_profiles": proof["response_profiles"],
                  "complete_cache_profiles": proof["complete_cache_profiles"],
                  "input_assumptions": [], "saved_match_relation": proof["relation"]},
        "cases": rows,
        "scope": "Independent complete cache mapping; null target depth means no connected path exists.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    args.out.with_name(args.out.stem + "_paths.json").write_text(json.dumps(details, indent=2) + "\n")
    print(json.dumps({label: {"lut": row["resources"]["logic_lut_cells"],
                             "register_depth": row["maximum_register_depth"],
                             "target_depths": row["target_depths"]} for label, row in rows.items()}, indent=2))


if __name__ == "__main__":
    main()
