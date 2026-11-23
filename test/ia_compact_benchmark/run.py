#!/usr/bin/env python3
"""在相同物理共享 RAM 上比较 IA 编译开关的 GEMM 周期与访存量。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from planner_profile import normalize_profile, profile_header
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare import checked_payload, storage_statistics


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def profile(enabled):
    return normalize_profile(dict(size=16, bus_width=64, ps_compress=True,
        ia_cache_blocks=4, ps_frame_count=16, ps_storage_rows=0,
        shared_bank_bytes=8192, shared_bank_count=7, shared_total_bytes=57344,
        im2col_cache_bytes=4096, output_banks_s16_max=4,
        ram_continuous_read_beat_cycles=1, ram_read_first_latency=8,
        dma_max_bytes=2048, force_raw=True, ia_compact_enable=enabled), root=ROOT)


def prepare_case(runner, planner, planner_library, source, target, schedule=None):
    target.mkdir(parents=True, exist_ok=True)
    manifest = source / "case.json"
    record = json.loads(manifest.read_text())
    tensors = {name: checked_payload(source / value["path"], value)
               for name, value in record["tensors"].items()}
    image = bytearray(runner.SENTINEL * runner.WORDS)
    cursor = 4096
    locations = {}
    # 每个操作数独立保留 128 字节边界，完整内存检查包含未写区域。
    for name in ("lhs", "rhs", "bias", "multipliers", "shifts", "output"):
        cursor = (cursor + 127) // 128 * 128
        locations[name] = cursor
        if name != "output":
            payload = tensors[name].tobytes()
            image[cursor:cursor + len(payload)] = payload
        cursor += tensors[name].nbytes
    if cursor > len(image) or tensors["output"].size > runner.WORDS:
        raise ValueError("Model GEMM exceeds this testbench's addressable memory")
    golden = bytearray(image)
    dst = locations["output"]
    golden[dst:dst + tensors["output"].nbytes] = tensors["output"].tobytes()
    cfg = [0] * 64
    settings = {0: 0x4e505531, 1: 16, 2: 4, 3: record["m"], 4: record["k"],
        5: record["n"], 6: 1, 7: 1, 9: 16, 10: runner.WORDS, 11: runner.WORDS,
        12: 0, 13: 1, 14: locations["lhs"], 15: locations["rhs"],
        16: locations["bias"], 17: dst, 18: record["k"], 19: record["k"],
        20: record["n"], 21: record["input_offset"], 22: 0,
        23: record["output_offset"], 24: locations["multipliers"], 25: locations["shifts"],
        26: record["activation_min"], 27: record["activation_max"]}
    for index, value in settings.items():
        cfg[index] = value & 0xffffffff
    if schedule is None:
        schedule = planner.schedule(planner_library, cfg, tensors["rhs"].tobytes())
    cfg[6], cfg[7], cfg[8] = (schedule[key] for key in ("ia_reuse", "w_reuse", "dataflow_mode"))
    cfg[30] = schedule["row_groups"] | schedule["col_groups"] << 16
    cfg[31] = schedule["row_tail_tiles"] | schedule["col_tail_tiles"] << 16
    cfg[61], cfg[62] = schedule["ps_control"], schedule["ia_bank_count"]
    (target / "config.mem").write_text("".join(f"{value & 0xffffffff:08x}\n" for value in cfg))
    (target / "required.mem").write_text("@00000000\n0\n")
    runner.sparse_mem(target / "init.mem", image)
    runner.sparse_mem(target / "golden.mem", golden)
    runner.accumulator_mem(target / "acc.mem", tensors["accumulators"].ravel())
    selected = dict(name=record["name"], model=record["model"], sample=record["sample"],
        operator_index=record["operator_index"], m=record["m"], k=record["k"], n=record["n"],
        corpus_manifest_sha256=digest(manifest), configuration=cfg, schedule=schedule,
        physical_memory_bytes=57344, dataflow="IS" if cfg[8] else "WS",
        ia_stream="rhs" if cfg[8] else "lhs",
        ia_statistics=storage_statistics(tensors["rhs"] if cfg[8] else tensors["lhs"],
                                        0 if cfg[8] else record["input_offset"]),
        file_sha256={name: digest(target / name) for name in (
            "config.mem", "init.mem", "golden.mem", "required.mem", "acc.mem")})
    save(target / "case.json", selected)
    return selected


def prepare(args, runner, planner):
    catalogue = json.loads((args.corpus / "corpus.json").read_text())
    libraries = {}
    for enabled in (0, 1):
        selected = profile(enabled)
        save(args.out / f"profile_{enabled}.json", selected)
        libraries[enabled] = planner.planner(SimpleNamespace(repo=ROOT),
            args.out / f"planner_{enabled}", selected, profile_header(selected))
    cases = []
    for item in catalogue["cases"]:
        manifest = args.corpus / item["manifest"]
        if digest(manifest) != item["manifest_sha256"]:
            raise ValueError("Corpus manifest changed")
        source = manifest.parent
        variants = {}
        for label, enabled, fixed in (("off_auto", 0, False), ("on_fixed", 1, True), ("on_auto", 1, False)):
            directory = args.out / "cases" / item["name"] / label
            selected_schedule = variants["off_auto"]["record"]["schedule"] if fixed else None
            result = prepare_case(runner, planner, libraries[enabled], source, directory, selected_schedule)
            variants[label] = dict(directory=str(directory), record=result, compact=enabled)
        cases.append(dict(name=item["name"], variants=variants))
    save(args.out / "prepared.json", dict(corpus_sha256=digest(args.corpus / "corpus.json"), cases=cases))
    print(json.dumps(dict(prepared=True, cases=len(cases))))


def validated_binary(build):
    metadata = json.loads((build / "build.json").read_text())
    binary = build / "obj/Vtb_conv_npu"
    if metadata["returncode"] or not metadata["sources_unchanged_during_build"]:
        raise ValueError("The simulator build did not complete from stable sources")
    if digest(binary) != metadata["binary_sha256"]:
        raise ValueError("Simulator executable differs from its build record")
    snapshot = build / "source_inputs"
    recorded = build / "source_inputs.json"
    if not recorded.exists():
        for name, expected in metadata["source_sha256"].items():
            source = Path(metadata["source_root"]) / name if name.startswith(("rtl/", "include/")) else ROOT / name
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError(f"Simulator input changed before it was saved: {source}")
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        save(recorded, metadata["source_sha256"])
    if json.loads(recorded.read_text()) != metadata["source_sha256"]:
        raise ValueError("Saved source inventory differs from the simulator build")
    for name, expected in metadata["source_sha256"].items():
        source = snapshot / name
        if digest(source) != expected:
            raise ValueError(f"Simulator input changed: {source}")
    return binary, metadata


def run(args, runner):
    prepared = json.loads((args.out / "prepared.json").read_text())
    executables = {enabled: validated_binary(args.builds / f"compile_{enabled}") for enabled in (0, 1)}
    for enabled, (_, metadata) in executables.items():
        expected = dict(size=16, bus_width=64, vector_pe_count=16, cache_data_bytes=4096,
                        cache_line_bytes=128, shared_bank_bytes=8192, shared_bank_count=7,
                        ps_compress=True, force_raw=True, ia_compact_enable=enabled)
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Simulator parameters differ from the planner profile")
    measurements = {}
    for label, enabled in (("off_auto", 0), ("on_fixed", 1), ("on_auto", 1)):
        directories = [Path(item["variants"][label]["directory"]) for item in prepared["cases"]]
        result = runner.run_suite(executables[enabled][0], args.out, label, directories,
                                 no_random=True, timeout=args.timeout)
        save(args.out / (label + ".json"), result)
        if not result["passed"]:
            raise RuntimeError(f"GEMM comparison failed: {label}")
        measurements[label] = result["measurements"]
    results = []
    totals = defaultdict(lambda: dict(off_cycles=0, fixed_cycles=0, auto_cycles=0,
                                     off_read_bytes=0, fixed_read_bytes=0, auto_read_bytes=0, cases=0))
    for index, case in enumerate(prepared["cases"]):
        values = {label: rows[index] for label, rows in measurements.items()}
        record = case["variants"]["off_auto"]["record"]
        for label, enabled in (("off_auto", 0), ("on_fixed", 1), ("on_auto", 1)):
            row = values[label]
            if row["ia_compact_capable"] != enabled or row["ia_compact_active"] != enabled:
                raise ValueError("Runtime IA mode differs from the requested compiled variant")
            if row["int32_checks"] != record["m"] * record["n"]:
                raise ValueError("The independent INT32 reference did not cover every output")
        off, fixed, auto = (values[label]["cycles"] for label in ("off_auto", "on_fixed", "on_auto"))
        results.append(dict(name=case["name"], model=record["model"], m=record["m"], k=record["k"], n=record["n"],
            measurements=values, fixed_speedup=off / fixed, auto_speedup=off / auto,
            schedules={label: case["variants"][label]["record"]["schedule"] for label in values}))
        for key in (record["model"], "all"):
            total = totals[key]
            total["cases"] += 1
            total["off_cycles"] += off
            total["fixed_cycles"] += fixed
            total["auto_cycles"] += auto
            for prefix, label in (("off", "off_auto"), ("fixed", "on_fixed"), ("auto", "on_auto")):
                total[prefix + "_read_bytes"] += values[label]["ar_bytes"]
    for total in totals.values():
        total.update(fixed_speedup=total["off_cycles"] / total["fixed_cycles"],
                     auto_speedup=total["off_cycles"] / total["auto_cycles"])
    report = dict(passed=True, cases=results, totals=dict(totals),
        physical_memory_bytes=57344, clock_frequency_mhz=150,
        cycles="calc_start accepted through done_valid, excluding completion backpressure",
        prepared_sha256=digest(args.out / "prepared.json"),
        build_manifests={str(enabled): digest(args.builds / f"compile_{enabled}/build.json") for enabled in (0, 1)},
        simulates_end_to_end_model=False)
    save(args.out / "summary.json", report)
    print(json.dumps(dict(passed=True, totals=dict(totals)), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--builds", type=Path)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.corpus = args.corpus.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    runner = load_module("ia_npu_runner", ROOT / "test/conv_npu/run.py")
    planner = load_module("ia_storage_planner", ROOT / "test/gemmini_comparison/run_storage_operators.py")
    if not args.skip_prepare:
        prepare(args, runner, planner)
    if args.build or args.build_only:
        if args.builds is None:
            parser.error("--builds is required for compilation")
        for enabled in (0, 1):
            print(f"BUILD_IA_COMPACT {enabled}", flush=True)
            runner.build(args.builds / f"compile_{enabled}", 16, "verilator", args.jobs,
                cache_sets=16, cache_policy=3, ps_compress=True, pool_bytes=16384, force_raw=True,
                bus_width=64, shared_bank_bytes=8192, shared_bank_count=7, ps_frame_count=16,
                source_root=args.source_root, cache_line_bytes=128, address_width=19,
                vector_pe_count=16, ia_compact_enable=enabled)
            print(f"BUILD_PASS {enabled}", flush=True)
    if not args.prepare_only and not args.build_only:
        if args.builds is None:
            parser.error("--builds is required for RTL execution")
        run(args, runner)


if __name__ == "__main__":
    main()
