#!/usr/bin/env python3
"""组合各方向 64 bit/周期的公开加速器结果与实际输出文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-replay", type=Path, required=True)
    parser.add_argument("--coral-fair", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, coral, out = args.public_replay.resolve(), args.coral_fair.resolve(), args.out.resolve()
    assert source != out and coral != out
    public = read(source / "public_replay_summary.json")
    fair = read(coral / "fair_coral64.json")
    building = read(coral / "build.json")
    assert public["passed"] and fair["passed"] and building["passed"]
    assert fair["case_count"] == 31 and fair["output_values"] == 225375
    assert fair["source_unchanged"] and fair["all_outputs_equal"] and fair["compatibility_128_checked"]
    assert fair["public_replay_summary_sha256"] == sha(source / "public_replay_summary.json")
    assert fair["build_manifest_sha256"] == sha(coral / "build.json")
    assert fair["binary_sha256"] == building["binary_sha256"]
    rows = {row["name"]: row for row in fair["results"]}
    out.mkdir(parents=True, exist_ok=True)
    copied = {}

    def copy(path, relative):
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied[str(relative)] = sha(target)

    for relative, expected in public["results_sha256"].items():
        assert sha(source / relative) == expected
        if not relative.startswith("coral/"): copy(source / relative, Path(relative))
    for relative in ("gemmini/execution.json", "vta/execution.json", "nvdla/execution.json"):
        copy(source / relative, Path(relative))
    for case in public["common_cases"]:
        name = case["name"]
        group = "gemm" if case["kind"] == "gemm" else "conv"
        relative = Path("gemmini") / group / (name + ".output.bin" if group == "gemm" else name + "/result.output.bin")
        copy(source / relative, relative)
        if group == "gemm":
            copy(source / "vta/cases" / name / "actual.bin", Path("vta/cases") / name / "actual.bin")
            row = rows[name]
            assert row["output_sha256"] == case["output_sha256"] and row["output_elements"] == case["output_elements"]
            for filename in ("actual.bin", "manifest.json", "memory.bin", "control.bin", "setup.txt",
                             "expected.bin", "expected_padded.bin", "run.log", "result.json"):
                path = coral / "service64" / name / filename
                if filename == "actual.bin": assert sha(path) == row["output_sha256"]
                elif filename in row["input_file_sha256"]:
                    assert sha(path) == row["input_file_sha256"][filename]
                copy(path, Path("coral/cases/external_staged") / name / filename)
            case["cycles"]["coral_vme"] = row["drained_cycles"]
    for case in public["nvdla_exact_cases"]:
        name = case.get("case", case.get("name"))
        relative = Path("nvdla") / name / "canonical_output.bin"
        copy(source / relative, relative)
    coral_results = {"accelerator": "Google Coral NPU VME", "source_commit": fair["source_commit"],
        "configuration": "VmeCoreMiniAxi, ITCM 8 KiB, DTCM 32 KiB, AXI128, 64-bit service per direction",
        "mode": "external", "variant": "staged", "primary_cycle_metric": "drained_cycles",
        "physical_axi_bits": 128, "effective_service_bits_per_direction": 64,
        "results": fair["results"]}
    save(out / "coral/coral_results_external_staged.json", coral_results)
    copy(coral / "fair_coral64.json", Path("coral/fair_coral64.json"))
    copy(coral / "build.json", Path("coral/build.json"))
    public["scope"] = "Public accelerator RTL with 64-bit external memory service per direction"
    public["memory"]["service_bits_per_cycle_per_direction"] = {
        name: 64 for name in ("gemmini_bird", "vta", "coral_vme", "nvdla")}
    public["memory"].pop("first_read_latency_cycles", None)
    public["memory"].pop("beats_per_cycle_per_direction", None)
    public["memory"]["first_read_service_latency_cycles"] = 8
    public["memory"]["first_full_beat_latency_cycles"] = {
        "gemmini_bird": 8, "vta": 8, "coral_vme": 9, "nvdla": 8}
    public["memory"]["coral_full_beat_service_cycles"] = 2
    public["memory"]["coral_first_full_read_latency_cycles"] = 9
    public["configuration"]["coral_vme"].update(
        physical_axi_bits=128, effective_service_bits_per_direction=64)
    public["execution"]["coral_vme"] = {
        "source_commit": fair["source_commit"], "binary_sha256": fair["binary_sha256"],
        "program_sha256": fair["program_sha256"], "build_manifest_sha256": sha(out / "coral/build.json"),
        "model_library_reused": True, "host_driver_compiled": True,
        "reused_model_inputs": building["reused_model_inputs"],
        "test_sources_sha256": building["test_sources_sha256"],
        "compiler_version": building["compiler_version"],
        "model_verilator_version": building["model_verilator_version"],
        "service_tests": fair["service_tests"], "physical_axi_bits": 128,
        "effective_service_bits_per_direction": 64}
    save(out / "coral/execution.json", public["execution"]["coral_vme"])
    public["totals"]["coral_vme"] = {"case_count": 31, "output_elements": 225375,
        "cycles": fair["coral64_cycles"], "all_outputs_match_common_reference": True,
        "service_bits_per_cycle_per_direction": 64, "service_byte_counts_checked": True}
    public["results_sha256"] = {relative: sha(out / relative) for relative in public["results_sha256"]}
    public["fair_service"] = {"coral_results_sha256": sha(out / "coral/fair_coral64.json"),
        "coral_build_sha256": sha(out / "coral/build.json"),
        "source_public_replay_sha256": fair["public_replay_summary_sha256"],
        "npu_reference_use": "Actual output byte comparison; NPU performance is measured separately",
        "collector_sha256": sha(Path(__file__)), "copied_files_sha256": copied}
    save(out / "public_replay_summary.json", public)
    lines = ["# 64 bit/周期外部存储性能比较", "",
        "读、写两个方向分别最多服务 8 字节/周期，外部内存为 2 MiB，每方向最多保持四项事务。Coral 的物理 AXI 接口为 128 位；每个 16 字节数据拍使用两个连续的 8 字节服务步骤。首次读服务发生在地址接收至少 8 周期之后，首次完整 16 字节响应最早在第 9 周期提供。", "",
        f"Coral 的 31 项共同 GEMM 全部通过，{fair['output_values']:,} 个输出值逐字节等于 NPU、Gemmini、VTA 及共同参考输出。每项同时检查完整 2 MiB 内存的输出区域之外保持不变、读写请求字节数与服务字节数相同，以及结束时没有部分数据拍或未完成响应。", "",
        f"Coral 总计 {fair['coral64_cycles']:,} 周期。同一驱动在每周期 16 字节服务配置下运行 31 项任务，总计 {fair['coral128_cycles']:,} 周期，与固定资料的逐项周期和访问数量一致。NPU 性能由完整性能工具按指定缓冲配置另行测量；本目录保存的 NPU 来源用于实际输出字节检查。", "",
        "| 用例 | Coral 周期 | 读服务字节 | 写服务字节 | 输出值数量 |",
        "|---|---:|---:|---:|---:|"]
    for row in fair["results"]:
        lines.append(f"| `{row['name']}` | {row['drained_cycles']} | {row['read_service_bytes']} | {row['write_service_bytes']} | {row['output_elements']} |")
    lines += ["", "计算配置为 64 个四乘积单元，每周期最多执行 256 个 INT8 乘加。测试直接改变外部存储服务时序，表中周期均来自 RTL 运行。复现入口为 `test/public_accelerator_fairness/run_coral_fair.py`；源码、模型库、编译命令与程序摘要保存在 `coral/build.json`，逐次执行命令和服务计数保存在 `coral/fair_coral64.json`。", ""]
    (out / "public_replay_summary.md").write_text("\n".join(lines))
    print(json.dumps({"passed": True, "coral_cases": 31, "coral_cycles": fair["coral64_cycles"],
                      "coral_output_values": fair["output_values"], "out": str(out)}))


if __name__ == "__main__":
    main()
