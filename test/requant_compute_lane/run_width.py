#!/usr/bin/env python3
"""证明量化舍入和偏移的完整输入范围适合三十五位有符号结果。"""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/npu/writeback/requant_compute_lane.sv"
    text = source.read_text()
    calculation = re.search(r"    assign offset_value =.*?(?=    always_ff)", text, re.S)
    if calculation is None or "logic signed [34:0] rounded_q, round_value, offset_value;" not in text:
        raise RuntimeError("量化算术声明与检查接口不一致")
    helper = ROOT / "rtl/common/parallel_prefix_add.sv"
    round_adder = ROOT / "rtl/npu/writeback/requant_round_add.sv"
    hashes = {str(path): digest(path) for path in (source, helper, round_adder, Path(__file__).resolve())}
    model = out / "width_proof.sv"
    model.write_text('''module width_proof (
    input logic signed [33:0] shift_o_quotient,
    input logic shift_o_increment, i_s16,
    input logic signed [31:0] i_dst_offset,
    output logic equal
);
    logic signed [34:0] round_value, offset_value;
    logic unused_round_carry;
    logic signed [63:0] extended_result, reference_sum;
    logic signed [63:0] quotient_extended, offset_extended;
''' + calculation[0] + '''
    assign extended_result = {{29{round_value[34]}}, round_value};
    assign quotient_extended = {{30{shift_o_quotient[33]}}, shift_o_quotient};
    assign offset_extended = i_s16 ? 64'sd0 : {{32{i_dst_offset[31]}}, i_dst_offset};
    assign reference_sum = quotient_extended + offset_extended + 64'(shift_o_increment);
    assign equal = extended_result == reference_sum;
endmodule
''')
    script = out / "proof.ys"
    script.write_text("read_slang -D SYNTHESIS=1 --top width_proof " +
                      shlex.join([str(helper), str(round_adder), str(model)]) + "\n" +
                      "setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n" +
                      "prep -top width_proof -flatten\nopt -full\n" +
                      "sat -prove equal 1 -verify -show-inputs -show-outputs\n")
    formal_log = out / "formal.log"
    run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
         "--worker", str(script)], formal_log)
    if "SUCCESS" not in formal_log.read_text():
        raise RuntimeError("量化算术范围检查未完成")
    bench = out / "tb.sv"
    bench.write_text('''module tb;
    logic [67:0] stimulus, saved;
    wire i_s16, shift_o_increment;
    wire signed [31:0] i_dst_offset;
    wire signed [33:0] shift_o_quotient;
    wire equal;
    integer checks=0, directed=0, unknown_inputs=0;
    assign {i_s16,shift_o_increment,i_dst_offset,shift_o_quotient}=stimulus;
    width_proof dut(.*);
    function automatic logic [33:0] quotient_value(input integer index);
        case (index)
            0:quotient_value=-34'sd8589934592;
            1:quotient_value=34'sd8589934591;
            2:quotient_value=-34'sd2147483648;
            3:quotient_value=34'sd2147483647;
            4:quotient_value=34'sd0;
            5:quotient_value=34'sd1;
            6:quotient_value=-34'sd1;
            default:quotient_value=34'sh155555555;
        endcase
    endfunction
    function automatic logic [31:0] offset_value(input integer index);
        case (index)
            0:offset_value=32'h80000000;
            1:offset_value=32'h7fffffff;
            2:offset_value=32'd0;
            3:offset_value=32'd1;
            4:offset_value=32'hffffffff;
            5:offset_value=32'h55555555;
            6:offset_value=32'haaaaaaaa;
            default:offset_value=32'h80000001;
        endcase
    endfunction
    task automatic check;
        #1;
        if(dut.extended_result !== dut.reference_sum)
            $fatal(1,"量化舍入偏移不一致 sample=%0d",checks);
        checks++;
    endtask
    initial begin
        for(integer mode=0;mode<2;mode++)
            for(integer increment=0;increment<2;increment++)
                for(integer quotient=0;quotient<8;quotient++)
                    for(integer offset=0;offset<8;offset++)begin
                        stimulus={1'(mode),1'(increment),offset_value(offset),quotient_value(quotient)};
                        check();directed++;
                    end
        for(integer sample=0;sample<2048;sample++)begin
            stimulus={$urandom,$urandom,$urandom};check();saved=stimulus;
            for(integer index=0;index<68;index++)begin
                stimulus=saved;stimulus[index]=1'bx;check();unknown_inputs++;
                stimulus=saved;stimulus[index]=1'bz;check();unknown_inputs++;
            end
        end
        $display("REQUANT_WIDTH_PASS checks=%0d directed=%0d unknown_inputs=%0d",checks,directed,unknown_inputs);
        $finish;
    end
endmodule
''')
    binary = out / "simulation"
    run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(model), str(bench)],
        out / "compile.log")
    simulation_log = out / "simulation.log"
    run(["vvp", str(binary)], simulation_log)
    marker = re.search(r"REQUANT_WIDTH_PASS (.*)", simulation_log.read_text())
    if marker is None:
        raise RuntimeError("量化四态算术检查未完成")
    if hashes != {path: digest(Path(path)) for path in hashes}:
        raise RuntimeError("量化源码在检查期间发生变化")
    report = {"passed": True, "source_sha256": hashes, "result_width": 35,
              "reference_width": 64, "formal_unconstrained_input_bits": 68,
              "minimum_result": -10737418240, "maximum_result": 10737418239,
              "four_state": {key: int(value) for key, value in
                             re.findall(r"(\w+)=(\d+)", marker[1])},
              "log_sha256": {path.name: digest(path) for path in (formal_log, simulation_log)}}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
