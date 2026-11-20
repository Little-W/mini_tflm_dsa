#!/usr/bin/env python3
"""比较正式标量单元与已完成布线的 DSP 电路，检查级联连接和资源。"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapped_graph(path):
    design = json.loads(path.read_text())
    module = next(
        value for value in design["modules"].values()
        if int(value.get("attributes", {}).get("top", "0"), 2)
    )
    cells = {
        name.removeprefix("g_dsp."): {
            field: cell[field]
            for field in ("type", "parameters", "port_directions", "connections")
        }
        for name, cell in module["cells"].items()
    }
    return {"ports": module["ports"], "cells": cells}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--routed-reference", type=Path, required=True,
                        help="包含 mapped.json 和 implementation/routed*.json 的目录")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference_mapped = args.routed_reference / "mapped.json"
    routed_path = args.routed_reference / "implementation/routed.json"
    resources_path = args.routed_reference / "implementation/routed_resources.json"
    candidate = mapped_graph(args.mapped)
    reference = mapped_graph(reference_mapped)
    if candidate != reference:
        raise RuntimeError("Mapped ports, cell parameters, or connections differ")

    cells = candidate["cells"]
    source_name = "g_partial[2].u_multiply.u_dsp"
    destination_name = "u_add.u_dsp"
    if cells[source_name]["connections"]["PCOUT"] != cells[destination_name]["connections"]["PCIN"]:
        raise RuntimeError("The 48-bit DSP cascade is not directly connected")
    dsp_cells = [cell for cell in cells.values() if cell["type"] == "DSP48E1"]
    if len(dsp_cells) != 5 or any(int(cell["parameters"]["PREG"], 2) != 1 for cell in dsp_cells):
        raise RuntimeError("Expected five DSP48E1 cells with PREG enabled")

    routed = json.loads(routed_path.read_text())["modules"]["top"]
    locations = {
        name: routed["cells"][name]["attributes"]["NEXTPNR_BEL"]
        for name in (source_name, destination_name)
    }
    resources = json.loads(resources_path.read_text())
    if not resources["routing_completed"] or resources["unplaced_cells"] or resources["resource_errors"]:
        raise RuntimeError("The reference implementation has not completed legal routing")
    result = {
        "passed": True,
        "mapped_sha256": digest(args.mapped),
        "routed_reference_mapped_sha256": digest(reference_mapped),
        "normalized_graph_sha256": hashlib.sha256(
            json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
        "normalization": "Remove only the g_dsp. instance prefix; compare every port, cell type, parameter, direction and connection",
        "routed_json_sha256": digest(routed_path),
        "routed_resources_sha256": digest(resources_path),
        "direct_cascade_bits": 48,
        "cascade_locations": locations,
        "routed_resources": resources,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": True, "direct_cascade_bits": 48,
                      "physical_lut_positions": resources["physical_lut_positions"]}))


if __name__ == "__main__":
    main()
