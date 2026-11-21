#!/usr/bin/env python3
"""比较实际组范围下一值在 X/Z 控制和数据输入下的逐位结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from range_write_check import NAMES, PARAMETERS, REFERENCE, ROOT, unit


PROFILES = ((2, 1), (2, 4), (2, 16), (16, 4), (16, 5), (16, 8), (16, 16), (64, 8))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def testbench():
    connections = ",".join(f".{name}({name})" for name in NAMES)
    bundle = "{" + ",".join(NAMES) + "}"
    text = f"""module range_four_state_case #({PARAMETERS})(output logic done);
logic [21:0] state;
conv_im2col_pkg::conv_cfg_t c;
logic rst_n,cfg_valid,cfg_ready,tile_commit,tile_invalid,tile_fast;
logic cache_rsp_valid,cache_rsp_error,wr_valid,wr_ready,chunk_reaches_end;
logic row_last_q,past_active_q,group_end_o_equal,group_shape_o_valid;
logic [31:0] q0,decode_index;
logic [CHUNK_COUNT_W-1:0] chunk_count;
logic [TILE_COUNT_W-1:0] active_remaining;
logic [p_saved_group_lanes:0] tile_channel_range,group_range_q,group_range_cfg;
logic [5:0][p_saved_group_lanes:0] group_range_next;
wire [p_saved_group_lanes:0] expected,actual;
localparam integer p_input_bits=22+$bits(conv_im2col_pkg::conv_cfg_t)+15+64+
    CHUNK_COUNT_W+TILE_COUNT_W+9*(p_saved_group_lanes+1);
localparam integer p_storage_bits=32*((p_input_bits+31)/32);
logic [p_storage_bits-1:0] packed_inputs,original_inputs;
logic [31:0] random_state;
integer count,pattern,bit_index,symbol,iteration,index;
reference #(.SIZE(SIZE),.LANES(LANES)) u_reference({connections},.result(expected));
current #(.SIZE(SIZE),.LANES(LANES)) u_current({connections},.result(actual));

function automatic logic [31:0] next_random(input logic[31:0] value);
    logic[31:0] mixed;
    begin
        mixed=value^(value<<13);
        mixed=mixed^(mixed>>17);
        next_random=mixed^(mixed<<5);
    end
endfunction

task automatic check_result;
    begin
        #1;
        count=count+1;
        if (expected !== actual)
            $fatal(1,"range four-state mismatch size=%0d lanes=%0d state=%b rst=%b cfg=%b%b tile=%b%b%b expected=%b actual=%b inputs=%b",
                SIZE,LANES,state,rst_n,cfg_valid,cfg_ready,tile_commit,tile_invalid,tile_fast,expected,actual,{bundle});
    end
endtask

task automatic randomize_binary;
    integer offset;
    begin
        for(offset=0;offset<p_storage_bits;offset=offset+32) begin
            random_state=next_random(random_state);
            packed_inputs[offset+:32]=random_state;
        end
        {bundle}=packed_inputs;
    end
endtask

initial begin
    done=0;
    count=0;
    if (p_input_bits!=$bits({bundle})) $fatal(1,"输入位宽检查未通过");
    random_state=32'h37ac92d1 ^ (SIZE<<8) ^ LANES;
    // 每种状态下逐位注入未知值，同时覆盖独立时钟过程的写入优先次序。
    for(pattern=0;pattern<48;pattern=pattern+1) begin
        randomize_binary();
        state=pattern<22 ? (22'b1<<pattern) : pattern<44 ? ~(22'b1<<(pattern-22)) : (pattern&1) ? '1 : '0;
        rst_n=1;
        cfg_valid=pattern[0];
        cfg_ready=pattern[1];
        tile_commit=pattern[2];
        tile_invalid=pattern[3];
        tile_fast=pattern[4];
        cache_rsp_valid=1;
        cache_rsp_error=pattern[0];
        wr_valid=1;
        wr_ready=1;
        row_last_q=pattern[1];
        chunk_reaches_end=pattern[2];
        active_remaining=TILE_COUNT_W'(SIZE);
        chunk_count=CHUNK_COUNT_W'(LANES);
        q0=pattern%31;
        decode_index=pattern[0] ? q0 : q0+1;
        original_inputs={bundle};
        check_result();
        for(bit_index=0;bit_index<p_input_bits;bit_index=bit_index+1) begin
            for(symbol=0;symbol<2;symbol=symbol+1) begin
                packed_inputs=original_inputs;
                packed_inputs[bit_index]=symbol ? 1'bz : 1'bx;
                {bundle}=packed_inputs;
                check_result();
            end
        end
    end
    // 固定种子的多处未知值覆盖状态、多路选择输入和范围数据。
    for(iteration=0;iteration<20000;iteration=iteration+1) begin
        randomize_binary();
        if (iteration%4<2) state=22'b1<<(iteration%22);
        if (iteration%4==2) state='0;
        rst_n=1;
        q0=iteration%31;
        if (iteration%2) decode_index=q0;
        packed_inputs={bundle};
        for(index=0;index<1+iteration%7;index=index+1) begin
            random_state=next_random(random_state);
            bit_index=random_state%p_input_bits;
            packed_inputs[bit_index]=random_state[6] ? 1'bx : 1'bz;
        end
        {bundle}=packed_inputs;
        check_result();
    end
    $display("RANGE_FOUR_STATE_PASS size=%0d lanes=%0d checked=%0d",SIZE,LANES,count);
    done=1;
end
endmodule

module range_four_state_tb;
wire [{len(PROFILES)-1}:0] done;
"""
    for index, (size, lanes) in enumerate(PROFILES):
        text += f"range_four_state_case #(.SIZE({size}),.LANES({lanes})) u_{index}(.done(done[{index}]));\n"
    return text + "initial begin wait (&done); $finish; end\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--candidate", type=Path, default=ROOT / "rtl/npu/conv/conv_im2col_frontend.sv")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").unlink(missing_ok=True)
    inputs = {"reference": args.reference.resolve(), "current": args.candidate.resolve()}
    hashes = {name: digest(path) for name, path in inputs.items()}
    source = out / "range_four_state.sv"
    source.write_text("".join(unit(name, path.read_text()) for name, path in inputs.items()) + testbench())
    package = ROOT / "rtl/npu/conv/conv_im2col_pkg.sv"
    executable = out / "simulation.vvp"
    with (out / "compile.log").open("w") as log:
        subprocess.run(["iverilog", "-g2012", "-s", "range_four_state_tb", "-o", str(executable), str(package), str(source)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / "simulation.log").open("w") as log:
        subprocess.run(["vvp", str(executable)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    matches = re.findall(r"RANGE_FOUR_STATE_PASS size=(\d+) lanes=(\d+) checked=(\d+)", (out / "simulation.log").read_text())
    if len(matches) != len(PROFILES):
        raise RuntimeError("四态配置覆盖未完成")
    if any(int(count) <= 20048 for _, _, count in matches):
        raise RuntimeError("逐位未知值注入覆盖未完成")
    if hashes != {name: digest(path) for name, path in inputs.items()}:
        raise RuntimeError("验证期间输入源码发生变化")
    cases = [dict(SIZE=int(size), LANES=int(lanes), checked=int(checked), passed=True) for size, lanes, checked in matches]
    report = dict(passed=True, strict_case_equality=True, source_sha256=hashes,
                  package_sha256=digest(package), generated_source_sha256=digest(source),
                  cases=cases, checked=sum(case["checked"] for case in cases))
    origin = re.search(r"source_sha256:\s*([a-f0-9]{64})", inputs["reference"].read_text())
    if origin:
        report["reference_origin_sha256"] = origin[1]
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
