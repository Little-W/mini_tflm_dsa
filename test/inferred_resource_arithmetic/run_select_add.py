#!/usr/bin/env python3
"""比较选择加法器的二态硬件表达式与四态仿真接口。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/compute/select_add.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference-ref", default="364e2ac7")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper_path = ROOT / "test/select_add_simd/run.py"
    spec = importlib.util.spec_from_file_location("select_add_checks", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    texts = {"candidate": args.candidate.read_text(), "reference": subprocess.check_output(
        ["git", "show", args.reference_ref + ":" + SOURCE], cwd=ROOT, text=True)}
    units = []
    for name, content in texts.items():
        path = out / (name + ".sv")
        path.write_text(re.sub(r"\bmodule select_add\b", "module " + name, content, count=1))
        units.append(path)
    formal = out / "compare.sv"
    formal.write_text(helper.FORMAL)
    profiles = [(width, use, split) for width in helper.WIDTHS for use in (0, 1) for split in (0, 1)]

    def prove(profile):
        width, use, split = profile
        name = f"w{width}_u{use}_s{split}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("read_slang --top compare -D SYNTHESIS=1 " +
            f"-GW={width} -GU={use} -GS={split} " + shlex.join(map(str, units + [formal])) +
            "\nprep -top compare -flatten\n" +
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           cwd=ROOT, check=True, timeout=120)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("选择加法器检查未完成：" + name)
        return {"width": width, "use_dsp": use, "split_12bit": split,
                "passed": True, "log_sha256": digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        proofs = list(pool.map(prove, profiles))
    bench = out / "four_state.sv"
    content = helper.FOUR + f"module tb; wire[{len(profiles)-1}:0] done;\n"
    for index, (width, use, split) in enumerate(profiles):
        content += f"four_case #(.W({width}),.U({use}),.S({split})) u_{index}(.done(done[{index}]));\n"
    bench.write_text(content + "initial begin wait(&done);$finish;end endmodule\n")
    simulation_units = []
    for path in units:
        simulation = path.with_name(path.stem + "_simulation.sv")
        simulation.write_text(path.read_text().replace("    begin : g_generic",
            "    generate\n    begin : g_generic", 1).replace("\nendmodule",
            "\n    endgenerate\nendmodule", 1))
        simulation_units.append(simulation)
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(out / "simulation"),
                        *map(str, simulation_units), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    with (out / "four_state.log").open("w") as stream:
        subprocess.run(["vvp", str(out / "simulation")], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    result = (out / "four_state.log").read_text()
    matches = re.findall(r"FOUR_STATE_PASS W=(\d+) U=(\d+) S=(\d+) checked=(\d+)", result)
    if len(matches) != len(profiles):
        raise RuntimeError("选择加法器四态比较未完成")
    if texts["candidate"] != args.candidate.read_text():
        raise RuntimeError("验证期间源文件发生变化")
    report = {"passed": True, "reference_ref": args.reference_ref,
              "source_sha256": hashlib.sha256(texts["candidate"].encode()).hexdigest(),
              "reference_sha256": hashlib.sha256(texts["reference"].encode()).hexdigest(),
              "test_sha256": digest(Path(__file__)), "four_state_helper_sha256": digest(helper_path),
              "formal_synthesis_defined": True, "functional_inputs_constrained": False,
              "binary_cases": proofs,
              "four_state_cases": [{"width": int(w), "use_dsp": int(u), "split_12bit": int(s),
                                    "comparisons": int(n), "passed": True} for w, u, s, n in matches],
              "four_state_comparisons": sum(int(n) for _, _, _, n in matches),
              "four_state_log_sha256": digest(out / "four_state.log")}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(profiles),
                      "four_state_comparisons": report["four_state_comparisons"]}))


if __name__ == "__main__":
    main()
