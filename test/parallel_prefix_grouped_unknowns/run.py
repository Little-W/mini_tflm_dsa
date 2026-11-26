#!/usr/bin/env python3
"""验证分段加法的原分组四态传播，比较全部和值及最高进位。"""
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
RTL = Path('rtl/common/parallel_prefix_add.sv')
REFERENCE = '8b3728c008e6093095c8ade34aa4516145bc6005'
PARAMETERS = ('p_width', 'p_group_width', 'p_preserve_groups',
              'p_carry_select_width', 'p_dsp_split_width',
              'p_parallel_high_prefix', 'p_keep_carry')
PROFILES = [(width, 8, 1, 0, 16 if width <= 32 else 20, 1, 0)
            for width in range(28, 37)]
PROFILES += [(width, group, preserve, 0, (width+1)//2, 1, 0)
             for width, group, preserve in ((2, 3, 0), (7, 3, 1), (8, 8, 0),
                 (17, 3, 0), (32, 3, 1), (32, 3, 0), (35, 3, 0), (46, 8, 1))]
PROFILES += [(width, group, preserve, 0, split, 1, 0)
             for width, group, preserve, split in ((29, 8, 0, 16), (32, 8, 0, 16),
                 (33, 4, 1, 17), (34, 4, 1, 20))]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, timeout=180):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def instance(name, module, index, width, profile, direct_subtract=False):
    selected = profile if module == 'parallel_prefix_add' else (*profile[:4], 0, 0, 1)
    values = ','.join(f'.{key}({value})' for key, value in zip(PARAMETERS, selected))
    if module == 'parallel_prefix_add':
        values += ',.p_preserve_grouped_unknowns(1)'
        if direct_subtract:
            values += ',.p_direct_subtract(1)'
    return (f'{module} #({values}) {name}_{index}('
            f'.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_carry(carry_in),'
            f'.o_sum({name}_result_{index}[{width-1}:0]),'
            f'.o_carry({name}_result_{index}[{width}]));')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--direct-subtract', action='store_true')
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=ROOT, text=True).strip()
    original = subprocess.check_output(['git', 'show', f'{revision}:{RTL}'], cwd=ROOT, text=True)
    reference = out/'reference.sv'
    reference.write_text(original.replace('parallel_prefix_add', 'prefix_reference'))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    helpers = resolve([source_root/RTL], source_root)
    hashes = {str(path.relative_to(source_root)): digest(path) for path in helpers}
    wrapper = out/'proof.sv'
    wrapper_source = '''
// 比较完整定宽加法及最高进位，不限制两个操作数和输入进位。
module proof #(
    parameter integer WIDTH=32, GROUP=8, PRESERVE=0,
    parameter integer SELECT=0, SPLIT=0, PARALLEL=0, KEEP_CARRY=1
)(input logic [WIDTH-1:0] a,b,input logic carry_in,output logic equal);
logic [WIDTH:0] candidate,reference_result,arithmetic_result;
parallel_prefix_add #(.p_width(WIDTH),.p_group_width(GROUP),.p_preserve_groups(PRESERVE),
    .p_carry_select_width(SELECT),.p_dsp_split_width(SPLIT),
    .p_parallel_high_prefix(PARALLEL),.p_keep_carry(KEEP_CARRY),
    .p_preserve_grouped_unknowns(1)) u_candidate(
    .i_a(a),.i_b(b),.i_carry(carry_in),.o_sum(candidate[WIDTH-1:0]),.o_carry(candidate[WIDTH]));
prefix_reference #(.p_width(WIDTH),.p_group_width(GROUP),.p_preserve_groups(PRESERVE),
    .p_carry_select_width(SELECT)) u_reference(
    .i_a(a),.i_b(b),.i_carry(carry_in),.o_sum(reference_result[WIDTH-1:0]),.o_carry(reference_result[WIDTH]));
assign arithmetic_result={1'b0,a}+{1'b0,b}+(WIDTH+1)'(carry_in);
assign equal=(candidate==reference_result)&&(candidate==arithmetic_result);
endmodule
'''
    if args.direct_subtract:
        wrapper_source = wrapper_source.replace('.p_preserve_grouped_unknowns(1))',
            '.p_preserve_grouped_unknowns(1),.p_direct_subtract(1))')
    wrapper.write_text(wrapper_source)
    formal_parameters = ('WIDTH', 'GROUP', 'PRESERVE', 'SELECT', 'SPLIT', 'PARALLEL', 'KEEP_CARRY')

    def prove(case):
        index, profile, synthesis = case
        name = f'{index:02d}_'+('synthesis' if synthesis else 'generic')
        folder = out/name
        folder.mkdir(exist_ok=True)
        options = ['-DSYNTHESIS=1'] if synthesis else []
        options += [f'-G{key}={value}' for key, value in zip(formal_parameters, profile)]
        script, log = folder/'formal.ys', folder/'formal.log'
        script.write_text('read_slang --top proof '+shlex.join(options+list(map(str,
            helpers+[reference, wrapper])))+'\n'+
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
            'prep -top proof -flatten\ncheck -assert\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'SUCCESS!' in log.read_text()
        print(name+' PASS', flush=True)
        return {'profile':dict(zip(PARAMETERS,profile)), 'synthesis':synthesis,
                'inputs_constrained':False, 'output_bits':profile[0]+1, 'passed':True,
                'script_sha256':digest(script), 'log_sha256':digest(log)}

    jobs = [(index, profile, synthesis) for index, profile in enumerate(PROFILES)
            for synthesis in (False, True)]
    with ThreadPoolExecutor(max_workers=max(1,args.jobs)) as pool:
        formal = list(pool.map(prove, jobs))

    bench = ['module tb; logic [63:0] a,b;logic carry_in;',
             f'logic [{len(PROFILES)-1}:0] equal;', 'integer samples=0;']
    for index, profile in enumerate(PROFILES):
        width=profile[0]
        bench += [f'logic [{width}:0] candidate_result_{index},reference_result_{index};',
                  instance('candidate','parallel_prefix_add',index,width,profile,args.direct_subtract),
                  instance('reference','prefix_reference',index,width,profile),
                  f'assign equal[{index}]=candidate_result_{index}===reference_result_{index};']
    bench += ['initial begin', 'for(integer sample=0;sample<8192;sample++)begin',
              'a={$urandom,$urandom};b={$urandom,$urandom};carry_in=sample[0];',
              'case(sample%12)',
              "0:a[(sample/12)%64]=1'bx;", "1:a[(sample/12)%64]=1'bz;",
              "2:b[(sample/12)%64]=1'bx;", "3:b[(sample/12)%64]=1'bz;",
              "4:carry_in=1'bx;", "5:carry_in=1'bz;",
              "6:begin a='1;b=0;end", "7:begin a='1;b='1;end",
              "8:begin a='0;b='0;end", "9:begin a='1;b='x;end",
              'default:begin end', 'endcase',
              '#1;', 'for(integer index=0;index<'+str(len(PROFILES))+';index++)',
              'if(!equal[index])$fatal(1,"加法四态结果不一致，配置 %0d 样本 %0d",index,sample);',
              'samples++;end', '$display("PASS samples=%0d",samples);$finish;', 'end endmodule']
    bench_path=out/'four_state.sv'
    bench_path.write_text('\n'.join(bench)+'\n')
    simulations=[]
    for synthesis in (False,True):
        name='synthesis' if synthesis else 'generic'
        binary=out/(name+'.vvp')
        options=['-DSYNTHESIS=1'] if synthesis else []
        execute(['iverilog','-g2012','-s','tb',*options,'-o',binary,
                 *helpers,reference,bench_path],out/(name+'_compile.log'))
        log=out/(name+'_simulation.log')
        execute(['vvp',binary],log)
        assert 'PASS samples=8192' in log.read_text()
        simulations.append({'synthesis':synthesis,'profiles':len(PROFILES),
                            'comparisons':8192*len(PROFILES),'passed':True,
                            'log_sha256':digest(log)})
        binary.unlink()
    assert hashes=={str(path.relative_to(source_root)):digest(path) for path in helpers}
    report={'passed':True,'reference_revision':revision,'source_sha256':hashes,
            'direct_subtract':args.direct_subtract,
            'test_sha256':digest(Path(__file__)),'formal':formal,'four_state':simulations}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'formal_profiles':len(formal),
                      'four_state_comparisons':sum(item['comparisons'] for item in simulations)}),flush=True)


if __name__=='__main__':
    main()
