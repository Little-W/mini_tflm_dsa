#!/usr/bin/env python3
"""按当前 SoC 的地址与量化参数，逐项比较 62 个算子的数值和时序。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONFIGURATION_PATH = HERE / "production_parameters.json"
CONFIGURATION = json.loads(CONFIGURATION_PATH.read_text())
TIMING_FIELDS = (
    "first_ar", "first_r", "last_r", "first_aw", "first_w", "last_w", "last_b",
    "done", "first_read_latency", "read_latency_min", "read_latency_max",
    "read_commands", "write_commands", "read_beats", "write_beats",
    "read_outstanding_max", "write_outstanding_max",
    "read_burst_bytes_max", "write_burst_bytes_max",
)
EXPECTED_PARAMETERS = {
    "matrix_requant_compute_lanes": 2,
    "vector_quantization_lanes": 1,
    "npu_address_width": 32,
    "matrix_dimension_count_width": 29,
}
PARAMETER_MODULES = {
    "matrix_requant_compute_lanes": [
        "npu_top.REQUANT_COMPUTE_LANES",
        "npu_top.u_matrix_engine.p_shared_requant_lanes",
        "npu_top.u_matrix_engine.p_requant_compute_lanes",
        "npu_top.u_matrix_engine.u_output_pipeline.p_requant_compute_lanes",
        "npu_top.u_matrix_engine.u_output_pipeline.u_vec_requant.p_compute_lanes",
    ],
    "vector_quantization_lanes": [
        "npu_top.g_vector_engine.u_engine.QUANT_LANES",
    ],
    "npu_address_width": ["npu_top.ADDR_WIDTH"],
    "matrix_dimension_count_width": [
        "npu_top.u_matrix_engine.DIM_COUNT_WIDTH",
        "npu_top.u_matrix_engine.u_output_pipeline.p_dim_count_width",
    ],
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("production_timing_common", HERE / "run.py")


def parameter_assertions():
    conditions = []
    for name, modules in PARAMETER_MODULES.items():
        for module in modules:
            conditions.append(module.replace("npu_top.", "u_dut.", 1) +
                              " == " + str(EXPECTED_PARAMETERS[name]))
    for name, value in {**CONFIGURATION["npu_parameters"],
                        **CONFIGURATION["derived_parameters"]}.items():
        conditions.append("u_dut." + name + " == " + str(value))
    fields = " ".join(name + "=%0d" for name in EXPECTED_PARAMETERS)
    signals = [modules[-1].replace("npu_top.", "u_dut.", 1)
               for modules in PARAMETER_MODULES.values()]
    return ("        assert (" + " &&\n                ".join(conditions) + ")\n"
            '            else $fatal(1, "Production parameters differ");\n'
            '        $display("COMMON_PRODUCTION_PARAMETERS ' + fields + '",\n            ' +
            ",\n            ".join(signals) + ");\n")


def worker():
    """复用固定版本的算子执行器，只补充参数观察与构建输入记录。"""
    storage = load("production_storage_operators",
                   ROOT / "test/gemmini_comparison/run_storage_operators.py")
    original_profile = storage.hardware_profile
    original_testbench = storage.testbench
    original_build = storage.build

    def hardware_profile(args, normalize):
        def production_normalize(source, **keywords):
            source = dict(source)
            source["ps_storage_rows"] = CONFIGURATION["npu_parameters"]["PS_STORAGE_ROWS"]
            return normalize(source, **keywords)
        result = original_profile(args, production_normalize)
        if result["quantization_lanes"] != EXPECTED_PARAMETERS["vector_quantization_lanes"]:
            raise ValueError("本测试要求当前 SoC 的向量一路量化配置")
        result.update(EXPECTED_PARAMETERS)
        result["production_npu_parameters"] = CONFIGURATION["npu_parameters"]
        result["production_derived_parameters"] = CONFIGURATION["derived_parameters"]
        return result

    def testbench(args):
        text = original_testbench(args)
        instance = r"npu_top\s*#\((.*?)\)\s*u_dut\s*\("
        matches = list(re.finditer(instance, text, re.S))
        if len(matches) != 1:
            raise ValueError("测试台需要一个明确的 NPU 顶层实例")
        arguments = ",\n        ".join("." + name + "(" + str(value) + ")"
            for name, value in CONFIGURATION["npu_parameters"].items())
        text = re.sub(instance, "npu_top #(\n        " + arguments + "\n    ) u_dut (", text, flags=re.S)
        marker = "        assert (sa_ready) else"
        if text.count(marker) != 1:
            raise ValueError("测试台需要一个明确的配置检查位置")
        return text.replace(marker, parameter_assertions() + marker)

    def build(args, runner, profile):
        args.verification_sources = [Path(__file__).resolve(), HERE / "run.py", CONFIGURATION_PATH]
        original_command = runner.command
        def command(values, *positional, **keywords):
            for index, value in enumerate(values):
                if value == "-DTB_PS_STORAGE_ROWS=0":
                    values[index] = "-DTB_PS_STORAGE_ROWS=" + str(
                        CONFIGURATION["npu_parameters"]["PS_STORAGE_ROWS"])
            return original_command(values, *positional, **keywords)
        runner.command = command
        try:
            return original_build(args, runner, profile)
        finally:
            runner.command = original_command

    storage.hardware_profile = hardware_profile
    storage.testbench = testbench
    storage.build = build
    return storage.main()


def observed_parameters(log):
    pattern = (r"^COMMON_PRODUCTION_PARAMETERS " +
               " ".join(name + r"=(\d+)" for name in EXPECTED_PARAMETERS) + "$" )
    matches = re.findall(pattern, log, re.M)
    if len(matches) != 1:
        raise ValueError("每个算子需要一次实际层次参数记录")
    result = dict(zip(EXPECTED_PARAMETERS, map(int, matches[0])))
    if result != EXPECTED_PARAMETERS:
        raise ValueError("实际层次参数与当前 SoC 配置不同")
    return result


def validate_timing(row):
    timing = row["timing"]
    if set(timing) != set(TIMING_FIELDS):
        raise ValueError("DMA 与事件字段集合不同: " + row["name"])
    if any(type(timing[field]) is not int for field in TIMING_FIELDS):
        raise ValueError("DMA 与事件字段需要整数值: " + row["name"])


def collect(out, inputs):
    result = common.collect(out, inputs)
    observed = {}
    for collection, _folder, _count in common.COLLECTIONS:
        for kind in ("gemm", "conv"):
            group = common.read(out / "collections" / collection / (kind + ".json"))
            for row in group["cases"]:
                log = Path(row["case_directory"]) / "run.log"
                observed[row["name"]] = observed_parameters(log.read_text())
    for row in result["cases"]:
        validate_timing(row)
        row["observed_production_parameters"] = observed[row["name"]]
    for name, expected in EXPECTED_PARAMETERS.items():
        if result["profile"].get(name) != expected:
            raise ValueError("构建配置缺少实际生产参数: " + name)
    result["parameter_modules"] = PARAMETER_MODULES
    result["production_configuration"] = CONFIGURATION
    result["production_configuration_sha256"] = common.digest(CONFIGURATION_PATH)
    result["timing_fields"] = TIMING_FIELDS
    result["runner_sha256"] = common.digest(__file__)
    common.write(out / "all_cases.json", result)
    return result


def compare(reference, current):
    for result in (reference, current):
        for name, expected in EXPECTED_PARAMETERS.items():
            if result["profile"].get(name) != expected:
                raise ValueError("比较记录缺少当前 SoC 参数: " + name)
        for row in result["cases"]:
            validate_timing(row)
            if row.get("observed_production_parameters") != EXPECTED_PARAMETERS:
                raise ValueError("比较记录缺少实际层次参数: " + row["name"])
    result = common.compare(reference, current)
    old = {row["name"]: row for row in reference["cases"]}
    new = {row["name"]: row for row in current["cases"]}
    for row in result["cases"]:
        name = row["name"]
        row["cycles_equal"] = row["reference_cycles"] == row["current_cycles"]
        row["timing_field_differences"] = {
            field: {"reference": old[name]["timing"][field],
                    "current": new[name]["timing"][field]}
            for field in TIMING_FIELDS
            if old[name]["timing"][field] != new[name]["timing"][field]
        }
        row["all_timing_fields_equal"] = not row["timing_field_differences"]
    result["checks"]["all_cycles_equal"] = all(row["cycles_equal"] for row in result["cases"])
    result["checks"]["all_19_timing_fields_equal"] = all(
        row["all_timing_fields_equal"] for row in result["cases"])
    result["passed"] = all(result["checks"].values())
    result["timing_fields"] = TIMING_FIELDS
    result["reference_commit"] = reference["source_commit"]
    result["current_commit"] = current["source_commit"]
    return result


def clean_objects(out):
    """保留执行文件和测试源码；删除可重建对象并压缩生成的 C++ 源码。"""
    directory = out / "sim/obj"
    records = []
    for path in sorted(directory.iterdir() if directory.is_dir() else []):
        if not path.is_file() or path.is_symlink():
            continue
        if not path.name.startswith(("Vtb_latest_operators", "verilated")):
            continue
        if path.suffix not in (".o", ".a", ".gch", ".d", ".cpp", ".h"):
            continue
        record = {"path": str(path.relative_to(out)), "bytes": path.stat().st_size,
                  "sha256": common.digest(path)}
        if path.suffix in (".cpp", ".h"):
            compressed = path.with_suffix(path.suffix + ".gz")
            with path.open("rb") as source, gzip.open(compressed, "wb") as target:
                shutil.copyfileobj(source, target)
            with gzip.open(compressed, "rb") as stream:
                if hashlib.sha256(stream.read()).hexdigest() != record["sha256"]:
                    raise ValueError("生成源码压缩摘要不同")
            record["compressed_path"] = str(compressed.relative_to(out))
            record["compressed_sha256"] = common.digest(compressed)
        path.unlink()
        records.append(record)
    common.write(out / "sim/object_archive.json", records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inputs-from", type=Path, required=True)
    parser.add_argument("--compare-with", type=Path)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--keep-objects", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("编译并行数需要为正整数")
    repo, out, inputs = args.repo.resolve(), args.out.resolve(), args.inputs_from.resolve()
    common.verify_inputs(repo, inputs)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    out.mkdir(parents=True, exist_ok=True)
    common.write(out / "invocation.json", {
        "command": sys.argv, "source_commit": commit,
        "input_manifest_sha256": common.digest(inputs / "input_manifest.json"),
        "parameters": EXPECTED_PARAMETERS, "parameter_modules": PARAMETER_MODULES,
        "production_configuration_sha256": common.digest(CONFIGURATION_PATH),
        "runner_sha256": common.digest(__file__),
    })
    if args.prepare_only:
        print(json.dumps({"prepared": 62, "source_commit": commit,
                          "parameters": EXPECTED_PARAMETERS}))
        return 0
    if not args.collect_only:
        command = [sys.executable, str(Path(__file__).resolve()), "--worker",
                   "--repo", str(repo), "--reference-root", str(inputs), "--out", str(out),
                   "--verilator", args.verilator, "--jobs", str(args.jobs),
                   "--bank-bytes", "8192", "--bank-count", "7", "--cache-bytes", "4096",
                   "--pe-count", "8", "--synthesis", "--fpga"]
        for index, (name, folder, count) in enumerate(common.COLLECTIONS):
            if shutil.disk_usage(out).free < 500 * 1024 * 1024:
                raise RuntimeError("开始下一集合前需要至少 500 MiB 可用空间")
            selected = command + ["--workloads", str(inputs / folder)]
            if index:
                selected.append("--skip-build")
            with (out / (name + ".log")).open("w") as stream:
                subprocess.run(selected, stdout=stream, stderr=subprocess.STDOUT, check=True)
            common.save_collection(out, name, count)
            print(json.dumps({"collection": name, "passed": True, "cases": count}), flush=True)
    result = collect(out, inputs)
    status = 0
    if args.compare_with:
        reference = args.compare_with.resolve()
        if reference.is_dir():
            reference /= "all_cases.json"
        comparison = compare(common.read(reference), result)
        common.write(out / "comparison.json", comparison)
        status = 0 if comparison["passed"] else 1
    if not args.keep_objects and not args.collect_only:
        clean_objects(out)
    print(json.dumps({"passed": status == 0, "case_count": result["case_count"],
                      "total_cycles": result["total_cycles"], "source_commit": commit,
                      "parameters": EXPECTED_PARAMETERS,
                      "result": str(out / "all_cases.json")}), flush=True)
    return status


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        del sys.argv[1]
        raise SystemExit(worker())
    raise SystemExit(main())
