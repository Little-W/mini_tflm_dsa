#!/usr/bin/env python3
"""验证实际偏置零值分组、控制器可见位宽及末级偏置需求选择。"""
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
PARENT = ROOT / "rtl/npu/top/npu_matrix_engine.sv"
HELPER = ROOT / "rtl/npu/top/npu_bias_presence.sv"
WIDTHS = (1, 16, 29, 32, 33, 64)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parent = PARENT.read_text()
    first = parent.index("    localparam int unsigned p_bias_zero_groups")
    zero_logic = parent[first:parent.index("    assign bias_execution_address_i_base", first)]
    instance = re.search(r"    npu_bias_presence u_bias_presence\s*\(.*?\);", parent, re.S).group(0)
    model = out / "proof.sv"
    model.write_text("""// 直接提取生产矩阵引擎的零值分组及偏置需求实例连接。
module integrated_proof #(parameter p_reg_width=32,
    parameter p_controller_bias_w=p_reg_width<32?p_reg_width:32) (
    input logic [p_reg_width-1:0] i_bias_base, // 完整偏置地址
    input logic [5:0] i_flags, // 模式、首末帧及通道地址零值条件
    output logic o_equal // 实际连接与完整表达式相同
);
    logic bias_base_nonzero, controller_bias_base_nonzero, exec_bias_present;
    logic o_frame_mode_q, o_is_mode, ws_final_bias, frame_exec_final, frame_exec_init, bias_zero_o_equal;
    logic expected;
    assign {o_frame_mode_q,o_is_mode,ws_final_bias,frame_exec_final,frame_exec_init,bias_zero_o_equal}=i_flags;
""" + zero_logic + instance + """
    assign expected=o_frame_mode_q ?
        ((i_bias_base!=0) && ((o_is_mode||ws_final_bias)?frame_exec_final:frame_exec_init) &&
         !bias_zero_o_equal) : (p_controller_bias_w'(i_bias_base)!=0);
    assign o_equal=(exec_bias_present===expected) &&
        (bias_base_nonzero===(i_bias_base!=0)) &&
        (controller_bias_base_nonzero===(p_controller_bias_w'(i_bias_base)!=0));
endmodule

module presence_proof(input logic [7:0] i_flags, output logic o_equal);
    logic actual, expected;
    npu_bias_presence u_presence(
        .i_frame_mode(i_flags[0]), .i_base_nonzero(i_flags[1]), .i_is_mode(i_flags[2]),
        .i_ws_final_bias(i_flags[3]), .i_frame_final(i_flags[4]), .i_frame_init(i_flags[5]),
        .i_address_zero(i_flags[6]), .i_visible_base_nonzero(i_flags[7]), .o_present(actual));
    assign expected=i_flags[0] ?
        (i_flags[1] && ((i_flags[2]||i_flags[3])?i_flags[4]:i_flags[5]) && !i_flags[6]) : i_flags[7];
    assign o_equal=actual===expected;
endmodule
""")
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolver([model], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [PARENT, HELPER]}
    formal = []
    for top, width in [("presence_proof", None)] + [("integrated_proof", value) for value in WIDTHS]:
        name = top if width is None else f"integrated{width}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        options = [] if width is None else [f"-Gp_reg_width={width}"]
        script.write_text(shlex.join(["read_slang", "--top", top, *options, *map(str, sources)]) +
            f"\nprep -top {top} -flatten\nsat -verify -prove o_equal 1\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError("偏置需求形式证明未完成")
        formal.append({"top": top, "width": width, "passed": True, "log_sha256": digest(log)})
    bench = out / "tb.sv"
    text = """// 穷举独立偏置资格的全部四态组合，并覆盖实际地址分组的所有输入位。
module tb;
    logic [7:0] flags;
    logic [63:0] address;
    logic presence_equal;
    logic [5:0] integrated_equal;
    presence_proof u_presence(.i_flags(flags), .o_equal(presence_equal));
"""
    for index, width in enumerate(WIDTHS):
        text += f"    integrated_proof #(.p_reg_width({width})) u_width{width}(.i_bias_base(address[{width-1}:0]), .i_flags(flags[5:0]), .o_equal(integrated_equal[{index}]));\n"
    text += """    function automatic logic four(input logic [1:0] value);
        case(value) 0:four=0; 1:four=1; 2:four=1'bx; 3:four=1'bz; endcase
    endfunction
    initial begin
        for(integer sample=0;sample<65536;sample++) begin
            for(integer bit_index=0;bit_index<8;bit_index++)
                flags[bit_index]=four(2'(sample>>(2*bit_index)));
            address={$urandom,$urandom};
            case(sample%8)
                0:address='0;
                1:address='1;
                2:address='x;
                3:address='z;
                4:begin address='0; address[(sample/8)%64]=1'bx; end
                5:begin address='0; address[(sample/8)%64]=1'bz; end
                default:begin end
            endcase
            #1;
            if(presence_equal!==1'b1 || integrated_equal!==6'b111111)
                $fatal(1,"Bias selection differs flags=%b address=%h",flags,address);
        end
        $display("BIAS_ZERO_SELECTION_PASS presence=65536 integrated=393216");
        $finish;
    end
endmodule
"""
    bench.write_text(text)
    binary = out / "four_state.vvp"
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), *map(str, sources), str(bench)],
            stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=180)
    (out / "run.log").write_text(result.stdout + result.stderr)
    if "BIAS_ZERO_SELECTION_PASS" not in result.stdout:
        raise RuntimeError("偏置需求四态比较未完成")
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in [PARENT, HELPER]}:
        raise RuntimeError("检查期间生产 RTL 发生变化")
    report = {"passed": True, "input_constraints": None, "source_sha256": hashes,
              "formal": formal, "presence_four_state_checks": 65536,
              "integrated_four_state_checks": 393216, "simulation_log_sha256": digest(out / "run.log")}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
