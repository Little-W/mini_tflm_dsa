#!/usr/bin/env python3
"""核对 IA 写入优化的同源检查结果并保存测量报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = tuple("rtl/npu/loaders/" + name + ".sv" for name in
                ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rtl-rev", default="9ef45ec8")
    args = parser.parse_args()
    build = args.build.resolve()
    hashes = {name: digest(ROOT / name) for name in SOURCES}
    rtl_commit = subprocess.check_output(["git", "rev-parse", args.rtl_rev], cwd=ROOT, text=True).strip()
    for name, expected in hashes.items():
        data = subprocess.check_output(["git", "show", rtl_commit + ":" + name], cwd=ROOT)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Saved RTL commit differs from checked source")
    reports = {name: json.loads((build / folder / "summary.json").read_text())
               for name, folder in (("columns", "column_formal"), ("cache", "cache_formal"),
                                    ("interface", "interface_fpga"), ("shared_ram", "shared"))}
    if not all(item["passed"] for item in reports.values()):
        raise RuntimeError("An IA verification result is incomplete")
    if reports["columns"]["source_sha256"] != hashes[SOURCES[0]]:
        raise RuntimeError("Column formal proof source differs")
    if reports["cache"]["source_sha256"][SOURCES[2]] != hashes[SOURCES[2]]:
        raise RuntimeError("Cache formal proof source differs")
    if reports["interface"]["source_sha256"] != hashes:
        raise RuntimeError("FPGA interface comparison source differs")
    shared_hashes = dict(reports["shared_ram"]["source_sha256"])
    shared_hashes.update(reports["shared_ram"]["related_source_sha256"])
    if any(shared_hashes[name] != value for name, value in hashes.items()):
        raise RuntimeError("Shared RAM comparison source differs")

    paths = json.loads((build / "native_paths.json").read_text())
    inputs = json.loads((build / "native_inputs/input_manifest.json").read_text())
    if inputs["current"] != hashes:
        raise RuntimeError("Synthesis input source differs")
    reference = reports["columns"]["reference_commit"]
    for name, expected in inputs["reference"].items():
        data = subprocess.check_output(["git", "show", reference + ":" + name], cwd=ROOT)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError("Synthesis reference source differs")

    synthesis = {}
    source_sets = {}
    selected_paths = ("ext_dma_wr_col_base_to_ram_data", "ext_dma_wr_valid_to_ram_data")
    for label, case in paths.items():
        normalized = {}
        for name, value in case["source_manifest"]["sources_sha256"].items():
            key = "rtl/npu/loaders/" + Path(name).name if "/native_inputs/" in name else name
            normalized[key] = value
        if any(normalized[name] != inputs[label][name] for name in SOURCES):
            raise RuntimeError("Mapped netlist source differs")
        source_sets[label] = normalized
        synthesis[label] = {
            "resources": case["resources"], "parameters": case["source_manifest"]["parameters"],
            "mapped_sha256": case["mapped_sha256"], "pre_lut_sha256": case["pre_lut_sha256"],
            "source_sha256": normalized,
            "longest_register_path_cells": case["complete_module"]["longest_register_path_cells"],
            "graph_complete": case["complete_module"]["graph_complete"],
            "write_path_depths": {name: value["longest_register_path_cells"]
                                  for name, value in case["write_paths"].items()},
            "representative_paths": {name: case["write_paths"][name]["register_to_register_paths"][:1]
                                     for name in selected_paths},
        }
    differences = {name for name, value in source_sets["current"].items()
                   if source_sets["reference"].get(name) != value}
    if differences != {SOURCES[0], SOURCES[2]}:
        raise RuntimeError("Synthesis contains additional source differences")

    shared = reports["shared_ram"]
    shared_keys = ("passed", "shared_data_ram_bytes", "allocation_bank_bytes", "physical_banks",
                   "profiles", "s8_offsets_per_profile", "s16_bit_patterns_per_wide_profile",
                   "value_checks", "cycle_value_checks", "control_checks", "port_checks",
                   "simultaneous_ia_rw_cycles", "simultaneous_ia_ps_cycles",
                   "wide_col7_cross_word_writes", "mask_patterns", "cycles",
                   "undefined_behavior_sanitizer", "compact_offset_width",
                   "sanitized_translation_units", "binary_sha256", "source_hashes_unchanged")
    result = {
        "passed": True, "reference_commit": reference,
        "rtl_commit": rtl_commit,
        "source_sha256": hashes, "same_source_verified": True,
        "synthesis": synthesis,
        "verification": {"column_formal": reports["columns"], "cache_formal": reports["cache"],
                         "fpga_interface": reports["interface"],
                         "shared_ram": {name: shared[name] for name in shared_keys}},
        "artifact_sha256": {name: digest(build / name) for name in
            ("column_formal/summary.json", "cache_formal/summary.json", "interface_fpga/summary.json",
             "shared/summary.json", "native_paths.json", "native/summary.json")},
        "tool_source_sha256": {name: digest(ROOT / name) for name in
            ("scripts/fpga/open_fpga_synth.py", "scripts/fpga/netlist_metrics.py",
             "test/ia_write_admission/run_formal.py", "test/ia_write_admission/run_interface.py",
             "test/ia_write_admission/paths.py", "test/ia_write_admission/summarize.py",
             "test/ia_write_admission/prepare_measurement.py")},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "source_sha256": hashes,
                      "logic_luts": {name: case["resources"]["logic_lut_cells"]
                                     for name, case in synthesis.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
