#!/usr/bin/env python3
"""验证矩阵分块维度的定宽算术、边界回绕和四态传播。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CASES = ((1, 1, 0), (1, 16, 4), (5, 32, 5), (16, 16, 4), (32, 16, 4), (32, 3, 2),
         (32, 32, 5), (32, 2147483648, 31), (48, 16, 4), (64, 16, 4),
         (64, 65536, 16), (64, 2147483648, 31), (80, 16, 4))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7eb7f3ed')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([ROOT/'rtl/npu/top/npu_packed_extent.sv'], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    proof = out/'formal.sv'
    proof.write_text('''module proof #(parameter int unsigned WIDTH=32,SIZE=16,SHIFT=4)(
input logic[WIDTH-1:0] value,input logic packed_mode,output logic equal);
logic[31:0] actual,expected;
npu_packed_extent #(.p_dimension_width(WIDTH),.p_size(SIZE),.p_size_shift(SHIFT)) u_extent(
.i_dimension(value),.i_packed(packed_mode),.o_extent(actual));
assign expected=packed_mode?32'((64'(value)+64'(SIZE)-64'd1)>>SHIFT):32'(value);
assign equal=actual===expected;
endmodule
''')

    def prove(case):
        width, size, shift = case
        name = f'w{width}_s{size}_h{shift}'
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(f"read_slang -USYNTHESIS -UXILINX_FPGA --top proof -GWIDTH={width} -GSIZE=32'h{size:08x} -GSHIFT={shift} "+
            shlex.join(list(map(str, sources))+[str(proof)])+
            '\nprep -top proof -flatten\ncheck -assert\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('形式检查未完成：'+str(log))
        print(name, 'PASS', flush=True)
        return {'width': width, 'size': size, 'shift': shift, 'passed': True,
                'inputs_constrained': False, 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, CASES))
    tb = ['module tb;logic[79:0] value;logic packed_mode;integer checks=0;']
    for index, (width, size, shift) in enumerate(CASES):
        tb += [f'wire[31:0] actual{index},expected{index};',
            f'npu_packed_extent #(.p_dimension_width({width}),.p_size({size}),.p_size_shift({shift})) u_{index}(',
            f'.i_dimension(value[{width-1}:0]),.i_packed(packed_mode),.o_extent(actual{index}));',
            f"assign expected{index}=packed_mode?32'((64'(value[{width-1}:0])+64'd{size}-64'd1)>>{shift}):32'(value[{width-1}:0]);"]
    tb += ['initial begin for(integer sample=0;sample<16384;sample++)begin',
        'value={$urandom,$urandom,$urandom};packed_mode=sample[0];',
        'case(sample%12)', "0:value[(sample/12)%80]=1'bx;", "1:value[(sample/12)%80]=1'bz;",
        "2:packed_mode=1'bx;", "3:packed_mode=1'bz;", "4:value='1;", "5:value=0;",
        "6:value=80'hffffffffffffffffffff-(sample%32);", "7:value=80'd1<<((sample/12)%80);",
        'default:begin end', 'endcase', '#1;']
    for index in range(len(CASES)):
        tb += [f'if(actual{index}!==expected{index})$fatal(1,"分块维度四态结果不同 case={index}");checks++;']
    tb += ['end $display("PASS checks=%0d",checks);$finish;end endmodule']
    bench, binary = out/'tb.sv', out/'tb.vvp'
    bench.write_text('\n'.join(tb)+'\n')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), *map(str, sources), str(bench)],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.check_output(['vvp', str(binary)], text=True, timeout=240)
    (out/'four_state.log').write_text(result)
    total = len(CASES)*16384
    if f'PASS checks={total}' not in result:
        raise RuntimeError('四态检查数量不足')
    subprocess.run([sys.executable, ROOT/'test/unsigned_sum_le/run_parent.py',
        '--reference', args.reference, '--out', out/'parent'], check=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('检查期间源文件发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'formal': checks,
        'four_state_comparisons': total,
        'parent': json.loads((out/'parent/validation.json').read_text())}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(total, 'four-state comparisons PASS', flush=True)


if __name__ == '__main__':
    main()
