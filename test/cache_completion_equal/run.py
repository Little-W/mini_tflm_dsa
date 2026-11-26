#!/usr/bin/env python3
"""验证填充标签相等比较及窗口缓存的全部输出和保存状态。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, timeout=600, check=True)


def bench(width):
    return f'''module tb;
localparam W={width};
logic [W-1:0] i_a,i_b,saved;
logic [31:0] random_state=32'h72ac591d;
wire equivalent;
integer checks=0;
completion_equal_proof #(.W(W)) dut(.*);
function automatic logic [31:0] advance(input logic [31:0] value);
 logic [31:0] result;
 result=value^(value<<13);result=result^(result>>17);
 return result^(result<<5);
endfunction
task automatic check;
 #1;
 if(equivalent!==1'b1)$fatal(1,"Completion tag differs width=%0d a=%h b=%h",W,i_a,i_b);
 checks++;
endtask
initial begin
 for(integer trial=0;trial<32;trial++)begin
  for(integer bit_index=0;bit_index<W;bit_index++)begin
   random_state=advance(random_state);saved[bit_index]=random_state[0];
  end
  if(trial==0)saved='0;
  if(trial==1)saved='1;
  i_a=saved;i_b=saved;check();
  for(integer bit_index=0;bit_index<W;bit_index++)begin
   i_a=saved;i_b=saved;i_a[bit_index]=1'bx;check();
   i_a[bit_index]=1'bz;check();
   i_a=saved;i_b[bit_index]=1'bx;check();
   i_b[bit_index]=1'bz;check();
   i_a=saved;i_b=saved;i_b[(bit_index+1)%W]=~saved[(bit_index+1)%W];
   i_a[bit_index]=1'bx;check();i_a[bit_index]=1'bz;check();
   i_a=saved;i_b=saved;i_a[(bit_index+1)%W]=~saved[(bit_index+1)%W];
   i_b[bit_index]=1'bx;check();i_b[bit_index]=1'bz;check();
  end
 end
 for(integer trial=0;trial<4096;trial++)begin
  for(integer bit_index=0;bit_index<W;bit_index++)begin
   random_state=advance(random_state);
   case(random_state[1:0])
    0:i_a[bit_index]=0;1:i_a[bit_index]=1;2:i_a[bit_index]=1'bx;3:i_a[bit_index]=1'bz;
   endcase
   case(random_state[3:2])
    0:i_b[bit_index]=0;1:i_b[bit_index]=1;2:i_b[bit_index]=1'bx;3:i_b[bit_index]=1'bz;
   endcase
  end
  check();
 end
 i_a='x;i_b='x;check();i_a='z;i_b='z;check();
 $display("COMPLETION_EQUAL_PASS width=%0d checks=%0d",W,checks);$finish;
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='32379597')
    parser.add_argument('--part', choices=('all', 'parent', 'comparison'), default='all')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    actual = ROOT/CACHE
    expected_text = subprocess.check_output(['git', 'show', f'{args.reference}:{CACHE}'],
                                            cwd=ROOT, text=True)
    actual_text = actual.read_text()
    original = '''  logic completion_tag_matches, unused_completion_less;
  // 完整标签在独立组合层次内并行比较，填充资格只在末级合并。
  parallel_unsigned_compare #(.p_width(32-LB)) u_completion_tag (
    .i_a(demand_addr[31:LB]), .i_b(fill_addr[31:LB]),
    .o_less(unused_completion_less), .o_equal(completion_tag_matches)
  );'''
    replacement = '''  logic completion_tag_matches;
  // 完整标签按三位形成相等结果，填充资格只在末级合并。
  conv_cache_snapshot_equal #(.p_width(32-LB)) u_completion_tag (
    .i_a(demand_addr[31:LB]), .i_b(fill_addr[31:LB]),
    .o_equal(completion_tag_matches)
  );'''
    if expected_text.count(original) != 1 or actual_text != expected_text.replace(original, replacement):
        raise ValueError('缓存源文件需要仅包含指定标签比较结构的变化')
    reference = out/'reference_cache.sv'
    reference.write_text(expected_text)
    source_sets = {name: dependencies([source], ROOT)
                   for name, source in [('reference', reference), ('current', actual)]}
    hashes = {str(path): digest(path) for sources in source_sets.values() for path in sources}
    profiles = [(2, 1, 8, 1, 32, 32), (2, 2, 16, 2, 32, 32),
                (4, 1, 32, 4, 64, 64), (16, 2, 128, 2, 64, 64)]
    names = ['SETS', 'WAYS', 'LINE_BYTES', 'DEMAND_DEPTH', 'BUS_WIDTH', 'READ_WIDTH']
    cases = []
    for profile in profiles:
        parameters = dict(zip(names, profile))
        for fpga in (False, True):
            name = 'cache_'+'_'.join(map(str, profile))+('_fpga' if fpga else '_generic')
            script, log = out/(name+'.ys'), out/(name+'.log')
            flags = [f'-G{key}={value}' for key, value in parameters.items()]
            if fpga:
                flags += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
            commands = []
            for label, sources in source_sets.items():
                commands += ['read_slang --top conv_windowed_cache '+shlex.join(
                    ['-I'+str(ROOT/'include'), *flags, *map(str, sources)]),
                    'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                    'prep -top conv_windowed_cache -flatten', 'memory_map', 'async2sync',
                    'opt -full', f'rename -top {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current proof', 'hierarchy -top proof',
                         # 归约输入的位序不参与结构匹配，完整归纳仍检查所有节点。
                         'equiv_struct -icells -fwd t:* t:$reduce_and %d',
                         'select *', 'equiv_induct -seq 2',
                         'equiv_simple -seq 1', 'opt_clean',
                         'equiv_status -assert']
            script.write_text('\n'.join(commands)+'\n')
            cases.append((name, script, log, parameters, fpga))

    def execute(case):
        name, script, log, parameters, fpga = case
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'Equivalence successfully proven!' not in log.read_text():
            raise ValueError('完整窗口缓存证明未完成：'+name)
        counts = re.findall(r'Found (\d+) \$equiv cells', log.read_text())
        print(name+' PASS', flush=True)
        return dict(name=name, parameters=parameters, fpga=fpga, passed=True,
                    equivalent_bits=int(counts[-1]), script_sha256=digest(script),
                    log_sha256=digest(log))

    formal = []
    if args.part != 'comparison':
        with ThreadPoolExecutor(max_workers=2) as pool:
            formal = list(pool.map(execute, cases))

    model = out/'comparison.sv'
    model.write_text('''module completion_equal_proof #(parameter W=25)(
 input logic [W-1:0] i_a,i_b,output logic equivalent);
logic expected,actual,unused_less;
parallel_unsigned_compare #(.p_width(W)) u_reference(
 .i_a,.i_b,.o_less(unused_less),.o_equal(expected));
conv_cache_snapshot_equal #(.p_width(W)) u_actual(.i_a,.i_b,.o_equal(actual));
assign equivalent=expected===actual;
endmodule
''')
    compare_sources = dependencies([model], ROOT)
    hashes.update({str(path): digest(path) for path in compare_sources})
    pointwise, four_state = [], []
    widths = () if args.part == 'parent' else (1, 2, 3, 16, 24, 25, 28, 29, 32, 46)
    for width in widths:
        for fpga in (False, True):
            name = f'equal_w{width}_'+('fpga' if fpga else 'generic')
            flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if fpga else []
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text('read_slang --top completion_equal_proof '+shlex.join(
                [f'-GW={width}', *flags, *map(str, compare_sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
                'prep -top completion_equal_proof -flatten\ncheck -assert\n'+
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SUCCESS!' not in log.read_text():
                raise ValueError('相等关系任意输入证明未完成')
            pointwise.append(dict(width=width, fpga=fpga, passed=True,
                                  log_sha256=digest(log)))
            tb = out/(name+'_tb.sv')
            tb.write_text(bench(width))
            binary = out/(name+'.vvp')
            run(['iverilog', '-g2012', '-s', 'tb', *flags, '-o', binary,
                 *compare_sources, tb], out/(name+'_compile.log'))
            sim = out/(name+'_simulation.log')
            run(['vvp', binary], sim)
            checks = 32*(1+8*width)+4098
            if f'COMPLETION_EQUAL_PASS width={width} checks={checks}' not in sim.read_text():
                raise ValueError('相等关系四态检查未完成')
            four_state.append(dict(width=width, fpga=fpga, checks=checks, passed=True,
                                   log_sha256=digest(sim)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    report = dict(passed=True, reference_commit=args.reference, source_sha256=hashes,
                  input_constraints=[], parent_outputs_and_state_every_cycle=bool(formal),
                  unchanged_outside_completion_tag=True, formal=formal,
                  pointwise=pointwise, four_state=four_state)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('CACHE_COMPLETION_EQUAL_PASS parent='+str(len(formal))+
          ' pointwise='+str(len(pointwise))+
          ' four_state='+str(sum(row['checks'] for row in four_state)))


if __name__ == '__main__':
    main()
