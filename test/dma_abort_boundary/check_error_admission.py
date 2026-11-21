#!/usr/bin/env python3
"""验证真实 DMA 错误接收逻辑的命令停止、响应握手和状态周期。"""
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
SOURCE = Path("rtl/npu/dma/axi_block_dma_arbiter.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    control = re.search(r"    if \(p_register_bus_error\).*?\n    end\n", source, re.S)
    if control is None:
        raise ValueError("无法定位错误状态生成过程")
    expressions = []
    for name in ("response_error_pending", "completed_error", "bus_error_event"):
        match = re.search(r"    assign " + name + r"\s*=.*?;", source, re.S)
        if match is None:
            raise ValueError("无法定位错误接收表达式：" + name)
        expressions.append(match[0])
    model = out / "error_admission.sv"
    model.write_text("""module error_admission #(parameter bit p_register_bus_error=1)(
    input logic clk, rst_n, abort,
    input logic m_axi_rvalid, m_axi_rready, m_axi_bvalid, m_axi_bready,
    input logic [1:0] m_axi_rresp, m_axi_bresp,
    input logic rd_dma_done, dma_rd_error, wr_dma_done, dma_wr_error,
    output logic correct
);
    logic local_abort, dma_abort, transfer_abort, bus_error_event, bus_error;
    logic response_error_pending, completed_error;
""" + control[0] + "\n" + "\n".join(expressions) + """
    logic expected_error_q;
    wire read_error = m_axi_rvalid && m_axi_rresp[1];
    wire write_error = m_axi_bvalid && m_axi_bresp[1];
    wire completion_error = (rd_dma_done && dma_rd_error) || (wr_dma_done && dma_wr_error);
    wire accepted_error = (read_error && m_axi_rready) ||
        (write_error && m_axi_bready) || completion_error;
    always_ff @(posedge clk) begin
        if (!rst_n) expected_error_q <= 1'b0;
        else expected_error_q <= accepted_error;
    end
    // 停止接收覆盖所有有效错误；响应背压不改变新命令资格。
    // 活动写通道与公开错误状态只使用已完成的响应握手。
    assign correct = p_register_bus_error ?
        ((local_abort == (abort || read_error || write_error || completion_error)) &&
         (dma_abort == (abort || accepted_error)) &&
         (bus_error == expected_error_q) &&
         (transfer_abort == (abort || expected_error_q)) &&
         (!accepted_error || local_abort)) :
        ((local_abort == abort) && (dma_abort == abort) && (transfer_abort == abort) &&
         (bus_error == accepted_error));
endmodule
""")
    report = {"passed": False, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "functional_inputs_constrained": False, "initial_reset_cycle": 1, "runs": []}
    for registered in (0, 1):
        script = out / f"register{registered}.ys"
        log = out / f"register{registered}.log"
        script.write_text(
            f"read_slang --top error_admission -Gp_register_bus_error={registered} " +
            shlex.quote(str(model)) + "\nprep -top error_admission -flatten\n" +
            "sat -seq 2 -prove-skip 1 -prove correct 1 -verify -set-def-inputs "
            "-set-init-def -set-at 1 rst_n 0\n" +
            "sat -seq 1 -tempinduct-inductonly -tempinduct-def -maxsteps 2 "
            "-prove correct 1 -verify -set-def-inputs -set-init-def\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           cwd=ROOT, check=True, timeout=60)
        text = log.read_text()
        if ("SAT proof finished - no model found: SUCCESS!" not in text or
                "Induction step proven: SUCCESS!" not in text):
            raise RuntimeError("错误接收逻辑证明未完成")
        report["runs"].append({"registered_bus_error": registered, "passed": True,
                               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
