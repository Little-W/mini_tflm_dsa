#!/usr/bin/env python3
"""测量完整 IA 控制器和帧调度器的资源及指定寄存器间路径。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "351f3fb63f8d8b36e46c36c7ab539cae475cc8d2"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from scripts.rtl.source_files import input_files, with_dependencies
from netlist_metrics import connected_paths, register_origins
from rtl_reference import read_rtl_source

IA_PARAMETERS = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                      COUNT_WIDTH=29, CACHE_BLOCKS=32, PS_FRAME_COUNT=16,
                      p_precomputed_packed_tiles=1, p_precomputed_frame_rows=1,
                      p_precomputed_slot_mask=1, p_indexed_slot_rows=1,
                      p_parallel_request_match=1)
PROFILES = {
    "ia_regular": ("ia_loader_ctrl", "rtl/npu/loaders/ia_loader_ctrl.sv",
                   dict(IA_PARAMETERS, COMPACT_S8=0), "w_group_last_idx", "w_cur_r"),
    "ia_compact": ("ia_loader_ctrl", "rtl/npu/loaders/ia_loader_ctrl.sv",
                   dict(IA_PARAMETERS, COMPACT_S8=1), "w_group_last_idx", "w_cur_r"),
    "scheduler": ("ps_window_scheduler", "rtl/npu/control/ps_window_scheduler.sv",
                  dict(SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=16),
                  "frame_k", "command_buffer_recoverable"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    cases = {}
    for name, (top, relative, parameters, _, _) in PROFILES.items():
        original = read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT, text=True)
        current = (ROOT / relative).read_text()
        for path in input_files(with_dependencies([ROOT / relative], ROOT), ROOT):
            hashes[str(path.relative_to(ROOT))] = digest(path)
        for variant, text in (("reference", original), ("candidate", current)):
            label = name + "_" + variant
            snapshot = out / (label + ".sv")
            snapshot.write_text(text)
            cases[label] = dict(top=top, parameters=parameters, sources=[str(snapshot)],
                                options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                                [f"-G{key}={value}" for key, value in parameters.items()],
                                configuration="完整控制模块的分组比较测量")
    config = out / "cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    with (out / "prepare.log").open("w") as stream:
        subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config", config,
                        "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    def measure(label):
        profile, variant = label.rsplit("_", 1)
        top, _, _, start, end = PROFILES[profile]
        cost, pre = out / "cost" / label, out / "pre" / label
        with (out / (label + "_map.log")).open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py",
                            "--source", pre, "--out", cost, "--mode", "physical-cost",
                            "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
                            "--wire-delay-ps", "300", "--delay-target-ps", "6667",
                            "--discard-abc9-temporaries"], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        metrics = json.loads((cost / "metrics.json").read_text())
        module = json.loads((cost / "mapped.json").read_text())["modules"][top]
        for name, origin in register_origins(pre / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        path = connected_paths(module, limit=1, group_limit=1,
            root_filter=lambda name, cell, port: start in cell.get("attributes", {}).get("fpga_register_origin", ""),
            sink_filter=lambda name, cell, port: end in cell.get("attributes", {}).get("fpga_register_origin", ""))
        if not path["graph_complete"]:
            raise RuntimeError("指定控制路径的连接分析未完成")
        row = dict(parameters=cases[label]["parameters"], resources=metrics["resources"],
                   maximum_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                   source_register=start, target_register=end,
                   targeted_path_cells=path["longest_register_path_cells"],
                   targeted_path=path["register_to_register_paths"][:1],
                   mapped_json_sha256=digest(cost / "mapped.json"),
                   metrics_sha256=digest(cost / "metrics.json"),
                   pre_lut_sha256=digest(pre / "pre_lut.il"))
        print(json.dumps(dict(case=label, lut=row["resources"]["lut_sites_nominal_before_packing"],
                              maximum=row["maximum_register_path_cells"],
                              targeted=row["targeted_path_cells"])), flush=True)
        return label, row

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = dict(pool.map(measure, cases))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("综合期间 RTL 内容发生变化")
    report = dict(reference=args.reference, source_sha256=hashes,
                  mapping=dict(mode="physical-cost", max_lut_inputs=8, small_lut_area_cost=1,
                               wire_delay_ps=300, delay_target_ps=6667), cases=records)
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
