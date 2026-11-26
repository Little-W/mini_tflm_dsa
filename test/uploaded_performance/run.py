#!/usr/bin/env python3
"""运行上传环境的 68 项任务，核对实际输出并保存相对 449e3fe4 的逐字段性能比较。"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile


PIPELINE_KEYS = {
    "conv_cache_demand_outstanding", "conv_register_descriptor",
    "conv_register_row_address", "conv_register_cache_request",
}
LOG_FIELDS = {
    "COMMON_OPERATOR_PASS": "measurement", "COMMON_TIMING": "timing",
    "COMMON_SCHEDULE": "observed_schedule", "COMMON_AR_INTERVAL": "observed_ar_interval",
    "COMMON_HARDWARE": "observed_hardware", "COMMON_VECTOR": "observed_vector",
    "COMMON_CACHE": "observed_cache",
}
PROFILE_PREFIXES = (
    "VECTOR_DW_PROFILE", "CONV_FRONTEND_PROFILE", "CONV_FRONTEND_IDLE",
    "CONV_FRONTEND_STATE", "[NPU_CTRL_UTIL]", "[NPU_CTRL_UTIL_SUMMARY]", "[NPU_UTIL]",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def source_snapshot(root, expected_commit):
    """逐文件核对冻结提交，符号链接使用其 Git 保存的链接文本。"""
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments])

    commit = git("rev-parse", "HEAD").decode().strip()
    require(commit == expected_commit, "待测源码提交不同")
    require(not git("status", "--porcelain", "--untracked-files=no").strip(), "待测源码包含已修改文件")
    files, submodules = {}, {}
    for entry in git("ls-tree", "-rz", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        name = filename.decode()
        path = root / name
        if kind == "commit":
            submodules[name] = object_id
            if (path / ".git").exists():
                actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
                require(actual == object_id, "子模块提交不同: " + name)
            continue
        require(kind == "blob", "未知 Git 对象: " + name)
        if mode == "120000":
            require(path.is_symlink(), "缺少符号链接: " + name)
            data = os.readlink(path).encode()
        else:
            require(path.is_file() and not path.is_symlink(), "缺少冻结源码: " + name)
            data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(blob == object_id, "源码与 Git 对象不同: " + name)
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "mode": mode}
    aggregate = hashlib.sha256("".join(name + "\0" + row["sha256"] + "\n"
                                       for name, row in sorted(files.items())).encode()).hexdigest()
    return {"commit": commit, "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
            "file_count": len(files), "aggregate_sha256": aggregate, "files": files, "submodules": submodules}


def pipeline_profile(root):
    """读取真实生产实例中的寄存及响应容量参数，供编译和仿真结果独立核对。"""
    text = (root / "rtl/npu/dma/axi_dual_block_dma.sv").read_text()
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    instances = re.findall(r"\bconv_im2col_frontend\s*#\((.*?)\)\s+u_frontend\s*\(", text, re.S)
    require(len(instances) == 1, "需要唯一的生产卷积前端实例")
    result = {}
    for parameter, key in (
        ("REGISTER_DESCRIPTOR", "conv_register_descriptor"),
        ("REGISTER_ROW_ADDRESS", "conv_register_row_address"),
        ("REGISTER_CACHE_REQUEST", "conv_register_cache_request"),
        ("CACHE_RESPONSE_DEPTH", "conv_cache_demand_outstanding"),
    ):
        matches = re.findall(r"\." + parameter + r"\s*\(([^()]*)\)", instances[0])
        require(len(matches) == 1, "生产参数缺失: " + parameter)
        token = re.sub(r"\s+", "", matches[0])
        match = re.fullmatch(r"(?:(?:[0-9]+)'([bBdDhHoO]))?([0-9a-fA-F]+)", token)
        require(match is not None, "生产参数必须为常量: " + parameter)
        base = {None: 10, "b": 2, "d": 10, "h": 16, "o": 8}[match[1].lower() if match[1] else None]
        result[key] = int(match[2], base)
    return result


def verify_profile(actual, reference, pipeline):
    """容量、并行度和外存服务逐项相同，内部寄存参数按待测 RTL 核对。"""
    for key, value in reference.items():
        if key not in PIPELINE_KEYS:
            require(actual.get(key) == value, "硬件资源或服务参数不同: " + key)
    for key, value in pipeline.items():
        require(actual.get(key) == value, "编译记录与生产实例参数不同: " + key)
    require(set(actual["rtl_simulation_defines"]) == {"SYNTHESIS", "XILINX_FPGA"}, "生产编译宏不同")


def flatten_numbers(value, prefix=""):
    """展开每个数值字段，保留完整字段路径。"""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result.update(flatten_numbers(item, prefix + ("." if prefix else "") + str(key)))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(flatten_numbers(item, f"{prefix}[{index}]"))
        return result
    return {prefix: value} if isinstance(value, (int, float)) and not isinstance(value, bool) else {}


def compare_numbers(previous, current):
    """保存全部数值变化；正的绝对差始终列入增加字段。"""
    old, new = flatten_numbers(previous), flatten_numbers(current)
    rows = []
    for field in sorted(old.keys() | new.keys()):
        before, after = old.get(field), new.get(field)
        delta = after - before if before is not None and after is not None else None
        rows.append({"field": field, "reference": before, "current": after, "delta": delta,
                     "change_percent": 100.0 * delta / before if delta is not None and before != 0 else None,
                     "status": ("added" if before is None else "removed" if after is None else
                                "increased" if delta > 0 else "decreased" if delta < 0 else "equal")})
    return rows


def profile_records(text, fixed):
    result = {}
    for prefix in PROFILE_PREFIXES:
        rows = fixed.log_records(text, prefix)
        if prefix == "CONV_FRONTEND_STATE":
            require(len({row["state"] for row in rows}) == len(rows), "前端状态计数重复")
            result[prefix] = {str(row["state"]): row["cycles"] for row in rows}
        else:
            result[prefix] = rows
    return result


def verify_collection(directory, collection, count, interval, source_commit, fixed,
                      expected, inputs, reference_root, reference_profile, pipeline):
    """核对完整内存、实际输出、生产配置、源文件、事件日志与外存响应。"""
    summary = read_json(directory / "summary.json")
    build = read_json(directory / "sim/build.json")
    planner = read_json(directory / "planner/build.json")
    require(summary["passed"] and summary["source_commit"] == source_commit and summary["case_count"] == count,
            "任务集合未完成: " + collection)
    require(summary["profile"] == build["profile"] == planner["profile"], "编译与执行参数不同")
    verify_profile(summary["profile"], reference_profile, pipeline)
    for manifest in (build, planner):
        require(manifest["returncode"] == 0 and manifest["sources_unchanged_during_build"], "编译或源文件检查未通过")
        for path, checksum in manifest["source_sha256"].items():
            require(digest(path) == checksum, "编译输入发生变化: " + path)
    require({"--assert", "-DSYNTHESIS=1", "-DXILINX_FPGA=1"}.issubset(build["command"]), "缺少运行断言或生产宏")
    require(digest(directory / "sim/obj/Vtb_latest_operators") == build["binary_sha256"], "执行文件校验值不同")
    testbench = (directory / "sim/tb_latest_operators.sv").read_text()
    require("localparam int WORDS = 524288;" in testbench and "u_mem.mem[i] !== golden[i]" in testbench
            and "assert (errors == 0)" in testbench, "缺少完整系统内存比较")
    rows, seen = [], set()
    for kind in ("gemm", "conv"):
        group = read_json(directory / kind / "summary.json")
        old_group = read_json(reference_root / "records" / collection / kind / "summary.json")
        old_rows = {row["name"]: row for row in old_group["cases"]}
        require(group["passed"] and group["source_commit"] == source_commit, "任务分组未通过")
        require(group["build_manifest_sha256"] == digest(directory / "sim/build.json"), "编译记录发生变化")
        require({row["name"] for row in group["cases"]} == set(old_rows), "任务列表不同")
        for row in group["cases"]:
            name = row["name"]
            require(name not in seen, "任务名称重复: " + name)
            seen.add(name)
            original, tensors, previous = expected[(collection, name)], inputs[(collection, name)], old_rows[name]
            require(kind == tensors["kind"] and row["passed"] and row["returncode"] == 0, "任务未通过: " + name)
            require(row["workload_manifest_sha256"] == tensors["manifest_sha256"]
                    and row["input_tensor_sha256"] == tensors["tensor_sha256"], "任务输入不同: " + name)
            require(previous["measurement"]["cycles"] == int(original["final_cycles"]), "原版本重放周期不同: " + name)
            folder = directory / kind / "cases" / name
            output = (folder / "canonical_output.bin").read_bytes()
            old_folder = reference_root / "records" / collection / kind / "cases" / name
            require(output == tensors["expected_output"].read_bytes()
                    == (old_folder / "canonical_output.bin").read_bytes(), "实际输出不同: " + name)
            checksum = hashlib.sha256(output).hexdigest()
            require(checksum == original["output_sha256"] == row["output_sha256"] == row["observed_output_sha256"],
                    "输出校验值不同: " + name)
            require(len(output) == tensors["output_bytes"], "输出字节数不同")
            require([int(value, 16) for value in (folder / "config.mem").read_text().split()]
                    == row["configuration_words"], "配置字不同")
            for filename, expected_hash in row["files"].items():
                require(digest(folder / filename) == expected_hash, "内存输入不同: " + name + "/" + filename)
            require(fixed.memory_segment(folder / "golden.mem", row["addresses"]["c"], len(output)) == output,
                    "实际输出与完整预期内存不同")
            require(row["command"][0] == str(directory / "sim/obj/Vtb_latest_operators")
                    and "+NO_RANDOM_WAIT" in row["command"], "运行程序或外存选项不同")
            text = (folder / "run.log").read_text()
            old_text = (old_folder / "run.log").read_text()
            for prefix, field in LOG_FIELDS.items():
                require(fixed.log_records(text, prefix) == [row[field]], "运行日志与记录不同: " + name + "/" + prefix)
            measurement, timing, ar = row["measurement"], row["timing"], row["observed_ar_interval"]
            require(measurement["cycles"] == timing["done"], "完成事件与周期计数不同")
            require(max(timing["last_r"], timing["last_b"]) <= timing["done"], "外存响应尚未完成")
            require(timing["read_latency_min"] >= 8, "首个读取响应早于八个周期")
            require(max(timing["read_outstanding_max"], timing["write_outstanding_max"]) <= 4, "未完成请求数超过四项")
            require(max(timing["read_burst_bytes_max"], timing["write_burst_bytes_max"]) <= 2048, "突发传输超过配置上限")
            require(timing["read_beats"] <= measurement["ar_bytes"] <= 8 * timing["read_beats"], "读取字节数与 AXI64 节拍数不同")
            require(ar["required"] == interval and ar["accepted"] == timing["read_commands"]
                    and (ar["accepted"] < 2 or ar["minimum"] >= interval), "读地址接收间隔不同")
            current_fields = {field: row[field] for field in LOG_FIELDS.values()}
            previous_fields = {field: previous[field] for field in LOG_FIELDS.values()}
            current_fields["diagnostics"] = profile_records(text, fixed)
            previous_fields["diagnostics"] = profile_records(old_text, fixed)
            fields = compare_numbers(previous_fields, current_fields)
            cycles, original_cycles = measurement["cycles"], int(original["final_cycles"])
            rows.append({"collection": collection, "kind": kind, "name": name, "passed": True,
                         "measured_cycles": cycles, "checkpoint_cycles": original_cycles,
                         "cycle_delta": cycles - original_cycles,
                         "cycle_change_percent": 100.0 * (cycles - original_cycles) / original_cycles,
                         "checkpoint_output_sha256": original["output_sha256"], "actual_output_sha256": checksum,
                         "actual_output_bytes": len(output), "workload_manifest_sha256": row["workload_manifest_sha256"],
                         "input_tensor_sha256": row["input_tensor_sha256"],
                         "measurement": measurement, "timing": timing, "observed_ar_interval": ar,
                         "checked_memory_words": fixed.MEMORY_WORDS, "all_external_responses_completed": True,
                         "current_fields": current_fields, "reference_fields": previous_fields,
                         "numeric_comparison": fields,
                         "increased_fields": [item for item in fields if item["status"] == "increased"],
                         "configuration_words_equal": row["configuration_words"] == previous["configuration_words"],
                         "remote_default_recorded_cycles": int(original["remote_default_cycles"]),
                         "remote_low_latency_recorded_cycles": int(original["remote_low_latency_cycles"])})
    require(len(rows) == count and seen == {name for stage, name in expected if stage == collection}, "任务集合不完整")
    return rows, build["binary_sha256"]


def verify_reference(reference, fixed, snapshot, inputs):
    """验证已实际重建的 449 结果及压缩文件，保留固定包中的所有参考记录。"""
    execution = read_json(reference / "execution.json")
    validation = read_json(reference / "validation.json")
    require(execution["passed"] and execution["source_commit"] == fixed.COMMIT
            and execution["source_unchanged"] and execution["single_simulator"]
            and execution["execution_kind"] == "fresh_build_and_rtl_simulation", "需要完整实际重建的 449 结果")
    require(read_json(reference / "source_snapshot.json") == snapshot, "原版本重放源码不同")
    require(read_json(reference / "preflight.json")["input_sha256"] == inputs, "原版本重放输入不同")
    require(digest(reference / execution["wrapper_file"]) == execution["wrapper_sha256"], "原版本运行脚本发生变化")
    for item in [*execution["archives"].values(), execution["simulator_archive"]]:
        path = (reference / item["path"]).resolve()
        require(path.is_relative_to(reference) and digest(path) == item["sha256"], "原版本压缩文件校验不同")
    require(validation["passed"] and validation["case_count"] == 68
            and validation["all_checkpoint_cycles_equal"] and validation["all_checkpoint_output_sha256_equal"]
            and validation["all_actual_outputs_equal_input_reference"] and validation["all_external_responses_completed"],
            "原版本独立检查未完成")
    return execution


def write_report(out, validation):
    rows = validation["cases"]
    fields = ("collection", "name", "kind", "checkpoint_cycles", "measured_cycles", "cycle_delta",
              "cycle_change_percent", "actual_output_bytes", "actual_output_sha256")
    with (out / "cases.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in rows)
    with (out / "field_comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("collection", "name", "field", "reference", "current", "delta", "change_percent", "status"))
        writer.writeheader()
        for row in rows:
            writer.writerows({"collection": row["collection"], "name": row["name"], **item}
                             for item in row["numeric_comparison"])
    lines = ["# 68 项 NPU 性能比较", "", f"待测提交：`{validation['source_commit']}`。",
             f"固定参考提交：`{validation['reference_commit']}`。", "",
             "两次实验分别从各自冻结源码实际编译，使用同一上传环境的 Python、Verilator、输入和外部内存服务。",
             "硬件资源为 9 个 4 KiB 共享存储块、64 KiB 卷积缓存、16 个向量计算单元、16 路量化和窗口通道、16×16 矩阵阵列及 64 位 AXI。实际内部寄存参数另见 `validation.json`。", "",
             f"68 项任务均完成数值检查，每项比较 524,288 个内存字，共 {validation['checked_memory_words_total']:,} 个内存字和 {validation['actual_output_bytes']:,} 个实际输出字节。所有外存响应在任务完成前结束。", "",
             "| 集合 | 项数 | 449 周期 | 当前周期 | 周期差 |", "|---|---:|---:|---:|---:|"]
    for name, values in validation["totals"].items():
        lines.append(f"| {name} | {values['cases']} | {values['reference_cycles']:,} | {values['current_cycles']:,} | {values['cycle_delta']:+,} |")
    increased = [row for row in rows if row["cycle_delta"] > 0]
    lines += ["", f"逐项周期增加：{len(increased)} 项。任何正的周期差均计入，比较不使用容差。", ""]
    if increased:
        lines += ["| 集合 | 任务 | 449 周期 | 当前周期 | 周期差 | 变化百分比 |", "|---|---|---:|---:|---:|---:|"]
        for row in increased:
            lines.append(f"| {row['collection']} | {row['name']} | {row['checkpoint_cycles']} | {row['measured_cycles']} | +{row['cycle_delta']} | {row['cycle_change_percent']:+.6f}% |")
        lines.append("")
    lines += ["`cases.csv` 保存每项周期、绝对差和百分比；`field_comparison.csv` 保存全部数值字段，包括 DMA 字节数与事务数、等待统计、利用率和事件时间。`validation.json` 中的 `increased_fields` 列出每项所有增加字段。新增或缺少的统计字段分别标记，不按零值代替。", "",
              "`records/` 保存实际输出、配置字和运行日志；`archives/` 保存完整内存图像、编译记录及仿真程序；`source_snapshot.json` 和 `execution.json` 保存源码和工具校验值。", ""]
    (out / "README.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="本次实际重建的 449 结果目录")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    environment, reference, root, out = [value.resolve() for value in
                                        (args.environment, args.reference, args.repo, args.out)]
    require(not out.is_relative_to(root) and not out.is_relative_to(environment), "输出目录必须独立于冻结源码和固定环境")
    require(not out.exists() or not any(out.iterdir()), "结果目录必须为空")
    fixed = load_module(environment / "scripts/run_npu_performance.py", "uploaded_fixed_runner")
    config = fixed.load_configuration(environment)
    original = fixed.source_snapshot(config["source"])
    fixed.verify_source_manifest(config["source_manifest"], original)
    recorded, expected = fixed.expected_cases(config)
    inputs, expected_outputs = fixed.verify_inputs(config, expected)
    reference_execution = verify_reference(reference, fixed, original, inputs)
    env = fixed.tool_environment(config)
    versions = fixed.tool_versions(config, env)
    require(versions == reference_execution["tools"], "当前与原版本使用的工具不同")
    before = source_snapshot(root, args.commit)
    pipeline = pipeline_profile(root)
    reference_profile = read_json(reference / "records/operators/hardware_profile.json")
    started = now()
    out.mkdir(parents=True)
    write_json(out / "source_snapshot.json", before)
    wrapper_sha = digest(Path(__file__))
    write_json(out / "preflight.json", {"passed": True, "source_commit": args.commit,
               "reference_commit": fixed.COMMIT, "input_sha256": inputs, "tools": versions,
               "reference_execution_sha256": digest(reference / "execution.json"),
               "reference_profile": reference_profile, "source_pipeline_parameters": pipeline})
    support = out / "support/reference/scripts/memory_service"
    support.mkdir(parents=True)
    for name in ("axi_memory.sv", "source_manifest.json"):
        shutil.copy2(config["memory_service"] / name, support / name)
    (out / "tools").mkdir()
    shutil.copy2(Path(__file__), out / "tools/run.py")
    run = out / "work"
    common = [str(config["python"]), str(root / "test/gemmini_comparison/run_storage_operators.py"),
              "--repo", str(root), "--reference-root", str(out / "support/reference"),
              "--out", str(run), "--verilator", str(config["verilator"]), "--jobs", "1",
              "--bank-bytes", "4096", "--bank-count", "9", "--cache-bytes", "65536", "--pe-count", "16",
              "--synthesis", "--fpga", "--clean-build-products", "--plusarg", "CONV_FRONTEND_PROFILE"]
    saver = fixed.load_saver(root)
    rows, binaries, commands, archives = [], set(), [], {}
    for collection, workload_key, count, interval in fixed.COLLECTIONS:
        command = common + ["--workloads", str(config[workload_key]), "--ar-min-interval", str(interval)]
        if collection != "operators":
            command.append("--skip-build")
        commands.append(command)
        print(f"PERFORMANCE_STAGE_START collection={collection} cases={count}", flush=True)
        with (out / (collection + "_run.log")).open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, check=True)
        checked, binary_sha = verify_collection(run, collection, count, interval, args.commit, fixed,
            expected, expected_outputs, reference, reference_profile, pipeline)
        rows.extend(checked)
        binaries.add(binary_sha)
        require(len(binaries) == 1, "各集合使用的仿真程序不同")
        archives[collection] = saver(run, out, collection)
        shutil.copy2(run / "sim/tb_latest_operators.sv", out / "records" / collection / "sim/tb_latest_operators.sv")
        write_json(out / "progress.json", {"completed_collections": list(archives), "cases": rows,
                                           "binary_sha256": binary_sha, "started_at": started})
        print(f"PERFORMANCE_STAGE_PASS collection={collection} cases={count} cycles={sum(row['measured_cycles'] for row in checked)}", flush=True)
    require(source_snapshot(root, args.commit) == before, "执行期间待测源码发生变化")
    require(fixed.source_snapshot(config["source"]) == original, "固定原版本源码发生变化")
    require(digest(Path(__file__)) == wrapper_sha, "执行期间比较脚本发生变化")
    require(len(rows) == 68, "任务总数不同")
    require(sum(row["actual_output_bytes"] for row in rows) == recorded["independent_output_comparison"]["canonical_output_bytes"],
            "实际输出总字节数不同")
    public = fixed.verify_public(environment / "reports/public_replay", out, rows, expected)
    binary = run / "sim/obj/Vtb_latest_operators"
    binary_archive = out / "archives/simulator.tar.gz"
    with tarfile.open(binary_archive, "w:gz", compresslevel=6) as compressed:
        compressed.add(binary, arcname="Vtb_latest_operators")
    with tarfile.open(binary_archive, "r:gz") as compressed:
        require(hashlib.sha256(compressed.extractfile("Vtb_latest_operators").read()).hexdigest() == next(iter(binaries)),
                "仿真程序压缩校验不同")
    binary.unlink()
    no_increase = all(row["cycle_delta"] <= 0 for row in rows)
    validation = {"passed": True, "validated_at": now(), "source_commit": args.commit, "reference_commit": fixed.COMMIT,
                  "case_count": len(rows), "checked_memory_words_per_case": fixed.MEMORY_WORDS,
                  "checked_memory_words_total": fixed.MEMORY_WORDS * len(rows),
                  "actual_output_bytes": sum(row["actual_output_bytes"] for row in rows),
                  "all_actual_outputs_equal_input_reference": True, "all_external_responses_completed": True,
                  "all_case_cycles_not_increased": no_increase, "positive_cycle_difference_tolerance": 0,
                  "reference_profile": reference_profile,
                  "current_profile": read_json(out / "records/operators/hardware_profile.json"),
                  "reference_pipeline_parameters": pipeline_profile(config["source"]),
                  "current_pipeline_parameters": pipeline, "public_comparison": public,
                  "totals": {name: {"cases": count,
                      "reference_cycles": sum(row["checkpoint_cycles"] for row in rows if row["collection"] == name),
                      "current_cycles": sum(row["measured_cycles"] for row in rows if row["collection"] == name),
                      "cycle_delta": sum(row["cycle_delta"] for row in rows if row["collection"] == name)}
                      for name, unused, count, interval in fixed.COLLECTIONS}, "cases": rows}
    write_json(out / "validation.json", validation)
    write_json(out / "execution.json", {"passed": True, "execution_kind": "fresh_build_and_rtl_simulation",
               "source_commit": args.commit, "source_git_tree": before["tree"], "source_unchanged": True,
               "source_aggregate_sha256": before["aggregate_sha256"], "reference_commit": fixed.COMMIT,
               "single_simulator": True, "binary_sha256": next(iter(binaries)), "build_jobs": 1,
               "started_at": started, "completed_at": now(), "commands": commands, "archives": archives,
               "simulator_archive": {"path": "archives/simulator.tar.gz", "sha256": digest(binary_archive)},
               "wrapper_sha256": wrapper_sha, "wrapper_file": "tools/run.py", "tools": versions,
               "performance_passed": no_increase})
    write_report(out, validation)
    print(json.dumps({"numerical_passed": True, "performance_passed": no_increase,
                      "case_count": len(rows), "totals": validation["totals"]}, ensure_ascii=False, indent=2))
    return 0 if no_increase else 1


if __name__ == "__main__":
    raise SystemExit(main())
