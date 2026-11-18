#!/usr/bin/env python3
"""Check complete NPU storage and capability parameters across cache sizes."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration

CAPACITIES = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)


def configurations():
    common = dict(PCR_ENGINE=1, SIZE=16, IA_CACHE_BLOCKS=4, PS_FRAME_COUNT=16,
                  AXI_READ_OUTSTANDING=4, PS_FORCE_RAW=1, SHARED_BANK_COUNT=7)
    standard = {**config.DEFAULTS, **config.read_config(ROOT / "config/npu.mk"), **common}
    fpga = {**config.DEFAULTS, **config.read_config(ROOT / "config/npu_fpga.mk"), **common}
    cases = []
    for index, capacity in enumerate(CAPACITIES):
        width = 32 if index % 2 == 0 else 64
        values = dict(standard, IM2COL_CACHE_BYTES=capacity, NPU_AXI_DATA_WIDTH=width,
                      SHARED_BANK_BYTES=2048, PS_POOL_BYTES=12288)
        cases.append((f"cache_{capacity}_bank_2048_axi_{width}", values))
    for capacity in (4096, 16384):
        values = dict(fpga, IM2COL_CACHE_BYTES=capacity, NPU_AXI_DATA_WIDTH=64,
                      SHARED_BANK_BYTES=8192, PS_POOL_BYTES=49152)
        cases.append((f"cache_{capacity}_bank_8192_axi_64", values))
    return [(name, config.validate_config(values, check_budget=False)) for name, values in cases]


def run_case(name, values, output, verilator):
    folder = Path(output) / name
    report = elaboration.measure(values, verilator=verilator, output_dir=folder,
                                 cache_dir=folder / "cache")
    capacity = values["IM2COL_CACHE_BYTES"]
    arrays = report["elaborated_state"]["buffer_arrays_bits"]
    capabilities = report["capability_parameters"]
    tops = {module: {key: capabilities[module][key] for key in
                    ("IM2COL_CACHE_BYTES", "CONV_CACHE_SETS", "CONV_CACHE_WAYS", "CONV_LINE_BYTES")}
            for module in ("npu_axil_top", "npu_top")}
    checks = {
        "complete_npu_storage": report["passed"],
        "data_array_bits": arrays["conv_data_cache"] == capacity * 8,
        "metadata_array_bits": arrays["conv_cache_metadata"] == (capacity // 16) * 322,
        "capability_bytes": capabilities["npu_axil_reg_if"]["CONV_CACHE_BYTES"] == capacity,
        "derived_cache_parameters": all(
            params == dict(IM2COL_CACHE_BYTES=capacity, CONV_CACHE_SETS=capacity // 32,
                           CONV_CACHE_WAYS=2, CONV_LINE_BYTES=16)
            for params in tops.values()),
        "shared_data_bits": arrays["ia_ps_shared_ram"] ==
            values["SHARED_BANK_BYTES"] * values["SHARED_BANK_COUNT"] * 8,
        "sources_unchanged": report["sources_unchanged"],
    }
    result = {
        "name": name, "passed": all(checks.values()), "checks": checks,
        "configuration": report["hardware_configuration"],
        "im2col_data_bits": arrays["conv_data_cache"],
        "im2col_metadata_bits": arrays["conv_cache_metadata"],
        "capability_bytes": capabilities["npu_axil_reg_if"]["CONV_CACHE_BYTES"],
        "top_cache_parameters": tops,
        "shared_data_bits": arrays["ia_ps_shared_ram"],
        "total_sequential_bits": report["elaborated_state"]["total_bits"],
        "buffer_array_bits": sum(arrays.values()),
        "source_sha256": report["source_sha256"],
        "verilator": report["verilator"],
        "elapsed_seconds": report["elapsed_seconds"],
        "report": str(folder / "result.json"),
    }
    (folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/im2col_config/elaboration")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    hashes = elaboration.sources_sha256()
    additional = {str(path.relative_to(ROOT)): elaboration.digest(path) for path in
                  (Path(__file__).resolve(), ROOT / "scripts/capacity/config.py",
                   ROOT / "config/npu.mk", ROOT / "config/npu_fpga.mk")}
    summary = {
        "passed": False, "complete": False,
        "scope": "Complete npu_axil_top Verilator elaboration and instantiated storage inventory",
        "budget_scope": "Hardware capacity checks; the software budget limit is evaluated separately",
        "source_sha256": {**hashes, **additional}, "profiles": [],
    }
    cases = configurations()
    order = {name: index for index, (name, _) in enumerate(cases)}
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        pending = {executor.submit(run_case, name, values, str(output), args.verilator): name
                   for name, values in cases}
        for future in as_completed(pending):
            result = future.result()
            summary["profiles"].append(result)
            summary["profiles"].sort(key=lambda row: order[row["name"]])
            (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps({key: result[key] for key in
                              ("name", "passed", "im2col_data_bits", "im2col_metadata_bits",
                               "capability_bytes", "elapsed_seconds")}), flush=True)
    summary["sources_unchanged"] = all(
        elaboration.digest(ROOT / name) == value for name, value in summary["source_sha256"].items())
    summary["all_profiles_match_sources"] = all(
        profile["source_sha256"] == hashes for profile in summary["profiles"])
    summary["complete"] = len(summary["profiles"]) == len(cases)
    summary["passed"] = summary["complete"] and summary["sources_unchanged"] and \
        summary["all_profiles_match_sources"] and all(profile["passed"] for profile in summary["profiles"])
    summary["elapsed_seconds"] = time.monotonic() - started
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(passed=summary["passed"], profiles=len(cases),
                          elapsed_seconds=summary["elapsed_seconds"],
                          report=str(output / "summary.json"))), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
