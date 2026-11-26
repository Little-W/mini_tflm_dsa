#!/usr/bin/env python3
"""验证完整帧地址模块的分段加法、状态推进和四态结果。"""
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
SOURCE = 'rtl/npu/top/frame_address_prepare.sv'
PROFILES = ((1, 0), (1, 1), (2, 1), (3, 1), (16, 0), (16, 1), (17, 1), (32, 1), (64, 1))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='a02b653f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_commit = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    original = subprocess.check_output(['git', 'show', reference_commit+':'+SOURCE], cwd=ROOT, text=True)
    current = (ROOT/SOURCE).read_text()
    snapshots = {}
    for label, content in (('reference', original), ('current', current)):
        snapshots[label] = out/(label+'.sv')
        snapshots[label].write_text(content)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies = resolve([ROOT/SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in dependencies}

    def prove(job):
        (size, mask), pipeline, synthesis = job
        name = f'n{size}_mask{mask}_pipe{pipeline}_fpga{int(synthesis)}'
        flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else ['-USYNTHESIS', '-UXILINX_FPGA']
        options = [f'-Gp_size={size}', f'-Gp_ready_mask_abort={mask}', f'-Gp_pipeline_products={pipeline}', *flags]
        commands = []
        for label, path in snapshots.items():
            commands += ['read_slang --top frame_address_prepare '+shlex.join(options+list(map(str, resolve([path], ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top frame_address_prepare -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename frame_address_prepare '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current proof', 'hierarchy -top proof', 'opt_merge',
            'equiv_simple -short -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in text:
            raise RuntimeError('完整帧地址模块比较未完成：'+name)
        print(name, match[1], 'PASS', flush=True)
        return {'size': size, 'ready_mask_abort': mask, 'pipeline_products': pipeline,
            'synthesis': synthesis, 'passed': True, 'proven_points': int(match[1]), 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, [(profile, pipe, mode) for profile in PROFILES
                                      for pipe in (0, 1) for mode in (False, True)]))

    # 两份完整模块共同接收任意数据和四态控制，逐半周期比较全部公开输出及保存状态。
    ports = re.findall(r'^\s*(input|output)\s+(?:wire\s+)?logic\s*(\[[^]]+\])?\s*(\w+)',
                       original[:original.index('\n);')], re.M)
    input_ports = [(width or '', name) for direction, width, name in ports if direction == 'input']
    output_ports = [(width or '', name) for direction, width, name in ports if direction == 'output']
    for label in snapshots:
        (out/(label+'_sim.sv')).write_text(snapshots[label].read_text().replace(
            'module frame_address_prepare #(', 'module '+label+' #(', 1))
    sim_sources = [out/'reference_sim.sv', out/'current_sim.sv',
                   *(path for path in dependencies if path != ROOT/SOURCE)]
    state = ['c_st', 'n_st', 'operation', 'phase', 'depth_rounded', 'depth_tiles', 'addend',
             'accumulated', 'result_low', 'execute_operation', 'execute_phase',
             'execute_product', 'execute_addend', 'execute_en', 'product_valid_q']
    state += [f'{name}[{index}]' for name in ('factor_a', 'factor_b', 'base', 'offset') for index in range(3)]
    comparisons = [f'(r.{name} === c.{name})' for name in state]
    comparisons += [f'(reference_{name} === current_{name})' for _, name in output_ports]
    bench = ['module tb; parameter integer SIZE=16, MASK=1, PIPELINE=1;']
    bench += [f'reg {width} {name};' for width, name in input_ports]
    bench += [f'wire {width} {label}_{name};' for label in snapshots for width, name in output_ports]
    for label, instance in (('reference', 'r'), ('current', 'c')):
        connections = [f'.{name}({name})' for _, name in input_ports]
        connections += [f'.{name}({label}_{name})' for _, name in output_ports]
        bench += [f'{label} #(.p_size(SIZE),.p_ready_mask_abort(MASK),.p_pipeline_products(PIPELINE)) {instance}('+','.join(connections)+');']
    bench += ['wire equal='+ ' && '.join(comparisons)+';',
              'task check; #1;if(equal!==1\'b1)$fatal(1,"Frame address comparison failed");endtask',
              'initial begin', 'clk=0;']
    bench += [f"{name}='0;" for _, name in input_ports if name != 'clk']
    bench += ['#1;clk=1;check();clk=0;check();', 'for(integer sample=0;sample<16384;sample++)begin']
    for width, name in input_ports:
        if name in ('clk', 'rst_n', 'i_start', 'i_abort', 'i_result_rdy'):
            continue
        bench += [f'{name}=$urandom;']
        if width:
            bench += [f"case(sample%131) 0:{name}='0;1:{name}='1;2:{name}[sample%32]=1'bx;3:{name}[sample%32]=1'bz;default:begin end endcase"]
    bench += ["rst_n=(sample%257)!=0;i_abort=(sample%73)==0;i_start=(sample%32)<3;i_result_rdy=(sample%19)<13;",
              "case(sample%509) 1:i_start=1'bx;2:i_abort=1'bz;3:i_result_rdy=1'bx;4:rst_n=1'bx;default:begin end endcase",
              'check();clk=1;check();clk=0;', 'end',
              '$display("FRAME_SEGMENTS_FOUR_STATE_PASS cycles=16384 comparisons=32770");$finish;end endmodule']
    bench_file = out/'tb.sv'
    bench_file.write_text('\n'.join(bench)+'\n')
    four_state = []
    for size, mask, pipe, synth in ((1,0,0,False),(3,1,0,True),(16,0,1,False),(16,1,1,True),
                                    (17,1,1,True),(32,1,0,True),(64,1,1,True)):
        name = f'four_n{size}_mask{mask}_pipe{pipe}_fpga{int(synth)}'
        binary = out/(name+'.vvp')
        with (out/(name+'_compile.log')).open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb',f'-Ptb.SIZE={size}',f'-Ptb.MASK={mask}',f'-Ptb.PIPELINE={pipe}',
                *(['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synth else []),'-o',str(binary),
                *map(str,sim_sources),str(bench_file)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        result = subprocess.check_output(['vvp',str(binary)],text=True,timeout=180)
        log = out/(name+'.log');log.write_text(result)
        assert 'PASS cycles=16384 comparisons=32770' in result
        four_state.append({'size':size,'ready_mask_abort':mask,'pipeline_products':pipe,'synthesis':synth,
            'passed':True,'cycles':16384,'comparisons':32770,'log_sha256':digest(log)})
        print(name,'PASS',flush=True)
    assert hashes == {name:digest(ROOT/name) for name in hashes}
    report = {'passed':True,'reference_commit':reference_commit,'source_sha256':hashes,
        'reference_sha256':digest(snapshots['reference']),'input_assumptions':[],
        'all_public_outputs_and_common_state_compared':True,'parent_proofs':checks,
        'four_state':four_state,'four_state_comparisons':sum(row['comparisons'] for row in four_state),
        'test_sha256':digest(Path(__file__))}
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('FRAME_SEGMENTS_ALL_PASS',len(checks),report['four_state_comparisons'],flush=True)


if __name__ == '__main__':
    main()
