#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""证明可选分段加法的完整结果，并验证实际映射后的全部时序输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--rtl-only', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = args.source_root.resolve() / 'rtl/common/parallel_prefix_add.sv'
    sources = (helper, HERE / 'measure.sv', Path(__file__).resolve())
    source_names = ('rtl/common/parallel_prefix_add.sv',
                    'test/parallel_prefix_dsp/measure.sv', 'test/parallel_prefix_dsp/run.py')
    hashes = {name: digest(path) for name, path in zip(source_names, sources)}
    profiles = [(width, (width+1)//2) for width in
                (1, 2, 3, 4, 7, 8, 12, 13, 16, 17, 18, 23, 24, 25, 31, 32, 33, 35, 46, 47, 64)]
    profiles += [(32, split) for split in (0, 1, 8, 12, 17, 23, 24, 32, 33)]
    profiles = [(width, split, preserve) for width, split in profiles for preserve in (0, 1)]
    formal = ['module proof(input logic[63:0]i_a,i_b,input logic i_carry,output logic equivalent);',
              f'logic[{len(profiles)-1}:0] compared;']
    bench = ['module tb; logic[63:0]a,b;logic carry_in;',
             f'logic[{len(profiles)-1}:0] compared;integer samples;']
    for index, (width, split, preserve) in enumerate(profiles):
        params = (f'.p_width({width}),.p_group_width(8),.p_preserve_groups(1\'b{preserve}),'
                  '.p_carry_select_width(16)')
        formal += [f'logic[{width}:0] actual_{index},expected_{index};',
                   f'parallel_prefix_add #({params},.p_dsp_split_width({split})) u{index}(',
                   f'.i_a(i_a[{width-1}:0]),.i_b(i_b[{width-1}:0]),.i_carry(i_carry),',
                   f'.o_sum(actual_{index}[{width-1}:0]),.o_carry(actual_{index}[{width}]));',
                   f'assign expected_{index}={{1\'b0,i_a[{width-1}:0]}}+'
                   f'{{1\'b0,i_b[{width-1}:0]}}+{width+1}\'(i_carry);',
                   f'assign compared[{index}]=actual_{index}==expected_{index};']
        bench += [f'logic[{width}:0] actual_{index},expected_{index};',
                  f'parallel_prefix_add #({params},.p_dsp_split_width({split})) u{index}(',
                  f'.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_carry(carry_in),',
                  f'.o_sum(actual_{index}[{width-1}:0]),.o_carry(actual_{index}[{width}]));',
                  f'parallel_prefix_add #({params}) r{index}(',
                  f'.i_a(a[{width-1}:0]),.i_b(b[{width-1}:0]),.i_carry(carry_in),',
                  f'.o_sum(expected_{index}[{width-1}:0]),.o_carry(expected_{index}[{width}]));',
                  f'assign compared[{index}]=actual_{index}===expected_{index};']
    formal += ['assign equivalent=&compared;', 'endmodule']
    bench += ['initial begin', 'samples=0;',
              'for(integer sample=0;sample<4096;sample++)begin',
              'a={$urandom,$urandom};b={$urandom,$urandom};carry_in=sample[0];',
              'case(sample%8)',
              '0:a[(sample/8)%64]=1\'bx;', '1:a[(sample/8)%64]=1\'bz;',
              '2:b[(sample/8)%64]=1\'bx;', '3:b[(sample/8)%64]=1\'bz;',
              '4:carry_in=1\'bx;', '5:carry_in=1\'bz;',
              '6:begin a=0;b=64\'hffff_ffff_ffff_ffff;end',
              'default:begin a=64\'hffff_ffff_ffff_ffff;b=a;end',
              'endcase', '#1;if((&compared)!==1\'b1)$fatal(1,"Four-state result differs");',
              'samples++;end', '$display("PREFIX_FOUR_STATE_PASS samples=%0d",samples);$finish;',
              'end', 'endmodule']
    model = out / 'proof.sv'
    model.write_text('\n'.join(formal)+'\n')
    script, log = out / 'proof.ys', out / 'proof.log'
    script.write_text(f'read_slang --top proof -DSYNTHESIS {helper} {model}\n'
                      'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                      'prep -top proof -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    proof = run_stage(script, log, dict(os.environ))
    if 'SUCCESS!' not in log.read_text():
        raise RuntimeError('完整位宽的形式证明未完成')
    bench_path, binary = out / 'four_state.sv', out / 'four_state.vvp'
    bench_path.write_text('\n'.join(bench)+'\n')
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, helper, bench_path], out / 'compile.log')
    run(['vvp', binary], out / 'four_state.log')
    if 'PREFIX_FOUR_STATE_PASS samples=4096' not in (out / 'four_state.log').read_text():
        raise RuntimeError('四态验证未完成')
    binary.unlink()
    report = {'passed': False, 'source_sha256': hashes, 'profiles': profiles,
              'formal_stage': proof, 'four_state_samples_per_profile': 4096, 'mapped_profiles': []}
    print('PREFIX_RTL_PASS profiles='+str(len(profiles)), flush=True)

    if not args.rtl_only:
        cases = {}
        for width, split in ((32, 16), (33, 17), (35, 18)):
            for carry in (-1, 0, 1):
                name = f'w{width}_carry{carry}'
                cases[name] = {'top': 'parallel_prefix_dsp_measure',
                               'sources': [str(helper), str(HERE / 'measure.sv')],
                               'options': ['-D', 'SYNTHESIS=1', f'-GWIDTH={width}',
                                           f'-GSPLIT={split}', f'-GCARRY={carry}'],
                               'configuration': '完整结果及最高进位的分段算术映射'}
        case_file = out / 'cases.json'
        case_file.write_text(json.dumps(cases, indent=2, ensure_ascii=False)+'\n')
        run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--source-root', args.source_root.resolve(),
             '--case-config', case_file, '--cases', *cases, '--out', out / 'mapping', '--resume'], out / 'mapping.log')
        import pyosys
        library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
        report['official_primitive_library_sha256'] = digest(library)
        for name, case in cases.items():
            folder = out / 'mapping' / name
            mapped = folder / 'mapped.json'
            metrics = json.loads((folder / 'metrics.json').read_text())
            width = int(name.split('_')[0][1:])
            carry = int(name.split('carry')[1])
            reference = out / (name+'_reference.sv')
            reference.write_text(f'''module reference(input logic i_clk,input logic[{width-1}:0]i_a,i_b,
input logic i_carry,output logic[{width}:0]o_sum);
logic[{width-1}:0]saved_a,saved_b;logic saved_carry,carry_in;
assign carry_in={carry}<0?saved_carry:({carry}!=0);
always_ff @(posedge i_clk)begin saved_a<=i_a;saved_b<=i_b;saved_carry<=i_carry;
o_sum<={{1'b0,saved_a}}+{{1'b0,saved_b}}+{width+1}'(carry_in);end
endmodule
''')
            commands = [f'read_slang --top reference {reference}', 'prep -top reference -flatten',
                        'opt -full', 'rename -hide w:*', 'design -stash reference',
                        'read_json '+str(mapped), 'delete =A:blackbox',
                        'read_verilog -overwrite +/xilinx/cells_sim.v',
                        'hierarchy -top parallel_prefix_dsp_measure', 'rename -top current',
                        'setattr -mod -unset keep_hierarchy', 'flatten -wb', 'proc',
                        'memory_map', 'async2sync', 'opt -full', 'rename -hide w:*',
                        'design -stash current', 'design -copy-from reference -as reference reference',
                        'design -copy-from current -as current current',
                        'equiv_make reference current proof', 'hierarchy -top proof',
                        'equiv_simple -seq 4', 'opt_clean', 'equiv_induct -seq 8', 'equiv_status -assert']
            proof_script, proof_log = out / (name+'.ys'), out / (name+'.log')
            proof_script.write_text('\n'.join(commands)+'\n')
            measurement = run_stage(proof_script, proof_log, dict(os.environ))
            if not re.search(rf'Of those cells {width+1} are proven and 0 are unproven', proof_log.read_text()):
                raise RuntimeError('实际映射的完整输出证明未完成：'+name)
            if metrics['resources']['dsp48e1'] != 1:
                raise RuntimeError('双段算术未使用单个 DSP：'+name)
            entry = {'name': name, 'width': width, 'carry': carry, 'passed': True,
                     'unbounded_equivalence': True, 'compared_output_bits': width+1,
                     'mapped_sha256': digest(mapped), 'resources': metrics['resources'],
                     'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                     'equivalence_stage': measurement}
            report['mapped_profiles'].append(entry)
            print(json.dumps({key: entry[key] for key in
                              ('name', 'passed', 'compared_output_bits', 'longest_register_path_cells')}), flush=True)
    if hashes != {name: digest(path) for name, path in zip(source_names, sources)}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
