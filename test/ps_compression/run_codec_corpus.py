#!/usr/bin/env python3
"""Compare exact INT32 codecs on validated PS rows from recorded RTL runs."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time

from stream_soc_trace import event_lines, verify as verify_stream
from planner_profile import normalize_profile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PAYLOAD_WORD_BYTES = 16
INT32_ROW_BYTES = 64


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_hashes():
    sources = [Path(__file__), HERE / "codec_corpus_compare.cpp",
               HERE / "cpp_adaptive_codec.hpp", HERE / "cpp_row_codec.hpp",
               HERE / "stream_soc_trace.py",
               HERE / "planner_profile.py",
               ROOT / "rtl/npu/gempact/ps_adaptive_codec.sv",
               ROOT / "rtl/npu/gempact/ps_frame_store.sv"]
    return {str(path.relative_to(ROOT)): digest(path) for path in sources}


def simulator_geometry(path):
    path = path.resolve()
    if path.is_dir():
        path /= "build.json"
    manifest = json.loads(path.read_text())
    require(manifest.get("returncode") == 0 and
            manifest.get("sources_unchanged_during_build") is True,
            "The simulator requires a successful build with stable source hashes")
    require(isinstance(manifest.get("binary_sha256"), str) and
            len(manifest["binary_sha256"]) == 64, "Missing simulator executable hash")
    for name in ("rtl/npu/gempact/ps_adaptive_codec.sv", "rtl/npu/gempact/ps_frame_store.sv"):
        require(manifest.get("source_sha256", {}).get(name) == digest(ROOT / name),
                f"Selected simulator uses a different codec source: {name}")
    profile = normalize_profile(manifest, root=ROOT)
    geometry = {key: profile[key] for key in ("bus_width", "shared_bank_bytes",
        "shared_bank_count", "shared_total_bytes", "ps_directory_rows",
        "ps_directory_bits_per_row")}
    geometry.update(payload_word_bits=128, payload_word_bytes=PAYLOAD_WORD_BYTES,
                    int32_row_lanes=16, int32_lane_bits=32, int32_row_bytes=INT32_ROW_BYTES,
                    external_axi_beat_bytes=profile["bus_width"] // 8)
    return dict(build_manifest=str(path), build_manifest_sha256=digest(path),
                simulator_sha256=manifest["binary_sha256"], geometry=geometry,
                recorded_profile=manifest.get("profile", manifest))


def recorded_cases(path, summary):
    """Yield one trace and its matrix jobs, retaining the recorded selection."""
    require(summary.get("passed") is True, f"Input report did not pass: {path}")
    for run in summary["results"]:
        require(run.get("passed") is True, f"Input case did not pass: {path}")
        if "case_dir" in run:
            if run["kind"] != "trace":
                continue
            directory = Path(run["case_dir"])
            policy = directory.parts[-4]
            metadata = dict(case=str(directory), model=run["model_id"],
                            sample=run["sample_index"], policy=policy,
                            input_sha256=run["input_sha256"],
                            simulator_sha256=run["sim_binary_sha256"],
                            firmware_elf_sha256=run["firmware_elf_sha256"])
            pairs = []
            for job in run["jobs"]:
                if job["vector"]:
                    continue
                layers = [layer for layer in run["gemm_layers"]
                          if layer["start_cycle"] <= job["cycle"] < layer["end_cycle"]]
                require(len(layers) == 1, "Matrix job must belong to one operator")
                pairs.append((job, layers[0]))
        else:
            directory = path.parent / "cases" / run["name"]
            policy = "raw" if run["ps_control"] & 1 else "adaptive"
            metadata = dict(case=run["name"], model=run["model"],
                            sample=run["sample"], policy=policy,
                            input_sha256=run["input_sha256"],
                            simulator_sha256=run["simulator_sha256"],
                            firmware_elf_sha256=run["firmware_elf_sha256"])
            layer = {key: run[key] for key in
                     ("operator_index", "operator_name", "rows", "reduction", "cols")}
            layer["kind"] = "dense" if run["operator_name"] == "FULLY_CONNECTED" else "conv"
            pairs = [(run["job"], layer)]
        metadata.update(run_log_sha256=run["run_log_sha256"],
                        event_file_sha256=run["ps"]["event_file_sha256"],
                        write_data_sha256=run["ps"]["write_data_sha256"],
                        read_data_sha256=run["ps"]["read_data_sha256"])
        yield directory, metadata, pairs


def extract(summaries, output, hardware, selected_cases=()):
    groups, files, inputs = [], [], []
    seen = set()
    total_rows = 0
    total_replay_checks = 0
    requested, matched = set(selected_cases), set()
    with output.open("wb") as target:
        for path in summaries:
            summary = json.loads(path.read_text())
            inputs.append(dict(path=str(path), sha256=digest(path)))
            for directory, metadata, pairs in recorded_cases(path, summary):
                identifiers = {metadata["case"], str(directory.resolve())}
                if requested and not requested.intersection(identifiers):
                    continue
                matched.update(requested.intersection(identifiers))
                require(metadata["simulator_sha256"] == hardware["simulator_sha256"],
                        "Recorded events and selected simulator have different executable hashes")
                geometry = hardware["geometry"]
                for job, _ in pairs:
                    require(job["ia_bytes"] + job["ps_bytes"] == geometry["shared_total_bytes"] and
                            job["ia_bytes"] == job["ia_banks"] * geometry["shared_bank_bytes"],
                            "Recorded layer allocation differs from the selected shared-bank geometry")
                event_path = (directory / "ps_events.txt").resolve()
                if not event_path.exists():
                    event_path = event_path.with_suffix(event_path.suffix + ".gz")
                require(event_path not in seen, f"Duplicate event file: {event_path}")
                seen.add(event_path)
                log_path = directory / "run.log"
                require(digest(log_path) == metadata["run_log_sha256"],
                        "Run log differs from the recorded report")
                check = verify_stream(event_path, log_path.read_text())
                require(all(check[key] == metadata[key] for key in
                            ("event_file_sha256", "write_data_sha256", "read_data_sha256")),
                        "PS event content differs from the recorded report")
                require(check["summary"]["discarded"] == 0,
                        "Codec corpus requires fully completed frames")
                files.append(dict(path=str(event_path), sha256=digest(event_path),
                                  run_log_path=str(log_path),
                                  run_log_sha256=digest(log_path), stream_check=check))
                total_replay_checks += check["summary"]["reads"] * 16
                mapping = {}
                for job, layer in pairs:
                    require(job["job"] not in mapping, "Duplicate matrix job identifier")
                    group_id = len(groups)
                    mapping[job["job"]] = group_id
                    groups.append(dict(id=group_id, **metadata, job=job, layer=layer,
                                       records=0, first_rows=0, timing=[]))
                active = None
                for line in event_lines(event_path, hashlib.sha256()):
                    kind, *words = line.split()
                    fields = dict(word.split("=", 1) for word in words)
                    if kind == "F":
                        active = {key: int(value) for key, value in fields.items()}
                        active.update(writes=[], reads=[])
                    elif kind in ("W", "R"):
                        active["writes" if kind == "W" else "reads"].append(int(fields["cycle"]))
                        if kind == "R":
                            continue
                        job_id = int(fields["job"])
                        require(job_id in mapping, "Stored PS row has no matrix job")
                        group_id = mapping[job_id]
                        group = groups[group_id]
                        row = int(fields["row"])
                        job = group["job"]
                        raw = bool(job["ps_control"] & 1 or
                                   job["ps_raw_rows"] == job["ps_rows"])
                        data = int(fields["data"], 16).to_bytes(INT32_ROW_BYTES, "little")
                        target.write(struct.pack("<IIII", group_id, int(row == 0), int(raw), row))
                        target.write(data)
                        group["records"] += 1
                        group["first_rows"] += row == 0
                        total_rows += 1
                    elif kind == "E":
                        if active["job"] in mapping:
                            group = groups[mapping[active["job"]]]
                            group["timing"].append(dict(
                                rows=active["rows"], init=active["init"], final=active["final"],
                                accept=active["cycle"], end=int(fields["cycle"]),
                                first_write=active["writes"][0] if active["writes"] else None,
                                last_write=active["writes"][-1] if active["writes"] else None,
                                first_read=active["reads"][0] if active["reads"] else None,
                                last_read=active["reads"][-1] if active["reads"] else None))
                        active = None
                    elif kind == "X":
                        active = None
    for group in groups:
        require(group["records"] == group["job"]["ps_rows"],
                f"Recorded PS count differs for group {group['id']}")
    require(total_rows > 0, "No stored PS rows were found")
    require(matched == requested, "A selected case was not present in the supplied reports")
    return dict(inputs=inputs, files=files, groups=groups, rows=total_rows,
                int32_replay_checks=total_replay_checks, rows_sha256=digest(output))


def metrics(counts):
    raw_payload = counts["rows"] * INT32_ROW_BYTES
    directory = counts["directory_bits"] / 8
    raw_directory = counts["raw_directory_bits"] / 8
    payload = counts["payload_bytes"]
    total = payload + directory
    return dict(**counts, directory_bytes=directory, raw_directory_bytes=raw_directory,
                raw_payload_bytes=raw_payload,
                payload_compression_ratio=raw_payload / payload if payload else None,
                record_compression_ratio=(raw_payload + raw_directory) / total if total else None,
                ratio_to_raw_payload_with_directory=raw_payload / total if total else None,
                average_payload_words=payload / (counts["rows"] * PAYLOAD_WORD_BYTES) if counts["rows"] else 0,
                average_payload_bytes=payload / counts["rows"] if counts["rows"] else 0,
                average_directory_bytes=directory / counts["rows"] if counts["rows"] else 0,
                average_record_bytes=total / counts["rows"] if counts["rows"] else 0,
                mean_nonzero_lanes=counts["nonzero_lanes"] / counts["rows"] if counts["rows"] else 0)


def aggregate(corpus, comparison):
    profiles = {group["id"]: group["profiles"] for group in comparison["groups"]}
    counters = ("rows", "first_rows", "payload_bytes", "useful_bytes", "directory_bits", "raw_directory_bits",
                "nonzero_lanes", "first_payload_bytes")

    def empty():
        return {**{key: 0 for key in counters}, "formats": {}, "words_histogram": [0] * 5}

    def accumulate(target, profile):
        for key in counters:
            target[key] += profile[key]
        for opcode, count in profile["formats"].items():
            target["formats"][opcode] = target["formats"].get(opcode, 0) + count
        for words, count in enumerate(profile["words_histogram"]):
            target["words_histogram"][words] += count

    categories, layer_totals, model_totals, dataflows = [defaultdict(empty) for _ in range(4)]
    observed_bytes = 0
    observed_jobs = []
    for group in corpus["groups"]:
        if not group["records"]:
            continue
        current = profiles[group["id"]]
        observed = next(profile for profile in current if profile["name"] == "observed")
        job = group["job"]
        require(observed["rows"] == job["ps_rows"] and
                observed["payload_bytes"] == job["ps_write_words"] * PAYLOAD_WORD_BYTES and
                observed["formats"].get("3", 0) == job["ps_raw_rows"],
                f"C++ representation differs from recorded RTL words for group {group['id']}")
        observed_bytes += observed["payload_bytes"]
        observed_jobs.append(dict(
            id=group["id"], case=group["case"], policy=group["policy"], model=group["model"],
            sample=group["sample"], operator_index=group["layer"]["operator_index"],
            kind=group["layer"]["kind"], dataflow="IS" if job["is"] else "WS",
            matrix_rows=group["layer"]["rows"], reduction=group["layer"]["reduction"],
            matrix_cols=group["layer"]["cols"], r=job["r"], w=job["w"],
            ia_banks=job["ia_banks"], ps_control=job["ps_control"],
            task_cycles=job["task_cycles"], payload_read_bytes=job["ps_read_words"] * PAYLOAD_WORD_BYTES,
            **metrics({key: value for key, value in observed.items() if key != "name"})))
        for profile in current:
            category = (group["policy"], group["layer"]["kind"], profile["name"])
            layer_key = (group["policy"], group["model"], group["sample"],
                         group["layer"]["operator_index"], profile["name"])
            model_key = (group["policy"], group["model"], group["layer"]["kind"], profile["name"])
            flow_key = (*model_key[:-1], "IS" if group["job"]["is"] else "WS", profile["name"])
            for target in (categories[category], layer_totals[layer_key],
                           model_totals[model_key], dataflows[flow_key]):
                accumulate(target, profile)
    category_results = [dict(policy=policy, kind=kind, profile=profile, **metrics(counts))
                        for (policy, kind, profile), counts in sorted(categories.items())]
    layer_results = [dict(policy=policy, model=model, sample=sample, operator_index=operator,
                         profile=profile, **metrics(counts))
                     for (policy, model, sample, operator, profile), counts in sorted(layer_totals.items())]
    model_results = [dict(policy=policy, model=model, kind=kind, profile=profile, **metrics(counts))
                     for (policy, model, kind, profile), counts in sorted(model_totals.items())]
    flow_results = [dict(policy=policy, model=model, kind=kind, dataflow=flow,
                        profile=profile, **metrics(counts))
                    for (policy, model, kind, flow, profile), counts in sorted(dataflows.items())]
    return dict(recorded_payload_bytes=observed_bytes,
                recorded_payload_read_bytes=sum(group["job"]["ps_read_words"] * PAYLOAD_WORD_BYTES
                                                for group in corpus["groups"]),
                categories=category_results, models=model_results,
                dataflows=flow_results, layers=layer_results, observed_jobs=observed_jobs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, action="append", required=True,
                        help="Passed network or plan-sweep summary; repeat for several corpora")
    parser.add_argument("--sim", type=Path, required=True,
                        help="Selected simulator directory or build.json for physical memory geometry")
    parser.add_argument("--case", action="append", default=[],
                        help="Optional exact recorded case name or absolute case directory; may be repeated")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--recorded-codec", choices=("rice", "adaptive"), default="adaptive",
                        help="Codec used by the recorded RTL: adaptive includes Sparse128 opcode 7")
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = source_hashes()
    hardware = simulator_geometry(args.sim)
    geometry = hardware["geometry"]
    started = time.monotonic()
    corpus = extract([path.resolve() for path in args.summary], out / "rows.bin", hardware, args.case)
    (out / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n")
    compiler = shutil.which(args.compiler) or args.compiler
    binary = out / "codec_corpus_compare"
    compile_command = [compiler, "-O2", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I" + str(HERE),
                       str(HERE / "codec_corpus_compare.cpp"), "-o", str(binary)]
    with (out / "compile.log").open("w") as log:
        subprocess.run(compile_command, stdout=log, stderr=subprocess.STDOUT, check=True)
    run_command = [str(binary), str(out / "rows.bin"), args.recorded_codec,
                   str(geometry["ps_directory_bits_per_row"])]
    with (out / "comparison.json").open("w") as report, (out / "run.log").open("w") as log:
        subprocess.run(run_command, stdout=report, stderr=log, check=True)
    comparison = json.loads((out / "comparison.json").read_text())
    require(comparison["passed"], "Candidate roundtrip comparison failed")
    require(comparison["physical_directory_bits_per_row"] == geometry["ps_directory_bits_per_row"] and
            comparison["physical_payload_word_bytes"] == PAYLOAD_WORD_BYTES,
            "C++ codec accounting differs from the simulator geometry")
    aggregates = aggregate(corpus, comparison)
    csv_fields = ("policy", "model", "sample", "operator_index", "kind", "dataflow",
                  "matrix_rows", "reduction", "matrix_cols", "r", "w", "ia_banks", "ps_control",
                  "task_cycles", "rows", "payload_bytes", "payload_read_bytes", "directory_bytes",
                  "average_payload_words", "average_payload_bytes", "average_record_bytes", "payload_compression_ratio",
                  "record_compression_ratio", "ratio_to_raw_payload_with_directory",
                  *(f"opcode_{index}" for index in range(8)))
    with (out / "observed_jobs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        for job in aggregates["observed_jobs"]:
            row = {key: job[key] for key in csv_fields if not key.startswith("opcode_")}
            row.update({f"opcode_{index}": job["formats"].get(str(index), 0) for index in range(8)})
            writer.writerow(row)
    unchanged = hashes == source_hashes()
    require(unchanged, "Codec sources changed during comparison")
    require(all(item["sha256"] == digest(item["path"]) for item in corpus["inputs"] + corpus["files"]),
            "Recorded input files changed during comparison")
    require(all(item["run_log_sha256"] == digest(item["run_log_path"]) for item in corpus["files"]),
            "Recorded run logs changed during comparison")
    require(digest(hardware["build_manifest"]) == hardware["build_manifest_sha256"],
            "Simulator build metadata changed during comparison")
    result = dict(passed=True, scope="Offline C++ exact INT32 codec comparison on validated RTL PS events",
                  recorded_codec=args.recorded_codec, rows=corpus["rows"],
                  groups=len(comparison["groups"]), trace_files=len(corpus["files"]),
                  int32_replay_checks=corpus["int32_replay_checks"],
                  int32_candidate_roundtrip_checks=comparison["int32_roundtrip_checks"],
                  hardware=hardware,
                  physical_payload_word_bytes=PAYLOAD_WORD_BYTES,
                  physical_directory_rows=geometry["ps_directory_rows"],
                  physical_directory_bits_per_row=geometry["ps_directory_bits_per_row"],
                  physical_directory_bytes=geometry["ps_directory_rows"] * geometry["ps_directory_bits_per_row"] / 8,
                  current_opcode_names={"0": "COPY", "1": "S16", "2": "S24", "3": "RAW32",
                                        "4": "Rice128", "5": "Rice256", "6": "Rice384", "7": "Sparse128"},
                  directory_accounting="Each encoded record is charged its directory entry; the physical directory is allocated once and reused across frames.",
                  byte_accounting="Payload bytes include padding to 16-byte PS words. Directory bytes are exact bit counts divided by eight; entries are not separately rounded to whole bytes. Useful bytes count the encoded content before PS-word padding.",
                  word_accounting="PS read/write word counters and words_histogram use 128-bit words. INT32 lanes use 32 bits. External AXI beats use the selected simulator bus width.",
                  ratio_accounting="Payload ratio compares 64 bytes per original row with padded payload bytes. Record ratio includes the original hardware directory in its numerator and the candidate directory in its denominator. ratio_to_raw_payload_with_directory excludes the original directory from the numerator.",
                  opcode_accounting="Per-opcode counts are reconstructed by the matching C++ codec from recorded INT32 rows; each job's observed payload words and RAW counts must match RTL counters.",
                  cycle_accounting="Recorded task cycles are retained in corpus.json; candidate codec byte counts do not estimate execution cycles.",
                  source_sha256=hashes, sources_unchanged=unchanged,
                  binary_sha256=digest(binary), rows_sha256=corpus["rows_sha256"],
                  input_summaries=corpus["inputs"], selected_cases=args.case,
                  compiler_version=subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                  undefined_behavior_sanitizer=True,
                  compile_command=compile_command, run_command=run_command,
                  elapsed_seconds=time.monotonic() - started, **aggregates)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("passed", "scope", "rows", "trace_files", "int32_replay_checks",
                       "int32_candidate_roundtrip_checks", "recorded_payload_bytes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
