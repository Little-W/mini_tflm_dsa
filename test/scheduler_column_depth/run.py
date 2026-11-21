#!/usr/bin/env python3
"""证明实际列增量表达式及完整调度器所有状态和公开输出逐周期一致。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from support import ROOT, REFERENCE, check_sources, digest, increment_body, prepare_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/scheduler_column_depth/formal")
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--widths", nargs="+", type=int, default=list(range(1, 34)))
    parser.add_argument("--profiles", nargs="+", default=["1:1:1", "4:3:4", "16:16:32", "16:16:0", "16:17:64"])
    args = parser.parse_args()
    if not args.widths or min(args.widths) < 1:
        parser.error("列计数器宽度必须大于零")
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference)
    report = {
        "passed": False, "inputs": manifest, "input_assumptions": [],
        "state_relation": "Every identically named register and every public output is compared; equal register states remain equal for every input sequence.",
        "memory_relation": "Both complete metadata memories and frame K memories are expanded and compared.",
        "increment_profiles": [], "scheduler_profiles": [],
    }

    def run(name, commands, expected):
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        text = log.read_text()
        if result.returncode != 0 or expected not in text:
            raise RuntimeError(f"形式验证未完成：{log}")
        return {"passed": True, "script_sha256": digest(script), "log_sha256": digest(log)}, text

    for width in args.widths:
        models = []
        for label in ("reference", "current"):
            models.append(
                f"module {label}(input wire [{width-1}:0] next_column_tile, "
                f"output wire [{width-1}:0] column_after_part);\n"
                f"    localparam TILE_W = {width-1};\n" +
                increment_body(paths[label].read_text()) + "endmodule\n")
        models.append(f"""module increment_proof(input wire [{width-1}:0] value,
    output wire equivalent);
    wire [{width-1}:0] reference_value, current_value;
    reference u_reference(value, reference_value);
    current u_current(value, current_value);
    assign equivalent = reference_value == current_value;
endmodule
""")
        model = out / f"increment_w{width}.sv"
        model.write_text("\n".join(models))
        result, _ = run(f"increment_w{width}", [
            f"read_slang --top increment_proof {shlex.quote(str(model))}",
            "prep -top increment_proof -flatten",
            "sat -prove equivalent 1 -verify -show-inputs -show-outputs",
        ], "SAT proof finished - no model found: SUCCESS!")
        report["increment_profiles"].append({"width": width, **result})

    for profile in args.profiles:
        size, frames, reuse = map(int, profile.split(":"))
        commands = []
        for label in ("reference", "current"):
            sources = " ".join(shlex.quote(str(path)) for path in [paths[label]] + helpers)
            commands += [
                f"read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top ps_window_scheduler "
                f"-GSIZE={size} -GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} {sources}",
                "prep -top ps_window_scheduler -flatten", "memory_map", "async2sync", "opt_clean",
                f"rename ps_window_scheduler {label}", f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert",
        ]
        result, text = run(f"scheduler_s{size}_f{frames}_r{reuse}", commands,
                           "Equivalence successfully proven")
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if match is None or int(match[2]) != 0:
            raise RuntimeError("完整调度器仍包含未证明的等价位")
        row = {"SIZE": size, "FRAME_COUNT": frames, "MAX_REUSE_TILES": reuse,
               "equivalent_bits": int(match[1]), **result}
        report["scheduler_profiles"].append(row)
        print(json.dumps(row), flush=True)
    check_sources(manifest)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(out / "summary.json")


if __name__ == "__main__":
    main()
