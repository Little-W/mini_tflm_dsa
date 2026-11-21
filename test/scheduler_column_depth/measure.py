#!/usr/bin/env python3
"""在相同 xc7 综合设置下比较列计数器分组增量的资源与实际连接路径。"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import subprocess
import sys

from support import ROOT, REFERENCE, PARAMETERS, check_sources, prepare_inputs

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/scheduler_column_depth/measurement")
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    source_root, paths, _, manifest = prepare_inputs(out, args.reference)
    options = ["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"] + [
        f"-G{name}={value}" for name, value in PARAMETERS.items()]
    cases = {label: {
        "top": "ps_window_scheduler", "options": options,
        "sources": [str(path.relative_to(source_root))],
        "configuration": "完整调度器，SIZE=16、FRAME_COUNT=16、MAX_REUSE_TILES=32",
    } for label, path in paths.items()}
    config = out / "cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(source_root), "--case-config", str(config),
               "--cases", "reference", "current", "--out", str(out / "synthesis")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    check_sources(manifest)
    synthesis = json.loads((out / "synthesis/summary.json").read_text())
    report = {"inputs": manifest, "parameters": PARAMETERS,
              "tool": synthesis["tool"], "part": synthesis["part"], "family": synthesis["family"],
              "scope": "Independent scheduler synthesis and connected register path cell counts",
              "method": "synth_xilinx -top ps_window_scheduler -family xc7 -noiopad -noclkbuf -flatten",
              "cases": {}}
    fields = ("logic_lut_cells", "distributed_ram_lut_sites_nominal",
              "shift_register_lut_sites_nominal", "lut_sites_nominal_before_packing",
              "flip_flops", "carry4", "ramb36e1", "ramb18e1", "dsp48e1")
    for label in ("reference", "current"):
        folder = out / "synthesis" / label
        metrics = json.loads((folder / "metrics.json").read_text())
        module = json.loads((folder / "mapped.json").read_text())["modules"]["ps_window_scheduler"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin

        def origin(cell):
            return cell.get("attributes", {}).get("fpga_register_origin", "")

        row = {"resources": {name: metrics["resources"][name] for name in fields},
               "module_maximum_register_depth": metrics["paths"]["longest_register_path_cells"],
               "paths": {}}
        for target in ("prediction_column_s0", "next_column_tile"):
            paths = connected_paths(module, limit=32,
                root_filter=lambda name, cell, port: origin(cell).startswith("next_column_tile "),
                sink_filter=lambda name, cell, port: port == "D" and origin(cell).startswith(target + " "))
            (folder / (target + "_paths.json")).write_text(json.dumps(paths, indent=2) + "\n")
            longest = paths["register_to_register_paths"][0]
            row["paths"][target] = {
                "maximum_cells": paths["longest_register_path_cells"],
                "startpoint": longest["startpoint"]["register_origin"],
                "endpoint": longest["endpoint"]["register_origin"],
                "cell_types": dict(collections.Counter(cell["type"] for cell in longest["path"])),
            }
        exact = connected_paths(module, limit=8,
            root_filter=lambda name, cell, port: origin(cell) == "next_column_tile [0]",
            sink_filter=lambda name, cell, port: port == "D" and origin(cell) == "prediction_column_s0 [28]")
        row["next_column_tile_0_to_prediction_column_s0_28"] = exact["longest_register_path_cells"]
        report["cases"][label] = row
    (out / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
