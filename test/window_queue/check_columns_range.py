#!/usr/bin/env python3
"""验证窗口列数范围的完整位宽、参数边界和四态语义。"""
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
RTL = Path("rtl/npu/dma/conv_window_queue.sv")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_root.resolve() / RTL, args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_hash = digest(source)
    helper = re.search(r"(?m)^module conv_window_cols_range\b.*?endmodule", source.read_text(), re.S)
    if helper is None:
        raise RuntimeError("未找到完整列数范围模块")
    limits = sorted({0, 3, 5, 17, 33, 255, 257, 0xfffffffe, 0xffffffff} |
                    {1 << bit for bit in range(32)} |
                    {(1 << bit) - 1 for bit in range(1, 32)})
    width = len(limits)
    instances = []
    for index, limit in enumerate(limits):
        instances.append(f"""  logic actual_{index}, expected_{index};
  conv_window_cols_range #(.p_max_cols(32'h{limit:08x})) u_range_{index}(
    .i_columns(columns), .o_valid(actual_{index}));
  assign expected_{index} = columns > 32'd0 && columns <= 32'h{limit:08x};
  assign equivalent[{index}] = actual_{index} === expected_{index};
""")
    model_text = helper.group() + f"""
module comparison(input logic [31:0] columns, output logic [{width-1}:0] equivalent);
{''.join(instances)}endmodule
"""
    model = out / "model.sv"
    model.write_text(model_text)
    proof = out / "proof.ys"
    proof.write_text("read_slang --top comparison -DSYNTHESIS=1 " + shlex.quote(str(model)) + "\n"
                     "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                     "prep -top comparison -flatten\ncheck -assert\n"
                     f"sat -verify -prove equivalent {width}'b{'1'*width} -set-def-inputs\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", proof], out / "proof.log")
    boundaries = sorted({value & 0xffffffff for limit in limits for value in (limit-1, limit, limit+1)})
    boundary_checks = "\n".join(f"        columns=32'h{value:08x};check();" for value in boundaries)
    bench = out / "four_state.sv"
    bench.write_text(model_text + f"""module tb;
      logic [31:0] columns, saved, random_state=32'h7b402c69;
      logic [{width-1}:0] equivalent;
      integer checks=0;
      comparison u_comparison(.*);
      task automatic check;
        #1;if(equivalent!=={width}'b{'1'*width})$fatal(1,"Columns range differs at sample %0d",checks);
        checks++;
      endtask
      initial begin
{boundary_checks}
        for(integer trial=0;trial<64;trial++)begin
          for(integer bit_index=0;bit_index<32;bit_index++)begin
            random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
            columns[bit_index]=random_state[0];
          end
          if(trial%4==0)columns='0;
          if(trial%4==1)columns='1;
          saved=columns;check();
          for(integer bit_index=0;bit_index<32;bit_index++)begin
            columns=saved;columns[bit_index]=1'bx;check();
            columns=saved;columns[bit_index]=1'bz;check();
          end
          columns='x;check();columns='z;check();
        end
        $display("COLUMNS_RANGE_FOUR_STATE_PASS checks=%0d",checks);$finish;
      end
    endmodule
""")
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", bench],
        out / "four_state_compile.log")
    run(["vvp", out / "four_state.vvp"], out / "four_state.log")
    count = len(boundaries) + 64 * 67
    if f"COLUMNS_RANGE_FOUR_STATE_PASS checks={count}" not in (out / "four_state.log").read_text():
        raise RuntimeError("列数范围四态检查未完成")
    if digest(source) != source_hash:
        raise RuntimeError("检查期间源码发生变化")
    result = {"passed": True, "input_bits_unconstrained": 32, "parameter_limits": limits,
              "four_state_vectors": count, "configurations_per_vector": width,
              "source_sha256": {str(source): source_hash}, "checker_sha256": digest(__file__),
              "model_sha256": digest(model), "proof_log_sha256": digest(out / "proof.log")}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("COLUMNS_RANGE_PASS", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
