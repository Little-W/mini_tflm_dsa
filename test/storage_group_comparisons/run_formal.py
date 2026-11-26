#!/usr/bin/env python3
"""证明分组比较保持完整 IA 控制器和帧调度器的状态、存储及公开输出。"""
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
REFERENCE = "351f3fb63f8d8b36e46c36c7ab539cae475cc8d2"
SOURCES = {"ia_loader_ctrl": Path("rtl/npu/loaders/ia_loader_ctrl.sv"),
           "ps_window_scheduler": Path("rtl/npu/control/ps_window_scheduler.sv")}
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
from scripts.rtl.source_files import input_files, with_dependencies
from rtl_reference import read_rtl_source

PRODUCTION_IA = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                     COUNT_WIDTH=29, CACHE_BLOCKS=32, PS_FRAME_COUNT=16,
                     p_precomputed_packed_tiles=1, p_precomputed_frame_rows=1,
                     p_precomputed_slot_mask=1, p_indexed_slot_rows=1,
                     p_parallel_request_match=1)
PROFILES = {
    "ia_small": ("ia_loader_ctrl", dict(SIZE=3, BUS_WIDTH=32, CACHE_BLOCKS=4,
                                       COUNT_WIDTH=8, PS_FRAME_COUNT=3)),
    "ia_regular": ("ia_loader_ctrl", dict(SIZE=16, BUS_WIDTH=32, CACHE_BLOCKS=4,
                                         COUNT_WIDTH=32, COMPACT_S8=0)),
    "ia_production": ("ia_loader_ctrl", dict(PRODUCTION_IA, COMPACT_S8=0)),
    "ia_compact": ("ia_loader_ctrl", dict(PRODUCTION_IA, COMPACT_S8=1)),
    "ia_large": ("ia_loader_ctrl", dict(SIZE=32, BUS_WIDTH=64, CACHE_BLOCKS=32,
                                       COUNT_WIDTH=32, PS_FRAME_COUNT=32)),
    "scheduler_single": ("ps_window_scheduler", dict(SIZE=1, FRAME_COUNT=1, MAX_REUSE_TILES=1)),
    "scheduler_three": ("ps_window_scheduler", dict(SIZE=4, FRAME_COUNT=3, MAX_REUSE_TILES=4)),
    "scheduler_production": ("ps_window_scheduler", dict(SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=16)),
    "scheduler_reuse32": ("ps_window_scheduler", dict(SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=32)),
    "scheduler_seventeen": ("ps_window_scheduler", dict(SIZE=16, FRAME_COUNT=17, MAX_REUSE_TILES=64)),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_sets = {}
    hashes = {}
    reference_hashes = {}
    for top, relative in SOURCES.items():
        reference = out / (top + "_reference.sv")
        reference.write_text(read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT, text=True))
        candidate = out / (top + "_candidate.sv")
        candidate.write_bytes((ROOT / relative).read_bytes())
        original_registers = set(re.findall(r"\b(\w+)\s*<=", reference.read_text()))
        candidate_registers = set(re.findall(r"\b(\w+)\s*<=", candidate.read_text()))
        if original_registers != candidate_registers:
            raise RuntimeError("分组比较需要保留全部状态寄存器：" + top)
        source_sets[top] = {name: with_dependencies([path], ROOT)
                            for name, path in (("reference", reference), ("candidate", candidate))}
        for path in input_files(with_dependencies([ROOT / relative], ROOT), ROOT):
            hashes[str(path.relative_to(ROOT))] = digest(path)
        reference_hashes[top] = digest(reference)

    def prove(job):
        name, fpga = job
        top, parameters = PROFILES[name]
        label = name + ("_fpga" if fpga else "_generic")
        flags = (["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else
                 ["-USYNTHESIS", "-UXILINX_FPGA"])
        flags += [f"-G{key}={value}" for key, value in parameters.items()]
        commands = []
        for variant in ("reference", "candidate"):
            commands += ["read_slang --top " + top + " " +
                         shlex.join(flags + list(map(str, source_sets[top][variant]))),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top " + top + " -flatten", "memory_map", "async2sync", "opt_clean",
                         "rename " + top + " " + variant, "design -stash " + variant]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make reference candidate proof", "hierarchy -top proof",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 4", "equiv_status -assert"]
        script, log = out / (label + ".ys"), out / (label + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=360)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("完整状态等价检查未完成：" + label)
        row = dict(name=name, top=top, fpga=fpga, parameters=parameters, passed=True,
                   proven_bits=int(match[1]), script_sha256=digest(script), log_sha256=digest(log))
        print(json.dumps(row), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(prove, ((name, fpga) for name in PROFILES for fpga in (False, True))))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=hashes,
                  reference_sha256=reference_hashes, runner_sha256=digest(__file__),
                  input_value_constraints=None, handshake_constraints=None,
                  all_public_outputs_and_state_compared=True,
                  all_memory_contents_compared=True, profiles=records,
                  proven_bits=sum(row["proven_bits"] for row in records))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
