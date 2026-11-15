#!/usr/bin/env python3
"""Archive the completed 10 + 2 + 1 SoC runs without generated simulator C++."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.destination.resolve()
    if dest.exists():
        raise SystemExit(f"refusing to overwrite an existing evidence directory: {dest}")
    summaries = ["summary.json", "latency4_summary.json", "is_summary.json"]
    all_results = []
    for name in summaries:
        data = json.loads((source / name).read_text())
        assert data["passed"]
        all_results.extend(data["results"])
    assert len(all_results) == 13 and all(r["passed"] for r in all_results)
    source_checks = {}
    manifests = ["sim/build.json", "firmware_df0/firmware.json", "firmware_df1/firmware.json"]
    for name in manifests:
        data = json.loads((source / name).read_text())
        mismatches = [file for file, value in data["source_sha256"].items() if sha(ROOT / file) != value]
        if mismatches:
            raise SystemExit(f"sources changed since {name}: {mismatches}")
        source_checks[name] = {"source_files": len(data["source_sha256"]), "all_current_sources_match": True}
    sim_manifest = json.loads((source / "sim/build.json").read_text())
    assert sim_manifest["binary_sha256"] == sha(source / "sim/obj/Vtb_conv_soc_perf")
    assert all(r["simulation_binary_sha256"] == sim_manifest["binary_sha256"] for r in all_results)
    for name in summaries + ["results.csv", "results_extra.csv", "comparisons.csv", "comparisons.json",
                              "smoke.log", "smoke.json"]:
        if (source / name).exists():
            copy_file(source / name, dest / name)
    for name in ["sim/build.json", "sim/compile.log", "sim/reuse.log"]:
        if (source / name).exists():
            copy_file(source / name, dest / name)
    for dirname in ["firmware_df0", "firmware_df1", "firmware_smoke", "initial_cpu_smoke"]:
        if (source / dirname).exists():
            shutil.copytree(source / dirname, dest / dirname)
    # Preserve each newly generated vector tree in its relative position so
    # case metadata remains portable after the archive is moved.
    for summary_name in summaries:
        record = json.loads((source / summary_name).read_text())
        vector_dir = Path(record['vector_generation']['manifest']).parent
        if not (dest / vector_dir).exists():
            shutil.copytree(source / vector_dir, dest / vector_dir,
                            ignore=shutil.ignore_patterns('reference.so', 'driver_tiling_oracle'))
    for result in all_results:
        name = f"{result['layer']}_mode{result['mode']}_lat{result['fixed_response_latency']}"
        src_case, dst_case = source / "cases" / name, dest / "cases" / name
        for filename in ["case.json", "result.json", "result.mem", "run.log"]:
            copy_file(src_case / filename, dst_case / filename)
        compressed = gzip.compress((src_case / "data.mem").read_bytes(), mtime=0)
        (dst_case / "data.mem.gz").write_bytes(compressed)
    for name in ["run.py", "summarize.py", "archive.py", "tb_conv_soc_perf.sv", "benchmark.h",
                 "benchmark.c", "benchmark_baseline.c", "benchmark_baseline_e8.c"]:
        copy_file(HERE / name, dest / "harness_snapshot" / name)
    post = {
        "passed": True, "performance_runs": 13,
        "primary_runs": 10, "extra_latency_runs": 2, "extra_is_runs": 1,
        "register_boot_smoke_is_not_a_performance_run": True,
        "compared_output_bytes": sum(r["cpu_result"]["compared_outputs"] for r in all_results),
        "npu_commands": sum(r["counters"]["call_window"]["jobs"] for r in all_results),
        "conv_commands": sum(r["counters"]["call_window"]["conv_jobs"] for r in all_results),
        "all_runs_same_simulator_binary": True, "simulation_binary_sha256": sim_manifest["binary_sha256"],
        "source_checks": source_checks,
        "omitted_generated_artifacts": "Simulator executable, generated C++, object files and PCH; their binary/source hashes remain in the manifests.",
        "memory_image_format": "case data.mem.gz decompresses to the exact sparse $readmemh input recorded by case.json",
    }
    (dest / "post_run_validation.json").write_text(json.dumps(post, indent=2) + "\n")
    index = {str(p.relative_to(dest)): {"sha256": sha(p), "bytes": p.stat().st_size}
             for p in sorted(dest.rglob("*")) if p.is_file()}
    (dest / "evidence_index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(dest)
    print(json.dumps(post, indent=2))


if __name__ == "__main__":
    main()
