#!/usr/bin/env python3
"""测量完整 IA 加载器的资源、配置坐标路径和预取范围路径。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, REFERENCE, PROFILES, digest, snapshot
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=["production", "compact"])
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources, hashes = snapshot(out / "sources", args.reference)
    cases = {}
    for name in args.profiles:
        for variant in ("reference", "candidate"):
            label = name + "_" + variant
            parameters = PROFILES[name]
            cases[label] = dict(top="ia_loader", parameters=parameters,
                sources=list(map(str, sources[variant])),
                options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                        [f"-G{key}={value}" for key, value in parameters.items()],
                configuration="完整 IA 加载器的分组坐标比较")
    config = out / "cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "prepare.log").open("w") as stream:
        subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config", config,
                        "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    def measure(label):
        cost, pre = out / "cost" / label, out / "pre" / label
        with (out / (label + "_map.log")).open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py",
                            "--source", pre, "--out", cost, "--mode", "physical-cost",
                            "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
                            "--wire-delay-ps", "300", "--delay-target-ps", "6667",
                            "--discard-abc9-temporaries"], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        metrics = json.loads((cost / "metrics.json").read_text())
        module = json.loads((cost / "mapped.json").read_text())["modules"]["ia_loader"]
        for name, origin in register_origins(pre / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        paths = {}
        for name, start, end in (("coordinate", "0_base_q", "demand_lookup_match_q"),
                                 ("prefetch", "global_reduction_q", "prefetch_prepare_in_range")):
            result = connected_paths(module, limit=1, group_limit=1,
                root_filter=lambda _, cell, port: start in cell.get("attributes", {}).get("fpga_register_origin", ""),
                sink_filter=lambda _, cell, port: end in cell.get("attributes", {}).get("fpga_register_origin", ""))
            if not result["graph_complete"]:
                raise RuntimeError("指定 IA 路径的连接分析未完成")
            paths[name] = result
        row = dict(parameters=cases[label]["parameters"], resources=metrics["resources"],
                   maximum_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                   targeted_paths=paths, mapped_json_sha256=digest(cost / "mapped.json"),
                   metrics_sha256=digest(cost / "metrics.json"), pre_lut_sha256=digest(pre / "pre_lut.il"))
        print(json.dumps(dict(case=label, lut=row["resources"]["lut_sites_nominal_before_packing"],
                              maximum=row["maximum_register_path_cells"],
                              targeted={key:value["longest_register_path_cells"] for key,value in paths.items()})), flush=True)
        return label, row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = dict(pool.map(measure, cases))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("综合期间 RTL 内容发生变化")
    report = dict(reference=args.reference, source_sha256=hashes,
                  mapping=dict(mode="physical-cost", max_lut_inputs=8, small_lut_area_cost=1,
                               wire_delay_ps=300, delay_target_ps=6667), cases=records)
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
