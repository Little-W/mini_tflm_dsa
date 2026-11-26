#!/usr/bin/env python3
"""证明完整偏置分组状态逐周期等价，并检查四态控制与定宽回绕。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/npu_output_pipeline.sv')
REFERENCE = '8b3728c008e6093095c8ade34aa4516145bc6005'
PROFILES = ((1, 1, 32), (16, 32, 32), (32, 32, 16), (32, 64, 64))
EXTRACT = runpy.run_path(str(ROOT / 'test/bias_row_final_select/extract_control.py'))
DEPENDENCIES = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def control(source):
    end = re.search(r'^\s*logic signed \[31:0\] bias_rhs', source, re.M)
    if end:
        source = source[:end.start()] + '\n genvar rq_i;\nendmodule\n'
    result = EXTRACT['module_source'](source)
    declaration = '        logic is_bias_target_zero;'
    if result.count(declaration) > 1:
        result = result.replace(declaration, '', 1)
    return result


def run(command, log, timeout=180):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def simulate(out, snapshots, helpers):
    for label, path in snapshots.items():
        (out/(label+'_sim.sv')).write_text(path.read_text().replace(
            'module bias_row_control', 'module bias_row_control_'+label, 1))
    inputs = ['clk', 'core_rst_n', 'init_cfg_ia', 'is_mode', 'acc_data_valid',
              'bias_switch', 'send_ia_trigger', 'bias_sleep', 'exec_m', 'is_bias_group_rows_target']
    outputs = [('o_row_idx', 9), ('o_read_idx', 9), ('o_group_base', 32),
               ('o_last_group_base', 32), ('o_last_rows', 10), ('o_rows_valid', 10),
               ('o_rows_valid_pending', 10)]
    declarations = '\n'.join(f'logic [{width-1}:0] {label}_{name};'
                             for label in snapshots for name, width in outputs)
    instances = '\n'.join('bias_row_control_'+label+' u_'+label+' ('+
        ','.join(['.'+name+'('+name+')' for name in inputs]+
                 ['.'+name+'('+label+'_'+name+')' for name, _ in outputs])+');'
        for label in snapshots)
    bundles = {label: '{'+','.join(label+'_'+name for name, _ in outputs)+'}' for label in snapshots}
    testbench = out/'four_state_tb.sv'
    testbench.write_text(f'''
module tb;
logic clk=0,core_rst_n=0,init_cfg_ia=0,is_mode=0,acc_data_valid=0;
logic bias_switch=0,send_ia_trigger=0,bias_sleep=0;
logic[31:0] exec_m=0;
logic[9:0] is_bias_group_rows_target=0;
integer checks=0;
{declarations}
{instances}
task tick;
 #1;clk=1;#1;
 if({bundles['reference']} !== {bundles['candidate']}) $fatal(1,"偏置控制结果不一致，周期 %0d",checks);
 checks=checks+1;clk=0;
endtask
initial begin
 repeat(3)tick();core_rst_n=1;
 for(int iteration=0;iteration<6000;iteration++)begin
  init_cfg_ia=($urandom%4)==0;is_mode=($urandom%5)!=0;
  acc_data_valid=$random;bias_switch=$random;send_ia_trigger=$random;bias_sleep=$random;
  exec_m=$random;is_bias_group_rows_target=10'($random);
  if(iteration%11==0)exec_m[iteration%32]=1'bx;
  if(iteration%13==0)is_bias_group_rows_target[iteration%10]=1'bx;
  if(iteration%17==0)is_mode=1'bx;
  if(iteration%19==0)acc_data_valid=1'bz;
  tick();
 end
 $display("PASS %0d four-state cycle comparisons",checks);$finish;
end
endmodule
''')
    reports = []
    for synthesis in (False, True):
        name = 'synthesis' if synthesis else 'generic'
        executable = out/(name+'.vvp')
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(executable)]
        if synthesis:
            command += ['-D', 'SYNTHESIS=1']
        command += [str(out/(label+'_sim.sv')) for label in snapshots]
        command += [str(path) for path in helpers]+[str(out/'reference_mask.sv'), str(testbench)]
        run(command, out/(name+'_simulation_build.log'))
        log = out/(name+'_simulation.log')
        run(['vvp', str(executable)], log)
        assert 'PASS 6003' in log.read_text()
        reports.append({'synthesis': synthesis, 'cycles': 6003, 'passed': True, 'log_sha256': digest(log)})
    return reports


def helper_formal(out, helpers):
    """独立检查分组地址、大小关系与相等关系的全部输入组合。"""
    wrapper = out/'helper_compare.sv'
    wrapper.write_text("""
module helper_compare #(
    parameter integer WIDTH=32, COUNT_WIDTH=10
)(input logic [WIDTH-1:0] base,bound,
  input logic [COUNT_WIDTH-1:0] rows,
  output logic equal);
logic [WIDTH-1:0] candidate_sum,reference_sum;
logic candidate_less,candidate_equal;
npu_output_bias_advance #(.p_width(WIDTH),.p_count_width(COUNT_WIDTH)) u_candidate(
    .i_base(base),.i_rows(rows),.i_bound(bound),.o_sum(candidate_sum),
    .o_less(candidate_less),.o_equal(candidate_equal));
assign reference_sum=base+WIDTH'(rows);
assign equal={candidate_sum,candidate_less,candidate_equal}==
    {reference_sum,(reference_sum<bound),(reference_sum==bound)};
endmodule
""")
    reports = []
    for width,count in ((1,1),(2,1),(8,7),(16,5),(32,10),(64,9),(8,12)):
        folder=out/f'helper_w{width}_c{count}'
        folder.mkdir(exist_ok=True)
        script=folder/'formal.ys'
        script.write_text('read_slang --top helper_compare -D SYNTHESIS=1 '+
            f'-GWIDTH={width} -GCOUNT_WIDTH={count} '+
            shlex.join(map(str,[wrapper]+helpers))+'\n'+
            'setattr -mod -unset keep_hierarchy\n'+
            'prep -top helper_compare -flatten\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        log=folder/'formal.log'
        run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],log)
        assert 'SUCCESS' in log.read_text()
        reports.append({'width':width,'count_width':count,'passed':True,
                        'script_sha256':digest(script),'log_sha256':digest(log)})
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'], cwd=ROOT, text=True).strip()
    original = subprocess.check_output(['git', 'show', f'{commit}:{SOURCE}'], cwd=ROOT, text=True)
    snapshots = {}
    for label, source in [('reference', original), ('candidate', (ROOT/SOURCE).read_text())]:
        path = out / (label+'.sv')
        contents = control(source)
        if label == 'reference':
            contents = contents.replace('npu_output_bias_mask', 'npu_output_bias_mask_reference')
        path.write_text(contents)
        snapshots[label] = path
    helpers = DEPENDENCIES['with_dependencies']([
        ROOT/'rtl/npu/top/npu_output_bias_advance.sv',
        ROOT/'rtl/npu/top/npu_output_bias_mask.sv',
        ROOT/'rtl/npu/top/npu_output_bias_row_select.sv',
        ROOT/'rtl/common/unsigned_compare.sv',
        ROOT/'rtl/common/parallel_prefix_add.sv'], ROOT)
    old_mask = out/'reference_mask.sv'
    old_mask.write_text(subprocess.check_output(
        ['git','show',f'{commit}:rtl/npu/top/npu_output_bias_mask.sv'],
        cwd=ROOT,text=True).replace('module npu_output_bias_mask', 'module npu_output_bias_mask_reference'))
    helper_args = ' '.join(shlex.quote(str(path)) for path in helpers+[old_mask])
    report = {'reference_commit': commit, 'inputs_constrained': False, 'profiles': [],
              'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in helpers+[ROOT/SOURCE]}}
    for size, groups, width in PROFILES:
        for synthesis in (False, True):
            name = f's{size}_g{groups}_w{width}_{"synthesis" if synthesis else "generic"}'
            folder = out/name
            folder.mkdir(exist_ok=True)
            commands = []
            define = '-D SYNTHESIS=1' if synthesis else ''
            for label, snapshot in snapshots.items():
                commands += [f'read_slang --top bias_row_control -GSIZE={size} -GBIAS_GROUP_BLOCKS_MAX={groups} -GREG_WIDTH={width} {define} {shlex.quote(str(snapshot))} {helper_args}',
                             'prep -top bias_row_control -flatten', 'async2sync', 'opt -full',
                             f'rename bias_row_control {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
            script = folder/'formal.ys'
            script.write_text('\n'.join(commands)+'\n')
            log = folder/'formal.log'
            run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
            assert 'Equivalence successfully proven' in log.read_text()
            report['profiles'].append({'size': size, 'groups': groups, 'width': width,
                                       'synthesis': synthesis, 'passed': True,
                                       'script_sha256': digest(script), 'log_sha256': digest(log)})
            print(name+' PASS', flush=True)
    report['helper_profiles'] = helper_formal(out, helpers)
    report['four_state_simulation'] = simulate(out, snapshots, helpers)
    for path, expected in report['source_sha256'].items():
        assert digest(ROOT/path) == expected
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
