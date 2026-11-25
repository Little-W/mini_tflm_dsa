#!/usr/bin/env python3
"""比较 IA 状态、发送资格和启动脉冲的时序及四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/loaders/ia_loader_ctrl.sv"
INPUTS = (
    "init_start", "load_ia_granted", "l1_load_complete",
    "l1_load_complete_event", "cache_tile_done", "last_send",
    "ia_iter_last", "w_iter_last", "prefetch_active", "retirement_l1",
    "send_ia_trigger", "cache_l1_done",
)
OUTPUTS = (
    "ia_data_valid", "cache_l1_start", "ready_snapshot",
    "busy_snapshot", "state_snapshot",
)


def extract(source: str, label: str) -> str:
    begin = source.index("  typedef enum logic [2:0] {")
    end = source.index("  // =====================================================================", begin)
    state = source[begin:end]
    begin = source.index("  logic send_group_ready_r;")
    end = source.index("  // =====================================================================", begin)
    ready = source[begin:end]
    begin = source.index("  always_comb begin\n    state_nxt = state;")
    end = source.index("  assign all_done =", begin)
    next_state = source[begin:end]
    state_update = "  // 状态与发送资格共同接收"
    if state_update in source:
        next_state = source[source.index(state_update):begin] + next_state
    begin = source.index("  // 规则：L1 组的所有 R 个 slot")
    end = source.index("  // ia_sending_done", begin)
    outputs = source[begin:end]
    header = (
        f"module send_flags_{label}(input logic clk,rst_n,"
        + ",".join(INPUTS)
        + ",output logic ia_data_valid,cache_l1_start,"
        + "output logic [2:0] state_snapshot,"
        + "output logic ready_snapshot,busy_snapshot);\n"
    )
    return (
        header + "logic in_l1_output;\n" + state + ready + next_state + outputs
        + "assign state_snapshot=state;\n"
        + "assign ready_snapshot=send_group_ready_r;\n"
        + "assign busy_snapshot=in_l1_output;\nendmodule\n"
    )


def testbench() -> str:
    current = "{" + ",".join(OUTPUTS) + "}"
    reference = "{" + ",".join("ref_" + name for name in OUTPUTS) + "}"
    lines = ["module tb;\nlogic clk=0,rst_n=0;\n"]
    lines += [f"logic {name}=0;\n" for name in INPUTS]
    for prefix in ("", "ref_"):
        for name in OUTPUTS:
            width = "[2:0] " if name == "state_snapshot" else ""
            lines.append(f"wire {width}{prefix}{name};\n")
    connections = ",".join(f".{name}(ref_{name})" for name in OUTPUTS)
    lines += [
        "send_flags_current dut(.*);\n",
        f"send_flags_reference reference_dut({connections},.*);\n",
        "integer cycles=0;\n",
        "task compare_outputs;\n",
        f"if({current} !== {reference})\n",
        '$fatal(1,"send flags differ cycle=%0d cur=%b ref=%b",'
        f"cycles,{current},{reference});\nendtask\n",
        "task tick; #1;compare_outputs();clk=1;#1;compare_outputs();\n",
        "cycles++;clk=0;#1;endtask\n",
        "initial begin repeat(4)tick();\n",
        "for(integer sample=0;sample<100000;sample++)begin\n",
        "rst_n=sample%51!=0;\n",
    ]
    lines += [f"{name}=$urandom;\n" for name in INPUTS]
    lines += ["if(sample>2000)begin case(sample%30)\n"]
    for index, name in enumerate(("rst_n",) + INPUTS):
        lines.append(f"{2*index}:{name}=1'bx;{2*index+1}:{name}=1'bz;\n")
    lines += [
        "default:;endcase end\ntick();end\n",
        '$display("SEND_FLAGS_PASS cycles=%0d",cycles);\n',
        "$finish;end\nendmodule\n",
    ]
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="45c6caec")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(
        ["git", "rev-parse", args.reference + "^{commit}"], cwd=ROOT, text=True
    ).strip()
    sources = {
        "reference": subprocess.check_output(
            ["git", "show", revision + ":" + SOURCE], cwd=ROOT, text=True
        ),
        "current": (ROOT / SOURCE).read_text(),
    }
    commands = []
    for label, source in sources.items():
        path = out / (label + ".sv")
        path.write_text(extract(source, label))
        commands += [
            f"read_slang --top send_flags_{label} {path}",
            f"prep -top send_flags_{label} -flatten", "async2sync", "opt_clean",
            f"rename send_flags_{label} {label}", f"design -stash {label}",
        ]
    commands += [
        "design -copy-from reference -as reference reference",
        "design -copy-from current -as current current",
        "equiv_make reference current proof", "hierarchy -top proof",
        "equiv_simple -seq 2", "opt_clean", "equiv_induct -seq 3",
        "equiv_status -assert",
    ]
    script = out / "proof.ys"
    script.write_text("\n".join(commands) + "\n")
    with (out / "proof.log").open("w") as log:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
             "--worker", str(script)], stdout=log, stderr=subprocess.STDOUT,
            check=True,
        )
    (out / "tb.sv").write_text(testbench())
    with (out / "compile.log").open("w") as log:
        subprocess.run(
            ["iverilog", "-g2012", "-s", "tb", "-o", str(out / "sim.vvp"),
             str(out / "reference.sv"), str(out / "current.sv"), str(out / "tb.sv")],
            stdout=log, stderr=subprocess.STDOUT, check=True,
        )
    run = subprocess.run(
        ["vvp", str(out / "sim.vvp")], capture_output=True, text=True, timeout=180
    )
    (out / "run.log").write_text(run.stdout + run.stderr)
    print(run.stdout, end="", flush=True)
    run.check_returncode()
    cycles = int(re.search(r"SEND_FLAGS_PASS cycles=(\d+)", run.stdout)[1])
    assert cycles == 100004
    assert (ROOT / SOURCE).read_text() == sources["current"]
    summary = dict(
        passed=True, reference_commit=revision, cycles=cycles,
        formal_input_constraints=False, compare_before_and_after_edge=True,
        source_sha256={label: hashlib.sha256(source.encode()).hexdigest()
                       for label, source in sources.items()},
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
