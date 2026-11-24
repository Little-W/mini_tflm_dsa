#!/usr/bin/env python3
"""验证历史坐标准备阶段的完整模运算和连续位置输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def model(source: str) -> str:
    first = source.index("  if (!p_register_descriptor) begin : g_history_columns\n")
    last = source.index("  // 已保存的位置差", first)
    body = source[first:last]
    return """module comparison #(parameter int p_check_group=-1)(input logic i_clk,i_start,input logic[95:0] stimulus,
output logic equivalent);
localparam bit p_register_descriptor=0;
logic[2:0] phase=0;
logic[63:0] history_fields;
logic[31:0] position_q;
logic[31:0] i_last_p;
logic[15:0] i_last_x;
typedef struct packed {logic[15:0] output_w;} cfg_t;
typedef struct packed {logic[31:0] position;} tile_t;
cfg_t i_c;
tile_t committing_tile;
assign {i_last_p,i_last_x,i_c.output_w}=history_fields;
assign committing_tile.position=stimulus[31:0];
always_ff @(posedge i_clk) begin
  position_q<=stimulus[31:0];
  if(i_start)begin phase<=1;history_fields<=stimulus[95:32];end
  else if(phase!=0 && phase<4)phase<=phase+1'b1;
end
logic[32:0] p_history_delta_q;
logic unused_delta_carry;
parallel_prefix_add #(.p_width(33),.p_group_width(4),.p_preserve_groups(1'b1)) u_delta(
  .i_a({1'b0,position_q}),.i_b(~{1'b0,i_last_p}),.i_carry(1'b1),
  .o_sum(p_history_delta_q),.o_carry(unused_delta_carry));
logic[16:0] p_sum,p_sum_reduced,history_column_sum,history_column_reduced;
logic history_width_reached,history_column_advance;
logic unused_sum_carry,unused_reduce_carry;
logic[17:0] reduce_a,reduce_b,reduce_generate,reduce_sum;
parallel_prefix_add #(.p_width(17),.p_group_width(4),.p_preserve_groups(1'b1),.p_carry_select_width(8)) u_sum(
  .i_a({1'b0,i_last_x}),.i_b({1'b0,p_history_delta_q[15:0]}),.i_carry(1'b0),
  .o_sum(p_sum),.o_carry(unused_sum_carry));
assign reduce_a={2'b0,i_last_x}^{2'b0,p_history_delta_q[15:0]}^~{2'b0,i_c.output_w};
assign reduce_generate=({2'b0,i_last_x}&{2'b0,p_history_delta_q[15:0]})|
  (({2'b0,i_last_x}|{2'b0,p_history_delta_q[15:0]})&~{2'b0,i_c.output_w});
assign reduce_b={reduce_generate[16:0],1'b1};
parallel_prefix_add #(.p_width(18),.p_group_width(4),.p_preserve_groups(1'b1),.p_carry_select_width(8)) u_reduce(
  .i_a(reduce_a),.i_b(reduce_b),.i_carry(1'b0),.o_sum(reduce_sum),.o_carry(unused_reduce_carry));
assign p_sum_reduced=reduce_sum[16:0];
assign history_width_reached=!reduce_sum[17];
""" + body + """
wire[34:0] observed={history_column_sum,history_column_reduced,history_column_advance};
wire[34:0] expected={p_sum,p_sum_reduced,history_width_reached};
wire[17:0] expected_origin={2'b0,i_last_p[15:0]}-{2'b0,i_last_x};
wire[17:0] expected_limit=expected_origin+{2'b0,i_c.output_w};
wire position_borrow=position_q[15:0]<i_last_p[15:0];
wire[16:0] direct_column={1'b0,position_q[15:0]}-g_history_columns.origin_q[16:0];
wire[17:0] direct_reduced={2'b0,position_q[15:0]}-g_history_columns.limit_q;
wire[16:0] expected_column=direct_column+{position_borrow,16'b0};
wire[17:0] expected_reduced=direct_reduced+{1'b0,position_borrow,16'b0};
if(p_check_group<0)begin:g_all
  assign equivalent=phase<3 || observed===expected;
end else if(p_check_group==0)begin:g_origin
  assign equivalent=phase<2 || g_history_columns.origin_q==expected_origin;
end else if(p_check_group==1)begin:g_limit
  assign equivalent=phase<2 || g_history_columns.limit_q==expected_limit;
end else if(p_check_group==2)begin:g_column
  assign equivalent=phase<3 || history_column_sum==expected_column;
end else begin:g_reduced
  assign equivalent=phase<3 || {history_column_advance,history_column_reduced}==
    {!expected_reduced[17],expected_reduced[16:0]};
end
endmodule
"""


BENCH = """module tb;
logic i_clk=0,i_start=0;
logic[95:0] stimulus,known_stimulus;
wire equivalent;
integer checks=0;
comparison dut(.*);
task automatic tick;
  #1;i_clk=1;#1;i_clk=0;
  if(equivalent!==1'b1)$fatal(1,"History preparation mismatch check=%0d",checks);
  checks++;
endtask
task automatic run_case;
  i_start=1;tick();i_start=0;tick();tick();
  for(int update=0;update<4;update++)begin
    stimulus[31:0]=$urandom;tick();
  end
endtask
initial begin
  for(int trial=0;trial<16;trial++)begin
    known_stimulus={$urandom,$urandom,$urandom};stimulus=known_stimulus;run_case();
    for(int bit_index=0;bit_index<96;bit_index++)begin
      stimulus=known_stimulus;stimulus[bit_index]=1'bx;run_case();
      stimulus=known_stimulus;stimulus[bit_index]=1'bz;run_case();
    end
    stimulus='x;run_case();stimulus='z;run_case();
  end
  $display("HISTORY_COLUMNS_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    geometry = root / "rtl/npu/conv/conv_im2col_geometry.sv"
    helper = root / "rtl/common/parallel_prefix_add.sv"
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (geometry, helper)}
    rtl = out / "model.sv"
    rtl.write_text(model(geometry.read_text()))
    formal = []
    for group in range(4):
        script = out / f"group_{group}.ys"
        script.write_text(f"read_slang --top comparison -Gp_check_group={group} -D SYNTHESIS=1 " +
                          shlex.join(map(str, (helper, rtl))) + "\n" +
                          "prep -top comparison -flatten\nopt\ncheck -assert\n" +
                          "sat -seq 6 -set-def-inputs -prove equivalent 1 -verify\n")
        log = out / f"group_{group}.log"
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        formal.append({"group": group, "passed": True,
                       "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"HISTORY_COLUMN_GROUP_PASS group={group}", flush=True)
    local_helper = out / helper.name
    local_helper.write_text(helper.read_text().replace("parameter int unsigned", "parameter integer"))
    bench = out / "bench.sv"
    bench.write_text(BENCH)
    binary = out / "run.vvp"
    with (out / "build.log").open("w") as stream:
        subprocess.run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb",
                        "-o", str(binary), str(local_helper), str(rtl), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
    with (out / "run.log").open("w") as stream:
        subprocess.run([shutil.which("vvp") or "vvp", str(binary)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    output = (out / "run.log").read_text()
    if "HISTORY_COLUMNS_FOUR_STATE_PASS" not in output:
        raise AssertionError(output)
    current_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in hashes}
    if current_hashes != hashes:
        raise RuntimeError("历史坐标准备检查期间源文件发生变化")
    # 一次多项式逐项比较系数，连接各阶段的定宽算术关系。
    # d=P-L+65536*b；P-(L-X)+65536*b=X+d，减去宽度后关系保持。
    def add(left, right):
        return tuple(a + b for a, b in zip(left, right))
    def sub(left, right):
        return tuple(a - b for a, b in zip(left, right))
    position, last, column, width, correction = (
        (1, 0, 0, 0, 0), (0, 1, 0, 0, 0), (0, 0, 1, 0, 0),
        (0, 0, 0, 1, 0), (0, 0, 0, 0, 65536))
    delta = add(sub(position, last), correction)
    origin = sub(last, column)
    column_identity = sub(add(sub(position, origin), correction), add(column, delta))
    reduced_identity = sub(add(sub(position, add(origin, width)), correction), sub(add(column, delta), width))
    assert column_identity == reduced_identity == (0, 0, 0, 0, 0)
    report = {"passed": True, "source_sha256": hashes, "sources_unchanged": True,
              "unconstrained_input_bits": 97, "formal_steps": 6,
              "phase": "The history fields are saved at start; positions may change every cycle. "
                       "Both existing preparation edges precede comparison.",
              "formal": formal,
              "composition": {"variables": ["P", "L", "X", "W", "borrow"],
                              "column_coefficient_difference": column_identity,
                              "reduced_coefficient_difference": reduced_identity,
                              "moduli": [131072, 262144],
                              "delta_range": [0, 65535], "sum_range": [0, 131070],
                              "reduced_range": [-65535, 131070]},
              "four_state": output.strip()}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("HISTORY_COLUMNS_PASS formal_steps=6 " + output.splitlines()[0], flush=True)


if __name__ == "__main__":
    main()
