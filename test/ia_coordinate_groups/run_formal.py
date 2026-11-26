#!/usr/bin/env python3
"""检查相邻坐标分组比较与完整 IA 加载器的逐周期等价性。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "c22af198f70d71881b6d8ceceedd89f43733e1b9"
PARENT = Path("rtl/npu/loaders/ia_loader.sv")
HELPER = Path("rtl/npu/loaders/ia_ordered_coordinate_same.sv")
UPDATE = Path("rtl/npu/loaders/ia_ordered_coordinate_update.sv")
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import input_files, with_dependencies

PRODUCTION = dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32, COUNT_WIDTH=29,
                  ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12, p_dma_source_layout=1,
                  p_shared_write_stage=1, p_register_dma_request=1)
PROFILES = {
    "ordered_narrow": dict(SIZE=16, BUS_WIDTH=32, CACHE_BLOCKS=4, REG_WIDTH=16,
                          COUNT_WIDTH=12, COMPACT_S8=0, ORDERED_JOB=1),
    "production": dict(PRODUCTION, COMPACT_S8=0),
    "compact": dict(PRODUCTION, COMPACT_S8=1),
    "unordered": dict(SIZE=16, BUS_WIDTH=32, CACHE_BLOCKS=4, COUNT_WIDTH=8,
                      COMPACT_S8=1, ORDERED_JOB=0),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(out, reference):
    dependencies = with_dependencies([ROOT / PARENT], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in input_files(dependencies, ROOT)}
    sources = {}
    for variant in ("reference", "candidate"):
        folder = out / variant
        folder.mkdir(parents=True, exist_ok=True)
        overrides = []
        relatives = (PARENT, HELPER) if variant == "reference" else (PARENT, HELPER, UPDATE)
        for relative in relatives:
            text = (subprocess.check_output(["git", "show", reference + ":" + str(relative)],
                                           cwd=ROOT, text=True) if variant == "reference"
                    else (ROOT / relative).read_text())
            path = folder / relative.name
            path.write_text(text)
            overrides.append(path)
        sources[variant] = with_dependencies(overrides, ROOT)
    return sources, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources, hashes = snapshot(out / "sources", args.reference)
    for relative in (PARENT,):
        original = (out / "sources/reference" / relative.name).read_text()
        candidate = (out / "sources/candidate" / relative.name).read_text()
        if set(re.findall(r"\b(\w+)\s*<=", original)) != set(re.findall(r"\b(\w+)\s*<=", candidate)):
            raise RuntimeError("加载器状态寄存器集合发生变化")

    def prove(job):
        name, fpga = job
        parameters = PROFILES[name]
        label = name + ("_fpga" if fpga else "_generic")
        flags = (["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else
                 ["-USYNTHESIS", "-UXILINX_FPGA"])
        flags += [f"-G{key}={value}" for key, value in parameters.items()]
        commands = []
        for variant in ("reference", "candidate"):
            commands += ["read_slang --top ia_loader " +
                         shlex.join(flags + list(map(str, sources[variant]))),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top ia_loader -flatten", "memory_map", "async2sync", "opt_clean",
                         "rename ia_loader " + variant, "design -stash " + variant]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make reference candidate proof", "hierarchy -top proof",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 4", "equiv_status -assert"]
        script, log = out / (label + ".ys"), out / (label + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=480)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("完整加载器等价检查未完成：" + label)
        row = dict(profile=name, fpga=fpga, parameters=parameters, passed=True,
                   proven_bits=int(match[1]), script_sha256=digest(script), log_sha256=digest(log))
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(prove, ((name, fpga) for name in args.profiles for fpga in (False, True))))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=hashes,
                  runner_sha256=digest(__file__), input_value_constraints=None,
                  handshake_constraints=None, all_public_outputs_and_state_compared=True,
                  all_memory_contents_compared=True, profiles=records,
                  proven_bits=sum(row["proven_bits"] for row in records))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
