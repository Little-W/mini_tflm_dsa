#!/usr/bin/env python3
"""验证生产列尾比较使用的分组归并参数在完整位宽和四态输入下保持相同结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "rtl/npu/loaders/kernel_loader_ctrl.sv"
WIDTHS = (1, 2, 3, 5, 16, 29, 32, 47, 64)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = CONTROLLER.read_text()
    end = source.index("u_saved_column_last_equal")
    start = source.rfind("increment_equal", 0, end)
    match = re.search(r"p_reduce_group_width\((\d+)\)", source[start:end])
    if not match:
        raise ValueError("找不到生产列尾比较的分组宽度")
    group_width = int(match[1])
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolver([ROOT / "rtl/common/increment_equal.sv"], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [CONTROLLER, *sources]}
    runs = []
    for width in WIDTHS:
        folder = out / f"width{width}"
        folder.mkdir(exist_ok=True)
        model = folder / "proof.sv"
        model.write_text(f"""// 比较直接归并和生产参数下的分组归并。
module column_reduce_proof (
    input logic [{width-1}:0] i_value, // 当前定宽列位置
    input logic [{width-1}:0] i_target, // 列数上限
    output logic o_equal // 两种归并方式的结果相同
);
    logic reference_result, current_result;
    increment_equal #(.p_width({width}), .p_preserve_pairs(1'b1)) u_reference (
        .i_a(i_value), .i_target(i_target), .o_equal(reference_result));
    increment_equal #(.p_width({width}), .p_preserve_pairs(1'b1),
        .p_reduce_group_width({group_width})) u_current (
        .i_a(i_value), .i_target(i_target), .o_equal(current_result));
    assign o_equal = reference_result === current_result;
endmodule
""")
        script, log = folder / "proof.ys", folder / "proof.log"
        script.write_text(shlex.join(["read_slang", "--top", "column_reduce_proof", *map(str, sources), str(model)]) +
            "\nprep -top column_reduce_proof -flatten\nsat -verify -prove o_equal 1\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError(f"列尾分组形式证明未完成：{width}")
        bench = folder / "tb.sv"
        bench.write_text(f"""// 逐位覆盖未知值、高阻值及完整位宽的随机列位置。
module tb;
    logic [{width-1}:0] value, target;
    logic equal_result;
    integer checks=0;
    column_reduce_proof u_proof(.i_value(value), .i_target(target), .o_equal(equal_result));
    task automatic check;
        #1;
        if (equal_result!==1'b1) $fatal(1,"Column reduction differs");
        checks++;
    endtask
    initial begin
        value='0; target='1; check(); value='1; target='0; check();
        value='x; target='z; check(); value='z; target='x; check();
        for (integer sample=0;sample<8192;sample++) begin
            for (integer bit_index=0;bit_index<{width};bit_index++) begin
                value[bit_index]=1'($urandom);
                target[bit_index]=1'($urandom);
            end
            if (sample%2==0) target=value+{width}'d1;
            if (sample%3==0) value[sample%{width}]=1'bx;
            if (sample%5==0) target[sample%{width}]=1'bz;
            check();
        end
        $display("KERNEL_COLUMN_REDUCE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
""")
        binary = folder / "four_state.vvp"
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                *map(str, sources), str(model), str(bench)], stdout=stream,
                stderr=subprocess.STDOUT, check=True, timeout=120)
        result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=120)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        if "KERNEL_COLUMN_REDUCE_PASS checks=8196" not in result.stdout:
            raise RuntimeError(f"列尾分组四态比较未完成：{width}")
        row = {"width": width, "group_width": group_width, "passed": True,
               "formal_proven": True, "four_state_checks": 8196,
               "formal_log_sha256": digest(log), "simulation_log_sha256": digest(folder / "run.log")}
        runs.append(row)
        print(json.dumps(row), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in [CONTROLLER, *sources]}:
        raise RuntimeError("检查期间生产 RTL 发生变化")
    report = {"passed": True, "input_constraints": None, "source_sha256": hashes,
              "runs": runs, "four_state_checks": sum(row["four_state_checks"] for row in runs)}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
