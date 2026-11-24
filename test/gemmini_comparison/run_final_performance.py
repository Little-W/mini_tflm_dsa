#!/usr/bin/env python3
"""顺序验证冻结源码的 36、26 和 AR2 六项任务，并保存压缩结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from storage_vector_profile import resolve_vector_configuration
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_snapshot(root, expected_commit):
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True)
    commit = git("rev-parse", "HEAD").strip()
    if commit != expected_commit or git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("性能测试需要指定提交的干净源码目录")
    names = [name for name in git("ls-files", "-z").split("\0") if name]
    return {"source_commit": commit, "source_root": str(root),
            "sha256": {name: digest(root / name) for name in names if (root / name).is_file()},
            "sparse_unavailable": [name for name in names if not (root / name).is_file()]}


def execute(command, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), stdout=output, stderr=subprocess.STDOUT, check=True)


def save_collection(run, out, name):
    """保存独立记录和实际输出，压缩内存图像后释放本集合目录。"""
    records = out / "records" / name
    records.mkdir(parents=True, exist_ok=True)
    for filename in ("summary.json", "prepared.json", "hardware_profile.json"):
        shutil.copy2(run / filename, records / filename)
    if (run / "historical_source_verification.json").exists():
        shutil.copy2(run / "historical_source_verification.json", records / "historical_source_verification.json")
    for folder, filename in (("sim", "build.json"), ("planner", "build.json")):
        (records / folder).mkdir(exist_ok=True)
        shutil.copy2(run / folder / filename, records / folder / filename)
    for group in ("gemm", "conv"):
        target = records / group
        target.mkdir(exist_ok=True)
        shutil.copy2(run / group / "summary.json", target / "summary.json")
        summary = json.loads((run / group / "summary.json").read_text())
        for row in summary["cases"]:
            case = target / "cases" / row["name"]
            case.mkdir(parents=True, exist_ok=True)
            for filename in ("canonical_output.bin", "result.json", "run.log", "config.mem"):
                shutil.copy2(run / group / "cases" / row["name"] / filename, case / filename)
    archive = out / "archives" / (name + ".tar.gz")
    archive.parent.mkdir(parents=True, exist_ok=True)
    entries = ["gemm", "conv", "summary.json", "prepared.json", "hardware_profile.json", "historical_source_verification.json", "planner",
               "sim/build.json", "sim/compile.log", "sim/tb_latest_operators.sv", "sim/synthesis_monitors"]
    with tarfile.open(archive, "w:gz", compresslevel=6) as compressed:
        for entry in entries:
            if (run / entry).exists():
                compressed.add(run / entry, arcname="run/" + entry, recursive=True)
    with tarfile.open(archive, "r:gz") as compressed:
        if "run/gemm/summary.json" not in compressed.getnames() or "run/conv/summary.json" not in compressed.getnames():
            raise ValueError("压缩结果缺少任务集合摘要")
    for group in ("gemm", "conv"):
        shutil.rmtree(run / group)
    return {"path": str(archive), "bytes": archive.stat().st_size, "sha256": digest(archive),
            "records": str(records)}


def expected_hardware_profile(root, bank_bytes, bank_count, cache_bytes, pe_count):
    expected = json.loads((HERE / "public_operator_reference_20261123.json").read_text())["npu_profile"]
    expected.update(shared_bank_bytes=bank_bytes, shared_bank_count=bank_count,
                    shared_total_bytes=bank_bytes*bank_count, im2col_cache_bytes=cache_bytes)
    vector = resolve_vector_configuration(root, pe_count=pe_count, bank_count=bank_count, bus_width=64)
    expected.update({key: vector[key] for key in
                     ("vector_pe_count", "quantization_lanes", "window_lanes", "shared_quant_enable")})
    return expected


def save_capacity(source, out, snapshot):
    """保存容量展开结果，并核对实际性能源码中的每个展开输入。"""
    value = json.loads(source.read_text())
    if value.get("budget_scope") != "buffer-ram" or not value.get("source_unchanged"):
        raise ValueError("容量检查需要完成的 buffer-ram 展开结果")
    if set(value["targets"]) != {"generic", "asic"}:
        raise ValueError("容量摘要需要 generic 与 ASIC 两种展开配置")
    checked = {}
    for target, row in value["targets"].items():
        path = Path(row["result"])
        if not path.is_absolute():
            path = source.parent / path
        detail = json.loads(path.read_text())
        if not row["passed"] or not detail["passed"] or not detail["sources_unchanged"]:
            raise ValueError("容量展开未通过: " + target)
        for relative, checksum in detail["source_sha256"].items():
            if snapshot["sha256"].get(relative) != checksum:
                raise ValueError("容量与性能源码不同: " + relative)
            checked[relative] = checksum
        destination = out / "capacity_targets" / (target + ".json")
        write_json(destination, detail)
        row["result"] = str(destination.relative_to(out))
        row["result_sha256"] = digest(destination)
    if not checked:
        raise ValueError("容量结果缺少展开输入摘要")
    value.update(performance_source_commit=snapshot["source_commit"],
                 performance_sources_match=True, source_sha256=checked)
    write_json(out / "capacity.json", value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "reference-root", "supplementary-workloads", "exact-workloads", "public-replay",
                 "old-fast", "old-default", "regression-reference", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--verilator", default=shutil.which("verilator") or "verilator")
    parser.add_argument("--bank-bytes", type=int, choices=(2048, 4096, 8192), default=4096)
    parser.add_argument("--bank-count", type=int, choices=(6, 7, 8, 9), default=9)
    parser.add_argument("--cache-bytes", type=int, default=65536)
    parser.add_argument("--pe-count", type=int, choices=(8, 16), default=16)
    parser.add_argument("--capacity", type=Path,
                        help="同一生产源码的 generic 与 ASIC buffer-ram 容量摘要")
    parser.add_argument("--reuse-built-simulator", action="store_true",
                        help="复用当前输出目录中摘要完全相同的仿真程序")
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    root, out = args.repo, args.out
    before = source_snapshot(root, args.commit)
    write_json(out / "source_snapshot.json", before)
    if args.capacity:
        save_capacity(args.capacity, out, before)
    expected_profile = out / "expected_hardware_profile.json"
    write_json(expected_profile, expected_hardware_profile(root, args.bank_bytes, args.bank_count,
                                                          args.cache_bytes, args.pe_count))
    run = out / "run"
    common = [sys.executable, root / "test/gemmini_comparison/run_storage_operators.py",
              "--repo", root, "--reference-root", args.reference_root, "--out", run,
              "--verilator", args.verilator, "--jobs", "1", "--bank-bytes", str(args.bank_bytes), "--bank-count", str(args.bank_count),
              "--cache-bytes", str(args.cache_bytes), "--pe-count", str(args.pe_count), "--synthesis", "--fpga",
              "--clean-build-products", "--plusarg", "CONV_FRONTEND_PROFILE"]
    stages = [("operators", args.reference_root / "workloads", 36, 1),
              ("supplementary", args.supplementary_workloads, 26, 1),
              ("exact_ar2", args.exact_workloads, 6, 2)]
    archives, commands = {}, []
    binary_digest = None
    for stage, workloads, count, interval in stages:
        command = common + ["--workloads", workloads, "--ar-min-interval", str(interval)]
        if stage != "operators" or args.reuse_built_simulator:
            command += ["--skip-build"]
        commands.append(list(map(str, command)))
        print(f"PERFORMANCE_STAGE_START name={stage} cases={count}", flush=True)
        execute(command, out / (stage + "_run.log"))
        summary = json.loads((run / "summary.json").read_text())
        if not summary["passed"] or summary["case_count"] != count:
            raise ValueError("性能测试任务未完成: " + stage)
        current_digest = digest(run / "sim/obj/Vtb_latest_operators")
        if binary_digest is not None and current_digest != binary_digest:
            raise ValueError("不同任务集合使用了不同的仿真程序")
        binary_digest = current_digest
        check = out / "comparison" / stage
        if stage == "operators":
            execute([sys.executable, root / "test/gemmini_comparison/check_public_operators.py",
                     "--run", run, "--out", check, "--require-leading-gemm",
                     "--public-replay", args.public_replay, "--npu-profile", expected_profile], out / "operators_check.log")
            execute([sys.executable, HERE / "check_repository_operators.py", "--repo", root,
                     "--run", run, "--old-fast", args.old_fast.parent / "operators",
                     "--old-default", args.old_default.parent / "operators",
                     "--reference", args.regression_reference, "--case-count", "36", "--out", check],
                    out / "repository_operators_check.log")
            execute([sys.executable, HERE / "check_public_replay_outputs.py", "--run", run,
                     "--replay", args.public_replay, "--out", check], out / "public_outputs_check.log")
        elif stage == "supplementary":
            execute([sys.executable, HERE / "check_repository_operators.py", "--repo", root,
                     "--run", run, "--old-fast", args.old_fast, "--old-default", args.old_default,
                     "--reference", args.regression_reference, "--out", check], out / "supplementary_check.log")
        else:
            execute([sys.executable, HERE / "check_exact_operators.py", "--repo", root, "--run", run,
                     "--public", args.public_replay / "nvdla/results.json",
                     "--old-fast", args.old_fast.parent / "exact_ar2",
                     "--old-default", args.old_default.parent / "exact_ar2", "--reference", args.regression_reference,
                     "--out", check], out / "exact_check.log")
        archives[stage] = save_collection(run, out, stage)
        print(f"PERFORMANCE_STAGE_PASS name={stage} cases={count}", flush=True)
    after = source_snapshot(root, args.commit)
    if after != before:
        raise ValueError("性能测试过程中源码发生变化")
    binary = run / "sim/obj/Vtb_latest_operators"
    program_archive = out / "archives/simulator.tar.gz"
    with tarfile.open(program_archive, "w:gz", compresslevel=6) as compressed:
        compressed.add(binary, arcname="run/sim/obj/Vtb_latest_operators")
    program_record = {"path": str(program_archive), "sha256": digest(program_archive),
                      "binary_sha256": binary_digest, "bytes": program_archive.stat().st_size}
    execution = {"passed": True, "source_commit": args.commit, "source_unchanged": True,
                 "source_snapshot_sha256": digest(out / "source_snapshot.json"),
                 "binary_sha256": binary_digest, "single_simulator": True, "build_jobs": 1,
                 "case_counts": {stage: count for stage, unused, count, unused_interval in stages},
                 "commands": commands, "archives": archives, "simulator_archive": program_record,
                 "tools_sha256": {str(HERE / name): digest(HERE / name) for name in
                     ("run_final_performance.py", "check_repository_operators.py",
                      "check_exact_operators.py", "check_public_replay_outputs.py", "write_final_performance_report.py")}}
    write_json(out / "execution.json", execution)
    execute([sys.executable, HERE / "write_final_performance_report.py", "--results", out,
             "--public-replay", args.public_replay, "--out", out / "report"], out / "report.log")
    binary.unlink()
    print("FINAL_PERFORMANCE_PASS cases=68", flush=True)


if __name__ == "__main__":
    main()
