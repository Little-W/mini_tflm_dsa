#!/usr/bin/env python3
"""验证算术辅助节点的保留属性不改变完整输出及四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ((8, 4, 0), (16, 8, 0), (32, 16, 0), (32, 16, 1),
            (33, 17, 0), (35, 17, 0), (47, 23, 0), (32, 0, 0))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


MODEL = '''module retained_arithmetic #(
 parameter int p_width=32, p_split=16,
 parameter bit p_high=0
)(input logic [p_width-1:0] i_a,i_b,i_target,
 input logic i_carry, output logic o_equal);
 logic [1:0][p_width-1:0] sum;
 logic [1:0] carry, match;
 for(genvar side=0;side<2;side++)begin:g_side
  parallel_prefix_add #(.p_width(p_width),.p_group_width(4),
   .p_preserve_groups(1'b1),.p_dsp_split_width(p_split),
   .p_parallel_high_prefix(p_high),.p_keep_carry(side==0)) u_sum(
   .i_a,.i_b,.i_carry,.o_sum(sum[side]),.o_carry(carry[side]));
  add_equal #(.p_width(p_width),.p_preserve_bits(1'b1),
   .p_keep_bits(side==0)) u_match(
   .i_a,.i_b,.i_target,.i_carry_in(i_carry),.o_equal(match[side]));
 end
 assign o_equal=({carry[0],sum[0],match[0]}==={carry[1],sum[1],match[1]});
endmodule
'''


def bench(width, split, high):
    return f'''module tb;
 localparam int p_width={width};
 logic [p_width-1:0] i_a,i_b,i_target;
 logic i_carry,o_equal;
 integer checks=0;
 retained_arithmetic #(.p_width(p_width),.p_split({split}),.p_high({high})) dut(.*);
 task automatic check;
  #1;
  if(o_equal!==1'b1)$fatal(1,"Arithmetic outputs differ sample=%0d",checks);
  checks++;
 endtask
 initial begin
  for(integer sample=0;sample<4096;sample++)begin
   i_a=p_width'({{$urandom,$urandom}});
   i_b=p_width'({{$urandom,$urandom}});
   i_target=i_a+i_b;
   i_carry=sample[0];check();
   i_target=p_width'({{$urandom,$urandom}});check();
   i_a[sample%p_width]=1'bx;check();
   i_b[(sample+1)%p_width]=1'bz;check();
   i_target[(sample+2)%p_width]=1'bx;check();
   i_carry=1'bx;check();
   i_carry=1'bz;check();
  end
  $display("RETAINED_ARITHMETIC_PASS checks=%0d",checks);
  $finish;
 end
endmodule
'''


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    ROOT = args.repo.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependency = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependency([ROOT / 'rtl/common/parallel_prefix_add.sv',
                          ROOT / 'rtl/common/add_equal.sv'], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    model = out / 'model.sv'
    model.write_text(MODEL)
    rows = []
    for synthesis in (False, True):
        defines = ['-DSYNTHESIS=1'] if synthesis else []
        for width, split, high in PROFILES:
            folder = out / f'w{width}_split{split}_high{high}_synth{int(synthesis)}'
            folder.mkdir(exist_ok=True)
            script = folder / 'formal.ys'
            script.write_text('read_slang --top retained_arithmetic ' +
                              ' '.join(defines) + f' -Gp_width={width} -Gp_split={split} -Gp_high={high} ' +
                              shlex.join(map(str, [*sources, model])) +
                              '\nprep -top retained_arithmetic -flatten\ncheck -assert\n'
                              'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
            formal = folder / 'formal.log'
            run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], formal)
            if 'SAT proof finished - no model found: SUCCESS!' not in formal.read_text():
                raise RuntimeError(f'形式比较未完成：{formal}')
            test, binary = folder / 'test.sv', folder / 'test.vvp'
            test.write_text(bench(width, split, high))
            run(['iverilog', '-g2012', '-s', 'tb', *defines, '-o', binary, *sources, model, test],
                folder / 'compile.log')
            simulation = folder / 'simulation.log'
            run(['vvp', binary], simulation)
            if 'RETAINED_ARITHMETIC_PASS checks=28672' not in simulation.read_text():
                raise RuntimeError(f'四态比较未完成：{simulation}')
            rows.append({'width': width, 'split': split, 'parallel_high': bool(high),
                         'synthesis': synthesis, 'formal_passed': True, 'four_state_checks': 28672,
                         'formal_log_sha256': digest(formal), 'simulation_log_sha256': digest(simulation)})
            print(folder.name + ': PASS', flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('验证期间源码发生变化')
    report = {'passed': True, 'inputs_constrained': False,
              'compared_outputs': ['完整和值', '最高进位', '模加相等关系'],
              'checker_sha256': digest(__file__),
              'source_sha256': hashes, 'profiles': rows,
              'four_state_checks': sum(row['four_state_checks'] for row in rows)}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
