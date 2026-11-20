#!/usr/bin/env python3
"""统计前端描述符和缓存响应输入至实际消费寄存器的组合连接。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins, resources

PREFIX = "descriptor_observation_"
TARGETS = ("state", "request_index_q", "request_epoch_q", "request_progress_q",
           "request_addr_q", "row_base_ix", "row_base_iy", "addr")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(args.mapped.read_text())["modules"]["conv_im2col_frontend"]
    module = copy.deepcopy(original)
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    next_bit = max(bit for cell in module["cells"].values()
                   for bits in cell["connections"].values() for bit in bits if isinstance(bit, int)) + 1
    root_groups = {}
    boundaries = []

    # 观察单元只存在于内存中的分析图，综合网表及原始资源数量保持完整。
    def observe(label, bits, source):
        nonlocal next_bit
        names = []
        for index, bit in enumerate(bits):
            if not isinstance(bit, int):
                continue
            name = f"{PREFIX}{label}[{index}]"
            names.append(name)
            module["cells"][name] = {
                "type": "FDRE", "parameters": {},
                "attributes": {"fpga_register_origin": f"interface {label} [{index}]"},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [next_bit] if source else [bit],
                                "Q": [bit] if source else [next_bit]},
            }
            next_bit += 1
        return names

    for name, cell in list(module["cells"].items()):
        if cell["type"] == "$scopeinfo":
            if cell["connections"]:
                raise RuntimeError("Scope metadata has unexpected connections")
            del module["cells"][name]
            continue
        if not cell["type"].startswith(("conv_read_cache", "conv_next_use_predictor")):
            continue
        boundaries.append({"cell": name, "type": cell["type"]})
        del module["cells"][name]
        for port, bits in cell["connections"].items():
            if port in ("clk", "rst_n"):
                continue
            label = name + "." + port
            source = cell["port_directions"][port] == "output"
            names = observe(label, bits, source)
            if source:
                root_groups[label] = names
    for name, port in module["ports"].items():
        if name in ("clk", "rst_n"):
            continue
        source = port["direction"] == "input"
        names = observe(name, port["bits"], source)
        if source:
            root_groups[name] = names

    actual_root = lambda name, cell, port: not name.startswith(PREFIX)
    actual_sink = lambda name, cell, port: not name.startswith(PREFIX)
    internal = connected_paths(module, limit=20, group_limit=20,
                               root_filter=actual_root, sink_filter=actual_sink)
    if not internal["graph_complete"]:
        raise RuntimeError("Frontend internal connection graph is incomplete: " + json.dumps({
            "unclassified": internal["unclassified_cell_types"],
            "cycles": internal["combinational_cycle_nodes"],
        }))
    report = {
        "mapped_sha256": hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
        "pre_lut_sha256": hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
        "resources": resources(original["cells"]),
        "internal_paths": internal,
        "interface_boundaries": boundaries,
        "input_groups": {},
    }
    for group in ("tile_p0", "tile_q0", "tile_valid", "tile_rows", "tile_cols", "wr_ready",
                  "u_cache.rsp_valid", "u_cache.rsp_error", "u_cache.req_ready"):
        names = set(root_groups[group])
        paths = connected_paths(module, limit=100000, group_limit=100000,
                                root_filter=lambda name, cell, port: name in names,
                                sink_filter=actual_sink)
        targets = {}
        for target in TARGETS:
            selected = [path for path in paths["register_to_register_paths"]
                        if (path["endpoint"].get("register_origin") or "").startswith(target + " ")]
            targets[target] = {
                "connected": bool(selected),
                "longest_path_cells": max((path["combinational_cells"] for path in selected), default=0),
                "longest_paths": selected[:1],
            }
        report["input_groups"][group] = {
            "longest_path_cells": paths["longest_register_path_cells"],
            "targets": targets, "longest_paths": paths["register_to_register_paths"][:1],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "logic_lut_cells": report["resources"]["logic_lut_cells"],
        "longest_internal_path_cells": internal["longest_register_path_cells"],
        "inputs": {name: {target: value["longest_path_cells"] for target, value in group["targets"].items()}
                   for name, group in report["input_groups"].items()},
    }))


if __name__ == "__main__":
    main()
