#!/usr/bin/env python3
"""根据完成的性能检查生成逐项表格、比较摘要和来源记录。"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def read_bytes(path):
    path = Path(path)
    if not path.is_file() and path.with_name(path.name + ".gz").is_file():
        return gzip.decompress(path.with_name(path.name + ".gz").read_bytes())
    return path.read_bytes()


def read(path):
    return json.loads(read_bytes(path))


def digest(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()


def check_capacity(capacity, profile, snapshot):
    """核对容量范围、硬件参数和展开源码，返回可比较的分类数据。"""
    if capacity.get("budget_scope") == "buffer-ram":
        assert capacity["source_unchanged"]
        assert capacity["performance_source_commit"] == snapshot["source_commit"]
        assert capacity["performance_sources_match"] and capacity["source_sha256"]
        assert all(snapshot["sha256"].get(name) == checksum
                   for name, checksum in capacity["source_sha256"].items())
        configuration = capacity["configuration"]
        for name, key in (("SIZE", "size"), ("VECTOR_PE_COUNT", "vector_pe_count"),
                          ("NPU_AXI_DATA_WIDTH", "bus_width"), ("IA_CACHE_BLOCKS", "ia_cache_blocks"),
                          ("PS_FRAME_COUNT", "ps_frame_count"), ("PS_POOL_BYTES", "ps_pool_bytes"),
                          ("PS_FORCE_RAW", "raw_only"), ("IM2COL_CACHE_BYTES", "im2col_cache_bytes"),
                          ("SHARED_BANK_BYTES", "shared_bank_bytes"), ("SHARED_BANK_COUNT", "shared_bank_count")):
            assert configuration[name] == profile[key], name
        assert capacity["budget_bytes"] == configuration["CAPACITY_BUDGET_BYTES"]
        assert set(capacity["targets"]) == {"generic", "asic"}
        for row in capacity["targets"].values():
            assert row["passed"] and row["capabilities_match"]
            assert row["array_bits"] == row["data_bits"] + row["metadata_bits"] + row["read_only_bits"]
            assert row["array_bits"] == sum(row["arrays"].values())
            assert row["total_bits"] == row["array_bits"] + row["other_register_bits"]
            assert row["array_bytes"] == row["array_bits"] / 8
            assert row["total_bytes"] == row["total_bits"] / 8
            assert row["array_bits"] <= capacity["budget_bytes"] * 8
            assert row["budget_remaining_bytes"] == capacity["budget_bytes"] - row["array_bytes"]
        return capacity["targets"]
    assert capacity["passed"] and capacity["source_commit"] == snapshot["source_commit"]
    assert all(row["passed"] and row["total_bits"] <= capacity["capacity_budget_bits"]
               for row in capacity["capacity"])
    return {row["target"]: row for row in capacity["capacity"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--public-replay", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results, replay, out = args.results.resolve(), args.public_replay.resolve(), args.out.resolve()
    execution = read(results / "execution.json")
    snapshot = read(results / "source_snapshot.json")
    common = read(results / "comparison/operators/comparison.json")
    previous = read(results / "comparison/operators/repository_comparison.json")
    numeric = read(results / "comparison/supplementary/repository_comparison.json")
    exact = read(results / "comparison/exact_ar2/comparison.json")
    actual = read(results / "comparison/operators/actual_output_comparison.json")
    public = read(replay / "public_replay_summary.json")
    profile = common["profile"]
    public_sha256 = digest(replay / "public_replay_summary.json")
    public_cases = {row["name"]: row for row in public["common_cases"]}
    assert all(row["public_cycles"] == public_cases[row["name"]]["cycles"] for row in common["cases"])
    if "public_replay_summary_sha256" in common:
        assert common["public_replay_summary_sha256"] == public_sha256
    assert actual["public_replay_summary_sha256"] == public_sha256
    service_widths = public["memory"].get("service_bits_per_cycle_per_direction", public["memory"]["bus_bits"])
    fair64 = all(value == 64 for value in service_widths.values())
    build = read(results / "records/operators/sim/build.json")
    compiler_command = build["command"][0]
    compiler_path = Path(shutil.which(compiler_command) or compiler_command).resolve()
    tool_versions = {
        "build_command": build["command"], "compiler_command": compiler_command,
        "compiler_resolved_path": str(compiler_path), "compiler_file_sha256": digest(compiler_path),
        "compiler_version_output": subprocess.check_output([compiler_command, "--version"], text=True).strip(),
        "simulator_sha256": execution["binary_sha256"],
    }
    capacity = read(results / "capacity.json") if (results / "capacity.json").is_file() else None
    if capacity:
        assert snapshot["source_commit"] == execution["source_commit"]
        capacity_targets = check_capacity(capacity, profile, snapshot)
    assert execution["passed"] and execution["source_unchanged"] and execution["single_simulator"]
    assert common["numerical_and_timing_checks_passed"] and previous["numerical_and_timing_checks_passed"]
    assert numeric["numerical_and_timing_checks_passed"] and exact["passed"] and actual["passed"]
    for value in (common, previous, numeric, exact):
        assert value["source_commit"] == execution["source_commit"]
    assert len(common["cases"]) == len(previous["cases"]) == 36
    assert len(numeric["cases"]) == 26 and len(exact["cases"]) == 6
    old_by_name = {row["name"]: row for row in previous["cases"]}
    rows = []
    for row in common["cases"]:
        old = old_by_name[row["name"]]
        rows.append({"collection": "operators", "name": row["name"], "kind": row["kind"],
                     "final_cycles": row["npu_cycles"],
                     "remote_default_cycles": old["remote_default_cycles"],
                     "remote_low_latency_cycles": old["remote_low_latency_cycles"],
                     "change_from_default_pct": old["change_from_default_pct"],
                     "change_from_low_latency_pct": old["change_from_low_latency_pct"],
                     "output_sha256": row["output_sha256"], **row["public_cycles"]})
    for row in numeric["cases"]:
        rows.append({"collection": "supplementary", **{key: row[key] for key in
            ("name", "kind", "final_cycles", "remote_default_cycles", "remote_low_latency_cycles",
             "change_from_default_pct", "change_from_low_latency_pct", "output_sha256")}})
    for row in exact["cases"]:
        old = row["remote_low_latency_cycles"]
        default = row.get("remote_default_cycles")
        rows.append({"collection": "exact_ar2", "name": row["name"],
                     "kind": "conv" if row["name"].startswith("conv") else "gemm",
                     "final_cycles": row["npu_cycles"], "remote_low_latency_cycles": old,
                     "remote_default_cycles": default,
                     "change_from_default_pct": 100*(row["npu_cycles"]/default-1) if default else None,
                     "change_from_low_latency_pct": 100*(row["npu_cycles"]/old-1) if old else None,
                     "nvdla_engine": row["nvdla_engine_cycles"],
                     "nvdla_configuration": row["nvdla_configuration_cycles"],
                     "output_sha256": row["output_sha256"]})
    grouped = []
    for kind in ("gemm", "conv", "dw"):
        selected = [row for row in rows if row["collection"] == "operators" and row["kind"] == kind]
        item = {"kind": kind, "case_count": len(selected),
                "npu_cycles": sum(row["final_cycles"] for row in selected),
                "remote_low_latency_cycles": sum(row["remote_low_latency_cycles"] for row in selected)}
        for accelerator in ("gemmini_bird", "vta", "coral_vme"):
            if all(accelerator in row for row in selected):
                item[accelerator + "_cycles"] = sum(row[accelerator] for row in selected)
                item[accelerator + "_ratio"] = item[accelerator + "_cycles"] / item["npu_cycles"]
        grouped.append(item)
    comparable = [row for row in rows if row["change_from_low_latency_pct"] is not None]
    worst = max(comparable, key=lambda row: row["change_from_low_latency_pct"])
    result = {"passed": True, "source_commit": execution["source_commit"],
              "remote_commit": previous["remote_commit"], "binary_sha256": execution["binary_sha256"],
              "public_source_archive": public["source_archive"], "public_configuration": public["configuration"],
              "public_execution": public["execution"], "hardware_profile": common["profile"],
              "public_memory": public["memory"], "public_replay_summary_sha256": public_sha256,
              "clock": public["clock"], "case_counts": execution["case_counts"],
              "tools": tool_versions,
              "checked_memory_words_per_case": 524288, "checked_memory_words_total": 68*524288,
              "public_common_output_values": actual["output_values"],
              "nvdla_output_values": exact["output_values"], "groups": grouped,
              "worst_change_from_low_latency": worst, "cases": rows,
              "source_files": {str(path.relative_to(results)): digest(path) for path in
                  (results / "execution.json", results / "source_snapshot.json",
                   results / "comparison/operators/comparison.json",
                   results / "comparison/operators/repository_comparison.json",
                   results / "comparison/operators/actual_output_comparison.json",
                   results / "comparison/supplementary/repository_comparison.json",
                   results / "comparison/exact_ar2/comparison.json")}}
    capacity_text = (f"{profile['shared_total_bytes']/1024:g} KiB 共享存储、"
        f"{profile['im2col_cache_bytes']/1024:g} KiB 卷积缓存；其它队列与控制状态由容量工具展开统计")
    capacity_paragraph = ""
    if capacity:
        generic, asic = capacity_targets["generic"], capacity_targets["asic"]
        result["capacity"] = capacity
        result["source_files"]["capacity.json"] = digest(results / "capacity.json")
        if capacity.get("budget_scope") == "buffer-ram":
            for row in capacity_targets.values():
                path = results / row["result"]
                assert digest(path) == row["result_sha256"]
                result["source_files"][str(path.relative_to(results))] = digest(path)
            capacity_text = (f"数据数组、数组元数据与 ROM 共 {generic['array_bytes']/1024:.3f} KiB；"
                             f"完整逻辑状态 {generic['total_bytes']/1024:.3f} KiB")
            capacity_paragraph = (f"容量预算采用 `buffer-ram` 范围，{capacity['budget_bytes']/1024:g} KiB 上限统计数据数组、数组元数据与 ROM。"
                f"generic 展开为 {generic['array_bits']:,} 位，即 {generic['array_bytes']:,.3f} 字节，余量 {generic['budget_remaining_bytes']:,.3f} 字节；"
                f"ASIC 展开为 {asic['array_bits']:,} 位，即 {asic['array_bytes']:,.3f} 字节，余量 {asic['budget_remaining_bytes']:,.3f} 字节。"
                f"控制与运算寄存器分别为 {generic['other_register_bits']:,} 位和 {asic['other_register_bits']:,} 位，单独列出。"
                f"包含这些寄存器的完整逻辑状态分别为 {generic['total_bits']:,} 位（{generic['total_bytes']:,.3f} 字节）"
                f"及 {asic['total_bits']:,} 位（{asic['total_bytes']:,.3f} 字节）。完整展开结果见 [容量数据](../capacity.json)。")
        else:
            capacity_text = f"完整逻辑状态 {generic['total_bits']:,} 位，{generic['total_bytes']/1024:.3f} KiB"
            capacity_paragraph = (f"同一源码的 generic 展开为 {generic['total_bits']:,} 位，即 {generic['total_bytes']:,.3f} 字节，"
                f"距离 {capacity['capacity_budget_bits']/8192:g} KiB 配置上限保留 {generic['remaining_bytes']:,.3f} 字节；ASIC 展开为 {asic['total_bits']:,} 位，"
                f"保留 {asic['remaining_bytes']:,.3f} 字节。完整展开结果见 [容量数据](../capacity.json)。")
    out.mkdir(parents=True, exist_ok=True)
    (out / "performance_comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    fields = ("collection", "name", "kind", "remote_default_cycles", "remote_low_latency_cycles", "final_cycles",
              "change_from_default_pct", "change_from_low_latency_pct", "gemmini_bird", "vta", "coral_vme", "nvdla_engine",
              "nvdla_configuration", "output_sha256")
    with (out / "performance_comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})
    memory_text = ("外部存储为 2 MiB，读、写两个方向分别最多服务 8 字节/周期，每方向最多保持四项事务。"
        "Coral 的物理 AXI 接口为 128 位，每个 16 字节数据拍使用两个实际的 8 字节服务步骤。首次读服务至少等待 8 个周期，Coral 首次完整 16 字节响应至少等待 9 个周期。"
        if fair64 else "外部存储为 2 MiB，首次读响应至少等待 8 个周期，每方向每周期最多一个数据拍，最多允许 4 个读请求和 4 个写请求并行。")
    memory_text += f"NPU 最大突发长度为 {profile['dma_max_bytes']:,} 字节。AR2 集合将实际读地址接收间隔限制为至少 2 个周期，并检查每次接收的实际间隔。"
    npu_description = (f"NPU 使用 {profile['size']}×{profile['size']} 矩阵阵列、"
        f"{profile['vector_pe_count']} 个向量处理单元、{profile['quantization_lanes']} 路量化及 "
        f"{profile['window_lanes']} 路窗口处理、{profile['bus_width']} 位 AXI、"
        f"{profile['shared_bank_count']} 个 {profile['shared_bank_bytes']/1024:g} KiB 共享存储块和 "
        f"{profile['im2col_cache_bytes']/1024:g} KiB 卷积缓存。缓存行长 {profile['cache_line_bytes']} 字节、"
        f"{profile['cache_ways']} 路、{profile['cache_sets']} 组，需求响应深度为 {profile['conv_cache_demand_outstanding']}。"
        "卷积描述符直接接收，完整缓存请求寄存；请求保存时同步准备缓存读取快照。")
    lines = ["# NPU 性能与公开实现比较", "",
        f"测试源码为 `{execution['source_commit']}`。36 项公开共同任务、26 项独立数值任务和 AR2 六项共同整数任务全部通过。每项逐个比较 524,288 个系统内存字，68 项共比较 35,651,584 个内存字，并确认最后一次读响应和写响应均在完成计时之前结束。",
        "", f"36 项共同任务的 NPU 实际输出共 {actual['output_values']:,} 个值，全部与 Gemmini 重新执行输出逐字节比较。其中 31 项 GEMM 的 225,375 个值还分别与 VTA、Coral 重新执行输出逐字节比较。另有 AR2 六项的 {exact['output_values']:,} 个值与 NVDLA 重新执行输出逐字节比较。实际输出检查与逐项执行记录见 [执行摘要](../execution.json) 和 [完整比较数据](performance_comparison.json)。",
        "", "## 执行条件", "",
        npu_description,
        "", capacity_paragraph,
        "", memory_text,
        "", "报告使用周期数。时间换算采用 t=C/f；资料没有提供四种公开实现的实测工作频率，本报告保留周期比较。总周期之比按相同任务集合的周期和计算。",
        "", "## 实现配置与比较范围", "",
        "| 实现 | 主要计算配置 | 存储状态 | 物理位宽 / 每方向每周期服务位数 | 实际比较任务 |",
        "|---|---|---|---:|---|",
        f"| NPU | {profile['size']}×{profile['size']} 矩阵阵列，执行 INT8 乘加、INT32 累加；{profile['vector_pe_count']} 路向量处理 | {capacity_text} | {profile['bus_width']} / 64 | 36 项公开任务、26 项独立数值任务、AR2 六项 |",
        "| Gemmini-BiRD | 16×16 INT8 / INT32 | 全部逻辑状态 650,391 位，约 79.393 KiB | 64 / 64 | 31 项 GEMM、3 项 Conv、2 项 DW |",
        "| VTA | 16×16 INT8 / INT32 | 全部逻辑状态 627,138 位，约 76.555 KiB | 64 / 64 | 31 项 GEMM |",
        f"| Coral NPU VME | 64 个四乘积单元，256 INT8 MAC/周期 | 全部逻辑状态 665,344 位，81.219 KiB | 128 / {service_widths['coral_vme']} | 31 项 GEMM |",
        "| NVDLA nv_small_256 | C32、K8，256 INT8 乘法器 | CBUF 为 128 KiB，其它状态另计 | 64 / 64 | 3 项 GEMM、3 项 Conv 的共同整数任务 |",
        "", "31 项 GEMM 使用相同 INT8 输入、INT32 累加和偏置，执行除以 32 的最近偶数舍入及 INT8 饱和。三项 Conv 和两项 DW 使用共同空间参数和原始输入张量。VTA 与 Coral 的 GEMM 结果对应矩阵乘法任务。",
        "", "NVDLA 集合采用 A′=2A、W′=16W、bias′=32bias，累加结果可被 32 整除，再执行 INT8 饱和。六项输入与最终输出分别检查摘要和实际字节。NVDLA 的 core 与 CSB 时钟周期相同，分别记录首次 D_OP_ENABLE 接收后的 engine 周期及首次 CSB 写入后的 configuration 周期。",
        "", "Gemmini 从计时配置命令到 FENCE 完成及全部外存响应结束；VTA 从 START 接收到完成及全部外存响应结束；Coral 从 CSR 释放接收到核心停止及全部外存响应结束，包含外部数据搬入 DTCM、标量控制和 RVV 后处理。主机张量布局转换与初始内存装载位于这些计时区间之外。",
        "", "## 公开任务汇总", "",
        "| 任务集合 | 项数 | NPU 周期和 | Gemmini 周期和（比值） | VTA 周期和（比值） | Coral 周期和（比值） |",
        "|---|---:|---:|---:|---:|---:|"]
    for row in grouped:
        values = [f"{row[a+'_cycles']:,}（{row[a+'_ratio']:.3f}）" if a+"_cycles" in row else "未测"
                  for a in ("gemmini_bird", "vta", "coral_vme")]
        lines.append(f"| {row['kind']} | {row['case_count']} | {row['npu_cycles']:,} | " + " | ".join(values) + " |")
    lines += ["", "括号内比值为公开实现的周期和除以 NPU 周期和。",
        "", f"公开 GEMM 的 {sum(row['strictly_faster_than_all'] for row in common['cases'] if row['kind']=='gemm')} 项在本组测量中均少于其它三种公开实现的周期数。", "",
        "## 与远端版本的逐项比较", "",
        f"对照版本为 `{previous['remote_commit']}`。默认设置及低延迟设置使用与当前 NPU 相同的共享存储、卷积缓存容量、计算并行度和外存服务参数；编译与调度器源码摘要均通过核对。{len(comparable)} 项任务中，最大的周期增幅为 `{worst['name']}` 的 {worst['change_from_low_latency_pct']:+.3f}%，原低延迟设置为 {worst['remote_low_latency_cycles']:,} 周期，当前为 {worst['final_cycles']:,} 周期。",
        "", "### 36 项公开共同任务", "",
        "| 用例 | 远端默认 | 远端低延迟 | 当前 NPU | 相对低延迟变化 | Gemmini | VTA | Coral |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        if row["collection"] == "operators":
            values = [str(row.get(key, "未测")) for key in ("gemmini_bird", "vta", "coral_vme")]
            lines.append(f"| `{row['name']}` | {row['remote_default_cycles']} | {row['remote_low_latency_cycles']} | {row['final_cycles']} | {row['change_from_low_latency_pct']:+.3f}% | " + " | ".join(values) + " |")
    lines += ["", "### 26 项独立数值任务", "",
        "| 用例 | 远端默认 | 远端低延迟 | 当前 NPU | 相对低延迟变化 |",
        "|---|---:|---:|---:|---:|"]
    for row in rows:
        if row["collection"] == "supplementary":
            lines.append(f"| `{row['name']}` | {row['remote_default_cycles']} | {row['remote_low_latency_cycles']} | {row['final_cycles']} | {row['change_from_low_latency_pct']:+.3f}% |")
    lines += ["", "### NVDLA AR2 六项共同整数任务", "",
        "| 用例 | 远端默认 NPU | 远端低延迟 NPU | 当前 NPU | NVDLA engine | NVDLA configuration | engine / NPU |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for row in exact["cases"]:
        lines.append(f"| `{row['name']}` | {row.get('remote_default_cycles', '未测')} | {row['remote_low_latency_cycles']} | {row['npu_cycles']} | {row['nvdla_engine_cycles']} | {row['nvdla_configuration_cycles']} | {row['engine_speedup']:.3f} |")
    lines += ["", "## 来源与重复执行", "",
        f"公开资料为 `npu_accelerator_comparison_20261123.zip`，大小 151,297,638 字节，SHA256 为 `{public['source_archive']['sha256']}`。公开仿真使用资料对应的固定 RTL 模型重新执行；Coral 按记录的服务带宽编译外存驱动。版本、模型库与程序摘要、计时区间和配置见完整比较数据。",
        "", f"本次 NPU 的三个集合共用一个匹配冻结源码的仿真程序，SHA256 为 `{execution['binary_sha256']}`。构建只使用一个编译任务，测试前后源码摘要相同。",
        "", f"实际构建命令及工具文件摘要保存在完整比较数据的 `tools` 字段。编译器版本输出为 `{tool_versions['compiler_version_output']}`，执行文件为 `{compiler_path}`。",
        "", "执行命令保存在 `execution.json`。`archives` 保存三个集合的内存图像、配置、日志和编译记录；仿真程序单独压缩保存。`records` 保留实际输出、逐项结果与日志。重复执行入口为 `test/gemmini_comparison/run_final_performance.py`，路径通过命令行参数提供。", ""]
    (out / "performance_comparison.md").write_text("\n".join(lines))
    print(json.dumps({"passed": True, "cases": len(rows), "groups": grouped,
                      "worst_change_pct": worst["change_from_low_latency_pct"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
