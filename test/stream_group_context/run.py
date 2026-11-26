#!/usr/bin/env python3
"""按前端配置、通道保存及有效运行阶段验证流式模块完整输出。"""
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
STREAM = Path("rtl/npu/conv/conv_im2col_stream.sv")
PROFILES = (
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128,
     "p_bus_width": 64, "p_register_descriptor": 0, "p_register_row_address": 0},
    {"p_size": 16, "p_slot_w": 5, "p_lanes": 8, "p_line_bytes": 128,
     "p_bus_width": 64, "p_register_descriptor": 1, "p_register_row_address": 1},
    {"p_size": 8, "p_slot_w": 3, "p_lanes": 3, "p_line_bytes": 16,
     "p_bus_width": 32, "p_register_descriptor": 0, "p_register_row_address": 1},
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wrapper(source):
    header = source[source.index("module conv_im2col_stream"):source.index(");")+2]
    header = header.replace("module conv_im2col_stream", "module stream_contract", 1)
    header = re.sub(r"(?m)^\s*input[^\n]*\bi_(?:ch0_q|ch0|state)\b[^\n]*\n", "", header)
    for original, renamed in (("i_c", "i_context"), ("i_wr_valid", "i_output_valid"),
                              ("i_committing_tile_packed", "i_commit_fields")):
        header = re.sub(r"\b"+original+r"\b", renamed, header)
    lines = header[:header.rfind(");")].rstrip().splitlines()
    declaration, marker, comment = lines[-1].partition("//")
    lines[-1] = declaration.rstrip() + "," + (" //"+comment if marker else "")
    header = "\n".join(lines) + """
  input logic [4:0] i_phase, // 前端独热状态对应的阶段编号
  output logic [2:0] contract_group_flags // 保存高段关系与通道状态的一致性比较
);
"""
    observed = "u_stream.g_tile_group_range[1].g_short_remaining.u_group_context.range_flags" \
        if " u_group_context (" in source else "reference_flags"
    return header + """
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w=p_tile_count_w;
  localparam int p_prepared_slot_w=p_slot_w;
  localparam int p_prepared_coord_w=p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
  logic [15:0] i_ch0_q,group_width;
  logic [31:0] i_ch0;
  logic i_wr_valid;
  st_t i_state;
  conv_cfg_t i_c;
  prepared_tile_t committed;
  logic [p_prepared_tile_width-1:0] i_committing_tile_packed;
  logic [2:0] reference_flags;
  // 前端状态寄存器保存独热状态，写输出只在三个流式阶段有效。
  assign i_state=st_t'(27'd1<<i_phase);
  assign i_wr_valid=i_output_valid&&
    (i_state[$clog2(WAIT_WORD)]||i_state[$clog2(STREAM)]||i_state[$clog2(ZERO_STREAM)]);
  assign i_ch0=32'(i_ch0_q);
  always_comb begin
    i_c=i_context;
    i_c.group_c=group_width;
    committed=prepared_tile_t'(i_commit_fields);
    if(!p_register_descriptor)begin
      committed.channel=i_ch0;
      if(i_incoming_next_position_fast)committed.channel={16'd0,i_window_next_ch};
    end
  end
  assign i_committing_tile_packed=committed;
  conv_im2col_stream #(.p_size(p_size),.p_slot_w(p_slot_w),.p_lanes(p_lanes),
    .p_line_bytes(p_line_bytes),.p_bus_width(p_bus_width),.p_register_descriptor(p_register_descriptor),
    .p_register_row_address(p_register_row_address))u_stream(.*);
  // 配置接收保持通道；有效快速提交和归约解码分别更新起始通道。
  always_ff @(posedge i_clk or negedge i_rst_n)begin
    if(!i_rst_n)begin group_width<=0;i_ch0_q<=0;end
    else if(i_cfg_valid&&i_cfg_ready)group_width<=i_cfg.group_c;
    else if(i_tile_commit)begin
      if(committed.invalid)begin end
      else if(committed.fast)i_ch0_q<=16'(committed.channel);
    end else begin
      unique case(1'b1)
        i_state[$clog2(Q_DECODE)]:begin
          if(i_q0==0)i_ch0_q<=0;
          else if(i_group_shape_o_valid)i_ch0_q<=o_group_range_channel[2];
          else if(i_c.group_c==3&&i_q0<27)i_ch0_q<=i_current_q_remainder;
        end
        i_state[$clog2(Q_WAIT)]:if(i_decode_index==i_q0)i_ch0_q<=16'(i_decode_inner);
        default:begin end
      endcase
    end
  end
  parallel_unsigned_compare #(.p_width(16-p_tile_count_w))u_reference_high(
    .i_a(i_ch0_q[15:p_tile_count_w]),.i_b(group_width[15:p_tile_count_w]),
    .o_less(reference_flags[0]),.o_equal(reference_flags[1]));
  increment_equal #(.p_width(16-p_tile_count_w))u_reference_next(
    .i_a(i_ch0_q[15:p_tile_count_w]),.i_target(group_width[15:p_tile_count_w]),
    .o_equal(reference_flags[2]));
  assign contract_group_flags=""" + observed + ";\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--candidate-stream", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out, reference = args.out.resolve(), args.reference_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources, hashes = {}, {}
    for side, tree in (("gold", reference), ("gate", ROOT)):
        stream = args.candidate_stream.resolve() if side == "gate" and args.candidate_stream else tree/STREAM
        contract = out / (side+"_contract.sv")
        contract.write_text(wrapper(stream.read_text()))
        helper = runpy.run_path(str(tree / "scripts/rtl/source_files.py"))
        sources[side] = helper["with_dependencies"]([stream,contract],tree)
        hashes[side] = {str(path):digest(path) for path in helper["input_files"](sources[side],tree)}
    results=[]
    for index,parameters in enumerate(PROFILES):
        commands=[]
        for side,tree in (("gold",reference),("gate",ROOT)):
            options=["--top","stream_contract","-DSYNTHESIS=1","-I"+str(tree/"include")]
            options += [f"-G{name}={value}" for name,value in parameters.items()]
            commands += ["read_slang "+shlex.join(options+list(map(str,sources[side]))),
              "prep -top stream_contract -flatten","memory_map","async2sync","opt",
              "rename stream_contract "+side,"design -stash "+side]
        commands += ["design -copy-from gold gold","design -copy-from gate gate",
          "equiv_make gold gate equivalent","hierarchy -top equivalent","opt_merge",
          "equiv_simple -short -seq 1","opt_clean","equiv_induct -seq 3","equiv_status -assert"]
        script,log=out/f"profile{index}.ys",out/f"profile{index}.log"
        script.write_text("\n".join(commands)+"\n")
        with log.open("w") as output:
            subprocess.run([sys.executable,str(ROOT/"scripts/fpga/open_fpga_synth.py"),"--worker",str(script)],
                cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True,timeout=600)
        content=log.read_text()
        points=re.search(r"Of those cells (\d+) are proven and (\d+) are unproven",content)
        if "Equivalence successfully proven!" not in content or points is None or int(points[2]):
            raise RuntimeError(f"流式高段上下文等价未完成：{log}")
        results.append({"parameters":parameters,"passed":True,"proven_points":int(points[1]),
                        "log_sha256":digest(log)})
        print(json.dumps(results[-1]),flush=True)
    if any(digest(path)!=value for side in hashes.values() for path,value in side.items()):
        raise RuntimeError("验证期间 RTL 内容发生变化")
    report={"passed":True,"cases":results,"source_sha256":hashes,
      "scope":"完整流式输出；组宽和起始通道按前端保存，采用独热运行阶段及对应的写输出资格",
      "all_public_outputs_compared":True,"source_unchanged":True}
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
