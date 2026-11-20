#!/usr/bin/env python3
"""逐项检查 1.2 倍性能要求，并分别保存硬件算子与模型逐层结果。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def integer(value, name):
    require(type(value) is int and value > 0, name + " 必须为正整数")
    return value


def threshold(npu, gemmini):
    """使用整数乘法比较 6*NPU 与 5*Gemmini，避免浮点舍入改变结论。"""
    npu = integer(npu, "NPU 周期")
    gemmini = integer(gemmini, "Gemmini 周期")
    limit = 5 * gemmini // 6
    return dict(npu_cycles=npu, gemmini_cycles=gemmini, speedup=gemmini / npu,
                passed=6 * npu <= 5 * gemmini, maximum_npu_cycles=limit,
                cycles_above_target=max(0, npu - limit),
                integer_check=dict(npu_times_six=6 * npu, gemmini_times_five=5 * gemmini))


def unique_rows(rows, key, label):
    result = {}
    for row in rows:
        item = key(row)
        require(item not in result, label + " 包含重复项：" + str(item))
        result[item] = row
    require(result, label + " 为空")
    return result


def measured_operator(row):
    """比较完整命令时间，并同时记录从 Gemmini 循环启动计算的时间。"""
    candidates = {name: row[name] for name in ("gemmini", "gemmini_native", "gemmini_im2col")
                  if name in row}
    require(candidates, "缺少 Gemmini 算子结果：" + row["name"])
    complete_name, complete = min(candidates.items(), key=lambda item: item[1]["cycles"])
    strict = []
    for name, value in candidates.items():
        cycles = integer(value["cycles"], "Gemmini 完整命令周期")
        launch = value.get("launch_to_complete_cycles")
        if launch is not None and launch >= 0:
            integer(launch, "Gemmini 循环启动周期")
            require(launch <= cycles, "循环启动时间超过完整命令时间")
            strict.append((launch, name, "loop_launch_to_completion"))
        else:
            strict.append((cycles, name, "complete_command"))
    strict_cycles, strict_name, interval = min(strict)
    npu = integer(row["npu"]["cycles"], "NPU 完整命令周期")
    return dict(name=row["name"], operation=row["operation"], shape=row["shape"],
                **threshold(npu, strict_cycles), gemmini_variant=strict_name,
                gemmini_interval=interval, complete_command_variant=complete_name,
                complete_command=threshold(npu, complete["cycles"]))


def summarize(rows):
    require(rows, "待检查的结果为空")
    return dict(count=len(rows), passed_count=sum(row["passed"] for row in rows),
                passed=all(row["passed"] for row in rows),
                minimum_speedup=min(row["speedup"] for row in rows),
                failed_items=[row for row in rows if not row["passed"]], items=rows)


def verified_operator_report(path, workloads):
    """读取已完成配置和数值检查的报告；性能状态始终重新计算。"""
    report = load(path)
    verified = report.get("numerical_and_configuration_passed",
                          report.get("comparison_verified"))
    require(verified is True, "输入算子报告尚未通过配置和数值检查")
    rows = report["gemm"] + report["convolution"]
    actual = unique_rows(rows, lambda row: row["name"], "算子报告")
    expected = {}
    for group in ("gemm", "conv"):
        catalogue = load(workloads / group / "workloads.json")
        for entry in catalogue["cases"]:
            require(entry["name"] not in expected, "共同算子目录包含重复名称")
            expected[entry["name"]] = entry
    require(set(actual) == set(expected), "算子报告的项目清单与共同输入不一致")
    for name, row in actual.items():
        require(row["verification"]["workload"]["sha256"] == expected[name]["manifest_sha256"],
                "算子报告与共同输入定义不一致：" + name)
    return summarize([measured_operator(row) for row in rows])


def verify_vector_resources(profile, capacity):
    """以实际实例数量和展开参数核对计算、量化及窗口并行度。"""
    instances = capacity["elaborated_state"]["module_instances"]
    require(instances.get("vector_engine") == 1, "容量报告必须包含一个向量计算模块")
    actual_pe = instances.get("vector_pe")
    integer(actual_pe, "实际向量乘累加单元数量")
    if "vector_pe_count" in profile:
        require(actual_pe == profile["vector_pe_count"], "向量乘累加单元数量与仿真配置不一致")
        vector_parameters = capacity["capability_parameters"].get("vector_engine", {})
        for parameter, field in (("PE_COUNT", "vector_pe_count"),
                                 ("QUANT_LANES", "quantization_lanes"),
                                 ("WINDOW_LANES", "window_lanes")):
            require(parameter in vector_parameters, "容量报告缺少实际向量参数：" + parameter)
            require(vector_parameters[parameter] == profile[field], "向量配置不一致：" + parameter)
        if "shared_quant_enable" in profile:
            require(vector_parameters.get("SHARED_QUANT_ENABLE") == profile["shared_quant_enable"],
                    "共享量化配置与实际展开参数不一致")
    return dict(physical_pe_count=actual_pe,
        **{key: profile[key] for key in ("quantization_lanes", "window_lanes", "shared_quant_enable") if key in profile})


def verify_cache_resources(profile, capacity):
    """核对实际行长、路数、集合数及其数据容量。"""
    parameters = capacity["capability_parameters"]["npu_top"]
    resources = {field: parameters[parameter] for parameter, field in (
        ("CONV_LINE_BYTES", "cache_line_bytes"), ("CONV_CACHE_WAYS", "cache_ways"),
        ("CONV_CACHE_SETS", "cache_sets"))}
    for field, value in resources.items():
        integer(value, field)
        if field in profile:
            require(profile[field] == value, "缓存展开参数与性能仿真不一致：" + field)
    require(resources["cache_line_bytes"] * resources["cache_ways"] * resources["cache_sets"] ==
            profile["im2col_cache_bytes"], "缓存几何参数与数据容量不一致")
    return resources


def verify_npu_build(root, capacity):
    """核对实际仿真器、编译参数和容量统计使用的 RTL 文件内容。"""
    build = load(root / "sim/build.json")
    require(build["returncode"] == 0 and build["sources_unchanged_during_build"], "NPU 构建记录无效")
    binary = root / "sim/obj/Vtb_latest_operators"
    require(binary.is_file(), "缺少 NPU 仿真器")
    require(build.get("binary_sha256") == digest(binary), "NPU 仿真器与构建记录不一致")
    profile = build["profile"]
    require(profile["size"] == 16 and profile["bus_width"] == 64 and
            profile["dma_max_bytes"] == 2048, "NPU 阵列或 DMA 配置不一致")
    require(profile["memory_timing"]["ram_read_first_latency"] == 8 and
            profile["memory_timing"]["ram_continuous_read_beat_cycles"] == 1,
            "NPU RAM 读取时序不一致")
    require(capacity["passed"] and capacity["capabilities_match"] and capacity["sources_unchanged"],
            "NPU 容量统计未通过")
    require(capacity["elaborated_state"]["total_bits"] <= 81920 * 8, "NPU 超过 80 KiB 存储上限")
    parameters = {"SIZE": "size", "NPU_AXI_DATA_WIDTH": "bus_width",
                  "SHARED_BANK_BYTES": "shared_bank_bytes", "SHARED_BANK_COUNT": "shared_bank_count",
                  "IM2COL_CACHE_BYTES": "im2col_cache_bytes", "IA_CACHE_BLOCKS": "ia_cache_blocks",
                  "PS_FRAME_COUNT": "ps_frame_count", "PS_POOL_BYTES": "ps_pool_bytes"}
    for source, field in parameters.items():
        require(capacity["configuration"][source] == profile[field], "NPU 容量配置不一致：" + source)
    require(bool(capacity["configuration"]["PS_FORCE_RAW"]) == profile["raw_only"], "部分和存储格式不一致")
    rtl_hashes = {name[name.index("rtl/"):]: value for name, value in build["source_sha256"].items()
                  if "/rtl/" in name}
    for name, value in rtl_hashes.items():
        if name.startswith("rtl/npu/"):
            require(capacity["source_sha256"].get(name) == value,
                    "容量测量与性能测量使用不同 RTL：" + name)
    # 当前 RTL 以 ASIC 定义选择共享存储的端口结构，两个统计必须展开相同结构。
    def fixed_channels(command):
        return not any(item.startswith(("-DASIC_SYNTHESIS", "-DASIC_SRAM")) for item in command)
    measured_fixed = profile.get("fixed_ps_channels", fixed_channels(build["command"]))
    capacity_fixed = capacity["capability_parameters"]["npu_top"].get(
        "p_fixed_ps_channels", fixed_channels(capacity["command"]))
    build["storage_structure_matches"] = measured_fixed == capacity_fixed
    build["storage_structure"] = dict(simulation_fixed_channels=measured_fixed,
                                       capacity_fixed_channels=capacity_fixed)
    build["vector_resources"] = verify_vector_resources(profile, capacity)
    build["cache_resources"] = verify_cache_resources(profile, capacity)
    return build


def raw_operator_report(args):
    """核对本轮运行记录、共同张量、外部 RAM 服务和各算子的完成时间。"""
    capacity = load(args.npu_capacity)
    npu_build = verify_npu_build(args.npu_results, capacity)
    gemmini_build = load(args.gemmini_build)
    require(gemmini_build["sources_unchanged_during_build"], "Gemmini 编译源文件发生变化")
    require(digest(gemmini_build["simulator"]) == gemmini_build["simulator_sha256"], "Gemmini 仿真器内容不一致")
    config = gemmini_build["configuration"]
    require(config["dma_bus_bits"] == 64 and config["dma_max_bytes"] == 2048,
            "Gemmini DMA 配置不一致")
    if args.gemmini_capacity:
        gemmini_capacity = load(args.gemmini_capacity)
        require(gemmini_capacity["passed"], "Gemmini 容量统计未通过")
        bits = gemmini_capacity.get("total_bits", gemmini_capacity.get("elaborated_state", {}).get("total_bits"))
        if bits is None:
            bits = gemmini_capacity.get("state", {}).get("total_bits")
        require(type(bits) is int and bits <= 81920 * 8, "Gemmini 容量统计缺失或超过 80 KiB")
        generated = Path(gemmini_build["generated_rtl"]).name
        rtl_hashes = [value for name, value in gemmini_capacity["source_sha256"].items()
                      if Path(name).name == generated]
        require(rtl_hashes == [gemmini_build["generated_rtl_sha256"]],
                "Gemmini 容量统计与性能测量使用不同 RTL")
    required_memory = {"first_read_latency_cycles": 8, "read_beat_interval_cycles": 1,
                       "inter_burst_read_gap_cycles": 1, "read_outstanding_limit": 4,
                       "write_outstanding": 4, "physical_memory_bytes": 2097152}
    for key, value in required_memory.items():
        require(gemmini_build["memory_service"][key] == value, "Gemmini RAM 服务不一致：" + key)
    results = []
    for group in ("gemm", "conv"):
        catalogue = load(args.workloads / group / "workloads.json")
        expected = unique_rows(catalogue["cases"], lambda row: row["name"], group + " 输入目录")
        npu_summary = load(args.npu_results / group / "summary.json")
        require(npu_summary["passed"] and npu_summary["profile"] == npu_build["profile"], "NPU 算子组检查未通过")
        require(npu_summary["binary_sha256"] == npu_build["binary_sha256"], "NPU 算子组仿真器内容不一致")
        npu = unique_rows(npu_summary["cases"], lambda row: row["name"], "NPU " + group)
        require(set(npu) == set(expected), "NPU 算子清单不完整或包含额外项目：" + group)
        names = ["gemmini"] if group == "gemm" else ["gemmini_native", "gemmini_im2col"]
        references = {}
        for name in names:
            directory = "operators_gemm" if group == "gemm" else "operators_conv_" + name.removeprefix("gemmini_")
            summary = load(args.gemmini_results / directory / "results.json")
            require(summary["build_manifest_sha256"] == digest(args.gemmini_build), "Gemmini 构建身份不一致")
            references[name] = unique_rows(summary["cases"], lambda row: row["name"], name)
            require(set(references[name]) == set(expected), "Gemmini 算子清单不完整或包含额外项目：" + name)
        for name, entry in expected.items():
            manifest_path = args.workloads / group / entry["manifest"]
            require(digest(manifest_path) == entry["manifest_sha256"], "输入算子定义发生变化：" + name)
            manifest = load(manifest_path)
            hashes = {key: value["sha256"] for key, value in manifest["tensors"].items()}
            for tensor in manifest["tensors"].values():
                require(digest(manifest_path.parent / tensor["path"]) == tensor["sha256"], "输入张量发生变化：" + name)
            row = npu[name]
            require(row["passed"] and row["returncode"] == 0, "NPU 算子未通过：" + name)
            require(row["workload_manifest_sha256"] == entry["manifest_sha256"] and
                    row["input_tensor_sha256"] == hashes, "NPU 输入张量不一致：" + name)
            require(row["observed_output_sha256"] == hashes["c_s8"], "NPU 输出不一致：" + name)
            case = args.npu_results / group / "cases" / name
            for filename, expected_hash in row["files"].items():
                require(digest(case / filename) == expected_hash, "NPU 仿真输入发生变化：" + filename)
            log = (case / "run.log").read_text()
            require("COMMON_OPERATOR_PASS" in log, "NPU 日志缺少成功记录：" + name)
            timing = row["timing"]
            cycles = row["measurement"]["cycles"]
            require(cycles == timing["done"] and timing["read_latency_min"] >= 8, "NPU 计时不一致：" + name)
            require(timing["read_outstanding_max"] <= 4 and timing["write_outstanding_max"] <= 4,
                    "NPU 未完成事务数超出上限")
            require(row["measurement"]["ar_bytes"] == timing["read_beats"] * 8, "NPU 读取拍数不一致")
            if "vector_pe_count" in npu_build["profile"]:
                expected_vector = dict(pe_count=npu_build["profile"]["vector_pe_count"],
                    quantization_lanes=npu_build["profile"]["quantization_lanes"],
                    window_lanes=npu_build["profile"]["window_lanes"])
                if "shared_quant_enable" in npu_build["profile"]:
                    expected_vector["shared_quant_enable"] = npu_build["profile"]["shared_quant_enable"]
                require(row.get("observed_vector") == expected_vector,
                        "测试台实际向量参数与构建配置不一致：" + name)
            if "cache_line_bytes" in npu_build["profile"]:
                expected_cache = {key: npu_build["profile"][key] for key in (
                    "cache_line_bytes", "cache_sets", "cache_ways")}
                require(row.get("observed_cache") == expected_cache,
                        "测试台实际缓存参数与构建配置不一致：" + name)
            shape = {key: row[key] for key in ("m", "n", "k")} if group == "gemm" else row["conv"]
            combined = dict(name=name, operation="gemm" if group == "gemm" else manifest["operator"],
                            shape=shape, npu=dict(cycles=cycles))
            for variant, values in references.items():
                value = values[name]
                require(value["passed"] and value["output_mismatches"] == 0 and
                        value["outside_output_mismatches"] == 0, "Gemmini 输出检查未通过：" + name)
                require(value["workload_manifest_sha256"] == entry["manifest_sha256"] and
                        value["expected_output_sha256"] == hashes["c_s8"], "Gemmini 输入或输出规格不一致：" + name)
                require(value["axi_data_bits"] == 64 and value["read_latency_min"] >= 8 and
                        value["max_read_outstanding_observed"] <= 4 and
                        value["max_write_outstanding_observed"] <= 4, "Gemmini 接口计时不一致")
                if group == "gemm":
                    output = args.gemmini_results / "operators_gemm" / (name + ".output.bin")
                else:
                    output = args.gemmini_results / ("operators_conv_" + variant.removeprefix("gemmini_")) / name / "result.output.bin"
                require(digest(output) == hashes["c_s8"], "Gemmini 实际输出内容不一致：" + name)
                if manifest.get("operator") == "depthwise":
                    require(value["loop_depthwise_launches"] > 0 and value["dwconv_active_cycles"] > 0,
                            "Gemmini 未执行 DW 专用数据流：" + name)
                combined[variant] = value
            result = measured_operator(combined)
            result.update(npu_read_bytes=row["measurement"]["ar_bytes"],
                          npu_write_bytes=row["measurement"]["write_bytes"],
                          npu_read_requests=row["measurement"]["ar_requests"],
                          npu_write_requests=timing["write_commands"],
                          workload_manifest_sha256=entry["manifest_sha256"])
            results.append(result)
    report = summarize(results)
    report["npu_storage_bytes"] = capacity["elaborated_state"]["total_bits"] / 8
    report["npu_source_commit"] = npu_summary["source_commit"]
    report["npu_binary_sha256"] = npu_build["binary_sha256"]
    report["gemmini_binary_sha256"] = gemmini_build["simulator_sha256"]
    report["configuration_checked"] = npu_build["storage_structure_matches"] and args.gemmini_capacity is not None
    report["storage_structure"] = npu_build["storage_structure"]
    report["vector_resources"] = npu_build["vector_resources"]
    report["cache_resources"] = npu_build["cache_resources"]
    report["pending_checks"] = []
    if not npu_build["storage_structure_matches"]:
        report["pending_checks"].append("NPU 容量统计与性能仿真必须使用相同的共享存储端口结构")
    if args.gemmini_capacity is None:
        report["pending_checks"].append("需要提供与生成 RTL 相同版本的 Gemmini 容量统计")
    return report


def model_report(path, prepared):
    """逐个模型输入检查全部节点，保留 RESHAPE 等软件执行节点。"""
    report = load(path)
    require(report["passed"] and report["verification"]["passed"] and
            report["verification"]["complete_suite"], "模型结果尚未完成配置与输出检查")
    expected = {}
    for manifest_path in sorted(prepared.glob("*/manifest.json")):
        manifest = load(manifest_path)
        for sample in manifest["samples"]:
            for node in manifest["graph"]["nodes"]:
                key = manifest["name"], sample["sample_index"], node["index"]
                require(key not in expected, "模型参考数据包含重复输入或节点：" + str(key))
                expected[key] = node
    require(expected, "模型目录没有参考节点")
    rows = unique_rows(report["layer_samples"], lambda row: (row["model"], row["sample"], row["index"]), "模型逐层结果")
    require(set(rows) == set(expected), "模型输入或节点清单不完整")
    variants = list(report["variants"])
    require(variants and "native" in variants, "缺少 Gemmini native 固件结果")
    sample_results = []
    grouped = defaultdict(list)
    for key, row in sorted(rows.items()):
        node = expected[key]
        for field in ("op", "input_shapes", "output_shapes", "options"):
            require(row[field] == node[field], "模型节点定义不一致：" + str(key))
        require(row["output_exact"], "模型节点输出不一致：" + str(key))
        npu = integer(row["npu"]["cycles"], "逐层 NPU 周期")
        choices = [(integer(row[name]["cycles"], "逐层 Gemmini 周期"), name) for name in variants]
        gemmini, variant = min(choices)
        sample_results.append(dict(model=key[0], sample=key[1], index=key[2], operation=node["op"],
                                   gemmini_variant=variant, **threshold(npu, gemmini)))
        grouped[(key[0], key[2])].append(row)
    layer_results = []
    for (model, index), values in sorted(grouped.items()):
        npu = sum(row["npu"]["cycles"] for row in values)
        gemmini, variant = min((sum(row[name]["cycles"] for row in values), name) for name in variants)
        per_input = [row for row in sample_results if (row["model"], row["index"]) == (model, index)]
        measured = threshold(npu, gemmini)
        measured["aggregate_passed"] = measured["passed"]
        measured["minimum_sample_speedup"] = min(row["speedup"] for row in per_input)
        measured["passed"] = measured["passed"] and all(row["passed"] for row in per_input)
        layer_results.append(dict(model=model, index=index, operation=values[0]["op"], samples=len(values),
                                  gemmini_variant=variant, **measured))
    result = summarize(layer_results)
    result["sample_results"] = summarize(sample_results)
    result["minimum_sample_speedup"] = result["sample_results"]["minimum_speedup"]
    result["passed"] = result["passed"] and result["sample_results"]["passed"]
    result["cycle_definition"] = "逐层记录固件的实际经过周期；层汇总使用相同输入的整数周期之和"
    result["selection_definition"] = "逐层选取最快 Gemmini 固件结果；此选择只用于逐层要求，不重建整网时间"
    return result


def write_outputs(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    columns = ["group", "name", "model", "index", "operation", "sample", "samples", "npu_cycles", "gemmini_cycles",
               "speedup", "minimum_sample_speedup", "passed", "aggregate_passed",
               "maximum_npu_cycles", "cycles_above_target", "gemmini_variant"]
    with path.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore")
        writer.writeheader()
        for group in ("operators", "model_layers"):
            for row in result.get(group, {}).get("items", []):
                writer.writerow(dict(group=group, **row))
        for row in result.get("model_layers", {}).get("sample_results", {}).get("items", []):
            writer.writerow(dict(group="model_layer_samples", **row))
    lines = ["# 逐层性能检查", "", "目标加速比为 1.2，采用整数条件 `6 × NPU 周期 ≤ 5 × Gemmini 周期`。", "",
             "| 测量范围 | 项数 | 达标项数 | 最小加速比 | 全部达标 |", "| --- | ---: | ---: | ---: | --- |"]
    for group, title in (("operators", "独立硬件算子"), ("model_layers", "完整模型逐层记录")):
        if group not in result:
            continue
        value = result[group]
        lines.append(f"| {title} | {value['count']} | {value['passed_count']} | {value['minimum_speedup']:.6f}× | {'是' if value['passed'] else '否'} |")
        if "sample_results" in value:
            sample = value["sample_results"]
            lines.append(f"| 完整模型逐层记录（逐输入） | {sample['count']} | {sample['passed_count']} | {sample['minimum_speedup']:.6f}× | {'是' if sample['passed'] else '否'} |")
    for group in ("operators", "model_layers"):
        for item in result.get(group, {}).get("pending_checks", []):
            lines += ["", "待完成配置检查：" + item + "。"]
    lines += ["", "## 逐项结果", "", "| 范围 | 项目 | NPU 周期 | Gemmini 周期 | 加速比 | 达标 | 仍需减少周期 |",
              "| --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for group in ("operators", "model_layers"):
        for row in result.get(group, {}).get("items", []):
            name = row.get("name", f"{row.get('model')} node {row.get('index')}")
            lines.append(f"| {group} | {name} | {row['npu_cycles']} | {row['gemmini_cycles']} | {row['speedup']:.6f}× | {'是' if row['passed'] else '否'} | {row['cycles_above_target']} |")
    failures = result.get("model_layers", {}).get("sample_results", {}).get("failed_items", [])
    if failures:
        lines += ["", "## 未达到要求的模型输入", "",
                  "| 模型 | 节点 | 输入 | NPU 周期 | Gemmini 周期 | 加速比 | 仍需减少周期 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row in failures:
            lines.append(f"| {row['model']} | {row['index']} | {row['sample']} | {row['npu_cycles']} | {row['gemmini_cycles']} | {row['speedup']:.6f}× | {row['cycles_above_target']} |")
    lines += ["", "独立硬件算子计时包括传输、计算和写回；同时计算 Gemmini 完整命令与循环启动后的结果，采用较严格值检查。",
              "模型层汇总使用同一层全部输入的整数周期之和；层是否达标同时检查每个输入。RESHAPE 节点保留在结果中。", ""]
    path.with_suffix(".md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-report", type=Path, help="已验证的独立算子比较报告")
    parser.add_argument("--npu-results", type=Path, help="本轮 run_storage_operators.py 输出目录")
    parser.add_argument("--gemmini-results", type=Path)
    parser.add_argument("--workloads", type=Path)
    parser.add_argument("--npu-capacity", type=Path)
    parser.add_argument("--gemmini-capacity", type=Path)
    parser.add_argument("--gemmini-build", type=Path)
    parser.add_argument("--model-report", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not any((args.operator_report, args.npu_results, args.model_report)):
        parser.error("至少提供一组算子或模型结果")
    if args.operator_report and args.npu_results:
        parser.error("算子汇总报告与原始结果只能选择一种输入方式")
    if args.operator_report and not args.workloads:
        parser.error("算子报告检查需要 --workloads 提供完整共同输入清单")
    if args.npu_results and not all((args.gemmini_results, args.workloads, args.npu_capacity, args.gemmini_build)):
        parser.error("原始算子检查需要双方结果、共同输入、NPU 容量与 Gemmini 构建记录")
    if args.model_report and not args.prepared:
        parser.error("模型检查需要 --prepared 提供完整参考节点清单")
    result = dict(format_version=1, required_speedup="6/5", input_checks_passed=True,
                  generator_sha256=digest(__file__))
    if args.operator_report:
        result["operators"] = verified_operator_report(args.operator_report, args.workloads)
    elif args.npu_results:
        result["operators"] = raw_operator_report(args)
    if args.model_report:
        result["model_layers"] = model_report(args.model_report, args.prepared)
    result["input_checks_passed"] = all(value.get("configuration_checked", True) for name, value in result.items()
                                       if name in ("operators", "model_layers"))
    result["passed"] = result["input_checks_passed"] and all(value["passed"] for name, value in result.items()
                                                           if name in ("operators", "model_layers"))
    result["sources"] = {name: dict(path=str(value.resolve()), sha256=digest(value))
                         for name, value in vars(args).items()
                         if name != "out" and isinstance(value, Path) and value.is_file()}
    write_outputs(args.out, result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("operators", "model_layers", "sources")}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
