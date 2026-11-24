#!/usr/bin/env python3
"""映射完整 DMA/NPU 并检查跨模块组合路径，顺序执行以限制内存占用。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


SCOPES = [
    ("frontend_internal", r"u_frontend\.(?!u_cache)", r"u_frontend\.(?!u_cache)"),
    ("window_queue_to_cache", "u_window_queue", "u_cache.*u_window"),
    ("cache_to_frontend", "u_cache.*u_window", r"u_frontend\.(?!u_cache)"),
    ("cache_internal", "u_cache.*u_window", "u_cache.*u_window"),
    ("linear_dma", r"(^|\.)u_linear\.", r"(^|\.)u_linear\."),
    ("cache_to_output", "u_cache.*u_window", "fe_output|fe_matrix_output"),
    ("frontend_to_cache", r"u_frontend\.(?!u_cache)", "u_cache.*u_window"),
    ("window_queue_to_frontend", "u_window_queue", r"u_frontend\.(?!u_cache)"),
    ("all_to_frontend_request", ".", r"u_frontend\.request_"),
    ("all_to_cache_lookup", ".",
     r"u_cache.*u_window.*(lookup_|work_request|matches_q|response_snapshot_ready|preview_selected|g_direct_snapshot_fields)"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def revision(root):
    commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    changed = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True)
    if changed:
        raise ValueError("完整路径检查需要已提交且未修改的源码目录")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=("dma_vivado", "dma_performance", "npu_top", "npu_performance"),
                        default=["dma_vivado", "dma_performance", "npu_top", "npu_performance"])
    parser.add_argument("--maximum-depth", type=int, default=11)
    parser.add_argument("--abc9-batch-size", type=int, default=64,
                        help="每个独立 ABC9 进程映射的完整模块数")
    parser.add_argument("--native-combinational-helpers", action="store_true",
                        help="按相同参数复用原生组合模块定义，保留全部硬件实例")
    parser.add_argument("--preserve-rtl-module", action="append", default=[], metavar="MODULE",
                        help="为完整 NPU 保留指定原始 RTL 组件，可重复传入；映射后展开完整路径")
    parser.add_argument("--reuse-rtl-module-definition", action="append", default=[],
                        choices=("ws_systolic_cell",), metavar="MODULE",
                        help="严格比较已保留组件的完整定义后复用相同定义，保留所有硬件实例")
    parser.add_argument("--resume", action="store_true",
                        help="复用输入摘要相同的展开结果和完整设计检查点")
    args = parser.parse_args()
    if args.maximum_depth < 1:
        parser.error("--maximum-depth must be positive")
    if args.abc9_batch_size < 1:
        parser.error("--abc9-batch-size must be positive")
    root, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = revision(root)
    summary_path = out / "validation_summary.json"
    summary = {"revision": commit, "maximum_depth": args.maximum_depth, "cases": {}, "passed": True}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        if summary["revision"] != commit or summary["maximum_depth"] != args.maximum_depth:
            raise ValueError("输出目录已有不同提交或路径深度条件的记录")
    for case in dict.fromkeys(args.cases):
        print(f"TIMING_START case={case} revision={commit}", flush=True)
        folder = out / case
        folder.mkdir(exist_ok=True)
        synth = [sys.executable, str(root / "scripts/fpga/open_fpga_synth.py"),
                 "--source-root", str(root), "--out", str(out), "--cases", case,
                 "--case-config", str(root / "test/conv_frontend/timing_cases.json"),
                 "--max-register-path-cells", str(args.maximum_depth),
                 "--abc9-batch-size", str(args.abc9_batch_size)]
        if args.resume:
            synth.append("--resume")
        if args.native_combinational_helpers:
            synth.append("--native-combinational-helpers")
        if case in ("npu_top", "npu_performance"):
            for module in dict.fromkeys(args.preserve_rtl_module):
                synth += ["--preserve-rtl-module", module]
            for module in dict.fromkeys(args.reuse_rtl_module_definition):
                synth += ["--reuse-rtl-module-definition", module]
        with (folder / "synthesis_stdout.log").open("w") as log:
            subprocess.run(synth, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=root)
        scopes = list(SCOPES)
        if case in ("npu_top", "npu_performance"):
            scopes.extend([
                ("partial_sum_to_ram", "u_ps_buffer.*u_store", "g_shared_ia_ps.*u_ram"),
                ("partial_sum_to_controller", "u_ps_buffer.*u_store", "u_npu_controller"),
            ])
        else:
            scopes.insert(0, ("all_storage", ".", "."))
        measure = [sys.executable, str(root / "test/conv_frontend/tools/measure_complete_paths.py"),
                   "--mapped", str(folder / "mapped.json"), "--pre-lut", str(folder / "pre_lut.il"),
                   "--top", "npu_top" if case in ("npu_top", "npu_performance") else "axi_dual_block_dma",
                   "--out", str(folder / "complete_paths.json"), "--path-limit", "60",
                   "--require-scope-max-depth", str(args.maximum_depth)]
        for scope in scopes:
            measure += ["--scope", *scope]
        with (folder / "measurement_stdout.log").open("w") as log:
            measured = subprocess.run(measure, stdout=log, stderr=subprocess.STDOUT, cwd=root)
        report = json.loads((folder / "complete_paths.json").read_text())
        manifest = json.loads((folder / "manifest.json").read_text())
        unchanged = commit == revision(root) and all(
            digest(root / name) == expected for name, expected in manifest["sources_sha256"].items())
        if not unchanged:
            raise ValueError("映射过程中源码发生变化")
        report.update(analysis_source_revision=commit, source_unchanged=True,
                      measurement_command=measure, synthesis_command=synth,
                      manifest_sha256=digest(folder / "manifest.json"))
        for value in report["critical_scopes"].values():
            value["connected_endpoint_ports"] = sum(value["endpoint_depth_histogram"].values())
        write_json(folder / "complete_paths.json", report)
        entry = {
            "passed": measured.returncode == 0, "graph_complete": report["graph_complete"],
            "source_unchanged": unchanged, "resources": report["resources"],
            "all_paths": {key: value["maximum_combinational_cells"]
                          for key, value in report["path_groups"].items()},
            "critical_scopes": {
                key: {field: value[field] for field in
                      ("maximum_combinational_cells", "scope_available", "graph_complete",
                       "selected_start_ports", "selected_endpoint_ports", "connected_endpoint_ports")}
                for key, value in report["critical_scopes"].items()},
            "scope_requirement": report["scope_requirement"],
            "complete_paths_sha256": digest(folder / "complete_paths.json"),
            "manifest_sha256": digest(folder / "manifest.json"),
        }
        summary["cases"][case] = entry
        summary["passed"] = all(value["passed"] for value in summary["cases"].values())
        write_json(summary_path, summary)
        for name in ("mapped.json", "mapped.v", "pre_lut.il", "elaborated.il"):
            original = folder / name
            if original.exists():
                with original.open("rb") as source, gzip.open(str(original) + ".gz", "wb", compresslevel=6) as target:
                    shutil.copyfileobj(source, target)
                original.unlink()
        print(json.dumps({"case": case, **entry}), flush=True)
        if measured.returncode:
            return measured.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
