#!/usr/bin/env python3
"""验证窗口准备目标在配置更新、覆盖写入和描述符比较之间的时序关系。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import ROOT, digest, run


MODEL = '''module target_proof(
 input logic i_clk,i_rst_n,i_configure,i_write,
 input logic [32:0] i_new_step,
 input logic [31:0] i_reduction,i_target,
 output logic equivalent);
logic [32:0] step_q;
logic [31:0] reduction_q;
logic valid_q,actual,reference;
always_ff @(posedge i_clk or negedge i_rst_n) begin
 if(!i_rst_n)begin step_q<='0;valid_q<=1'b0;end
 else begin
  if(i_configure)begin step_q<=i_new_step;valid_q<=1'b0;end
  else if(i_write)valid_q<=1'b1;
 end
end
always_ff @(posedge i_clk)if(i_rst_n&&i_write)reduction_q<=i_reduction;
conv_descriptor_window_target u_actual(
 .i_clk,.i_write(i_rst_n&&i_write),.i_preparing_reduction(i_reduction),
 .i_saved_reduction(reduction_q),.i_step(step_q),.i_target,.o_equal(actual));
add_equal #(.p_width(33),.p_preserve_bits(1'b1)) u_reference(
 .i_a({1'b0,reduction_q}),.i_b(step_q),.i_target({1'b0,i_target}),
 .i_carry_in(1'b0),.o_equal(reference));
assign equivalent=!valid_q||(actual===reference);
endmodule
'''


BENCH = '''module tb;
logic i_clk=0,i_rst_n=0,i_configure=0,i_write=0;
logic [32:0] i_new_step='0;
logic [31:0] i_reduction='0,i_target='0;
wire equivalent;
integer checks=0;
target_proof dut(.*);
task automatic check;
 #1;if(equivalent!==1'b1)$fatal(1,"Window target mismatch");checks++;
endtask
task automatic tick;
 i_clk=0;#1;i_clk=1;check();i_clk=0;check();
endtask
logic [31:0] known_target;
logic [32:0] known_step;
initial begin
 tick();i_rst_n=1;
 for(integer trial=0;trial<96;trial++)begin
  i_configure=1;i_write=$urandom_range(0,1);i_new_step={$urandom,$urandom};tick();
  i_configure=0;i_write=1;i_reduction=$urandom;tick();i_write=0;
  i_target=32'(dut.reduction_q+dut.step_q);check();known_target=i_target;
  for(integer bit_index=0;bit_index<32;bit_index++)begin
   i_target=known_target;i_target[bit_index]=1'bx;check();
   i_target=known_target;i_target[bit_index]=1'bz;check();
  end
  i_target=$urandom;check();i_write=1;i_reduction=$urandom;tick();i_write=0;
  i_target='x;check();i_target='z;check();i_target=$urandom;
  known_step={$urandom,$urandom};
  for(integer bit_index=0;bit_index<33;bit_index++)begin
   i_new_step=known_step;i_new_step[bit_index]=1'bx;i_configure=1;tick();
   i_configure=0;i_write=1;i_reduction=$urandom;tick();i_write=0;check();
   i_new_step=known_step;i_new_step[bit_index]=1'bz;i_configure=1;tick();
   i_configure=0;i_write=1;i_reduction=$urandom;tick();i_write=0;check();
  end
  if(trial%11==0)begin i_rst_n=0;tick();i_rst_n=1;end
 end
 $display("WINDOW_TARGET_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_descriptor_window_target.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([args.source.resolve()], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    model = out/'target_proof.sv'
    model.write_text(MODEL)
    proofs, simulations = [], []
    for synthesis in (0, 1):
        name = f'synthesis{synthesis}'
        script, log = out/(name+'.ys'), out/(name+'.log')
        options = ['-DSYNTHESIS=1'] if synthesis else []
        script.write_text(slang_command(options)+'--top target_proof '+shlex.join([*options,*map(str,sources),str(model)])+
                         '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                         'prep -top target_proof -flatten\nasync2sync\nopt\ncheck -assert\n'
                         'sat -verify -tempinduct -seq 1 -maxsteps 4 -set-init-zero '
                         '-prove equivalent 1 -show-ports\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'Induction step proven: SUCCESS!' not in log.read_text():
            raise ValueError('窗口准备目标时序证明未完成')
        proofs.append(dict(synthesis=synthesis, passed=True, log_sha256=digest(log)))
        simulation_sources = []
        for path in sources:
            target = out/('simulation_'+path.name)
            target.write_text(path.read_text().replace('parameter int unsigned','parameter integer'))
            simulation_sources.append(target)
        generated_bench = out/'tb.sv'
        generated_bench.write_text(BENCH)
        binary = out/f'simulation_{synthesis}.vvp'
        options = ['-DSYNTHESIS=1'] if synthesis else []
        run(['iverilog','-g2012',*options,'-s','tb','-o',binary,*simulation_sources,model,generated_bench],
            out/f'compile_{synthesis}.log')
        simulation_log = out/f'simulation_{synthesis}.log'
        run(['vvp',binary],simulation_log)
        expected = 38804
        if f'WINDOW_TARGET_PASS checks={expected}' not in simulation_log.read_text():
            raise ValueError('窗口准备目标四态检查未完成')
        simulations.append(dict(synthesis=synthesis, passed=True, checks=expected,
                                log_sha256=digest(simulation_log)))
    if any(digest(path) != value for path,value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True,input_assumptions=[],source_sha256=hashes,
                  sequential_environment='配置更新清除窗口有效位，窗口准备边沿保存归约起点；配置步长在两次配置更新之间保持。',
                  temporal_induction=proofs,four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('WINDOW_TARGET_PASS formal=2 four_state='+str(sum(row['checks'] for row in simulations)))


if __name__ == '__main__':
    main()
