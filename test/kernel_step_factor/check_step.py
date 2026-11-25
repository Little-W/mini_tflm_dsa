#!/usr/bin/env python3
"""从实际 RTL 提取完整分组步长，检查任意输入、寄存器更新及四态行为。"""
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
SOURCE = Path("rtl/npu/loaders/kernel_loader_ctrl.sv")
PROFILES = ((32, 29), (32, 32), (64, 64), (64, 32), (32, 11),
            (11, 11), (10, 11), (11, 10), (8, 8), (4, 3),
            (2, 1), (32, 0), (7, 16))
SEED = 20261125


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(source, name):
    """提取声明、二十五倍求和及完整选择，不另写待测算术函数。"""
    start = source.index("  logic [REG_WIDTH-1:0] group_addr_step_next;")
    end = source.index("  count_t last_group_width;", start)
    arithmetic = source[start:end]
    selections = [match for match in re.finditer(
        r"case\s*\(w_reuse_total\).*?endcase", source, re.S)
        if "group_addr_step_next" in match[0]]
    if len(selections) != 1:
        raise ValueError("需要唯一的完整分组步长选择")
    begin = selections[0].start()
    finish = source.index("    last_col_in_group =", begin)
    selection = source[begin:finish]
    writes = re.findall(r"group_addr_step_q\s*<=\s*([^;]+);", source)
    if writes != ["'0", "group_addr_step_next"]:
        raise ValueError("步长寄存器需要重新检查复位与写入规则")
    if not re.search(r"S_INIT:\s*begin\s*(?://[^\n]*\n\s*)*"
                     r"group_addr_step_q\s*<=\s*group_addr_step_next;", source):
        raise ValueError("步长寄存器的更新状态需要重新检查")
    auxiliary = source[source.index("\nendmodule") + len("\nendmodule"):]
    auxiliary = auxiliary.replace("`default_nettype wire", "")
    return f"""module {name} #(
    parameter integer REG_WIDTH = 32, COUNT_WIDTH = 29
)(
    input logic clk, rst_n, clear, enable,
    input logic [REG_WIDTH-1:0] col_addr_step,
    input logic [((COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH)-1:0] w_reuse_total,
    output logic [REG_WIDTH-1:0] o_step,
    output logic [REG_WIDTH-1:0] o_saved
);
    localparam integer CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
    typedef logic [CNT_W-1:0] count_t;
{arithmetic}
    always_comb begin
{selection}
    end
    assign o_step = group_addr_step_next;
    // 原寄存器由异步复位清零，清空事件保持地址，初始化状态保存完整步长。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_saved <= '0;
        end else if (clear) begin
        end else if (enable) begin
            o_saved <= group_addr_step_next;
        end
    end
endmodule
""" + auxiliary


def run_worker(folder, name, commands):
    script = folder / (name + ".ys")
    script.write_text("\n".join(commands) + "\n")
    log = folder / (name + ".log")
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=600)
    return {"script_sha256": digest(script), "log_sha256": digest(log)}


def bench(reg_width, count_width, samples):
    return f"""`timescale 1ns/1ps
module tb;
    localparam integer REG_WIDTH = {reg_width}, COUNT_WIDTH = {count_width};
    localparam integer CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
    logic clk = 0, rst_n = 0, clear = 0, enable = 0;
    logic [REG_WIDTH-1:0] col_addr_step = '0;
    logic [CNT_W-1:0] w_reuse_total = '0;
    wire [REG_WIDTH-1:0] reference_step, current_step, reference_saved, current_saved;
    integer seed = {SEED + reg_width * 131 + count_width};
    integer discard_random, checked = 0;
    logic [REG_WIDTH-1:0] previous_saved, expected_saved;
    logic [63:0] random_bits;
    step_reference #(.REG_WIDTH(REG_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) u_reference (
        .clk(clk), .rst_n(rst_n), .clear(clear), .enable(enable),
        .col_addr_step(col_addr_step), .w_reuse_total(w_reuse_total),
        .o_step(reference_step), .o_saved(reference_saved)
    );
    step_current #(.REG_WIDTH(REG_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) u_current (
        .clk(clk), .rst_n(rst_n), .clear(clear), .enable(enable),
        .col_addr_step(col_addr_step), .w_reuse_total(w_reuse_total),
        .o_step(current_step), .o_saved(current_saved)
    );
    task automatic compare;
        #1;
        if (reference_step !== current_step)
            $fatal(1, "组合步长不同：sample=%0d step=%h count=%h", checked, col_addr_step, w_reuse_total);
        previous_saved = reference_saved;
        expected_saved = previous_saved;
        if (!rst_n) expected_saved = '0;
        else if (clear) begin end
        else if (enable) expected_saved = reference_step;
        clk = 1;
        #1;
        if (reference_saved !== current_saved || current_saved !== expected_saved)
            $fatal(1, "保存、保持或复位行为不同：sample=%0d", checked);
        checked++;
        clk = 0;
        #1;
    endtask
    initial begin
        discard_random = $urandom(seed);
        compare();
        for (integer sample = 0; sample < {samples}; sample++) begin
            random_bits = {{$urandom, $urandom}};
            col_addr_step = REG_WIDTH'(random_bits);
            random_bits = {{$urandom, $urandom}};
            w_reuse_total = CNT_W'(random_bits);
            case (sample % 16)
                0: w_reuse_total = CNT_W'(1);
                1: w_reuse_total = CNT_W'(2);
                2: w_reuse_total = CNT_W'(4);
                3: w_reuse_total = CNT_W'(8);
                4: w_reuse_total = CNT_W'(16);
                5: w_reuse_total = CNT_W'(25);
                6: w_reuse_total = CNT_W'(32);
                7: w_reuse_total = CNT_W'(64);
                8: w_reuse_total = CNT_W'(128);
                9: w_reuse_total = CNT_W'(256);
                10: w_reuse_total = CNT_W'(512);
                11: w_reuse_total = CNT_W'(1024);
                12: w_reuse_total = '0;
                13: w_reuse_total = '1;
                default: begin end
            endcase
            rst_n = sample % 37 != 0;
            clear = sample % 7 == 0;
            enable = sample % 3 != 0;
            case (sample % 11)
                0: col_addr_step = '0;
                1: col_addr_step = '1;
                2: col_addr_step[sample % REG_WIDTH] = 1'bx;
                3: col_addr_step[sample % REG_WIDTH] = 1'bz;
                4: w_reuse_total[sample % CNT_W] = 1'bx;
                5: w_reuse_total[sample % CNT_W] = 1'bz;
                6: enable = 1'bx;
                7: enable = 1'bz;
                8: clear = 1'bx;
                9: clear = 1'bz;
                default: begin end
            endcase
            if (sample % 41 == 1) rst_n = 1'bx;
            if (sample % 41 == 2) rst_n = 1'bz;
            // 异步复位在时钟上升沿之前接受，同步检查另行覆盖保持和更新。
            #1;
            compare();
        end
        $display("KERNEL_STEP_FOUR_STATE_PASS cycles=%0d", checked);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="ed5c58ab")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12000)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    reference_text = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"],
                                            cwd=ROOT, text=True)
    current_text = (root / SOURCE).read_text()
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    helpers = resolve([root / "rtl/common/parallel_prefix_add.sv"], root)
    copies, hashes = [], {str(SOURCE): digest(root / SOURCE)}
    for path in helpers:
        relative = path.relative_to(root)
        reference_data = subprocess.check_output(["git", "show", f"{revision}:{relative}"], cwd=ROOT)
        if reference_data != path.read_bytes():
            raise ValueError("局部证明要求两版公共加法器完全相同：" + str(relative))
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(reference_data)
        copies.append(target)
        hashes[str(relative)] = digest(path)
    for label, content in (("reference", reference_text), ("current", current_text)):
        (out / (label + ".sv")).write_text(extract(content, "step_" + label))
    files = [out / "reference.sv", out / "current.sv", *copies]
    records = []
    for reg_width, count_width in PROFILES:
        folder = out / f"reg{reg_width}_count{count_width}"
        folder.mkdir(exist_ok=True)
        miter = folder / "miter.sv"
        miter.write_text(f"""module step_miter (
    input logic [{reg_width-1}:0] col_addr_step,
    input logic [{max(1, count_width)-1}:0] w_reuse_total,
    output logic mismatch
);
    wire [{reg_width-1}:0] reference_step, current_step;
    step_reference #(.REG_WIDTH({reg_width}), .COUNT_WIDTH({count_width})) u_reference (
        .clk(1'b0), .rst_n(1'b0), .clear(1'b0), .enable(1'b0),
        .col_addr_step(col_addr_step), .w_reuse_total(w_reuse_total),
        .o_step(reference_step), .o_saved()
    );
    step_current #(.REG_WIDTH({reg_width}), .COUNT_WIDTH({count_width})) u_current (
        .clk(1'b0), .rst_n(1'b0), .clear(1'b0), .enable(1'b0),
        .col_addr_step(col_addr_step), .w_reuse_total(w_reuse_total),
        .o_step(current_step), .o_saved()
    );
    assign mismatch = reference_step != current_step;
endmodule
""")
        formal = run_worker(folder, "arithmetic", [
            "read_slang -DSYNTHESIS=1 --top step_miter " + shlex.join(map(str, [*files, miter])),
            "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
            "prep -top step_miter -flatten", "opt_clean",
            "sat -verify -prove mismatch 0 -show-inputs -show-outputs"])
        commands = []
        for label in ("reference", "current"):
            top = "step_" + label
            commands += [
                f"read_slang -DSYNTHESIS=1 --top {top} -GREG_WIDTH={reg_width} "
                f"-GCOUNT_WIDTH={count_width} " + shlex.join(map(str, files)),
                "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                f"prep -top {top} -flatten", "async2sync", "opt_clean",
                f"rename {top} {label}", f"design -stash {label}"]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -short -seq 1", "equiv_induct -seq 2", "equiv_status -assert"]
        sequential = run_worker(folder, "register_equivalence", commands)
        testbench = folder / "tb.sv"
        testbench.write_text(bench(reg_width, count_width, args.samples))
        command = ["iverilog", "-g2012", "-s", "tb", "-o", str(folder / "simulation.vvp"),
                   *map(str, [*files, testbench])]
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(folder / "simulation.vvp")], capture_output=True,
                                text=True, check=True, timeout=180)
        (folder / "run.log").write_text(result.stdout + result.stderr)
        match = re.search(r"KERNEL_STEP_FOUR_STATE_PASS cycles=(\d+)", result.stdout)
        if match is None or int(match[1]) != args.samples + 1:
            raise RuntimeError("四态检查没有完成全部周期")
        record = {"reg_width": reg_width, "count_width": count_width,
                  "inputs_constrained": False, "formal": formal,
                  "register_equivalence": sequential,
                  "four_state_cycles": int(match[1]), "passed": True,
                  "testbench_sha256": digest(testbench), "run_log_sha256": digest(folder / "run.log")}
        records.append(record)
        print(json.dumps(record), flush=True)
    if hashes != {name: digest(root / name) for name in hashes}:
        raise RuntimeError("验证期间源文件发生变化")
    summary = {"passed": True, "reference_commit": revision, "source_sha256": hashes,
               "reference_controller_sha256": hashlib.sha256(reference_text.encode()).hexdigest(),
               "seed": SEED, "profiles": records,
               "four_state_cycles": sum(item["four_state_cycles"] for item in records)}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
