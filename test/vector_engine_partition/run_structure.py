#!/usr/bin/env python3
"""比较向量引擎公开接口、寄存器位数、存储容量和算术运算数量。"""
from pathlib import Path
import argparse
from collections import Counter
import hashlib
import json
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def number(value):
    return int(value, 2) if isinstance(value, str) else int(value)


def inspect(source_root, out, profile):
    out.mkdir(parents=True, exist_ok=True)
    sources = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"](
        [source_root / "rtl/npu/conv/vector_engine.sv"], source_root)
    command = ["read_slang", "--top", "vector_engine", "-D", "SYNTHESIS=1"]
    command += [f"-G{name}={value}" for name, value in profile.items()]
    command += list(map(str, sources))
    script = out / "structure.ys"
    script.write_text(shlex.join(command) + "\nprep -top vector_engine -flatten\n"
                      "memory_collect\nmemory_map\nopt -full\nwreduce\nopt -full\nwrite_json "
                      + str(out / "design.json") + "\n")
    with (out / "structure.log").open("w") as log:
        subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
    module = json.loads((out / "design.json").read_text())["modules"]["vector_engine"]
    registers = 0
    memories = []
    arithmetic = Counter()
    for name, cell in module["cells"].items():
        kind = cell["type"]
        if "dff" in kind or "latch" in kind:
            registers += len(cell["connections"]["Q"])
        if kind.startswith("$mem"):
            params = cell["parameters"]
            memories.append({"name": name, "bits": number(params["WIDTH"]) * number(params["SIZE"]),
                             "width": number(params["WIDTH"]), "depth": number(params["SIZE"])})
        if kind in {"$add", "$sub", "$mul", "$div", "$mod", "$lt", "$le", "$gt", "$ge"}:
            parameters = cell["parameters"]
            signature = kind + ":" + ":".join(
                f"{key}={number(value)}" for key, value in sorted(parameters.items()) if key.endswith("WIDTH"))
            arithmetic[signature] += 1
    return {"register_bits": registers, "memory_bits": sum(item["bits"] for item in memories),
            "memory_shapes": dict(Counter(f"{item['depth']}x{item['width']}" for item in memories)),
            "arithmetic": dict(arithmetic),
            "multipliers": {name: count for name, count in arithmetic.items() if name.startswith("$mul:")},
            "ports": {name: {"direction": port["direction"], "bits": len(port["bits"])}
                      for name, port in module["ports"].items()},
            "source_sha256": {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sources}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    profiles = [
        {"TILE": 16, "BUS_WIDTH": 64, "PE_COUNT": 8, "WINDOW_LANES": 8,
         "SHARED_QUANT_ENABLE": 1, "SHARED_STORAGE_ENABLE": 1},
        {"TILE": 16, "BUS_WIDTH": 64, "PE_COUNT": 16, "WINDOW_LANES": 16,
         "SHARED_QUANT_ENABLE": 0, "SHARED_STORAGE_ENABLE": 0},
    ]
    records = []
    for index, profile in enumerate(profiles):
        original = inspect(args.reference_root.resolve(), args.out / f"profile{index}/reference", profile)
        current = inspect(args.source_root.resolve(), args.out / f"profile{index}/current", profile)
        keys = ("register_bits", "memory_bits", "memory_shapes", "multipliers", "ports")
        checks = {key: original[key] == current[key] for key in keys}
        record = {"profile": profile, "checks": checks, "reference": original,
                  "current": current, "passed": all(checks.values())}
        records.append(record)
        (args.out / "summary.json").write_text(json.dumps(
            {"passed": all(item["passed"] for item in records), "checks": records}, indent=2) + "\n")
        print(json.dumps({"profile": profile, "checks": checks,
                          "register_bits": current["register_bits"], "memory_bits": current["memory_bits"]}), flush=True)
        if not record["passed"]:
            raise RuntimeError("向量引擎的展开结构需要核对")


if __name__ == "__main__":
    main()
