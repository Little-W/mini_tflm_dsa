#!/usr/bin/env python3
"""验证权重加载完成条件的完整控制状态及全部四态输入组合。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/kernel_loader_ctrl.sv'
HELPER = 'rtl/npu/loaders/kernel_completion_check.sv'
PROFILES = ((4, 4), (16, 16), (16, 29), (32, 32))
REFERENCE_BODY = '''logic [1:0] remaining_loads,remaining_sends;
logic loads_wrap,sends_wrap,load_count_reached;
assign remaining_loads=pending_loads-2'(load_done);
assign remaining_sends=pending_sends-2'd1;
assign loads_wrap=(remaining_loads!=0&&issued_zero)||(remaining_loads==2&&issued_one);
assign sends_wrap=(remaining_sends!=0&&issued_zero)||(remaining_sends==2&&issued_one);
assign load_count_reached=pending_loads==1||(pending_loads==2&&issued_zero);
assign expected=(all_done||(load_done&&all_issued&&load_count_reached))&&
    ((sends_wrap!=loads_wrap)?sends_wrap:remaining_sends<=remaining_loads);
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='1d809964')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, candidate = out/'reference.sv', out/'candidate.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    candidate.write_bytes((ROOT/SOURCE).read_bytes())
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in resolve([ROOT/SOURCE], ROOT)}

    def prove(job):
        (size, count), synthesis = job
        name = f'n{size}_c{count}_fpga{int(synthesis)}'
        options = [f'-GSIZE={size}', f'-GCOUNT_WIDTH={count}']
        if synthesis:
            options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        else:
            options += ['-USYNTHESIS', '-UXILINX_FPGA']
        commands = []
        for label, path in (('reference', reference), ('candidate', candidate)):
            commands += ['read_slang --top kernel_loader_ctrl '+shlex.join(options+list(map(str, resolve([path], ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top kernel_loader_ctrl -flatten', 'async2sync', 'opt_clean',
                'rename kernel_loader_ctrl '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate proof', 'hierarchy -top proof',
            'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in log.read_text():
            raise RuntimeError('完整权重控制模块形式检查未完成：'+name)
        print(name, match[1], 'PASS', flush=True)
        return {'size': size, 'count_width': count, 'synthesis': synthesis,
            'passed': True, 'proven_points': int(match[1]), 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, [(p, s) for p in PROFILES for s in (False, True)]))
    tb = out/'tb.sv'
    tb.write_text('''module tb;
logic[8:0] value;wire[1:0]pending_loads=value[1:0],pending_sends=value[3:2];
wire issued_zero=value[4],issued_one=value[5],all_done=value[6],all_issued=value[7],load_done=value[8];
wire actual,expected;
kernel_completion_check dut(.i_pending_loads(pending_loads),.i_pending_sends(pending_sends),
.i_issued_zero(issued_zero),.i_issued_one(issued_one),.i_all_loads_done(all_done),
.i_all_loads_issued(all_issued),.i_load_done(load_done),.o_complete(actual));
'''+REFERENCE_BODY+'''
initial begin
for(integer sample=0;sample<262144;sample++)begin
for(integer bit_index=0;bit_index<9;bit_index++)begin
case((sample>>(2*bit_index))&3)
0:value[bit_index]=1'b0;1:value[bit_index]=1'b1;
2:value[bit_index]=1'bx;3:value[bit_index]=1'bz;
endcase
end
#1;if(actual!==expected)$fatal(1,"完成条件四态结果不同 sample=%0d",sample);
end
$display("PASS checks=262144");$finish;
end endmodule
''')
    binary = out/'tb.vvp'
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, ROOT/HELPER, tb],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.check_output(['vvp', binary], text=True, timeout=120)
    (out/'four_state.log').write_text(result)
    if 'PASS checks=262144' not in result or hashes != {name: digest(ROOT/name) for name in hashes}:
        raise RuntimeError('完成条件检查未完成或源文件发生变化')
    report = {'passed': True, 'reference': args.reference, 'source_sha256': hashes,
        'inputs_constrained': False, 'all_public_outputs_and_common_state_compared': True,
        'formal': checks, 'four_state_combinations': 262144,
        'four_state_exhaustive': True, 'four_state_log_sha256': digest(out/'four_state.log')}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print('262144 four-state combinations PASS', flush=True)


if __name__ == '__main__':
    main()
