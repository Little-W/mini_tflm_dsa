#!/usr/bin/env python3
"""Independently audit archived SoC timing evidence without rerunning simulation."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE_PATH = "drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/riscv_conv_acc.c"
MATMUL_PATH = "drivers/tflm/NMSIS/NN/Source/ExtraAccFunctions/riscv_nn_mat_mult_acc.c"


def read(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    return gzip.decompress(path.with_name(path.name + ".gz").read_bytes())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> dict:
    return json.loads(read(path))


def fnv1a(data: bytes) -> int:
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--summaries", nargs="+", default=["summary.json", "latency4_summary.json", "is_summary.json"])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    out = (args.out or evidence / "fairness_audit").resolve()
    out.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name: str, condition: bool, detail=None) -> None:
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    # Pinned source identities permit an exported source tree without Git history.
    check("original_accelerated_conv_source_is_byte_identical",
          sha(read(HERE / "benchmark_baseline_e8.c")) == 'b7a38e67f1196c35d714de3c74b1f0afa03fd8508ffd7f84c8f5445d6a87d49b')
    check("same_original_accelerated_matmul_source",
          sha(read(ROOT / MATMUL_PATH)) == 'd7a2b9189e2a2b1d70c2082af62c511ba6f2271d58587ff1a995f63df89951c7')

    manifests = [evidence / "sim/build.json"] + sorted(evidence.glob("firmware_df*/firmware.json"))
    source_hashes = {}
    firmware_by_hash = {}
    for path in manifests:
        m = load(path)
        check(str(path.relative_to(evidence)) + ":build_success_and_stable",
              m["returncode"] == 0 and m["sources_unchanged_during_build"])
        for source, expected in m["source_sha256"].items():
            source_path = Path(source) if Path(source).is_absolute() else ROOT / source
            check(source + ":current_source_hash", sha(read(source_path)) == expected)
            source_hashes[source] = expected
        if "elf_sha256" in m:
            check(str(path.parent.name) + ":elf_hash", sha(read(path.parent / "cpu.elf")) == m["elf_sha256"])
            check(str(path.parent.name) + ":boot_image_hash", sha(read(path.parent / "cpu.mem")) == m["mem_sha256"])
            firmware_by_hash[m["elf_sha256"]] = m
    sim = load(evidence / "sim/build.json")
    runtime_identities = {(fw.get("runtime_lib_sha256"), fw.get("compiler_sha256"))
                          for fw in firmware_by_hash.values()}
    check("shared_memory_runtime_and_compiler", len(runtime_identities) == 1)
    for fw in firmware_by_hash.values():
        if fw.get("runtime_lib_sha256") and Path(fw["runtime_lib"]).is_file():
            check("actual_runtime_library_hash", sha(read(Path(fw["runtime_lib"]))) == fw["runtime_lib_sha256"])
        check("optimized_rv32_firmware_flags", all(flag in fw["command"] for flag in
              ["-march=rv32im_zicsr", "-mabi=ilp32", "-O3", "-ffreestanding", "-fno-builtin"]))

    audited = []
    manifest_hashes = {str(path.relative_to(evidence)): sha(read(path)) for path in manifests}
    metadata = {}
    for name in args.summaries:
        summary = load(evidence / name)
        check(name + ":pass", summary["passed"])
        manifest_hashes[name] = sha(read(evidence / name))
        generation = summary["vector_generation"]
        generated_manifest = evidence / generation["manifest"]
        check(name + ":fresh_generation_manifest", not generation["historical_vectors_used"] and
              sha(read(generated_manifest)) == generation["manifest_sha256"])
        generated = load(generated_manifest)
        for source, expected in generated["generation_source_sha256"].items():
            check(name + ":generator_source:" + source, sha(read(ROOT / source)) == expected)
        for r in summary["results"]:
            layer, mode, latency = r["layer"], r["mode"], r["fixed_response_latency"]
            key = (layer, mode, latency)
            check(str(key) + ":not_double_counted", key not in metadata)
            case = evidence / "cases" / f"{layer}_mode{mode}_lat{latency}"
            meta = load(case / "case.json")
            metadata[key] = meta
            log = read(case / "run.log").decode()
            check(str(key) + ":archived_result_matches_summary", load(case / "result.json") == r)
            check(str(key) + ":actual_simulation_pass", r["passed"] and not r["errors"] and
                  r["returncode"] == 0 and "SOC_PERF_PASS" in log and "SOC_PERF_OUTPUT_MISMATCH" not in log)
            check(str(key) + ":same_production_soc_binary", r["simulation_binary_sha256"] == sim["binary_sha256"])
            check(str(key) + ":known_firmware", r["firmware_elf_sha256"] in firmware_by_hash)
            check(str(key) + ":actual_memory_image_hash", sha(read(case / "data.mem")) == r["case_mem_sha256"] == meta["data_mem_sha256"])
            check(str(key) + ":portable_generated_case_path", meta["source_case_relative_to"] == "case_directory")
            source_case = (case / meta["source_case"]).resolve()
            for source, expected in meta["vector_sha256"].items():
                check(str(key) + ":generated_vector_hash:" + source, sha(read(source_case / source)) == expected)
            cpu, window = r["cpu_result"], r["counters"]["call_window"]
            line = re.findall(r"^SOC_PERF_COUNTER scope=call_window (.*)$", log, re.M)
            observed = dict((k, int(v)) for k, v in re.findall(r"(\w+)=(\d+)", line[0])) if len(line) == 1 else {}
            owner_line = re.findall(r"^SOC_PERF_OWNER scope=call_window (.*)$", log, re.M)
            if len(owner_line) == 1:
                observed.update((k, int(v)) for k, v in re.findall(r"(\w+)=(\d+)", owner_line[0]))
            check(str(key) + ":counter_log_matches_json", observed == window)
            begin = re.findall(r"SOC_PERF_PROGRESS cycle=(\d+) value=c0b10001", log)
            end = re.findall(r"SOC_PERF_PROGRESS cycle=(\d+) value=c0b10002", log)
            check(str(key) + ":one_complete_marker_window", len(begin) == len(end) == 1 and int(end[0]) - int(begin[0]) == window["cycles"])
            check(str(key) + ":cycle_subtraction_and_busy_bound",
                  (cpu["end_cycle"] - cpu["start_cycle"]) & 0xffffffff == cpu["total_call_cycles"] and
                  0 < window["npu_busy_cycles"] <= cpu["total_call_cycles"] <= window["cycles"])
            p = meta["parameters"]
            h, w, c, gc, group, kh, kw, oh, ow, co = p[:10]
            expected_jobs = (oh if kh == kw == 1 else (oh * ow + 31) // 32) if mode == 0 else 1
            check(str(key) + ":original_submission_count_and_command_kind",
                  window["jobs"] == window["done_jobs"] == meta["expected_starts"] == expected_jobs and
                  window["conv_jobs"] == int(mode != 0) and window["is_jobs"] == int(mode == 2))
            check(str(key) + ":actual_im2col_dma_owner",
                  (window["ia_im2col_blocks"] > 0) == (mode == 1) and
                  (window["kernel_im2col_blocks"] > 0) == (mode == 2))
            golden = read(source_case / "output.bin")
            check(str(key) + ":all_original_outputs_match",
                  len(golden) == oh * ow * co == cpu["compared_outputs"] and
                  cpu["output_fnv1a"] == fnv1a(golden) and
                  all(cpu[field] == 0 for field in ["nmsis_status", "error", "mismatches", "guard_errors"]))
            if mode != 0:
                check(str(key) + ":no_cpu_tensor_lowering_in_measured_call",
                      r["regions"]["input"]["cpu_read_bus_bytes"] == 0 and
                      r["regions"]["weight"]["cpu_read_bus_bytes"] == 0 and
                      r["regions"]["scratch"]["cpu_read_bus_bytes"] == 0 and
                      r["regions"]["scratch"]["cpu_write_bytes"] == 0 and
                      r["regions"]["scratch"]["npu_read_bytes"] == 0)
            audited.append({"layer": layer, "mode": mode, "latency": latency,
                            "call_cycles": cpu["total_call_cycles"], "npu_busy_cycles": window["npu_busy_cycles"],
                            "non_npu_busy_call_cycles": cpu["total_call_cycles"] - window["npu_busy_cycles"],
                            "marker_extra_cycles": window["cycles"] - cpu["total_call_cycles"],
                            "starts": window["jobs"], "output_bytes": len(golden),
                            "firmware_elf_sha256": r["firmware_elf_sha256"],
                            "npu_read_bytes": window["npu_read_bytes"], "regions": r["regions"]})
    rows = []
    for legacy in [r for r in audited if r["mode"] == 0]:
        hardware = next(r for r in audited if r["layer"] == legacy["layer"] and r["latency"] == legacy["latency"] and r["mode"] == 1)
        key = (legacy["layer"], legacy["latency"])
        a, b = metadata[(key[0], 0, key[1])], metadata[(key[0], 1, key[1])]
        check(str(key) + ":same_elf_for_baseline_and_hardware", legacy["firmware_elf_sha256"] == hardware["firmware_elf_sha256"])
        check(str(key) + ":same_exact_vectors_and_quantization", a["vector_sha256"] == b["vector_sha256"] and a["parameters"] == b["parameters"])
        check(str(key) + ":only_mode_and_expected_start_descriptor_differ",
              all(x == y for i, (x, y) in enumerate(zip(a["config_words"], b["config_words"])) if i not in (2, 36)))
        rows.append({"layer": key[0], "latency": key[1], "legacy_cycles": legacy["call_cycles"],
                     "hardware_ws_cycles": hardware["call_cycles"], "speedup": legacy["call_cycles"] / hardware["call_cycles"],
                     "legacy_npu_busy": legacy["npu_busy_cycles"], "hardware_npu_busy": hardware["npu_busy_cycles"],
                     "legacy_starts": legacy["starts"], "hardware_starts": hardware["starts"],
                     "legacy_npu_read_bytes": legacy["npu_read_bytes"], "hardware_npu_read_bytes": hardware["npu_read_bytes"],
                     "output_bytes": legacy["output_bytes"]})
    report = {"passed": True, "scope": "independent read-only audit; no new simulation or regenerated numerical vectors",
              "audit_script_sha256": sha(read(Path(__file__).resolve())),
              "actual_performance_runs": len(audited), "paired_comparisons": len(rows),
              "total_actual_npu_commands": sum(r["starts"] for r in audited),
              "total_compared_output_elements": sum(r["output_bytes"] for r in audited),
              "mode_run_counts": {str(mode): sum(r["mode"] == mode for r in audited) for mode in (0, 1, 2)},
              "archived_manifest_sha256": manifest_hashes, "source_sha256": source_hashes,
              "checks": checks, "results": audited, "comparisons": rows,
              "interpretation": [
                  "CPU rdcycle measures the complete function call; boot, tensor/guard initialization and output comparison are excluded.",
                  "NPU busy counts come from the slightly wider progress-marker interval; report the marker delta explicitly.",
                  "Call cycles minus busy cycles include CPU preparation, validation, MMIO submission and polling; they are not a measurement of im2col alone.",
                  "The old 1x1 path already submits raw input directly to ordinary GEMM and has no CPU im2col; preserve any slowdown.",
                  "The original 32-row spatial and per-output-row 1x1 submission policies are retained, so end-to-end speedup also includes changed submission granularity.",
                  "CPU native read counters count accepted 32-bit words, including unused byte lanes; NPU counters count addressed AXI bytes.",
                  "Results are operator tests using full original model dimensions and deterministic synthetic tensors, not a trained whole-network accuracy or performance claim."]}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (out / "comparisons.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["layer"])
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({"passed": True, "runs": len(audited), "paired_comparisons": len(rows),
                      "checks": len(checks), "current_source_files": len(source_hashes), "out": str(out)}))


if __name__ == "__main__":
    main()
