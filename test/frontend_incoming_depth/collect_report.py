#!/usr/bin/env python3
"""核对固定源码与验证结果，生成前端接收路径的测量报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=HERE / "measurement.json")
    args = parser.parse_args()
    base = args.results.resolve()
    names = ("formal", "channel_formal", "local", "channel_local", "window")
    reports = {name: json.loads((base / name / "summary.json").read_text()) for name in names}
    source_sha = digest(ROOT / SOURCE)
    reference = reports["formal"]["reference_commit"]
    reference_sha = hashlib.sha256(read_rtl_source(reference + ":" + SOURCE, cwd=ROOT)).hexdigest()
    for name, row in reports.items():
        if not row["passed"]:
            raise RuntimeError("Incomplete validation: " + name)
        if name != "window" and (row["source_sha256"] != source_sha or row["reference_sha256"] != reference_sha):
            raise RuntimeError("Source digest differs: " + name)
    window = reports["window"]
    if window["frontend_source_sha256"] != source_sha or window["reference_frontend_sha256"] != reference_sha:
        raise RuntimeError("The numeric model differs from the mapped source")
    if not window["resident_stream_cycle_equivalent"] or not window["transaction_statistics_equivalent"]:
        raise RuntimeError("Window comparison incomplete")
    changed = subprocess.check_output(["git", "diff", "--name-only", reference, "--", "rtl"], cwd=ROOT, text=True).splitlines()
    if changed != [SOURCE]:
        raise RuntimeError("Unexpected production RTL changes")
    if not reports["formal"]["unchanged_outside_compared_regions_and_channel_process"] or \
            not reports["channel_formal"]["other_main_process_unchanged_after_removing_channel_assignments"]:
        raise RuntimeError("The source composition checks are incomplete")
    for name, expected in reports["formal"]["common_source_sha256"].items():
        if digest(ROOT / name) != expected or hashlib.sha256(read_rtl_source(reference + ":" + name, cwd=ROOT)).hexdigest() != expected:
            raise RuntimeError("A common arithmetic source changed")
    numeric = next(line for line in window["tests"] if line.startswith("WINDOW_DMA_PASS "))
    resident = next(line for line in window["tests"] if line.startswith("CASE consecutive_hits "))
    numbers = lambda line: {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}
    measurement = dict(passed=True, reference_commit=reference, frontend_path=SOURCE,
        source_sha256=source_sha, reference_sha256=reference_sha,
        rtl_changes=[SOURCE], cycles_preserved=True,
        formal=dict(combinational_cases=reports["formal"]["cases"],
            channel_cases=reports["channel_formal"]["cases"],
            total_cases=len(reports["formal"]["cases"]) + len(reports["channel_formal"]["cases"]),
            inputs_constrained=False, channel_bits=16,
            actual_ready_valid_last_expressions=True,
            source_composition_checked=True,
            official_library_sha256=reports["channel_formal"]["official_library_sha256"],
            official_lut_models_sha256=reports["channel_formal"]["official_lut_models_sha256"]),
        mapping={}, window=dict(fpga=True, transactions=numbers(numeric), resident=numbers(resident),
            resident_trace_lines=window["resident_stream_cycles"],
            resident_trace_sha256=window["resident_stream_sha256"],
            resident_stream_cycle_equivalent=True, transaction_statistics_equivalent=True,
            executable_sha256=window["executable_sha256"],
            reference_executable_sha256=window["reference"]["executable_sha256"],
            tests=window["tests"]),
        report_sha256={name: digest(base / name / "summary.json") for name in names},
        script_sha256={path.name: digest(path) for path in sorted(HERE.glob("*.py"))})
    for name in ("local", "channel_local"):
        row = reports[name]
        result = dict(boundary=row["boundary"], mapping=row["mapping"], cases={})
        for label, case in row["cases"].items():
            folder = base / name / label
            for filename, key in (("mapped.json", "mapped_sha256"), ("pre_lut.il", "pre_lut_sha256"), ("mapping.log", "log_sha256")):
                if digest(folder / filename) != case[key]:
                    raise RuntimeError("Mapped artifact changed: " + str(folder / filename))
            if not all(path["graph_complete"] for path in case["paths"].values()) or not case["abc9_equivalent"]:
                raise RuntimeError("Incomplete mapped dependency or equivalence check")
            result["cases"][label] = dict(resources=case["resources"],
                paths={key: dict(cells=value["longest_register_path_cells"], graph_complete=True)
                       for key, value in case["paths"].items()},
                longest=case["paths"]["all" if name == "local" else "all_to_channel"]["distinct_register_path_groups"][:1],
                wrapper_sha256=case["source_sha256"], mapped_sha256=case["mapped_sha256"],
                pre_lut_sha256=case["pre_lut_sha256"], log_sha256=case["log_sha256"], abc9_equivalent=True)
        measurement["mapping"][name] = result
    args.out.write_text(json.dumps(measurement, ensure_ascii=False, indent=2) + "\n")
    print("FRONTEND_INCOMING_DEPTH_PASS", source_sha)


if __name__ == "__main__":
    main()
