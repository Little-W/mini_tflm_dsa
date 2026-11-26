#!/usr/bin/env python3
"""验证完整无符号和值的上限检查，覆盖任意二值输入和四态传播。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROFILES = [(w, g) for w in (1, 2, 4, 7, 8, 16, 17, 32) for g in (3, 4)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/common/unsigned_sum_le.sv'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    wrapper = out/'formal.sv'
    wrapper.write_text('''module proof #(parameter WIDTH=16, GROUP=4)(
input logic [WIDTH-1:0] a,b,limit, output logic equal);
logic within_limit;
unsigned_sum_le #(.p_width(WIDTH),.p_group_width(GROUP)) u_compare(
 .i_a(a),.i_b(b),.i_limit(limit),.o_within(within_limit));
assign equal=within_limit==(({1'b0,a}+{1'b0,b})<={1'b0,limit});
endmodule
''')

    def prove(profile):
        width, group = profile
        script, log = out/f'w{width}_g{group}.ys', out/f'w{width}_g{group}.log'
        script.write_text('read_slang --top proof '+
            f'-GWIDTH={width} -GGROUP={group} '+shlex.join([str(source), str(wrapper)])+
            '\nprep -top proof -flatten\ncheck -assert\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], check=True, stdout=stream, stderr=subprocess.STDOUT,
                timeout=180)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'形式检查未完成：{log}')
        print(f'width={width} group={group} PASS', flush=True)
        return {'width': width, 'group_width': group, 'inputs_constrained': False, 'passed': True}

    with ThreadPoolExecutor(max_workers=2) as pool:
        formal = list(pool.map(prove, PROFILES))
    bench = ['module tb;logic [31:0] a,b,limit;integer count=0;']
    for i, (width, group) in enumerate(PROFILES):
        bench += [f'wire result_{i};',
            f'unsigned_sum_le #(.p_width({width}),.p_group_width({group})) u_{i}(',
            f'.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_limit(limit[{width-1}:0]),.o_within(result_{i}));']
    bench += ['initial begin', 'for(integer sample=0;sample<32768;sample++)begin',
        'a=$urandom;b=$urandom;limit=$urandom;', 'case(sample%12)',
        "0:a[(sample/12)%32]=1'bx;", "1:b[(sample/12)%32]=1'bz;",
        "2:limit[(sample/12)%32]=1'bx;", "3:limit[(sample/12)%32]=1'bz;",
        "4:begin a='1;b='1;limit='1;end", "5:begin b=0;limit=a;end",
        "6:begin b=1;limit=a;end", "7:begin a=0;b=0;limit=0;end",
        "8:begin a='x;b='z;end", 'default:begin end', 'endcase', '#1;']
    for i, (width, group) in enumerate(PROFILES):
        bench += [f"if(result_{i} !== (({{1'b0,a[{width-1}:0]}}+{{1'b0,b[{width-1}:0]}})<={{1'b0,limit[{width-1}:0]}}))",
            f'$fatal(1,"四态比较不一致 width={width} group={group}");', 'count=count+1;']
    bench += ['end', '$display("FOUR_STATE_PASS checks=%0d",count);$finish;', 'end endmodule']
    tb, binary, log = out/'tb.sv', out/'tb.vvp', out/'four_state.log'
    tb.write_text('\n'.join(bench)+'\n')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(source), str(tb)],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    with log.open('w') as stream:
        subprocess.run(['vvp', str(binary)], check=True, stdout=stream, stderr=subprocess.STDOUT,
            timeout=180)
    if 'FOUR_STATE_PASS checks=524288' not in log.read_text():
        raise RuntimeError('四态比较数量不足')
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('运行期间 RTL 输入发生变化')
    report = {'passed': True, 'source_sha256': source_hash, 'formal': formal,
        'four_state_comparisons': 524288}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print('524288 four-state comparisons PASS', flush=True)


if __name__ == '__main__':
    main()
