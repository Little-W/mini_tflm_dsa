#!/usr/bin/env python3
"""验证活动描述符选择、完整权重加载器状态及未知输入的选择语义。"""
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
SOURCE = 'rtl/npu/loaders/kernel_loader.sv'
CONTROL = 'rtl/npu/loaders/kernel_loader_ctrl.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comb_block(text, assignment):
    for start in re.finditer(r'\balways_comb\s+begin\b', text):
        depth = 0
        for token in re.finditer(r'\bbegin\b|\bend\b', text[start.end()-5:]):
            depth += 1 if token.group() == 'begin' else -1
            if depth == 0:
                block = text[start.start():start.end()-5+token.end()]
                if assignment in block:
                    return block
                break
    raise ValueError('组合过程不存在：'+assignment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='548bda54')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([ROOT/SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    text = (ROOT/SOURCE).read_text()
    names = ('ctrl_load_req', 'managed_demand_available', 'unmanaged_demand_available',
             'demand_data_available', 'prefetch_available', 'managed_prefetch_available',
             'managed_request_eligible', 'managed_request_available', 'request_permitted', 'demand_issue')
    statements = []
    for name in names:
        match = re.search(r'\bassign\s+'+name+r'\s*=.*?;', text, re.S)
        if match is None:
            raise ValueError('请求资格表达式不存在：'+name)
        statements.append(match[0])
    for assignment in ('selected_request_available =', 'selected_prefetch =',
                       'load_weight_req =', 'port_use_active ='):
        statements.append(comb_block(text, assignment))
    model = out/'selection.sv'
    model.write_text('''// 从实际加载器提取请求和描述符选择的组合逻辑。
module selection(input logic [10:0] controls, // 任意请求、模式及预取状态
                 output logic equal); // 活动描述符资格与完整请求表达式相同
wire transfer_active=controls[0],managed_mode=controls[1],cache_flush=controls[2];
wire init_cfg=controls[3],ctrl_o_request_pending=controls[4],buf_load_ready=controls[5];
wire demand_confirmed=controls[6],ext_dma_busy=controls[7],command_waiting=controls[8];
wire [1:0] prefetch_state=controls[10:9];
localparam [1:0] PF_EMPTY=0,PF_PENDING=1,PF_LOADING=2,PF_CACHED=3;
logic ctrl_load_req,managed_demand_available,unmanaged_demand_available;
logic demand_data_available,prefetch_available,managed_prefetch_available;
logic managed_request_eligible,managed_request_available,request_permitted,demand_issue;
logic selected_request_available,selected_prefetch,prefetch_issue,load_weight_req,port_use_active;
'''+ '\n'.join(statements)+'''
assign equal=port_use_active===(!load_weight_req&&transfer_active);
endmodule
''')
    script, log = out/'selection.ys', out/'selection.log'
    script.write_text('read_slang --top selection '+shlex.quote(str(model))+
        '\nprep -top selection -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')

    def worker(script, log, timeout=480):
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        return log.read_text()

    if 'SUCCESS!' not in worker(script, log):
        raise RuntimeError('活动描述符资格证明未完成')
    reference = out/'reference.sv'
    reference_control = out/'reference_control.sv'
    current = out/'current.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    reference_control.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+CONTROL], cwd=ROOT))
    current.write_bytes((ROOT/SOURCE).read_bytes())

    def prove(profile):
        size, count, bus, fpga = profile
        name = f'n{size}_c{count}_b{bus}_fpga{int(fpga)}'
        options = [f'-GSIZE={size}', f'-GCOUNT_WIDTH={count}', f'-GBUS_WIDTH={bus}', '-GDATA_WIDTH=16']
        if fpga:
            options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        else:
            options += ['-USYNTHESIS', '-UXILINX_FPGA']
        commands = []
        for label, roots in (('reference', [reference, reference_control]), ('current', [current])):
            commands += ['read_slang --top kernel_loader '+shlex.join(options+list(map(str, resolve(roots, ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top kernel_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename kernel_loader '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current proof', 'hierarchy -top proof',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        result = worker(script, log)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', result)
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in result:
            raise RuntimeError('完整权重加载器证明未完成：'+name)
        print(name, match[1], 'PASS', flush=True)
        return {'size': size, 'count_width': count, 'bus_width': bus, 'fpga': fpga,
                'passed': True, 'proven_points': int(match[1]), 'log_sha256': digest(log)}

    profiles = ((4, 8, 32, False), (4, 8, 32, True), (16, 29, 32, True), (16, 29, 64, True))
    with ThreadPoolExecutor(max_workers=2) as pool:
        formal = list(pool.map(prove, profiles))
    tb = out/'tb.sv'
    tb.write_text('''// 穷举请求控制的四态组合，同时覆盖描述符位的十六种数据组合。
module tb;
logic [10:0] controls;wire equal;selection dut(controls,equal);
wire [15:0] issue=16'bzzzzxxxx11110000,active=16'bzx10zx10zx10zx10;
wire [15:0] actual=dut.port_use_active?active:issue;
wire [15:0] expected=dut.load_weight_req?issue:dut.transfer_active?active:issue;
initial begin
for(integer sample=0;sample<4194304;sample++)begin
for(integer bit_index=0;bit_index<11;bit_index++)begin
case((sample>>(2*bit_index))&3)
0:controls[bit_index]=1'b0;1:controls[bit_index]=1'b1;
2:controls[bit_index]=1'bx;3:controls[bit_index]=1'bz;
endcase
end
#1;if(equal!==1'b1||actual!==expected)$fatal(1,"活动描述符选择结果不同 sample=%0d",sample);
end
$display("PASS control_cases=4194304 descriptor_bit_comparisons=67108864");$finish;
end endmodule
''')
    binary = out/'tb.vvp'
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, model, tb],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.check_output(['vvp', binary], text=True, timeout=240)
    (out/'four_state.log').write_text(result)
    if 'PASS control_cases=4194304' not in result:
        raise RuntimeError('四态穷举检查未完成')
    if hashes != {name: digest(ROOT/name) for name in hashes}:
        raise RuntimeError('检查期间源文件发生变化')
    report = {'passed': True, 'reference': args.reference, 'source_sha256': hashes,
        'control_logic_extracted_from_source': True, 'inputs_constrained': False,
        'all_public_outputs_and_common_state_compared': True, 'formal': formal,
        'four_state_control_cases': 4194304, 'four_state_descriptor_bit_comparisons': 67108864,
        'four_state_log_sha256': digest(out/'four_state.log')}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(result.strip(), flush=True)


if __name__ == '__main__':
    main()
