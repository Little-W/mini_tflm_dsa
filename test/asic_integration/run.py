#!/usr/bin/env python3
"""运行 16 路 ASIC 配置的完整 NPU 数值与存储访问检查。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFINES = ["SYNTHESIS=1", "ASIC_SYNTHESIS=1", "ASIC_SRAM=1"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command: list[str], path: Path) -> None:
    with path.open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(str(path) + "\n" + path.read_text()[-8000:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--build-timeout", type=int, default=7200)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--lint-only", action="store_true")
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    executable = shutil.which(args.verilator)
    if executable is None:
        raise RuntimeError("Cannot locate Verilator: " + args.verilator)

    macro = ROOT / "test/requant_group_buffer_memory/sram_functional.sv"
    storage = source_root / "asic/rtl/smic40_sram_1r1w.sv"
    frame_observer = ROOT / "test/frame_address/npu_observer.sv"
    observer_paths, observer_hashes = {}, {}
    observer_directory = out / "observers"
    observer_directory.mkdir(exist_ok=True)
    sys.path.insert(0, str(ROOT / "test/monitors"))
    from observer_text import simulation_text
    for source in sorted((ROOT / "test/monitors").glob("*.sv")):
        content = source.read_text()
        destination = observer_directory / source.name
        destination.write_text(simulation_text(content))
        observer_paths[str(source)] = str(destination)
        observer_hashes[str(source.relative_to(ROOT))] = {
            "source_sha256": digest(source), "model_sha256": digest(destination)}
    extra_sources = [macro, storage, frame_observer]
    extra_hashes = {str(path): digest(path) for path in extra_sources}
    wrapper = out / "verilator_asic"
    wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n" +
        "observers = " + repr(observer_paths) + "\n" +
        "arguments = [observers.get(argument, argument) for argument in sys.argv[1:]]\n" +
        "command = " + repr([executable, *["-D" + value for value in DEFINES],
                              *map(str, extra_sources)]) + " + arguments\n" +
        "os.execv(command[0], command)\n")
    wrapper.chmod(0o755)
    command = [sys.executable, str(ROOT / "test/conv_npu/run.py"),
        "--out", str(out / "npu"), "--source-root", str(source_root),
        "--verilator", str(wrapper), "--jobs", str(args.jobs),
        "--build-timeout", str(args.build_timeout), "--sizes", "16",
        "--bus-width", "64", "--address-width", "19", "--vector-pe-count", "16",
        "--cache-bytes", "4096", "--cache-line-bytes", "128",
        "--shared-bank-bytes", "8192", "--shared-bank-count", "7",
        "--ps-compress", "--force-raw", "--pool-bytes", "49152"]
    if args.skip_build:
        command.append("--skip-build")
    if args.lint_only:
        command.append("--lint-only")
    execute(command, out / "functional.log")
    build = json.loads((out / "npu/s16/build.json").read_text())
    results = {"build": build}
    if not args.lint_only:
        results["functional"] = json.loads((out / "npu/summary.json").read_text())
        sim = out / "npu/s16"
        for name, script in (("capacity", "test/ps_capacity_limits/run_npu.py"),
                             ("output", "test/writeback_cyclic/run_npu.py")):
            execute([sys.executable, str(ROOT / script), "--out", str(out / name),
                     "--sim", str(sim)], out / (name + ".log"))
            results[name] = json.loads((out / name / "summary.json").read_text())
        sys.path.insert(0, str(ROOT / "test/frame_address"))
        from run_npu import packed_cases
        sys.path.insert(0, str(ROOT / "test/ps_compression"))
        from run_shared_npu import npu
        results["packed"] = npu.run_suite(sim / "obj/Vtb_conv_npu", out, "packed",
            packed_cases(out / "packed", build), no_random=False, timeout=900)
        if not all(results[name]["passed"] for name in ("functional", "capacity", "output", "packed")):
            raise RuntimeError("ASIC numerical comparison failed")
    if extra_hashes != {str(path): digest(path) for path in extra_sources}:
        raise RuntimeError("ASIC model or observer changed during validation")
    for name, hashes in observer_hashes.items():
        if digest(ROOT / name) != hashes["source_sha256"]:
            raise RuntimeError("Observer changed during validation: " + name)
    coverage = []
    for path in sorted(out.rglob("*.log")):
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith("FRAME_ADDRESS_NPU_PASS "):
                coverage.append({"log": str(path.relative_to(out)),
                    **{key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", line)}})
    report = {"passed": True, "lint_only": args.lint_only,
        "simulation_defines": DEFINES, "source_root": str(source_root),
        "foundry_model_used": False, "macro_model": "同步读、逐位写掩码及同址并发访问检查",
        "extra_source_sha256": extra_hashes, "observer_sha256": observer_hashes,
        "frame_start_delay_cycles": 12, "frame_coverage": coverage, "results": results}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "lint_only": args.lint_only,
        "tasks": results.get("functional", {}).get("task_count", 0),
        "int32_checks": results.get("functional", {}).get("int32_checks", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
