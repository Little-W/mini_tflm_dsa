#!/usr/bin/env python3
"""Export the fastest verified official schedule for each workload and capacity."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("command_generator",
                                            HERE.parent / "gemmini_command_trace/generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def replace_argument(command, key, value):
    if key not in command:
        command.extend([key, str(value)])
    else:
        command[command.index(key) + 1] = str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--searches", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    candidates = {}
    searches = []
    for directory in args.searches:
        directory = directory.resolve()
        aggregate = json.loads((directory / "results.json").read_text())
        if not aggregate["search_complete"]:
            raise ValueError("Schedule search has not completed: " + str(directory))
        searches.append({"directory": str(directory),
                         "results_sha256": digest(directory / "results.json")})
        for report in aggregate["cases"]:
            key = report["profile"], report["name"]
            case_dir = directory / key[0] / key[1]
            best = json.loads((case_dir / "best.json").read_text())
            if best["status"] != "passed":
                raise ValueError("Selected schedule did not pass RTL validation")
            source = case_dir / best["name"]
            if digest(source / "commands.txt") != best["commands_sha256"]:
                raise ValueError("Measured command stream changed")
            meta = json.loads((case_dir / "input/metadata.json").read_text())
            if meta["workload_manifest_sha256"] != report["workload_manifest_sha256"]:
                raise ValueError("Search and input workload definitions differ")
            result = best["result"]
            if (not result["passed"] or not result["memory_drained"] or
                    result["outside_output_mismatches"] or
                    best["observed_output_sha256"] != meta["expected_output_sha256"]):
                raise ValueError("Selected schedule failed output or memory checks")
            candidate = {"search": str(directory), "profile": key[0], "name": key[1],
                         "transpose": report.get("transpose", "none"),
                         "tensor_alignment_bytes": meta.get("tensor_alignment_bytes", 64),
                         "hardware_dma_max_bytes": report.get("hardware_dma_max_bytes", 64),
                         "flow": best["flow"], "tile": best["tile"],
                         "cycles": best["cycles"], "source": str(source),
                         "workload_manifest_sha256": meta["workload_manifest_sha256"],
                         "expected_output_sha256": meta["expected_output_sha256"],
                         "commands_sha256": best["commands_sha256"],
                         "all_legal_tiles_considered": report["exhaustive_legal_tiles"]}
            candidates.setdefault(key, []).append((candidate, meta, best))
    expected_keys = set(candidates)
    for directory in args.searches:
        report = json.loads((directory / "results.json").read_text())
        keys = {(case["profile"], case["name"]) for case in report["cases"]}
        if keys != expected_keys:
            raise ValueError("Search directories contain different workloads or capacities")
    selected = []
    for key, options in sorted(candidates.items()):
        if len({(item[0]["workload_manifest_sha256"], item[0]["expected_output_sha256"])
                for item in options}) != 1:
            raise ValueError("Candidate layouts do not represent the same computation")
        candidate, meta, best = min(options, key=lambda item: item[0]["cycles"])
        source = Path(candidate["source"])
        inputs = source.parent / "input"
        target = output / key[0] / "traces" / key[1]
        target.mkdir(parents=True, exist_ok=True)
        for filename in ("memory.bin", "expected_s8.bin"):
            shutil.copyfile(inputs / filename, target / filename)
        for filename in ("commands.txt", "emission.json"):
            shutil.copyfile(source / filename, target / filename)
        for filename, field in (("memory.bin", "memory_sha256"),
                                ("expected_s8.bin", "expected_output_sha256")):
            if digest(target / filename) != meta[field]:
                raise ValueError("Selected input payload checksum differs")
        meta["emission"] = json.loads((target / "emission.json").read_text())
        meta["commands_sha256"] = candidate["commands_sha256"]
        meta["transpose"] = candidate["transpose"]
        meta["selected_schedule"] = candidate
        workload = json.loads(Path(meta["workload_manifest"]).read_text())
        meta["validation"] = generator.validate_trace(
            generator.read_trace(target / "commands.txt"), workload, meta["tensors"],
            candidate["flow"], meta["emission"]["config"])
        command = list(meta["generator_command"])
        for flag, value in (("--memory", target / "memory.bin"),
                            ("--commands", target / "commands.txt"),
                            ("--metadata", target / "emission.json"),
                            ("--flow", candidate["flow"])):
            replace_argument(command, flag, value)
        if candidate["tile"] is not None:
            replace_argument(command, "--tile", ",".join(map(str, candidate["tile"])))
        meta["generator_command"] = command
        save(target / "metadata.json", meta)
        save(target / "selection.json", {"selected": candidate,
                                          "candidates": [item[0] for item in options]})
        selected.append(dict(candidate, metadata=str(target / "metadata.json")))
    save(output / "selection.json", {"searches": searches, "cases": selected})
    with (output / "selected_cycles.csv").open("w", newline="") as stream:
        fields = ["profile", "name", "cycles", "transpose", "tensor_alignment_bytes",
                  "hardware_dma_max_bytes", "flow", "tile", "metadata"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: (json.dumps(row[field]) if field == "tile" else row[field])
                         for field in fields} for row in selected)
    print("Selected verified schedules:", len(selected))


if __name__ == "__main__":
    main()
