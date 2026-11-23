#!/usr/bin/env python3
"""使用实际写回模块检查四态配置、数据传递和状态更新。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/oa_writer.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import input_files, with_dependencies


def digest(data):
    return hashlib.sha256(data).hexdigest()


BODY = r'''
    integer cycle_count = 0;
    integer scenario;
    integer step;
    integer checks = 0;
    reg [31:0] random_state = 32'h715d3c09;
    function automatic [31:0] random_word();
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        random_word = random_state;
    endfunction
    task automatic check_outputs();
        if (actual !== expected) begin
            $display("OA_GEOMETRY_FOUR_STATE_FAIL scenario=%0d cycle=%0d state=%b/%b actual=%h expected=%h",
                scenario, cycle_count, u_dut.state, u_ref.state, actual, expected);
            $fatal(1, "四态公开输出必须逐周期一致");
        end
        checks = checks + 1;
    endtask
    task automatic tick();
        #1;
        if (cycle_count != 0) check_outputs();
        clk = 1;
        #1;
        cycle_count = cycle_count + 1;
        check_outputs();
        clk = 0;
        #1;
    endtask
    initial begin
        tick();
        rst_n = 1;
        for (scenario = 0; scenario < SCENARIOS; scenario = scenario + 1) begin
            if (scenario % 11 == 0) begin
                rst_n = 0;
                tick();
                rst_n = 1;
            end
            dst_base = random_word(); dst_row_stride_b = random_word();
            k = 1 + random_word() % 1024; m = 1 + random_word() % 512;
            ia_reuse_num = (scenario % 13 == 0) ? random_word() : (1 << (scenario % 7));
            is_mode = scenario % 2; output_16bits = (scenario / 2) % 2;
            coalesce_enable = (scenario / 4) % 2;
            coalesce_cols = (scenario % 3 == 0) ? (1 << (scenario % 5)) : (scenario % 32);
            case (scenario % 16)
                0: k[(scenario / 16) % 32] = 1'bx;
                1: k[(scenario / 16) % 32] = 1'bz;
                2: m[(scenario / 16) % 32] = 1'bx;
                3: m[(scenario / 16) % 32] = 1'bz;
                4: ia_reuse_num[(scenario / 16) % 32] = 1'bx;
                5: ia_reuse_num[(scenario / 16) % 32] = 1'bz;
                6: is_mode = 1'bx;
                7: is_mode = 1'bz;
                8: coalesce_cols[scenario % 5] = 1'bx;
                9: coalesce_cols[scenario % 5] = 1'bz;
                10: begin k = random_word(); k[(scenario / 16) % 32] = 1'bx; m = random_word(); end
                11: begin ia_reuse_num = random_word(); ia_reuse_num[(scenario / 16) % 32] = 1'bz; end
                12: begin k = 0; m = 0; end
                13: begin k = 32'hfffffff1; m = 32'hfffffff0; end
                14: begin dst_row_stride_b[(scenario / 16) % 32] = 1'bx; output_16bits = 1'bx; end
                default: begin end
            endcase
            init_cfg = 1;
            tick();
            init_cfg = 0;
            for (step = 0; step < 24; step = step + 1) begin
                oa_fifo_req = 1; output_valid = step % 3 != 0;
                write_oa_granted = step % 4 != 0;
                dma_src_wready = step % 5 != 0;
                dma_busy = 1;
                dma_done = step % 7 == 6;
                output_data = {random_word(), random_word()};
                output_mask = random_word();
                if (step % 3 == 0) output_data[(scenario + step) % BUS_WIDTH] = 1'bx;
                if (step % 4 == 0) output_mask[(scenario + step) % (BUS_WIDTH/8)] = 1'bz;
                if (step == 8) begin
                    dst_base = random_word(); dst_row_stride_b = random_word();
                    k = random_word(); m = random_word(); ia_reuse_num = random_word();
                    is_mode = random_word(); coalesce_cols = random_word();
                end
                tick();
            end
        end
        $display("OA_GEOMETRY_FOUR_STATE_PASS scenarios=%0d cycles=%0d checks=%0d outputs=21", SCENARIOS, cycle_count, checks);
        $finish;
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--reference', default='7ff66a59')
    parser.add_argument('--reference-rtl', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['4:32:4', '8:64:6', '16:64:29', '32:64:32'])
    parser.add_argument('--scenarios', type=int, default=1024)
    args = parser.parse_args()
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    current = args.rtl.read_text()
    original = args.reference_rtl.read_text() if args.reference_rtl else read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    # Icarus 的参数类型语法使用 integer；这里涉及的宽度参数均为正数。
    def compatible(text):
        return text.replace('int unsigned', 'integer')
    (out/'current.sv').write_text(compatible(current))
    (out/'reference.sv').write_text(compatible(re.sub(r'\boa_writer\b', 'oa_writer_ref', original)))
    dependencies = with_dependencies([args.rtl.resolve()], ROOT)
    input_hashes = {str(path): digest(path.read_bytes()) for path in input_files(dependencies, ROOT)}
    copied_dependencies = []
    for index, path in enumerate(dependencies[1:]):
        copy = out / f'dependency_{index}.sv'
        copy.write_text(compatible(path.read_text()))
        copied_dependencies.append(copy)
    bench_source=ROOT/'test/oa_writer/tb_equivalence.sv'
    prefix=bench_source.read_text().split('    int unsigned cycle_count')[0]
    (out/'tb.sv').write_text(prefix+BODY)
    report=dict(passed=True,source_sha256=digest(current.encode()),reference_sha256=digest(original.encode()),
                input_sha256=input_hashes,
                bench_source_sha256=digest(bench_source.read_bytes()),runner_sha256=digest(Path(__file__).read_bytes()),
                parameter_integer_compatibility=True, strict_comparison=True, profiles=[])
    for profile in args.profiles:
        lanes,bus,count=map(int,profile.split(':'));label=f'n{lanes}_b{bus}_c{count}'
        binary=out/label
        cmd=['iverilog','-g2012','-s','tb_oa_writer_equivalence',
             f'-Ptb_oa_writer_equivalence.VLEN={lanes}',f'-Ptb_oa_writer_equivalence.BUS_WIDTH={bus}',
             f'-Ptb_oa_writer_equivalence.COUNT_WIDTH={count}',f'-Ptb_oa_writer_equivalence.SCENARIOS={args.scenarios}',
             '-o',str(binary),str(out/'current.sv'),str(out/'reference.sv'),str(out/'tb.sv'),
             *map(str,copied_dependencies)]
        with (out/(label+'_compile.log')).open('w') as log:
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=180)
        log=out/(label+'.log');log.write_text(result.stdout+result.stderr)
        match=re.search(r'OA_GEOMETRY_FOUR_STATE_PASS (.*)',result.stdout)
        if result.returncode or not match:raise RuntimeError(result.stdout+result.stderr)
        row=dict(vlen=lanes,bus_width=bus,count_width=count,passed=True,
                 **{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',match.group(1))},log_sha256=digest(log.read_bytes()), binary_sha256=digest(binary.read_bytes()))
        report['profiles'].append(row);print(json.dumps(row),flush=True)
    if current!=args.rtl.read_text():raise RuntimeError('验证期间 RTL 发生变化')
    if input_hashes != {name: digest(Path(name).read_bytes()) for name in input_hashes}:
        raise RuntimeError('验证期间模块依赖发生变化')
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
