#!/usr/bin/env python3
"""对描述符或坐标模块的全部输出和保存状态执行顺序等价证明。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCES = (
    "rtl/npu/conv/conv_im2col_pkg.sv",
    "rtl/npu/conv/conv_im2col_frontend_pkg.sv",
    "rtl/common/add_equal.sv",
    "rtl/common/parallel_prefix_add.sv",
    "rtl/common/unsigned_compare.sv",
    "rtl/common/onehot_check.sv",
    "rtl/common/onehot_mux.sv",
    "rtl/npu/conv/conv_coordinate_step.sv",
    "rtl/npu/conv/conv_coordinate_range.sv",
    "rtl/npu/conv/conv_im2col_descriptor.sv",
    "rtl/npu/conv/conv_im2col_geometry.sv",
)
INCLUDES = ("include/conv_im2col_prepared_tile.svh",)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registered", type=int, nargs="+", choices=(0, 1), default=(0, 1))
    parser.add_argument("--module", choices=("descriptor", "geometry"), default="descriptor")
    args = parser.parse_args()
    top = "conv_im2col_" + args.module
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    hashes = {}
    source_names = {}
    for side in ("reference", "current"):
        snapshot = out / side
        snapshots[side] = snapshot
        hashes[side] = {}
        source_names[side] = []
        for name in (*SOURCES, *INCLUDES):
            if side == "reference":
                try:
                    content = read_reference_file(ROOT, args.reference_ref, name)
                except FileNotFoundError:
                    if name in ("rtl/npu/conv/conv_coordinate_range.sv", "rtl/common/onehot_mux.sv"):
                        continue
                    raise
            else:
                content = (ROOT / name).read_bytes()
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[side][name] = hashlib.sha256(content).hexdigest()
            if name in SOURCES:
                source_names[side].append(name)

    results = []
    for registered in dict.fromkeys(args.registered):
        directory = out / f"registered{registered}"
        directory.mkdir(exist_ok=True)
        commands = []
        for side, label in (("reference", "gold"), ("current", "gate")):
            snapshot = snapshots[side]
            options = ["--top", top, "--single-unit", "--allow-use-before-declare",
                       "-D", "SYNTHESIS=1", "-I" + str(snapshot / "include"),
                       "-Gp_size=16", "-Gp_slot_w=5", "-Gp_lanes=16",
                       "-Gp_line_bytes=128", f"-Gp_register_descriptor={registered}"]
            commands.extend([
                "read_slang " + shlex.join(options + [str(snapshot / name) for name in source_names[side]]),
                f"prep -top {top} -flatten",
                "memory_map",
                "async2sync",
                "opt",
                f"rename {top} {label}",
                f"design -stash {label}",
            ])
        commands.extend([
            "design -copy-from gold -as gold gold",
            "design -copy-from gate -as gate gate",
            "equiv_make gold gate equivalence",
            "hierarchy -top equivalence",
            "equiv_simple",
            "equiv_induct -seq 2",
            "equiv_status -assert",
        ])
        script = directory / "proof.ys"
        script.write_text("\n".join(commands) + "\n")
        log = directory / "proof.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=600)
        if "Equivalence successfully proven!" not in log.read_text():
            raise RuntimeError(f"等价证明没有完成：{log}")
        results.append({"p_register_descriptor": registered, "passed": True,
                        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"{args.module.upper()}_EQUIVALENCE_PASS registered={registered}", flush=True)
    sources_unchanged = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                            for name, digest in hashes["current"].items())
    if not sources_unchanged:
        raise RuntimeError("等价证明期间源文件发生变化")
    report = {"passed": True, "reference_ref": args.reference_ref, "module": top,
              "sources_unchanged": sources_unchanged,
              "source_sha256": hashes, "inputs_constrained": False,
              "scope": "all public outputs and matched state, complete 32-bit arithmetic",
              "parameters": {"p_size": 16, "p_slot_w": 5, "p_lanes": 16, "p_line_bytes": 128},
              "runs": results}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
