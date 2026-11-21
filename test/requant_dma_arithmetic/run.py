#!/usr/bin/env python3
"""比较实际量化 DMA 地址和偏移表达式的全部二态输入与四态样本。"""
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
PROFILES = [(width, lanes) for width in (1, 8, 17, 24, 32, 40, 48, 64)
            for lanes in (1, 3, 16, 32)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/writeback/vec_requant.sv'
    text = source.read_text()
    region = re.search(r'  localparam int p_dma_address_width.*?(?=  assign dma_base_addr =)',
                       text, re.S).group(0)
    if text.count('load_offset <= load_next_offset;') != 2:
        raise RuntimeError('量化偏移更新没有使用同一个经过比较的表达式')
    model = out / 'arithmetic.sv'
    model.write_text('''module arithmetic #(
    parameter integer REG_WIDTH=32, VLEN=16,
    parameter integer VLEN_CNT_W=(VLEN<=1)?1:$clog2(VLEN+1)
)(
    input wire [31:0] quant_tile_idx_load_r, load_offset, mul_base_r, sh_base_r,
    input wire [VLEN_CNT_W-1:0] beats_expect,
    input wire load_phase,
    output wire [REG_WIDTH+31:0] current_result, reference_result,
    output wire correct
);
    localparam integer BYTES_PER_WORD=REG_WIDTH/8;
    localparam PH_MUL=1'b0;
    wire [REG_WIDTH-1:0] dma_base_addr_cur;
    wire [REG_WIDTH-1:0] reference_address = (load_phase == PH_MUL)
        ? (mul_base_r + (quant_tile_idx_load_r * VLEN + load_offset) * BYTES_PER_WORD)
        : (sh_base_r + (quant_tile_idx_load_r * VLEN + load_offset) * BYTES_PER_WORD);
    wire [31:0] reference_offset = load_offset + REG_WIDTH'(beats_expect);
''' + region + '''
    assign current_result={dma_base_addr_cur,load_next_offset};
    assign reference_result={reference_address,reference_offset};
    assign correct=current_result==reference_result;
endmodule
''')
    summary = {'passed': False, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'inputs_constrained': False, 'profiles': []}
    for width, lanes in PROFILES:
        name = f'w{width}_v{lanes}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('read_verilog -sv ' + shlex.quote(str(model)) + '\n' +
                          f'chparam -set REG_WIDTH {width} -set VLEN {lanes} arithmetic\n' +
                          'prep -top arithmetic -flatten\ncheck -assert\n' +
                          'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode or 'SAT proof finished - no model found: SUCCESS' not in log.read_text():
            raise RuntimeError(f'量化地址形式比较未通过：{log}')
        summary['profiles'].append({'register_width': width, 'lanes': lanes, 'formal_passed': True})
    instances = []
    for index, (width, lanes) in enumerate(PROFILES):
        count_width = max(1, lanes.bit_length())
        instances.append(f'''wire [{width+31}:0] current_{index},reference_{index};
    arithmetic #(.REG_WIDTH({width}),.VLEN({lanes})) u{index}(
        .quant_tile_idx_load_r(tile),.load_offset(offset),.mul_base_r(multiplier),
        .sh_base_r(shift),.beats_expect(beats[{count_width-1}:0]),.load_phase(phase),
        .current_result(current_{index}),.reference_result(reference_{index}),.correct());
    always @(check_result) if(check_result && current_{index} !== reference_{index})
        $fatal(1,"地址或偏移四态比较不一致，配置 {index}，样本 %0d",sample);
''')
    bench = out / 'tb.sv'
    bench.write_text('''module tb;
    reg [31:0] tile,offset,multiplier,shift;
    reg [5:0] beats;
    reg phase,check_result;
    integer sample;
''' + '\n'.join(instances) + '''
    initial begin
        check_result=0;
        for(sample=0;sample<10000;sample=sample+1)begin
            tile=$urandom;offset=$urandom;multiplier=$urandom;shift=$urandom;
            beats=$urandom;phase=sample[0];
            if(sample>=2000)begin
                case(sample%12)
                    0:tile[(sample/12)%32]=1'bx;
                    1:tile[(sample/12)%32]=1'bz;
                    2:offset[(sample/12)%32]=1'bx;
                    3:offset[(sample/12)%32]=1'bz;
                    4:multiplier[(sample/12)%32]=1'bx;
                    5:multiplier[(sample/12)%32]=1'bz;
                    6:shift[(sample/12)%32]=1'bx;
                    7:shift[(sample/12)%32]=1'bz;
                    8:beats[(sample/12)%6]=1'bx;
                    9:beats[(sample/12)%6]=1'bz;
                    10:phase=1'bx;
                    11:phase=1'bz;
                endcase
            end
            #1;check_result=1;#1;check_result=0;
        end
        $display("PASS samples=10000 profiles=32 checks=320000");
        $finish;
    end
endmodule
''')
    executable, log = out / 'four_state.vvp', out / 'four_state.log'
    subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
                    str(model), str(bench)], check=True)
    with log.open('w') as stream:
        subprocess.run(['vvp', str(executable)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'PASS samples=10000 profiles=32 checks=320000' not in log.read_text():
        raise RuntimeError('量化地址四态比较没有完成')
    summary.update(passed=True, four_state_samples=10000, four_state_result_comparisons=320000)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': len(PROFILES), 'four_state_checks': 320000}))


if __name__ == '__main__':
    main()
