#!/usr/bin/env python3
"""Measure connected combinational paths through a fully mapped design."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins, resources

INTERFACE_PREFIX = "__measurement_interface__"
DEFAULT_EXCLUDED_PORTS = ("clk", "rst_n", "i_clk", "i_rst_n")


def read_input(path):
    """Read the mapped source bytes from a plain or gzip file."""
    with (gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")) as stream:
        return stream.read()


def add_interface_boundaries(module, excluded_ports=DEFAULT_EXCLUDED_PORTS):
    """Add graph-only endpoint records without changing the synthesized circuit."""
    observed = copy.deepcopy(module)
    if any(name.startswith(INTERFACE_PREFIX) for name in observed["cells"]):
        raise ValueError("A mapped cell uses the reserved measurement prefix")
    bits = [bit for cell in observed["cells"].values()
            for connection in cell["connections"].values() for bit in connection
            if isinstance(bit, int)]
    bits += [bit for port in observed.get("ports", {}).values()
             for bit in port["bits"] if isinstance(bit, int)]
    next_bit = max(bits, default=0) + 1
    counts = {"input_bits": 0, "output_bits": 0}
    for port_name, port in observed.get("ports", {}).items():
        if port_name in excluded_ports:
            continue
        direction = port["direction"]
        if direction not in ("input", "output"):
            raise ValueError(f"Unsupported interface direction: {port_name} {direction}")
        for index, bit in enumerate(port["bits"]):
            if not isinstance(bit, int):
                continue
            source = direction == "input"
            name = f"{INTERFACE_PREFIX}{direction}:{port_name}[{index}]"
            observed["cells"][name] = {
                "type": "FDRE",
                "parameters": {},
                "attributes": {
                    "fpga_register_origin": f"interface {port_name}[{index}]",
                    "measurement_boundary": direction,
                },
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [next_bit if source else bit],
                                "Q": [bit if source else next_bit]},
            }
            next_bit += 1
            counts[direction + "_bits"] += 1
    return observed, counts


def measure(module, excluded_ports=DEFAULT_EXCLUDED_PORTS, path_limit=40, scopes=()):
    observed, counts = add_interface_boundaries(module, excluded_ports)

    def boundary(expected):
        def selected(name, cell, port):
            actual = cell.get("attributes", {}).get("measurement_boundary")
            return actual == expected
        return selected

    groups = {}
    for name, start, end in (
        ("register_to_register", None, None),
        ("input_to_register", "input", None),
        ("register_to_output", None, "output"),
        ("input_to_output", "input", "output"),
    ):
        paths = connected_paths(
            observed, limit=path_limit, group_limit=path_limit,
            root_filter=boundary(start), sink_filter=boundary(end))
        groups[name] = {
            "maximum_combinational_cells": paths["longest_register_path_cells"],
            "paths": paths["register_to_register_paths"],
            "distinct_path_groups": paths["distinct_register_path_groups"],
            "endpoint_depth_histogram": paths["endpoint_port_maximum_depth_histogram"],
            "graph_complete": paths["graph_complete"],
            "unclassified_cell_types": paths["unclassified_cell_types"],
            "combinational_cycle_nodes": paths["combinational_cycle_nodes"],
            "graph_nodes": paths["graph_nodes"],
            "visited_graph_nodes": paths["visited_graph_nodes"],
        }
    scoped_paths = {}
    for scope_name, start_pattern, end_pattern in scopes:
        if scope_name in scoped_paths:
            raise ValueError(f"Duplicate path scope: {scope_name}")
        starts, ends = set(), set()

        def matching(pattern, found):
            expression = re.compile(pattern)

            def selected(name, cell, port):
                origin = cell.get("attributes", {}).get("fpga_register_origin", "")
                matched = expression.search(name) or expression.search(origin)
                if matched:
                    found.add((name, port))
                return bool(matched)
            return selected

        paths = connected_paths(
            module, limit=path_limit, group_limit=path_limit,
            root_filter=matching(start_pattern, starts),
            sink_filter=matching(end_pattern, ends))
        scoped_paths[scope_name] = {
            "start_pattern": start_pattern, "endpoint_pattern": end_pattern,
            "selected_start_ports": len(starts), "selected_endpoint_ports": len(ends),
            "scope_available": bool(starts and ends),
            "maximum_combinational_cells": paths["longest_register_path_cells"],
            "paths": paths["register_to_register_paths"],
            "endpoint_depth_histogram": paths["endpoint_port_maximum_depth_histogram"],
            "graph_complete": paths["graph_complete"],
        }
    return {
        "resources": resources(module["cells"]),
        "interface_bits": counts,
        "excluded_ports": list(excluded_ports),
        "maximum_combinational_cells": max(
            group["maximum_combinational_cells"] for group in groups.values()),
        "graph_complete": all(group["graph_complete"] for group in groups.values()),
        "path_groups": groups,
        "critical_scopes": scoped_paths,
        "method": (
            "All internal modules remain connected in the flattened mapped circuit. "
            "Interface endpoint records exist only in the analysis graph and add no "
            "combinational cells or resource counts. Paths include LUT, carry, mux, "
            "asynchronous memory read, and configured DSP dependencies. Clock and reset "
            "ports are excluded explicitly. Structural depth does not include device "
            "or routing delay."
        ),
    }


def scope_requirement(report, maximum):
    """Require complete, nonempty endpoint selections for every named scope."""
    scopes = report["critical_scopes"]
    if not scopes:
        raise ValueError("At least one named scope is required")
    if maximum < 0:
        raise ValueError("Maximum path depth must be nonnegative")
    unavailable = [name for name, scope in scopes.items() if not scope["scope_available"]]
    incomplete = [name for name, scope in scopes.items() if not scope["graph_complete"]]
    exceeding = {name: scope["maximum_combinational_cells"] for name, scope in scopes.items()
                 if scope["maximum_combinational_cells"] > maximum}
    return {"maximum_combinational_cells": maximum,
            "met": not (unavailable or incomplete or exceeding),
            "unavailable_scopes": unavailable, "incomplete_scopes": incomplete,
            "exceeding_scopes": exceeding}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--top", default="conv_im2col_frontend")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--exclude-port", action="append", default=[])
    parser.add_argument("--path-limit", type=int, default=40)
    parser.add_argument("--require-max-depth", type=int)
    parser.add_argument("--require-scope-max-depth", type=int,
                        help="Require every named scope to contain endpoints and meet this depth")
    parser.add_argument("--scope", nargs=3, action="append", default=[],
                        metavar=("NAME", "START_REGEX", "ENDPOINT_REGEX"),
                        help="Select storage endpoints while retaining every internal combinational connection")
    args = parser.parse_args()
    if args.require_scope_max_depth is not None and not args.scope:
        parser.error("--require-scope-max-depth requires at least one --scope")
    mapped_bytes = read_input(args.mapped)
    pre_lut_bytes = read_input(args.pre_lut)
    design = json.loads(mapped_bytes)
    module = design["modules"][args.top]
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    report = measure(module, tuple(DEFAULT_EXCLUDED_PORTS) + tuple(args.exclude_port),
                     args.path_limit, args.scope)
    report.update(
        top=args.top,
        mapped_sha256=hashlib.sha256(mapped_bytes).hexdigest(),
        pre_lut_sha256=hashlib.sha256(pre_lut_bytes).hexdigest())
    if args.require_max_depth is not None:
        report["requirement"] = {
            "maximum_combinational_cells": args.require_max_depth,
            "met": (report["maximum_combinational_cells"] <= args.require_max_depth
                    if report["graph_complete"] else None),
        }
    if args.require_scope_max_depth is not None:
        report["scope_requirement"] = scope_requirement(report, args.require_scope_max_depth)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "graph_complete": report["graph_complete"],
        "maximum_combinational_cells": report["maximum_combinational_cells"],
        "path_groups": {name: group["maximum_combinational_cells"]
                        for name, group in report["path_groups"].items()},
    }))
    if (not report["graph_complete"] or report.get("requirement", {}).get("met") is False or
            report.get("scope_requirement", {}).get("met") is False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
