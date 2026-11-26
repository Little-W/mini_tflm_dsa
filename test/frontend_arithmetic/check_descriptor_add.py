#!/usr/bin/env python3
"""验证描述符定宽加法的全部输入组合和未知位传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, digest, run


def bench(width):
    return f'''module tb;
  localparam integer W = {width};
  reg [W-1:0] a,b;
  reg carry;
  wire equivalent;
  integer checks=0;
  integer seed=32'h537214be;
  match_proof u_proof(.i_a(a),.i_b(b),.i_carry(carry),.equivalent(equivalent));
  task check;
    begin
      #1;
      if(equivalent!==1'b1) $fatal(1,"descriptor arithmetic mismatch");
      checks=checks+1;
    end
  endtask
  function automatic reg symbol(input integer value);
    case(value&3)
      0:symbol=1'b0;
      1:symbol=1'b1;
      2:symbol=1'bx;
      3:symbol=1'bz;
    endcase
  endfunction
  initial begin
    for(integer pattern=0;pattern<64;pattern=pattern+1)begin
      a={{W{{symbol(pattern)}}}};
      b={{W{{symbol(pattern>>2)}}}};
      carry=symbol(pattern>>4);
      check();
    end
    for(integer trial=0;trial<8192;trial=trial+1)begin
      for(integer bit_index=0;bit_index<W;bit_index=bit_index+1)begin
        a[bit_index]=$random(seed)&1;
        b[bit_index]=$random(seed)&1;
      end
      carry=$random(seed)&1;
      check();
      if(trial%2==0)begin
        a[trial%W]=symbol(trial/2);
        b[(trial*7+1)%W]=symbol(trial/8);
      end else begin
        for(integer bit_index=0;bit_index<W;bit_index=bit_index+1)begin
          a[bit_index]=symbol($random(seed));
          b[bit_index]=symbol($random(seed));
        end
      end
      carry=symbol(trial/32);
      check();
    end
    $display("DESCRIPTOR_ADD_PASS width=%0d checks=%0d",W,checks);
    $finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_descriptor_add.sv')
    parser.add_argument('--module', choices=('conv_descriptor_add', 'conv_descriptor_address_add'),
                        default='conv_descriptor_add')
    parser.add_argument('--helpers', type=Path, nargs='*', default=[])
    parser.add_argument('--reference', default='eb466c72')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    hashes, formal, simulations = {}, [], []
    reference = None
    if args.module == 'conv_descriptor_address_add':
        reference = out/'reference_adder.sv'
        original = subprocess.check_output(['git', 'show', args.reference+
            ':rtl/npu/conv/conv_descriptor_address_add.sv'], cwd=ROOT, text=True)
        reference.write_text(re.sub(r'\bconv_descriptor_address_add\b', 'reference_adder', original))
    for width in (1, 16, 17, 24, 31, 32, 35, 39, 40, 46, 47, 64):
        wrapper = out/f'width{width}.sv'
        reference_statement = (f'reference_adder #(.p_width({width})) u_reference('
            '.i_a,.i_b,.i_carry,.o_sum(reference_sum));' if reference is not None else
            f"assign reference_sum=i_a+i_b+{width}'(i_carry);")
        wrapper.write_text(f'''module match_proof(input logic [{width-1}:0] i_a,i_b,
input logic i_carry,output logic equivalent);
logic [{width-1}:0] actual,reference_sum;
{args.module} #(.p_width({width})) u_actual(.i_a,.i_b,.i_carry,.o_sum(actual));
{reference_statement}
assign equivalent=actual===reference_sum;
endmodule
''')
        inputs = [args.source.resolve(), wrapper, *[p.resolve() for p in args.helpers]]
        if reference is not None:
            inputs.append(reference)
        sources = dependencies(inputs, ROOT)
        hashes.update({str(p): digest(p) for p in sources})
        simulation_sources = []
        for path in sources:
            target = out/('simulation_'+path.name)
            target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
                'localparam int unsigned', 'localparam integer'))
            simulation_sources.append(target)
        tb = out/f'tb{width}.sv'
        tb.write_text(bench(width))
        for synthesis in (0, 1):
            name = f'width{width}_synthesis{synthesis}'
            options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options, *map(str, sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top match_proof -flatten\ncheck -assert\n'
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise ValueError('描述符加法形式证明未完成：'+name)
            formal.append(dict(width=width, synthesis=synthesis, passed=True, log_sha256=digest(log)))
            binary = out/(name+'.vvp')
            run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary, *simulation_sources, tb],
                out/('compile_'+name+'.log'))
            log = out/('simulation_'+name+'.log')
            run(['vvp', binary], log)
            checks = 16448
            if f'DESCRIPTOR_ADD_PASS width={width} checks={checks}' not in log.read_text():
                raise ValueError('描述符加法四态检查未完成：'+name)
            simulations.append(dict(width=width, synthesis=synthesis, passed=True, checks=checks,
                                    log_sha256=digest(log)))
            print(name+' PASS', flush=True)
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源码发生变化')
    report = dict(passed=True, module=args.module, reference=args.reference if reference is not None else
                  '完整定宽加法表达式', input_assumptions=[], source_sha256=hashes,
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f'DESCRIPTOR_ADD_PASS formal={len(formal)} four_state={sum(x["checks"] for x in simulations)}')


if __name__ == '__main__':
    main()
