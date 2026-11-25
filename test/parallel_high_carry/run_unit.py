#!/usr/bin/env python3
"""证明并行高段前缀的完整算术结果，并比较两种编译方式的四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/common/parallel_prefix_add.sv"
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="777634ba")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"],
                                        cwd=ROOT, text=True)
    reference_path = out / "reference.sv"
    reference_path.write_text(re.sub(r"\b(parallel_prefix_add|parallel_prefix_native_sums)\b",
                                     r"reference_\1", reference))
    current_path = out / "current.sv"
    current_path.write_bytes((ROOT / SOURCE).read_bytes())
    configurations = [(16 + high, 16) for high in range(1, 24)]
    configurations += [(2, 1), (24, 1), (24, 23), (46, 23), (1, 0),
                       (32, 0), (32, 32), (47, 23), (64, 32)]
    profiles = [(width, split, preserve) for width, split in configurations
                for preserve in (0, 1)]
    formal = ["module proof(input logic [63:0] i_a,i_b,input logic i_carry,",
              "output logic equivalent);", f"logic [{len(profiles)-1}:0] compared;"]
    bench = ["module tb;logic [63:0] a,b;logic carry_in;integer samples;",
             f"logic [{len(profiles)-1}:0] compared;"]
    for index, (width, split, preserve) in enumerate(profiles):
        common = (f".p_width({width}),.p_group_width(8),.p_preserve_groups(1'b{preserve}),"
                  f".p_carry_select_width(16),.p_dsp_split_width({split})")
        formal += [f"logic [{width}:0] actual_{index},expected_{index};",
                   f"parallel_prefix_add #({common},.p_parallel_high_prefix(1'b1)) u{index}(",
                   f".i_a(i_a[{width-1}:0]),.i_b(i_b[{width-1}:0]),.i_carry(i_carry),",
                   f".o_sum(actual_{index}[{width-1}:0]),.o_carry(actual_{index}[{width}]));",
                   f"assign expected_{index}={{1'b0,i_a[{width-1}:0]}}+"
                   f"{{1'b0,i_b[{width-1}:0]}}+{width+1}'(i_carry);",
                   f"assign compared[{index}]=actual_{index}==expected_{index};"]
        bench += [f"logic [{width}:0] actual_{index},expected_{index};",
                  f"parallel_prefix_add #({common},.p_parallel_high_prefix(1'b1)) u{index}(",
                  f".i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_carry(carry_in),",
                  f".o_sum(actual_{index}[{width-1}:0]),.o_carry(actual_{index}[{width}]));",
                  f"reference_parallel_prefix_add #({common}) r{index}(",
                  f".i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_carry(carry_in),",
                  f".o_sum(expected_{index}[{width-1}:0]),.o_carry(expected_{index}[{width}]));",
                  f"assign compared[{index}]=actual_{index}===expected_{index};"]
    formal += ["assign equivalent=&compared;", "endmodule"]
    bench += ["task check;#1;if((&compared)!==1'b1)$fatal(1,\"Arithmetic differs\");"
              "samples++;endtask", "initial begin samples=0;",
              "for(integer sample=0;sample<4096;sample++)begin",
              "a={$urandom,$urandom};b={$urandom,$urandom};carry_in=sample[0];check();end",
              "for(integer pattern=0;pattern<8;pattern++)begin",
              "for(integer bit_index=0;bit_index<129;bit_index++)begin",
              "for(integer unknown=0;unknown<2;unknown++)begin",
              "a=pattern[0]?'1:'0;b=pattern[1]?'1:'0;carry_in=pattern[2];",
              "if(bit_index<64)a[bit_index]=unknown?1'bz:1'bx;",
              "else if(bit_index<128)b[bit_index-64]=unknown?1'bz:1'bx;",
              "else carry_in=unknown?1'bz:1'bx;check();end end end",
              "$display(\"HIGH_PREFIX_FOUR_STATE_PASS samples=%0d\",samples);$finish;end",
              "endmodule"]
    model = out / "proof.sv"
    model.write_text("\n".join(formal) + "\n")
    script, log = out / "proof.ys", out / "proof.log"
    script.write_text(f"read_slang --top proof -DSYNTHESIS {current_path} {model}\n"
                      "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                      "prep -top proof -flatten\ncheck -assert\n"
                      "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    proof = run_stage(script, log, dict(os.environ))
    if "SUCCESS!" not in log.read_text():
        raise RuntimeError("完整算术结果证明未完成")
    bench_path = out / "four_state.sv"
    bench_path.write_text("\n".join(bench) + "\n")
    samples = 4096 + 8 * 129 * 2
    four_state = []
    for synthesis in (False, True):
        label = "synthesis" if synthesis else "simulation"
        binary = out / (label + ".vvp")
        execute(["iverilog", "-g2012", "-s", "tb", "-o", binary,
                 *(["-DSYNTHESIS"] if synthesis else []),
                 current_path, reference_path, bench_path], out / (label + "_compile.log"))
        result_log = out / (label + ".log")
        execute(["vvp", binary], result_log)
        if f"HIGH_PREFIX_FOUR_STATE_PASS samples={samples}" not in result_log.read_text():
            raise RuntimeError("四态结果比较未完成")
        binary.unlink()
        four_state.append(dict(synthesis=synthesis, samples=samples,
                               complete_result_comparisons=samples*len(profiles),
                               log_sha256=digest(result_log)))
    report = dict(passed=True, reference_commit=revision,
                  source_sha256={"current": digest(current_path), "reference":
                                 hashlib.sha256(reference.encode()).hexdigest()},
                  profiles=profiles, unconstrained_arithmetic_proof=proof,
                  four_state=four_state)
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(dict(passed=True, profiles=len(profiles), four_state=four_state)), flush=True)


if __name__ == "__main__":
    main()
