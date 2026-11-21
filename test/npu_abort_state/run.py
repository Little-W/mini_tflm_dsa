#!/usr/bin/env python3
"""比较实际中止状态过程及其配置捕获、错误码和中止资格。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/top/npu_top.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text, name):
    begin = text.index("    always_ff @(posedge clk or negedge rst_n) begin\n"
                       "        if (!rst_n) begin\n            run_conv <=")
    end = text.index("    // Both operand loaders", begin)
    pending = re.search(r"    wire abort_pending = .*?;", text)[0]
    registered = "abort_pending_q" in pending
    return f"""module {name} #(parameter int p_config_width = 512)(
    input logic clk, rst_n, calc_start, sa_ready,
    input logic cfg_conv_enable, cfg_vector_enable, run_vector,
    input logic task_fault, dma_bus_error, conv_error,
    input logic dma_idle, conv_busy, operand_cache_idle, done_ready,
    input logic [p_config_width-1:0] cfg_conv,
    input logic [31:0] cfg_ps_control,
    output logic run_conv,
    output logic [p_config_width-1:0] conv_cfg_q,
    output logic [31:0] ps_control_q,
    output logic [1:0] abort_error_code,
    output wire [1:0] observed_state,
    output wire observed_pending, observed_core_reset_n);
    typedef enum logic [1:0] {{AB_IDLE, AB_DRAIN, AB_RESET, AB_DONE}} abort_t;
    abort_t abort_state;
""" + ("    logic abort_pending_q;\n" if registered else "") + pending + "\n" + \
        text[begin:end] + """
    assign observed_state = abort_state;
    assign observed_pending = abort_pending;
    assign observed_core_reset_n = rst_n && abort_state != AB_RESET;
endmodule
"""


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--current", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference", default="77e65876")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    texts = {"current": args.current.read_text(), "reference": subprocess.check_output(
        ["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)}
    snapshots = {}
    for label, text in texts.items():
        snapshots[label] = out / (label + ".sv")
        snapshots[label].write_text(extract(text, "abort_control"))
    result = {"passed": False, "reference": args.reference,
              "source_sha256": digest(args.current), "inputs_constrained": False,
              "proofs": []}
    for width in (1, 32, 512):
        commands = []
        for label, source in snapshots.items():
            commands += [
                f"read_slang --top abort_control -Gp_config_width={width} " + shlex.quote(str(source)),
                "prep -top abort_control -flatten", "async2sync", "opt_clean",
                f"rename abort_control {label}", f"design -stash {label}",
            ]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "equiv_induct -seq 3", "equiv_status -assert"]
        script = out / f"width{width}.ys"
        script.write_text("\n".join(commands) + "\n")
        log = script.with_suffix(".log")
        text = execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], log)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if match is None or int(match[2]):
            raise RuntimeError("中止状态等价检查未完成")
        result["proofs"].append({"passed": True, "configuration_width": width,
                                 "equivalent_bits": int(match[1]), "log_sha256": digest(log)})
    modules = out / "modules.sv"
    modules.write_text("\n".join(extract(t, "abort_" + label) for label, t in texts.items()))
    bench = out / "four_state.sv"
    flags = ["calc_start", "sa_ready", "cfg_conv_enable", "cfg_vector_enable", "run_vector",
             "task_fault", "dma_bus_error", "conv_error", "dma_idle", "conv_busy",
             "operand_cache_idle", "done_ready"]
    connections = ",".join("." + n for n in flags)
    body = r"""module tb;
    reg clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    reg FLAGS;
    reg [511:0] cfg_conv;
    reg [31:0] cfg_ps_control, random_state = 32'h1539b278;
    wire [550:0] current_value, reference_value;
    integer checks = 0;
    function automatic [31:0] random_word;
      begin
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        random_word = random_state;
      end
    endfunction
    function automatic four_value(input [1:0] v);
      case (v)
        0: four_value = 0;
        1: four_value = 1;
        2: four_value = 1'bx;
        3: four_value = 1'bz;
      endcase
    endfunction
    abort_current current (.clk, .rst_n, CONNECTIONS, .cfg_conv, .cfg_ps_control,
      .run_conv(current_value[0]), .abort_error_code(current_value[2:1]),
      .observed_state(current_value[4:3]), .observed_pending(current_value[5]),
      .observed_core_reset_n(current_value[6]), .ps_control_q(current_value[38:7]),
      .conv_cfg_q(current_value[550:39]));
    abort_reference reference (.clk, .rst_n, CONNECTIONS, .cfg_conv, .cfg_ps_control,
      .run_conv(reference_value[0]), .abort_error_code(reference_value[2:1]),
      .observed_state(reference_value[4:3]), .observed_pending(reference_value[5]),
      .observed_core_reset_n(reference_value[6]), .ps_control_q(reference_value[38:7]),
      .conv_cfg_q(reference_value[550:39]));
    initial begin
      {FLAGS} = '0; cfg_conv = 0; cfg_ps_control = 0;
      repeat (2) @(negedge clk);
      for (integer sample_index = 0; sample_index < 50000; sample_index = sample_index + 1) begin
        rst_n = sample_index % 64 != 0;
        cfg_ps_control = random_word();
        for (integer part = 0; part < 16; part = part + 1)
          cfg_conv[32*part+:32] = random_word();
ASSIGNMENTS
        #1;
        if (reference_value !== current_value) $fatal(1, "Asynchronous state mismatch");
        @(posedge clk); #1;
        if (reference_value !== current_value) $fatal(1, "Clocked state mismatch");
        checks = checks + 2;
        @(negedge clk);
      end
      $display("PASS checks=%0d", checks); $finish;
    end
endmodule
""".replace("FLAGS", ",".join(flags)).replace("CONNECTIONS", connections)
    body = body.replace("ASSIGNMENTS", "\n".join(
        f"        {name} = sample_index[0] ? four_value(2'(random_word())) : 1'(random_word());"
        for name in flags))
    bench.write_text(body)
    binary = out / "four_state.vvp"
    execute(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(modules), str(bench)],
            out / "four_state_build.log")
    log = out / "four_state_run.log"
    text = execute(["vvp", str(binary)], log)
    match = re.search(r"PASS checks=(\d+)", text)
    if match is None:
        raise RuntimeError("四态中止状态检查未完成")
    result["four_state"] = {"passed": True, "cycles": 50000, "checks": int(match[1]),
                             "compared_bits_per_check": 551, "log_sha256": digest(log)}
    if digest(args.current) != result["source_sha256"]:
        raise RuntimeError("验证期间源文件发生变化")
    result["passed"] = True
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
