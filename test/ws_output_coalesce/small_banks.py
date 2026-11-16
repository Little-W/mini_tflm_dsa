#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run complete matrix tasks with one and two S8 output FIFO banks."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/ws_output_small_banks")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    common = module("common_matrix_runner", ROOT / "test/gemmini_comparison/run_mini.py")
    generator = module("common_matrix_generator", ROOT / "test/gemmini_comparison/prepare.py")
    runner = common.load_runner(ROOT)
    workloads = args.out / "workloads"
    names = []
    for m in (1, 2, 9, 15, 16, 17, 31, 33):
        name = f"m{m}_n32_k17"
        generator.case(workloads, name, m, 32, 17, {"kind": "output_fifo_capacity"}, 20261116)
        names.append(name)
    summary = dict(passed=True, profiles=[])
    for banks in (1, 2):
        directory = args.out / f"banks{banks}"
        build = directory / "sim"
        build.mkdir(parents=True, exist_ok=True)
        parameters = SimpleNamespace(verilator=args.verilator, jobs=args.jobs,
            ia_cache_blocks=2, ps_frames=banks, ps_storage_rows=799,
            s16_output_banks=4, cache_sets=128, cache_policy=3)
        cases = [common.prepare_case(runner, workloads / name, directory / "cases" / name,
            2, banks, 799, schedule_mode="auto", dataflow="ws", layout="both-packed",
            s16_output_banks=4) for name in names]
        binary = common.build_comparison(runner, ROOT, build, parameters)
        suite = directory / "tasks.suite"
        suite.write_text("".join(" ".join(str(directory / "cases" / name / file)
            for file in ("config.mem", "init.mem", "golden.mem", "required.mem")) + "\n"
            for name in names))
        runs = []
        for random_wait in (False, True):
            label = "random_axi" if random_wait else "fixed_axi"
            log = directory / (label + ".log")
            command = [binary, "+SUITE=" + str(suite)] + ([] if random_wait else ["+NO_RANDOM_WAIT"])
            code = runner.command(command, log, timeout=120)
            text = log.read_text()
            measurements = common.records(text, "CONV_TASK_PASS")
            timings = common.records(text, "COMMON_TIMING")
            passed = code == 0 and len(measurements) == len(cases) and len(timings) == len(cases)
            passed = passed and f"CONV_NPU_PASS tasks={len(cases)}" in text
            if passed:
                assert all(item["error"] == 0 for item in measurements)
                if banks == 2:
                    assert all(item["write_burst_bytes_max"] >= 32 for item in timings)
            for case, measurement, timing in zip(cases, measurements, timings):
                assert measurement["cycles"] == timing["done"]
                measurement["name"] = case["name"]
                measurement["timing"] = timing
            runs.append(dict(passed=passed, returncode=code, random_wait=random_wait,
                tasks=len(cases), measurements=measurements,
                command=[str(value) for value in command],
                log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
            print(f"banks={banks} {label} passed={passed} tasks={len(measurements)}/{len(cases)}", flush=True)
            if not passed:
                print(text[-5000:], flush=True)
                break
        summary["profiles"].append(dict(s8_output_banks=banks, ia_cache_blocks=2,
            ps_frames=banks, ps_storage_rows=799, build_manifest=str(build / "build.json"), runs=runs))
        summary["passed"] = summary["passed"] and all(run["passed"] for run in runs)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if not summary["passed"]:
            break
    raise SystemExit(0 if summary["passed"] else 1)


if __name__ == "__main__":
    main()
