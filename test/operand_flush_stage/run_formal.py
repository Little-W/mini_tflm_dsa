#!/usr/bin/env python3
"""检查实际控制器的缓存清除寄存级与加载初始化顺序。"""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "rtl/npu/top/npu_top.sv", ROOT / "rtl/npu/control/npu_controller.sv"]
    top, controller = [p.read_text() for p in paths]
    if len(re.findall(r"\.cache_flush\s*\(operand_loader_flush_q\)", top)) != 2:
        raise ValueError("两个操作数加载器必须使用已保存的清除事件")
    fire = re.search(r"assign cfg_stage2_fire\s*=.*?;", top, re.S)[0]
    stage = re.search(r"always_ff @\(posedge clk or negedge core_rst_n\) begin\s*"
                      r"if \(!core_rst_n\) operand_loader_flush_q.*?\n    end", top, re.S)[0]
    stage = stage.replace("core_rst_n", "rst_n")
    header_end = controller.index("\n);")
    controller = controller[:header_end] + """
    ,
    input wire cfg_stage2_valid,
    input wire [2:0] cfg_capacity_phase,
    input wire frame_scheduler_ready
""" + controller[header_end:]
    formal = """
    wire ctrl_sa_ready = sa_ready;
    wire cfg_stage2_fire;
    logic operand_loader_flush_q;
""" + fire + "\n" + stage + """
    logic sampled = 1'b0;
    logic previous_reset, previous_fire, clear_sampled, configuration_pending;
    always_ff @(posedge clk) begin
        sampled <= 1'b1;
        previous_reset <= rst_n;
        previous_fire <= cfg_stage2_fire;
        if (!rst_n) begin
            clear_sampled <= 1'b0;
            configuration_pending <= 1'b0;
        end else begin
            if (cfg_stage2_fire) begin
                configuration_pending <= 1'b1;
                clear_sampled <= 1'b0;
            end
            if (operand_loader_flush_q) clear_sampled <= 1'b1;
            if (init_cfg_ia || init_cfg_weight) configuration_pending <= 1'b0;
        end
        if (sampled && previous_reset && rst_n) begin
            assert(operand_loader_flush_q == previous_fire);
            assert(!configuration_pending || clear_sampled || operand_loader_flush_q);
            if (operand_loader_flush_q) begin
                assert(!init_cfg_ia && !init_cfg_weight);
                assert(!send_ia_trigger && !send_weight_trigger && !weight_commit);
            end
            if (configuration_pending && (init_cfg_ia || init_cfg_weight))
                assert(clear_sampled);
        end
    end
"""
    controller = controller.replace("endmodule", formal + "\nendmodule")
    source = out / "controller_formal.sv"
    source.write_text(controller)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    report = dict(source_sha256=hashes,
                  scope="实际控制器全部输入任意；配置提交使用顶层实际就绪与相位条件",
                  properties=["清除事件延迟一个周期", "清除与加载初始化互斥",
                              "清除期间不发出计算输入或权重发送事件", "首次加载初始化前已采样清除事件"],
                  runs=[])
    for size, bus, width in [(4,32,16), (8,64,32), (16,64,32), (32,32,40)]:
        folder = out / f"s{size}_b{bus}_w{width}"
        folder.mkdir(exist_ok=True)
        script, log = folder / "run.ys", folder / "formal.log"
        script.write_text(f"read_slang --top npu_controller -GSIZE={size} -GBUS_WIDTH={bus} "
                          f"-GREG_WIDTH={width} {shlex.quote(str(source))}\n"
                          "prep -top npu_controller -flatten\nasync2sync\nchformal -lower\nopt_clean\n"
                          "sat -seq 3 -tempinduct -maxsteps 12 -set-at 1 rst_n 0 -prove-asserts -verify\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        if "Induction step proven: SUCCESS!" not in log.read_text():
            raise RuntimeError(f"初始化顺序证明未完成：{log}")
        item = dict(size=size, bus_width=bus, register_width=width, passed=True,
                    log_sha256=digest(log))
        report["runs"].append(item)
        print(json.dumps(item), flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in paths}:
        raise RuntimeError("验证期间源码发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
