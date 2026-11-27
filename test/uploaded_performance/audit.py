#!/usr/bin/env python3
"""独立核对性能实验的冻结源码、压缩记录、实际输出和逐项周期。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile

from run import digest, read_json, require, source_snapshot, summarize_cycles, verify_profile, write_json


COLLECTIONS = {"operators": 36, "supplementary": 26, "exact_ar2": 6}


def archived_file(archive, name):
    member = archive.getmember(name)
    require(member.isfile(), "压缩记录成员类型不同: " + name)
    with archive.extractfile(member) as stream:
        return stream.read()


def check_execution(directory):
    execution = read_json(directory / "execution.json")
    require(execution["passed"] and execution["source_unchanged"]
            and execution["single_simulator"]
            and execution["execution_kind"] == "fresh_build_and_rtl_simulation",
            "性能实验需要实际重新编译并完成运行")
    require(digest(directory / execution["wrapper_file"]) == execution["wrapper_sha256"],
            "实验入口摘要不同")
    for item in [*execution["archives"].values(), execution["simulator_archive"]]:
        path = (directory / item["path"]).resolve()
        require(path.is_relative_to(directory) and digest(path) == item["sha256"],
                "实验压缩文件摘要不同")
    with tarfile.open(directory / execution["simulator_archive"]["path"], "r:gz") as archive:
        data = archived_file(archive, "Vtb_latest_operators")
        require(hashlib.sha256(data).hexdigest() == execution["binary_sha256"],
                "仿真程序摘要不同")
    return execution


def audit(source, current, reference):
    execution = check_execution(current)
    reference_execution = check_execution(reference)
    validation = read_json(current / "validation.json")
    reference_validation = read_json(reference / "validation.json")
    require(execution["tools"] == reference_execution["tools"], "两次实验的工具不同")
    require(validation["passed"] and reference_validation["passed"]
            and reference_validation["all_checkpoint_cycles_equal"]
            and reference_validation["all_checkpoint_output_sha256_equal"],
            "数值检查或固定参考周期检查未通过")
    require(validation["reference_commit"] == reference_execution["source_commit"],
            "参考提交不同")
    revision = execution["source_commit"]
    snapshot = source_snapshot(source, revision)
    require(snapshot == read_json(current / "source_snapshot.json"), "冻结源码摘要不同")
    require(snapshot["tree"] == execution["source_git_tree"]
            and snapshot["aggregate_sha256"] == execution["source_aggregate_sha256"],
            "执行记录的源码摘要不同")
    require(validation["source_commit"] == revision, "验证记录的提交不同")
    declared = {(row["collection"], row["kind"], row["name"]): row
                for row in validation["cases"]}
    require(len(declared) == len(validation["cases"]) == 68, "任务名称重复或数量不同")
    checked_sources, output_bytes, rows = set(), 0, []
    for collection, count in COLLECTIONS.items():
        archive_path = current / "archives" / (collection + ".tar.gz")
        reference_path = reference / "archives" / (collection + ".tar.gz")
        collection_rows = []
        with tarfile.open(archive_path, "r:gz") as archive, \
                tarfile.open(reference_path, "r:gz") as previous_archive:
            member_names = archive.getnames()
            require(len(set(member_names)) == len(member_names), "压缩记录成员名称重复")
            build_bytes = archived_file(archive, "run/sim/build.json")
            build = json.loads(build_bytes)
            require(build == read_json(current / "records" / collection / "sim/build.json"),
                    "保存的编译记录与压缩记录不同")
            require(build["returncode"] == 0 and build["sources_unchanged_during_build"]
                    and build["binary_sha256"] == execution["binary_sha256"],
                    "编译结果不同")
            for filename, checksum in build["source_sha256"].items():
                path = Path(filename)
                require(path.is_file() and digest(path) == checksum, "编译输入摘要不同: " + filename)
                checked_sources.add(filename)
            require({"--assert", "-DSYNTHESIS=1", "-DXILINX_FPGA=1"}.issubset(build["command"]),
                    "编译选项缺少断言或生产条件")
            verify_profile(build["profile"], validation["reference_profile"],
                           validation["current_pipeline_parameters"])
            bench = archived_file(archive, "run/sim/tb_latest_operators.sv").decode()
            require("localparam int WORDS = 524288;" in bench
                    and "u_mem.mem[i] !== golden[i]" in bench and "assert (errors == 0)" in bench,
                    "仿真程序缺少完整内存比较")
            for kind in ("gemm", "conv"):
                group_path = "run/" + kind + "/summary.json"
                group = json.loads(archived_file(archive, group_path))
                old_group = json.loads(archived_file(previous_archive, group_path))
                require(group == read_json(current / "records" / collection / kind / "summary.json"),
                        "保存的结果与压缩记录不同")
                require(group["passed"] and group["source_commit"] == revision
                        and group["build_manifest_sha256"] == hashlib.sha256(build_bytes).hexdigest(),
                        "任务分组的状态、提交或编译摘要不同")
                old_rows = {row["name"]: row for row in old_group["cases"]}
                require({row["name"] for row in group["cases"]} == set(old_rows), "任务集合不同")
                for row in group["cases"]:
                    name, previous = row["name"], old_rows[row["name"]]
                    stored = declared[(collection, kind, name)]
                    folder = "run/" + kind + "/cases/" + name + "/"
                    output = archived_file(archive, folder + "canonical_output.bin")
                    require(output == archived_file(previous_archive, folder + "canonical_output.bin"),
                            "实际输出不同: " + name)
                    output_sha = hashlib.sha256(output).hexdigest()
                    require(output_sha == row["output_sha256"] == row["observed_output_sha256"]
                            == stored["actual_output_sha256"] == stored["checkpoint_output_sha256"],
                            "输出摘要不同: " + name)
                    for filename, checksum in row["files"].items():
                        require(hashlib.sha256(archived_file(archive, folder + filename)).hexdigest()
                                == checksum, "内存图像或配置摘要不同: " + name + "/" + filename)
                    require(row["configuration_words"] == previous["configuration_words"]
                            and row["input_tensor_sha256"] == previous["input_tensor_sha256"]
                            == stored["input_tensor_sha256"], "配置或输入不同: " + name)
                    require(row["passed"] and row["returncode"] == 0, "数值仿真未通过: " + name)
                    cycles = row["measurement"]["cycles"]
                    old_cycles = previous["measurement"]["cycles"]
                    log = archived_file(archive, folder + "run.log").decode()
                    markers = re.findall(r"^COMMON_OPERATOR_PASS (.*)$", log, flags=re.M)
                    require(len(markers) == 1 and re.search(r"\bcycles=" + str(cycles) + r"\b", markers[0]),
                            "运行日志的完成周期不同: " + name)
                    require(cycles == row["timing"]["done"] == stored["measured_cycles"]
                            and old_cycles == stored["checkpoint_cycles"]
                            and cycles - old_cycles == stored["cycle_delta"], "周期比较不同: " + name)
                    timing = row["timing"]
                    require(max(timing["last_r"], timing["last_b"]) <= cycles
                            and timing["read_latency_min"] >= 8
                            and max(timing["read_outstanding_max"], timing["write_outstanding_max"]) <= 4,
                            "外存完成或服务配置检查未通过: " + name)
                    output_bytes += len(output)
                    collection_rows.append({"collection": collection, "kind": kind, "name": name,
                        "reference_cycles": old_cycles, "current_cycles": cycles,
                        "cycle_delta": cycles-old_cycles, "output_bytes": len(output),
                        "output_sha256": output_sha})
        require(len(collection_rows) == count, "集合任务数量不同: " + collection)
        rows.extend(collection_rows)
    no_increase = all(row["cycle_delta"] <= 0 for row in rows)
    cycle_summary = summarize_cycles([{**row, "checkpoint_cycles": row["reference_cycles"],
                                      "measured_cycles": row["current_cycles"]} for row in rows])
    for record in (execution, validation):
        if "cycle_summary" in record:
            require(record["cycle_summary"] == cycle_summary, "周期总数或最大增加任务不同")
    require(no_increase == execution["performance_passed"]
            == validation["all_case_cycles_not_increased"], "性能汇总不同")
    require(output_bytes == validation["actual_output_bytes"] == 411414
            and validation["checked_memory_words_total"] == 68*524288,
            "输出字节数或内存检查数量不同")
    return {"passed": True, "source_commit": revision, "source_tree": snapshot["tree"],
        "source_files_checked": snapshot["file_count"], "compiled_sources_checked": len(checked_sources),
        "reference_commit": reference_execution["source_commit"], "case_count": len(rows),
        "memory_words_checked": 68*524288, "output_bytes": output_bytes,
        "performance_passed": no_increase, "increased_case_count": sum(row["cycle_delta"] > 0 for row in rows),
        "cycle_summary": cycle_summary,
        "reference_cycles": sum(row["reference_cycles"] for row in rows),
        "current_cycles": sum(row["current_cycles"] for row in rows), "cases": rows,
        "current_validation_sha256": digest(current/"validation.json"),
        "current_execution_sha256": digest(current/"execution.json"),
        "reference_validation_sha256": digest(reference/"validation.json"),
        "reference_execution_sha256": digest(reference/"execution.json"),
        "binary_sha256": execution["binary_sha256"],
        "reference_binary_sha256": reference_execution["binary_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source_root.resolve(), args.current.resolve(), args.reference.resolve())
    write_json(args.out, result)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
