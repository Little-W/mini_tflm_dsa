#!/usr/bin/env python3
"""复用固定 Coral RTL 库，检查每方向 64 bit/周期的共同 GEMM 性能。"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time


HERE = Path(__file__).resolve().parent
CORAL_COMMIT = "f385a31b4af454be21063fca1d17351b35a3a99c"
ARCHIVE_SHA = "177b003e89bcaf1a233c8053d5c70708b1c0b08cf5b97f6e487c2af5735457b1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def execute(command, log, timeout=600):
    with Path(log).open("w") as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def input_path(root, relative):
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("模型输入路径必须位于指定目录内: " + relative)
    return path


def portable_model(args):
    source_manifest = args.model_inputs / "model_inputs.json"
    manifest = read(source_manifest)
    assert manifest["format_version"] == 1
    assert manifest["source_commit"] == CORAL_COMMIT
    assert manifest["source_archive_sha256"] == ARCHIVE_SHA
    assert manifest["platform"] == {"system": platform.system(), "machine": platform.machine()}
    assert "Verilator 5.054 " in manifest["verilator"]
    assert manifest["provenance_files_sha256"]
    for relative, expected in manifest["provenance_files_sha256"].items():
        assert sha(input_path(args.model_inputs, relative)) == expected
    upstream = read(args.comparison_root / "coral/UPSTREAM.json")
    assert upstream["commit"] == CORAL_COMMIT
    required_sources = {"coral/rtl/VmeCoreMiniAxi.sv", "coral/rtl/vme_observation.vlt",
                        "coral/upstream/hdl/verilog/sram_backdoor.cc",
                        "coral/upstream/hdl/verilog/sram_backdoor.h",
                        "coral/benchmark/shared_gemm_staged.elf"}
    assert required_sources <= set(manifest["comparison_source_sha256"])
    assert manifest["comparison_source_sha256"]["coral/rtl/VmeCoreMiniAxi.sv"] == upstream["generated_rtl_sha256"]
    source_checks = {}
    for relative, expected in manifest["comparison_source_sha256"].items():
        path = input_path(args.comparison_root, relative)
        assert sha(path) == expected, path
        source_checks[str(path)] = expected
    runtime = args.reference_root / "tools/verilator/include"
    assert {"verilated.h", "verilated_dpi.h", "verilated_threads.h"} <= set(manifest["runtime_headers_sha256"])
    for relative, expected in manifest["runtime_headers_sha256"].items():
        path = input_path(runtime, relative)
        assert sha(path) == expected, path
        source_checks[str(path)] = expected
    required_objects = {"VVmeCoreMiniAxi__ALL.a", "verilated.o", "verilated_dpi.o",
                        "verilated_threads.o", "sram_backdoor.o"}
    names = required_objects | {name for name in manifest["files"] if name.endswith(".h")}
    assert len(names) >= 10 and names == set(manifest["files"])
    for name, row in manifest["files"].items():
        assert Path(name).name == name
        path = input_path(args.model_inputs, name + ".gz")
        assert sha(path) == row["compressed_sha256"], path
        assert path.stat().st_size == row["compressed_bytes"], path
    return source_manifest, manifest, source_checks


def build(args, out):
    destination = out / "build"
    destination.mkdir(exist_ok=True)
    if args.model_inputs:
        source_manifest, manifest, source_checks = portable_model(args)
        rtl_root = args.comparison_root / "coral/upstream"
        commit = manifest["source_commit"]
        object_root = args.model_inputs
    else:
        source_manifest = args.coral_work / "coral_build/sim_build.json"
        manifest = read(source_manifest)
        source_checks = {}
        for original, expected in manifest["source_sha256"].items():
            relative = original.split("/public_accelerator_work/", 1)[-1]
            path = args.coral_work / relative
            assert path.is_file() and sha(path) == expected, path
            source_checks[str(path)] = expected
        rtl_root = args.coral_work / "coralnpu"
        commit = subprocess.check_output(["git", "-C", str(rtl_root), "rev-parse", "HEAD"], text=True).strip()
        assert commit == CORAL_COMMIT
        object_root = args.coral_work / "coral_build/obj"
    names = ["VVmeCoreMiniAxi__ALL.a", "verilated.o", "verilated_dpi.o",
             "verilated_threads.o", "sram_backdoor.o"]
    names += (sorted(name for name in manifest["files"] if name.endswith(".h")) if args.model_inputs
              else [path.name.removesuffix(".gz") for path in sorted(object_root.glob("*.h.gz"))])
    assert len(names) >= 10
    inputs = {}
    for name in names:
        compressed = object_root / (name + ".gz")
        target = destination / name
        with gzip.open(compressed, "rb") as source, target.open("wb") as sink:
            shutil.copyfileobj(source, sink)
        inputs[str(compressed)] = {"compressed_sha256": sha(compressed),
                                  "uncompressed_sha256": sha(target),
                                  "uncompressed_bytes": target.stat().st_size}
        if args.model_inputs:
            expected = manifest["files"][name]
            assert inputs[str(compressed)]["uncompressed_sha256"] == expected["uncompressed_sha256"]
            assert target.stat().st_size == expected["uncompressed_bytes"]
    runtime = args.reference_root / "tools/verilator"
    compiler = shutil.which(args.cxx)
    assert compiler
    common = [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-pthread"]
    include = ["-I" + str(destination), "-isystem", str(runtime / "include"),
               "-isystem", str(runtime / "include/vltstd"), "-I" + str(rtl_root)]
    host = destination / "coral_fair.o"
    binary = destination / "coral_fair"
    commands = [common + include + ["-c", str(HERE / "coral_axi_benchmark.cpp"), "-o", str(host)],
                [compiler, str(host), str(destination / "VVmeCoreMiniAxi__ALL.a"),
                 *[str(destination / name) for name in names[1:5]],
                 "-pthread", "-latomic", "-o", str(binary)],
                common + [str(HERE / "test_axi_byte_service.cpp"), "-o", str(destination / "test_axi_byte_service")],
                [str(destination / "test_axi_byte_service")]]
    started = time.monotonic()
    for index, command in enumerate(commands): execute(command, destination / f"step{index}.log")
    assert "AXI_BYTE_SERVICE_PASS cases=16" in (destination / "step3.log").read_text()
    sources = {str(path): sha(path) for path in [Path(__file__).resolve(),
               HERE / "coral_axi_benchmark.cpp", HERE / "axi_byte_service.hpp",
               HERE / "test_axi_byte_service.cpp"]}
    result = {"passed": True, "source_commit": commit, "source_manifest_sha256": sha(source_manifest),
              "source_checks": source_checks, "reused_model_inputs": inputs,
              "test_sources_sha256": sources, "commands": commands,
              "compiler": compiler, "compiler_sha256": sha(compiler),
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True).strip(),
              "model_verilator_version": manifest["verilator"],
              "runtime_headers_sha256": {str(runtime / "include" / name): sha(runtime / "include" / name)
                 for name in ("verilated.h", "verilated_dpi.h", "verilated_threads.h")},
              "binary": str(binary), "binary_sha256": sha(binary),
              "service_tests": 16, "elapsed_seconds": time.monotonic() - started,
              "model_library_reused": True, "rtl_recompiled": False,
              "portable_model_inputs": bool(args.model_inputs)}
    save(out / "build.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    model = parser.add_mutually_exclusive_group(required=True)
    model.add_argument("--coral-work", type=Path)
    model.add_argument("--model-inputs", type=Path,
                       help="含 model_inputs.json 和压缩对象/头文件的固定模型目录")
    parser.add_argument("--comparison-root", type=Path,
                        help="npu_accelerator_comparison_20261123.zip 的解压目录")
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--public-replay", type=Path, required=True)
    parser.add_argument("--npu-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    if args.model_inputs and not args.comparison_root:
        parser.error("--model-inputs 需要 --comparison-root")
    for key in ("coral_work", "model_inputs", "comparison_root", "reference_root", "public_replay", "npu_run", "out"):
        value = getattr(args, key)
        if value is not None:
            setattr(args, key, value.resolve())
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    building = read(out / "build.json") if args.skip_build else build(args, out)
    assert building["passed"] and sha(building["binary"]) == building["binary_sha256"]
    assert all(sha(path) == value for path, value in building["test_sources_sha256"].items())
    if args.build_only:
        print("CORAL_FAIR_BUILD_PASS", flush=True)
        return
    public = read(args.public_replay / "public_replay_summary.json")
    assert public["passed"] and public["source_archive"]["sha256"] == ARCHIVE_SHA
    source = args.public_replay / "coral"
    if "fair_service" in public:
        fair_path = source / "fair_coral64.json"
        assert sha(fair_path) == public["fair_service"]["coral_results_sha256"]
        fair = read(fair_path)
        assert fair["passed"] and fair["compatibility_128_checked"]
        old_rows = {row["name"]: row for row in fair["compatibility_results"]}
        fair_rows = {row["name"]: row for row in fair["results"]}
        suite = []
        for case in public["common_cases"]:
            if case["kind"] != "gemm": continue
            path = source / "cases/external_staged" / case["name"] / "manifest.json"
            assert sha(path) == fair_rows[case["name"]]["input_file_sha256"]["manifest.json"]
            row = read(path)
            assert row["name"] == case["name"] and all(row[key] == case["shape"][key] for key in ("m", "n", "k"))
            assert row["expected_sha256"] == case["output_sha256"]
            suite.append(row)
    else:
        suite = read(source / "cases/external/suite.json")
        old_rows = {row["name"]: row for row in read(source / "coral_results_external_staged.json")["results"]}
    assert len(suite) == len(old_rows) == 31
    npu_summary = read(args.npu_run / "summary.json")
    assert npu_summary["passed"]
    program = (args.comparison_root / "coral/benchmark/shared_gemm_staged.elf" if args.model_inputs
               else args.coral_work / "coral_benchmark/shared_gemm_staged.elf")
    assert sha(program) == public["execution"]["coral_vme"]["program_sha256"]
    rows, all_commands, hashes = [], [], {}
    for service_bytes in (16, 8):
        for case in suite:
            name = case["name"]
            if args.case and name not in args.case: continue
            original = source / "cases/external_staged" / name
            target = out / f"service{service_bytes * 8}" / name
            target.mkdir(parents=True, exist_ok=True)
            for filename in ("setup.txt", "memory.bin", "control.bin", "expected.bin", "expected_padded.bin", "manifest.json"):
                path = original / filename
                shutil.copy2(path, target / filename)
                hashes[str(path)] = sha(path)
            assert sha(target / "memory.bin") == case["memory_sha256"]
            assert sha(target / "control.bin") == case["control_sha256"]
            assert sha(target / "expected.bin") == case["expected_sha256"]
            command = [building["binary"], str(program), str(target), "8", str(service_bytes)]
            started = time.monotonic()
            execute(command, target / "run.log")
            all_commands.append(command)
            result = [json.loads(line) for line in (target / "run.log").read_text().splitlines()
                      if line.startswith("{")]
            assert len(result) == 1
            row = result[0]
            assert row["passed"] and row["mismatches"] == 0 and row["memory_drained"]
            assert not row["partial_services_pending"]
            assert row["read_service_bytes"] == row["read_requested_bytes"]
            assert row["write_service_bytes"] == row["write_requested_bytes"]
            assert row["read_service_max_bytes_per_cycle"] <= service_bytes
            assert row["write_service_max_bytes_per_cycle"] <= service_bytes
            assert row["max_read_outstanding"] <= 4 and row["max_write_outstanding"] <= 4
            assert row["first_read_service_latency_min"] >= 8
            assert row["first_full_read_latency_min"] >= 8 + 16 // service_bytes - 1
            if service_bytes == 8:
                if row["read_full_beats"] >= 2:
                    assert row["read_full_beat_min_interval"] >= 2
                if row["write_full_beats"] >= 2:
                    assert row["write_full_beat_min_interval"] >= 2
            old = old_rows[name]
            if service_bytes == 16:
                for key, value in old.items():
                    if key in row and isinstance(value, (int, float, bool)):
                        assert row[key] == value, (name, key, row[key], value)
            for key in ("read_requested_bytes", "write_requested_bytes", "read_beats", "write_beats",
                        "written_bytes", "expected_matrix_instructions", "vme_pe_command_handshakes"):
                assert row[key] == old[key], (name, key)
            actual = (target / "actual.bin").read_bytes()
            npu = args.npu_run / "gemm/cases" / name
            references = {"expected": target / "expected.bin", "coral_public": original / "actual.bin",
                          "npu": npu / "canonical_output.bin",
                          "gemmini": args.public_replay / "gemmini/gemm" / (name + ".output.bin"),
                          "vta": args.public_replay / "vta/cases" / name / "actual.bin"}
            for path in references.values(): assert actual == path.read_bytes(), (name, path)
            assert len(actual) == case["m"] * case["n"]
            npu_result = read(npu / "result.json")
            row.update(name=name, source_commit=CORAL_COMMIT, dense_macs=case["dense_macs"],
                       output_sha256=sha(target / "actual.bin"),
                       input_file_sha256={filename: sha(target / filename) for filename in
                         ("setup.txt", "memory.bin", "control.bin", "expected.bin", "expected_padded.bin", "manifest.json")},
                       compared_output_sha256={key: sha(path) for key, path in references.items()},
                       original_128_cycles=old["drained_cycles"], npu_cycles=npu_result["measurement"]["cycles"],
                       all_outputs_equal=True, wall_seconds=time.monotonic() - started)
            rows.append(row)
            save(target / "result.json", row)
            print(f"CORAL_SERVICE_PASS bits={service_bytes * 8} case={name} cycles={row['drained_cycles']}", flush=True)
    selected = bool(args.case)
    fair = [row for row in rows if row["effective_service_bits"] == 64]
    compatible = [row for row in rows if row["effective_service_bits"] == 128]
    assert len(fair) == len(compatible) and (selected or len(fair) == 31)
    assert all(sha(path) == value for path, value in building["test_sources_sha256"].items())
    assert all(sha(path) == value for path, value in hashes.items())
    summary = {"passed": True, "selected_cases": selected, "case_count": len(fair),
               "source_commit": CORAL_COMMIT, "source_archive_sha256": ARCHIVE_SHA,
               "physical_axi_bits": 128, "effective_service_bits_per_direction": 64,
               "physical_memory_bytes": 2097152, "first_read_service_latency": 8,
               "first_16byte_read_latency_min": 9, "outstanding_reads": 4, "outstanding_writes": 4,
               "int8_products_per_cycle": 256, "clock_unit": "cycles",
               "primary_cycle_metric": "drained_cycles", "binary_sha256": building["binary_sha256"],
               "program_sha256": sha(program), "build_manifest_sha256": sha(out / "build.json"),
               "npu_source_commit": npu_summary["source_commit"], "npu_summary_sha256": sha(args.npu_run / "summary.json"),
               "public_replay_summary_sha256": sha(args.public_replay / "public_replay_summary.json"),
               "output_values": sum(row["output_elements"] for row in fair),
               "coral64_cycles": sum(row["drained_cycles"] for row in fair),
               "coral128_cycles": sum(row["drained_cycles"] for row in compatible),
               "npu_cycles": sum(row["npu_cycles"] for row in fair),
               "compatibility_128_checked": True, "all_outputs_equal": True,
               "service_tests": building["service_tests"], "source_unchanged": True,
               "commands": all_commands, "input_sources_sha256": hashes,
               "results": fair, "compatibility_results": compatible}
    name = "fair_coral64_selected" if selected else "fair_coral64"
    save(out / (name + ".json"), summary)
    columns = ["name", "m", "n", "k", "dense_macs", "npu_cycles", "original_128_cycles", "drained_cycles",
               "read_service_bytes", "write_service_bytes", "read_service_cycles", "write_service_cycles",
               "read_full_beats", "write_full_beats", "read_full_beat_min_interval", "write_full_beat_min_interval",
               "output_elements", "output_sha256"]
    with (out / (name + ".csv")).open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row[key] for key in columns} for row in fair)
    print(f"CORAL_FAIR_PASS cases={len(fair)} values={summary['output_values']} cycles={summary['coral64_cycles']}")


if __name__ == "__main__":
    main()
