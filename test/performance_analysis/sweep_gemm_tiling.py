#!/usr/bin/env python3
"""Measure legal WS/IS groups against unchanged shared GEMM operands."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ceildiv(a: int, b: int) -> int:
    return (a + b - 1) // b


def next_power(value: int) -> int:
    return 1 << (value - 1).bit_length()


def plan(m: int, n: int, mode: int, r: int, w: int) -> dict:
    rows, cols = (n, m) if mode else (m, n)
    tr, tc = ceildiv(rows, 16), ceildiv(cols, 16)
    rg, cg = ceildiv(tr, r), ceildiv(tc, w)
    return dict(ia_reuse=r, w_reuse=w, row_groups=rg,
                row_tail_tiles=tr - (rg - 1) * r, col_groups=cg,
                col_tail_tiles=tc - (cg - 1) * w)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--workloads", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--gemmini", nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cases", nargs="+")
    p.add_argument("--jobs", type=int, default=4)
    a = p.parse_args()
    repo, workloads, out = a.repo.resolve(), a.workloads.resolve(), a.out.resolve()
    reference = a.reference.resolve()
    common = load(repo / "test/gemmini_comparison/run_mini.py", "common_gemm_runner")
    runner = common.load_runner(repo)
    before = json.loads((reference / "summary.json").read_text())
    build = json.loads((reference / "sim/build.json").read_text())
    binary = reference / "sim/obj/Vtb_conv_npu"
    if not before["passed"] or digest(binary) != before["binary_sha256"]:
        raise ValueError("Reference binary has not passed its recorded workloads")
    for source, expected in build["source_sha256"].items():
        if digest(repo / source) != expected:
            raise ValueError("Binary and selected RTL differ: " + source)
    if digest(repo / "test/gemmini_comparison/axi_monitor.sv") != build["monitor_sha256"]:
        raise ValueError("Comparison monitor differs")
    original = {x["name"]: x for x in before["cases"]}
    cache_blocks = before["profile"]["ia_cache_blocks"]
    ps_frames = before["profile"]["ps_frames"]
    ps_storage_rows = before["profile"].get("ps_storage_rows", 0)
    targets = {}
    for item in a.gemmini:
        name, filename = item.split("=", 1)
        path = Path(filename).resolve()
        report = json.loads(path.read_text())
        for row in report["cases"]:
            if not row["passed"]:
                raise ValueError("Gemmini reference contains an unsuccessful run")
            targets.setdefault(row["name"], {})[name] = {
                "cycles": row["cycles"], "read_bytes": row["read_bytes"],
                "write_bytes": row["write_bytes"], "source_sha256": digest(path)}
    out.mkdir(parents=True, exist_ok=True)
    catalogue = json.loads((workloads / "workloads.json").read_text())
    work = []
    descriptions = {}
    for entry in catalogue["cases"]:
        if a.cases and entry["name"] not in a.cases:
            continue
        source = workloads / entry["manifest"]
        if digest(source) != entry["manifest_sha256"]:
            raise ValueError("Shared workload manifest differs")
        base = out / "inputs" / entry["name"]
        d = common.prepare_case(runner, source.parent, base, cache_blocks, ps_frames, ps_storage_rows)
        if d["workload_manifest_sha256"] != original[d["name"]]["workload_manifest_sha256"]:
            raise ValueError("Reference workload differs")
        descriptions[d["name"]] = d
        words = [int(x, 16) for x in (base / "config.mem").read_text().split()]
        for mode in (0, 1):
            tr, tc = [ceildiv(x, 16) for x in ((d["n"], d["m"]) if mode else (d["m"], d["n"]))]
            for r in (1, 2, 4, 8, 16):
                if r > next_power(tr) or r > max(1, cache_blocks // 2):
                    continue
                for w in (1, 2, 4, 8, 16):
                    if w > next_power(tc) or w > ps_frames:
                        continue
                    payload_rows = (min(r, tr) * 16 + 15) * (min(w, tc) + 1)
                    if ps_storage_rows and d["k"] > 16 and payload_rows > ps_storage_rows:
                        continue
                    tiling = plan(d["m"], d["n"], mode, r, w)
                    directory = out / "runs" / d["name"] / f'{"is" if mode else "ws"}_r{r}_w{w}'
                    directory.mkdir(parents=True, exist_ok=False)
                    cfg = list(words)
                    cfg[6], cfg[7], cfg[8] = r, w, mode
                    cfg[30] = tiling["row_groups"] | (tiling["col_groups"] << 16)
                    cfg[31] = tiling["row_tail_tiles"] | (tiling["col_tail_tiles"] << 16)
                    (directory / "config.mem").write_text("".join(f"{x:08x}\n" for x in cfg))
                    suite = directory / "gemm.suite"
                    suite.write_text(" ".join(str(x) for x in [directory / "config.mem", base / "init.mem", base / "golden.mem", base / "required.mem"]) + "\n")
                    sr, sc = (d["n"], d["m"]) if mode else (d["m"], d["n"])
                    read_payload = d["k"] * (sr * tiling["col_groups"] + sc * tiling["row_groups"])
                    record = {"name": d["name"], "m": d["m"], "n": d["n"], "k": d["k"],
                              "dataflow": "is" if mode else "ws", "tiling": tiling,
                              "source_manifest_sha256": d["workload_manifest_sha256"],
                              "config_sha256": digest(directory / "config.mem"),
                              "minimum_operand_payload_bytes_for_groups": read_payload,
                              "ps_payload_capacity_bound_bytes": payload_rows * 64,
                              "command": [str(binary), "+SUITE=" + str(suite), "+NO_RANDOM_WAIT", "+NPU_UTIL_TRACE", "+NPU_UTIL_SUMMARY"]}
                    work.append((directory, record))

    def execute(item):
        directory, row = item
        rc = runner.command(row["command"], directory / "run.log", timeout=180)
        text = (directory / "run.log").read_text()
        values = [common.records(text, prefix) for prefix in
                  ("CONV_TASK_PASS", "[NPU_UTIL]", "[NPU_CTRL_UTIL]", "COMMON_TIMING")]
        row["returncode"] = rc
        row["passed"] = rc == 0 and "CONV_NPU_PASS tasks=1" in text and all(len(x) == 1 for x in values)
        if row["passed"]:
            for key, value in zip(("measurement", "utilization", "controller", "timing"), values):
                row[key] = value[0]
            if row["timing"]["done"] != row["measurement"]["cycles"]:
                raise ValueError("Independent timing counters disagree")
        else:
            row["failure_tail"] = text[-4000:]
        (directory / "result.json").write_text(json.dumps(row, indent=2) + "\n")
        return row

    measured = []
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for future in as_completed([pool.submit(execute, item) for item in work]):
            row = future.result()
            measured.append(row)
            if not row["passed"]:
                print(json.dumps({"name": row["name"], "dataflow": row["dataflow"], "tiling": row["tiling"], "passed": False}), flush=True)
    cases = []
    for name, description in descriptions.items():
        choices = [x for x in measured if x["name"] == name and x["passed"]]
        if not choices:
            raise ValueError("No successful schedule: " + name)
        best = min(choices, key=lambda x: x["measurement"]["cycles"])
        reference_row = original[name]
        current_cycles = reference_row["measurement"]["cycles"]
        best_cycles = best["measurement"]["cycles"]
        fastest = min(x["cycles"] for x in targets[name].values())
        result = {"name": name, "m": description["m"], "n": description["n"], "k": description["k"],
                  "reference_cycles": current_cycles, "reference_tiling": reference_row["tiling"],
                  "reference_read_bytes": reference_row["measurement"]["ar_bytes"],
                  "reference_read_requests": reference_row["timing"]["read_commands"],
                  "gemmini": targets[name], "fastest_gemmini_cycles": fastest,
                  "best": best, "schedule_speedup": current_cycles / best_cycles,
                  "faster_than_all_gemmini": best_cycles < fastest,
                  "cycles_to_remove_for_strict_win": max(0, best_cycles - fastest + 1),
                  "cases_measured": len(choices)}
        cases.append(result)
        print(json.dumps({"name": name, "original": current_cycles, "best": best_cycles,
                          "mode": best["dataflow"], "r": best["tiling"]["ia_reuse"], "w": best["tiling"]["w_reuse"],
                          "target": fastest, "all_profiles_faster": result["faster_than_all_gemmini"]}), flush=True)
    result = {"passed": all(x["passed"] for x in measured), "runs": len(measured),
              "source_repository": str(repo), "source_commit": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
              "reference_summary_sha256": digest(reference / "summary.json"),
              "binary_sha256": digest(binary), "binary_sources_match_selected_tree": True,
              "ia_cache_blocks": cache_blocks, "ps_frames": ps_frames,
              "ps_storage_rows": ps_storage_rows,
              "workloads_sha256": digest(workloads / "workloads.json"),
              "conditions": "Same reset state, tensors, quantization, 16x16 array, recorded IA/PS capacities, and AXI memory service. Only WS/IS and legal power-of-two reuse groups vary; last-group counts give the exact tails.",
              "cases": cases,
              "failures": [x for x in measured if not x["passed"]]}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
