#!/usr/bin/env python3
"""逐周期比较两个完整控制模块，并检查加一比较的四态关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "351f3fb63f8d8b36e46c36c7ab539cae475cc8d2"
IA_SOURCE = Path("rtl/npu/loaders/ia_loader_ctrl.sv")
PS_SOURCE = Path("rtl/npu/control/ps_window_scheduler.sv")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
from scripts.rtl.source_files import input_files, with_dependencies
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=240)
    return log.read_text()


def compatible(text):
    return text.replace("int unsigned", "integer")


UNIT_BENCH = r'''
module tb;
 parameter integer WIDTH=29;
 reg [WIDTH-1:0] a='0,target='0;
 wire expected_plain, expected_grouped, actual;
 reg [31:0] random_state=32'h537f1a29;
 integer checks=0;
 add_equal #(.p_width(WIDTH)) u_plain (
   .i_a(a), .i_b({WIDTH{1'b0}}), .i_target(target),
   .i_carry_in(1'b1), .o_equal(expected_plain));
 add_equal #(.p_width(WIDTH), .p_preserve_bits(1'b1)) u_grouped (
   .i_a(a), .i_b({WIDTH{1'b0}}), .i_target(target),
   .i_carry_in(1'b1), .o_equal(expected_grouped));
 increment_equal #(.p_width(WIDTH), .p_preserve_pairs(1'b1),
   .p_reduce_group_width(6)) u_actual (.i_a(a), .i_target(target), .o_equal(actual));
 function automatic [31:0] random_word();
   random_state=random_state^(random_state<<13);
   random_state=random_state^(random_state>>17);
   random_state=random_state^(random_state<<5);
   random_word=random_state;
 endfunction
 function automatic logic symbol(input integer code);
   case(code&3)
     0:symbol=1'b0;1:symbol=1'b1;2:symbol=1'bx;default:symbol=1'bz;
   endcase
 endfunction
 initial begin
   for(integer sample=0;sample<(WIDTH==4?65536:8192);sample++)begin
     if(WIDTH==4)begin
       for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
         a[bit_index]=symbol(sample>>(2*bit_index));
         target[bit_index]=symbol(sample>>(2*(WIDTH+bit_index)));
       end
     end else begin
       a=WIDTH'({random_word(),random_word()});
       target=sample%3==0?a+WIDTH'(1):WIDTH'({random_word(),random_word()});
       if(sample%2==0)begin
         case(sample%16)
           0:a[sample%WIDTH]=1'bx;
           2:target[sample%WIDTH]=1'bz;
           4:begin a[sample%WIDTH]=1'bz;target[sample%WIDTH]=1'bx;end
           6:a='x;
           8:target='z;
           10:begin a='z;target='x;end
           default:begin
             for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
               a[bit_index]=symbol(random_word());
               target[bit_index]=symbol(random_word());
             end
           end
         endcase
       end
     end
     #1;
     if(actual!==expected_plain || actual!==expected_grouped)
       $fatal(1,"Increment comparison differs width=%0d sample=%0d",WIDTH,sample);
     checks++;
   end
   $display("INCREMENT_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tracked = input_files(with_dependencies([ROOT / IA_SOURCE, ROOT / PS_SOURCE], ROOT), ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in tracked}
    ia_support = runpy.run_path(str(ROOT / "test/ia_state_outputs/run_control_four_state.py"))
    port_parser = runpy.run_path(str(ROOT / "test/ia_timing/run_interface.py"))["port_declarations"]
    scheduler_bench = runpy.run_path(str(ROOT / "test/scheduler_shared_rows/run.py"))["bench"]

    # 保存完整 IA 控制器及依赖，端口声明只移除仿真器不接受的默认表达式。
    ia = out / "ia"
    ia.mkdir(exist_ok=True)
    ia_original = read_rtl_source(f"{args.reference}:{IA_SOURCE}", cwd=ROOT, text=True)
    ia_current = (ROOT / IA_SOURCE).read_text()
    original_ports = port_parser(re.sub(r"\(\*.*?\*\)", "", ia_original, flags=re.S))
    ports = port_parser(re.sub(r"\(\*.*?\*\)", "", ia_current, flags=re.S))
    if ports != original_ports:
        raise RuntimeError("IA 控制器的接口声明必须保持一致")
    for label, text in (("reference", ia_original), ("current", ia_current)):
        base = ia / "inputs" / label
        for path in with_dependencies([ROOT / IA_SOURCE], ROOT):
            target = base / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text if path == ROOT / IA_SOURCE else path.read_text())
    ia_support["simulation_sources"](ia, ports)
    for label in ("reference", "current"):
        path = ia / (label + ".sv")
        path.write_text(compatible(path.read_text()))
    ia_records = []
    for compact in (0, 1):
        parameters = dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, REG_WIDTH=32,
                          COUNT_WIDTH=29, CACHE_BLOCKS=32, COMPACT_S8=compact,
                          PS_FRAME_COUNT=16, p_indexed_slot_rows=1,
                          p_precomputed_slot_mask=1, p_precomputed_frame_rows=1,
                          p_precomputed_packed_tiles=1, p_parallel_request_match=1)
        bench_text = ia_support["testbench"](ports, parameters)
        bench_text = bench_text.replace("w_groups_total=1;\n", "w_groups_total=1;\n"
            "if(sample>=3000)w_groups_total=(sample%11==0)?$urandom:1+sample%7;\n")
        bench_text = bench_text.replace("w_group_last_width=1;\n", "w_group_last_width=1;\n"
            "if(sample>=3000)w_group_last_width=sample%17;\n")
        bench = ia / f"compact{compact}.sv"
        bench.write_text(compatible(bench_text))
        for fpga in (False, True):
            label = f"compact{compact}_fpga{int(fpga)}"
            binary, log = ia / (label + ".vvp"), ia / (label + ".log")
            definitions = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else []
            execute(["iverilog", "-g2012", *definitions, "-s", "tb", "-o", binary,
                     ia / "reference.sv", ia / "current.sv", bench], ia / (label + "_compile.log"))
            text = execute(["vvp", binary], log)
            match = re.search(r"CONTROL_FOUR_STATE_PASS cycles=(\d+) valid=(\d+) states=([01]+)", text)
            if not match or match[3] != "11111":
                raise RuntimeError("完整 IA 控制器四态检查未完成：" + label)
            row = dict(parameters=parameters, fpga=fpga, passed=True, cycles=int(match[1]),
                       valid_cycles=int(match[2]), states_seen=match[3], log_sha256=digest(log),
                       testbench_sha256=digest(bench), binary_sha256=digest(binary))
            ia_records.append(row)
            print(json.dumps(row), flush=True)

    # 调度器的所有公开输出在合法任务、压力暂停和未知控制输入下逐周期比较。
    scheduler = out / "scheduler"
    scheduler.mkdir(exist_ok=True)
    reference = scheduler / "reference.sv"
    original = read_rtl_source(f"{args.reference}:{PS_SOURCE}", cwd=ROOT, text=True)
    reference.write_text(compatible(original.replace("module ps_window_scheduler #", "module scheduler_reference #")))
    current = scheduler / "current.sv"
    current.write_text(compatible((ROOT / PS_SOURCE).read_text()
                                 .replace("module ps_window_scheduler #", "module scheduler_current #")))
    helpers = []
    for index, path in enumerate(with_dependencies([ROOT / PS_SOURCE], ROOT)[1:]):
        target = scheduler / f"dependency_{index}.sv"
        target.write_text(compatible(path.read_text()))
        helpers.append(target)
    bench = scheduler / "tb.sv"
    bench.write_text(scheduler_bench(8192))
    scheduler_records = []
    for size, frames, reuse in ((1, 1, 1), (4, 3, 4), (16, 16, 16), (16, 17, 64)):
        for fpga in (False, True):
            label = f"n{size}_f{frames}_r{reuse}_fpga{int(fpga)}"
            binary, log = scheduler / (label + ".vvp"), scheduler / (label + ".log")
            definitions = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else []
            execute(["iverilog", "-g2012", "-s", "tb", *definitions,
                     f"-Ptb.SIZE={size}", f"-Ptb.FRAME_COUNT={frames}",
                     f"-Ptb.MAX_REUSE_TILES={reuse}", "-o", binary,
                     reference, current, *helpers, bench], scheduler / (label + "_compile.log"))
            text = execute(["vvp", binary], log)
            match = re.search(r"SCHEDULER_SHARED_ROWS_FOUR_STATE_PASS checks=(\d+) unknown_checks=(\d+) commands=(\d+)", text)
            if not match:
                raise RuntimeError("完整帧调度器四态检查未完成：" + label)
            row = dict(size=size, frames=frames, reuse=reuse, fpga=fpga, passed=True,
                       cycles=int(match[1]), unknown_output_cycles=int(match[2]), commands=int(match[3]),
                       log_sha256=digest(log), binary_sha256=digest(binary))
            scheduler_records.append(row)
            print(json.dumps(row), flush=True)

    unit = out / "increment"
    unit.mkdir(exist_ok=True)
    unit_bench = unit / "tb.sv"
    unit_bench.write_text(UNIT_BENCH)
    unit_helpers = []
    for index, path in enumerate(with_dependencies([ROOT / "rtl/common/add_equal.sv",
                                                    ROOT / "rtl/common/increment_equal.sv"], ROOT)):
        target = unit / f"dependency_{index}.sv"
        target.write_text(compatible(path.read_text()))
        unit_helpers.append(target)
    unit_records = []
    for width in (1, 2, 3, 4, 5, 7, 8, 16, 29, 32, 48, 64):
        binary, log = unit / f"width{width}.vvp", unit / f"width{width}.log"
        execute(["iverilog", "-g2012", "-s", "tb", f"-Ptb.WIDTH={width}", "-o", binary,
                 *unit_helpers, unit_bench], unit / f"width{width}_compile.log")
        text = execute(["vvp", binary], log)
        match = re.search(r"INCREMENT_FOUR_STATE_PASS checks=(\d+)", text)
        if not match:
            raise RuntimeError("加一关系四态检查未完成")
        row = dict(width=width, passed=True, checks=int(match[1]), log_sha256=digest(log))
        unit_records.append(row)
        print(json.dumps(row), flush=True)

    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("仿真期间 RTL 内容发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=hashes,
                  runner_sha256=digest(__file__), ia=ia_records, scheduler=scheduler_records,
                  increment=unit_records, strict_four_state_comparison=True,
                  all_public_outputs_compared_each_cycle=True,
                  ia_cycles=sum(row["cycles"] for row in ia_records),
                  scheduler_cycles=sum(row["cycles"] for row in scheduler_records),
                  increment_checks=sum(row["checks"] for row in unit_records))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
