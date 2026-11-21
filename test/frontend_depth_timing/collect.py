#!/usr/bin/env python3
"""核对当前 DMA 源码、两种配置的测量以及实际事务和形式验证结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DMA_FILES = (
    "rtl/npu/conv/conv_im2col_frontend.sv",
    "rtl/npu/dma/cache/conv_next_use_predictor.sv",
    "rtl/npu/dma/cache/conv_read_cache.sv",
    "rtl/npu/dma/axi_dual_block_dma.sv",
    "rtl/npu/dma/axi_linear_block_dma.sv",
    "rtl/npu/dma/conv_window_queue.sv",
)
HELPER = "rtl/common/parallel_prefix_add.sv"
PROOFS = ("check", "stream_check", "stream_select_check", "address_check",
          "offset_check", "range_write_check", "range_four_state",
          "descriptor_pipeline_check", "prepared_address_check", "word_limit_check",
          "byte_step_check", "queue_check", "output_check")


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(recorded, expected, required):
    for name in required:
        found = {value for path, value in recorded.items()
                 if path == name or path.endswith("/" + name)}
        if found != {expected[name]}:
            raise RuntimeError("源码摘要不一致: " + name)


def performance_cases(lines):
    cases = {}
    for line in lines:
        if not line.startswith("CASE "):
            continue
        fields = line.split()
        cases[fields[1]] = {key: int(value) for key, value in
                           re.findall(r"(\w+)=(\d+)", line)}
    for name, count in (("single_beat_hits", 256), ("s16_single_beat_hits", 128)):
        result = cases[name]
        if not (result["requests"] == count and result["consecutive"] == count - 1 and
                result["maximum_interval"] == 1 and result["cycles"] == count):
            raise RuntimeError("单拍窗口每周期返回条件未满足: " + name)
    return {name: cases[name] for name in
            ("consecutive_hits", "single_beat_hits", "s16_single_beat_hits")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--synthesis", type=Path, required=True)
    parser.add_argument("--proofs", type=Path, required=True)
    parser.add_argument("--transactions", type=Path, nargs=2, required=True)
    parser.add_argument("--window-dma", type=Path, required=True)
    parser.add_argument("--cache-formal", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("measurement.json"))
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    expected = {name: digest(source_root / name) for name in (*DMA_FILES, HELPER)}
    synthesis = read(args.synthesis / "summary.json")
    report = {"scope": "完整 axi_dual_block_dma，含图像前端、缓存、队列和线性 DMA",
              "source_sha256": expected, "maximum_register_cells": 14,
              "tool": synthesis["tool"], "family": synthesis["family"],
              "part": synthesis["part"], "clock_period_ns": synthesis["clock_period_ns"],
              "method": synthesis["method"], "physical_timing_150mhz_confirmed": False,
              "cases": {}, "proofs": {}, "transactions": []}
    for name in ("dma_stream_soc", "dma_stream_w8_l16"):
        folder = args.synthesis / name
        manifest = read(folder / "manifest.json")
        metrics = read(folder / "metrics.json")
        boundary = read(folder / "boundary_paths.json")
        targets = read(folder / "target_paths.json")
        if targets["mapped_sha256"] != digest(folder / "mapped.json"):
            raise RuntimeError("目标端点分析所用综合网表不一致: " + name)
        verify_hashes(manifest["sources_sha256"], expected, (*DMA_FILES, HELPER))
        requirement = metrics["register_path_requirement"]
        if not (requirement["met"] and requirement["graph_complete"] and
                requirement["observed_combinational_cells"] <= 14):
            raise RuntimeError("完整 DMA 寄存器路径检查未满足要求: " + name)
        report["cases"][name] = {
            "parameters": manifest["parameters"], "resources": metrics["resources"],
            "register_path_requirement": requirement,
            "output_paths": {port: {
                "all_registers": item["maximum_cells"],
                "image_output_registers": item["registered_image_output"]["maximum_cells"],
            } for port, item in boundary["outputs"].items()},
            "target_paths": targets["profiles"],
            "report_sha256": {filename: digest(folder / filename) for filename in
                              ("metrics.json", "manifest.json", "boundary_paths.json", "target_paths.json")},
        }
    for name in PROOFS:
        path = args.proofs / name / "summary.json"
        result = read(path)
        if not result.get("passed", False):
            raise RuntimeError("形式验证未通过: " + name)
        target = (DMA_FILES[5] if name == "queue_check" else
                  DMA_FILES[3] if name == "output_check" else DMA_FILES[0])
        recorded = result.get("frontend_sha256", result.get("source_sha256"))
        if isinstance(recorded, dict) and "current" in recorded:
            if recorded["current"] != expected[target]:
                raise RuntimeError("形式验证源码不一致: " + name)
        elif isinstance(recorded, dict):
            verify_hashes(recorded, expected, [target])
        elif recorded != expected[target]:
            raise RuntimeError("形式验证源码不一致: " + name)
        report["proofs"][name] = result
        report["proofs"][name]["summary_sha256"] = digest(path)
    for folder in args.transactions:
        result = read(folder / "summary.json")
        if not result["passed"]:
            raise RuntimeError("前端实际事务未通过: " + str(folder))
        for case in result["configurations"]:
            verify_hashes(case["source_sha256"], expected, DMA_FILES[:3])
            report["transactions"].append({
                key: case[key] for key in ("case", "SIZE", "BUS_WIDTH", "LANES",
                    "LINE_BYTES", "CACHE_SETS", "REGISTER_CACHE_REQUEST",
                    "REGISTER_DESCRIPTOR", "CACHE_RESPONSE_DEPTH", "passed", "summary")
            })
    window = read(args.window_dma / "summary.json")
    if not (window["passed"] and window["fpga"]):
        raise RuntimeError("FPGA 窗口 DMA 事务未通过")
    verify_hashes(window["source_sha256"], expected, DMA_FILES)
    intervals = window["maximum_response_intervals"]
    if intervals != {"single_beat": 1, "within_descriptor": 3, "descriptor_boundary": 3}:
        raise RuntimeError("窗口 DMA 性能检查参数不一致")
    report["window_dma"] = {key: window[key] for key in (
        "passed", "fpga", "executable_sha256", "resident_stream_sha256",
        "resident_stream_cycles", "maximum_response_intervals", "tests")}
    report["window_dma"]["performance"] = performance_cases(window["tests"])
    cache = read(args.cache_formal / "summary.json")
    if not cache["passed"] or cache["inputs"]["source_sha256"] != expected[DMA_FILES[2]]:
        raise RuntimeError("完整缓存证明与当前源码不一致")
    for path, value in cache["inputs"]["helper_sha256"].items():
        if digest(source_root / path) != value:
            raise RuntimeError("缓存证明依赖源码不一致: " + path)
    report["cache_formal"] = {key: cache[key] for key in (
        "passed", "input_assumptions", "response_profiles", "complete_cache_profiles", "relation")}
    report["cache_formal"]["reference_commit"] = cache["inputs"]["reference_commit"]
    report["cache_formal"]["summary_sha256"] = digest(args.cache_formal / "summary.json")
    configuration_file = Path(__file__).with_name("configuration_measurement.json")
    configuration = read(configuration_file)
    if not configuration["passed"] or configuration["validation"]["source_sha256"]["current"] != expected[DMA_FILES[0]]:
        raise RuntimeError("配置表达式证明与当前源码不一致")
    report["configuration_formal"] = {
        "passed": True, "profiles": len(configuration["validation"]["runs"]),
        "strict_four_state_checks": configuration["strict_four_state_checks"],
        "report_sha256": digest(configuration_file),
    }
    linear_file = ROOT / "test/dma_read_length_depth/measurement.json"
    linear = read(linear_file)
    if not linear["passed"] or linear["source_sha256"][DMA_FILES[4]] != expected[DMA_FILES[4]]:
        raise RuntimeError("线性 DMA 证明与当前源码不一致")
    return_file = Path(__file__).with_name("linear_return_measurement.json")
    return_relation = read(return_file)
    if not return_relation["passed"] or return_relation["source_sha256"] != linear["reference_source_sha256"]:
        raise RuntimeError("线性 DMA 返回资格证明的参考源码不一致")
    report["linear_formal"] = {
        "passed": True, "profiles": len(linear["full_module_formal"]["profiles"]),
        "source_sha256": linear["source_sha256"],
        "return_qualification_proof_sha256": digest(return_file),
        "report_sha256": digest(linear_file),
    }
    report["passed"] = True
    report["collector_sha256"] = digest(Path(__file__))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("DMA_MEASUREMENT_COLLECTION_PASS", args.out)


if __name__ == "__main__":
    main()
