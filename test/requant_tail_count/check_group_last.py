#!/usr/bin/env python3
"""检查完整行结束比较模块与原始表达式的四态结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = "rtl/npu/writeback/vec_requant.sv"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run([str(value) for value in command], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "build/requant_group_last")
    args = parser.parse_args()
    path = args.source_root.resolve() / RELATIVE
    content = path.read_text()
    match = re.search(r"^module requant_group_last\b.*?^endmodule\b", content, re.M | re.S)
    if match is None:
        raise RuntimeError("缺少完整复用组结束比较模块")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = out / "requant_group_last.sv"
    helper.write_text(match[0] + "\n")
    profiles = []
    for width in (1, 4, 8, 16):
        folder = out / f"width{width}"
        folder.mkdir(exist_ok=True)
        bench = folder / "tb.sv"
        bench.write_text(f"""module tb;
    reg [{width-1}:0] row, last_row, mask, saved_row, saved_last, saved_mask;
    wire last_tile, last_group;
    wire expected_tile = row == last_row;
    wire expected_group = expected_tile || ((row & mask) == mask);
    integer checks=0, seed=20261125;
    requant_group_last #(.p_tile_width({width})) dut (
        .i_row(row), .i_last_row(last_row), .i_mask(mask),
        .o_last_tile(last_tile), .o_last_group(last_group)
    );
    task verify; begin
        #1;
        if ({{last_tile,last_group}} !== {{expected_tile,expected_group}})
            $fatal(1,"行结束比较的四态结果不一致");
        checks++;
    end endtask
    initial begin
        seed=$urandom(seed);
        for(integer sample=0;sample<10000;sample++) begin
            row=$urandom; last_row=$urandom; mask=$urandom;
            case(sample%8)
                0:row='0;
                1:row='1;
                2:mask='0;
                3:mask='1;
                4:last_row=row;
                5:row=row|mask;
                6:mask=row;
                default:begin end
            endcase
            verify();saved_row=row;saved_last=last_row;saved_mask=mask;
            row[sample%{width}]=1'bx;verify();row=saved_row;
            mask[sample%{width}]=1'bz;verify();mask=saved_mask;
            last_row[sample%{width}]=1'bx;verify();last_row=saved_last;
        end
        $display("GROUP_LAST_PASS checks=%0d",checks);$finish;
    end
endmodule
""")
        binary = folder / "simulation"
        execute(["iverilog", "-g2012", "-s", "tb", "-o", binary, helper, bench],
                folder / "compile.log")
        execute(["vvp", binary], folder / "simulation.log")
        if "GROUP_LAST_PASS checks=40000" not in (folder / "simulation.log").read_text():
            raise RuntimeError("行结束比较的四态验证未完成")
        profiles.append({"tile_width": width, "passed": True,
                         "four_state_comparisons": 40000,
                         "simulation_log_sha256": sha(folder / "simulation.log")})
    if path.read_text() != content:
        raise RuntimeError("验证期间源文件发生变化")
    report = {"passed": True, "source_sha256": sha(path),
              "helper_sha256": sha(helper), "random_seed": 20261125,
              "profiles": profiles, "four_state_comparisons": 160000}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
