#!/usr/bin/env python3
"""测量完整 IA 缓存管理器和加载器的资源及最长组合路径。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from run_formal import ROOT, REFERENCE, PARENT, CACHE, CACHE_PARAMETERS, IA_PARAMETERS, digest, original
from scripts.rtl.source_files import with_dependencies

PROFILES = {"cache": ("ia_loader_cache_mgr", dict(CACHE_PARAMETERS, COMPACT_S8=0)),
            "ia": ("ia_loader", dict(IA_PARAMETERS, COMPACT_S8=0))}
REUSED_LABELS = {"cache_reference": "reference", "cache_candidate": "safe_cache",
                 "ia_reference": "full_ia_reference", "ia_candidate": "safe_ia"}


def contents(path):
    if path.exists():
        return path.read_bytes()
    with gzip.open(Path(str(path) + ".gz"), "rb") as stream:
        return stream.read()


def content_digest(path):
    return hashlib.sha256(contents(path)).hexdigest()


def validate_manifest(path, variant, top, revision):
    manifest = json.loads(path.read_text())
    checked = {}
    for stored_name, expected in manifest["sources_sha256"].items():
        source = Path(stored_name)
        if source.is_absolute():
            if source.is_relative_to(ROOT):
                relative = source.relative_to(ROOT)
            elif source.name in ("ia_loader.sv", "ia_loader_cache_mgr.sv"):
                relative = Path("rtl/npu/loaders") / source.name
            elif source.name == "reference.sv" and top == "ia_loader_cache_mgr":
                relative = CACHE
            else:
                raise RuntimeError("无法对应测量源码：" + stored_name)
        else:
            relative = source
        payload = (original(relative, revision).encode() if variant == "reference"
                   else (ROOT / relative).read_bytes())
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise RuntimeError("测量源码与指定版本不同：" + str(relative))
        checked[str(relative)] = expected
    return manifest, checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--reuse-from", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.reuse_from:
        measured = args.reuse_from.resolve()
        labels = REUSED_LABELS
    else:
        measured, labels = out, {name + "_" + variant: name + "_" + variant
                                for name in PROFILES for variant in ("reference", "candidate")}
        cases = {}
        for name, (top, parameters) in PROFILES.items():
            for variant in ("reference", "candidate"):
                label = labels[name + "_" + variant]
                folder = out / "sources" / label
                folder.mkdir(parents=True, exist_ok=True)
                paths = []
                for relative in ([CACHE] if name == "cache" else [PARENT, CACHE]):
                    path = folder / relative.name
                    path.write_text(original(relative, args.reference) if variant == "reference"
                                    else (ROOT / relative).read_text())
                    paths.append(path)
                params = dict(parameters)
                if variant == "candidate":
                    params["p_zero_masked_write_data"] = 0
                cases[label] = dict(top=top, parameters=params,
                    configuration="完整 IA 写数据排列的资源与时序测量",
                    sources=list(map(str, with_dependencies(paths, ROOT))),
                    options=["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                            [f"-G{key}={value}" for key, value in params.items()])
        configuration = out / "cases.json"
        configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
        with (out / "prepare.log").open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--case-config",
                configuration, "--cases", *cases, "--out", out / "pre", "--through", "pre_lut"],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        for label in cases:
            with (out / (label + "_map.log")).open("w") as stream:
                subprocess.run([sys.executable, ROOT / "scripts/fpga/remap_fpga_luts.py", "--source",
                    out / "pre" / label, "--out", out / "cost" / label, "--mode", "physical-cost",
                    "--max-lut-inputs", "8", "--small-lut-area-cost", "1", "--wire-delay-ps", "300",
                    "--delay-target-ps", "6667", "--discard-abc9-temporaries"], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, check=True)
    records = {}
    for name, (top, _) in PROFILES.items():
        for variant in ("reference", "candidate"):
            key = name + "_" + variant
            label = labels[key]
            pre, cost = measured / "pre" / label, measured / "cost" / label
            manifest, hashes = validate_manifest(pre / "manifest.json", variant, top, args.reference)
            metrics = json.loads((cost / "metrics.json").read_text())
            row = dict(top=top, parameters=manifest["parameters"], source_sha256=hashes,
                       resources=metrics["resources"],
                       maximum_register_path_cells=metrics["paths"]["longest_register_path_cells"],
                       mapped_json_sha256=content_digest(cost / "mapped.json"),
                       pre_lut_sha256=content_digest(pre / "pre_lut.il"),
                       metrics_sha256=digest(cost / "metrics.json"))
            records[key] = row
            print(json.dumps(dict(case=key, lut=row["resources"]["lut_sites_nominal_before_packing"],
                                  maximum=row["maximum_register_path_cells"])), flush=True)
    report = dict(reference=args.reference, runner_sha256=digest(__file__),
        mapping=dict(mode="physical-cost", max_lut_inputs=8, small_lut_area_cost=1,
                     wire_delay_ps=300, delay_target_ps=6667), cases=records)
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
