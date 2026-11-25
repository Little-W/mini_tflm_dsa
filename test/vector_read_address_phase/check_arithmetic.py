#!/usr/bin/env python3
"""验证完整地址求和、四态结果，以及自动推断后的器件功能模型。"""
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
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage


BENCH = r'''
module tb;
reg clk=0;
reg [31:0] base, offset;
reg [15:0] channel;
wire [33:0] actual [2], expected [2];
integer checks=0;
reg [31:0] random_state=32'h619a72e5;
for(genvar preserve=0;preserve<2;preserve++) begin:g_preserve
  vector_read_address_add #(.p_preserve_groups(preserve)) u_current(
      .clk(clk),.i_base(base),.i_offset(offset),.i_channel(channel),
      .o_address(actual[preserve][31:0]),.o_carry(actual[preserve][33:32]));
  vector_read_address_add_reference #(.p_preserve_groups(preserve)) u_reference(
      .clk(clk),.i_base(base),.i_offset(offset),.i_channel(channel),
      .o_address(expected[preserve][31:0]),.o_carry(expected[preserve][33:32]));
end
function automatic [31:0] next_random(input [31:0] value);
  reg [31:0] intermediate;
  begin
    intermediate=value^(value<<13);
    intermediate=intermediate^(intermediate>>17);
    next_random=intermediate^(intermediate<<5);
  end
endfunction
initial begin
  for(integer sample=0;sample<100000;sample=sample+1) begin
    random_state=next_random(random_state);base=random_state;
    random_state=next_random(random_state);offset=random_state;
    random_state=next_random(random_state);channel=random_state[15:0];
    case(sample%13)
      0:base[sample%32]=1'bx;
      1:offset[sample%32]=1'bz;
      2:channel[sample%16]=1'bx;
      3:base='x;
      4:offset='z;
      5:channel='z;
      6:begin base=32'hffffffff;offset=32'hffffffff;channel=16'hffff;end
      7:begin base=32'h0003ffff;offset=32'h1;channel=16'hffff;end
      8:begin base=32'h7fffffff;offset=32'h1;channel=16'h0;end
      default:begin end
    endcase
    #1;
    for(integer preserve=0;preserve<2;preserve=preserve+1) begin
      if(actual[preserve]!==expected[preserve])
        $fatal(1,"address differs sample=%0d preserve=%0d",sample,preserve);
      checks=checks+1;
    end
    clk=~clk;
  end
  $display("ADDRESS_ARITHMETIC_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-revision', default='7ddc0d8d')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = ['rtl/npu/conv/vector_read_address_add.sv', 'rtl/common/parallel_prefix_add.sv']
    paths = [source / name for name in relative]
    hashes = {name: digest(source / name) for name in relative}
    reference = '\n'.join(subprocess.check_output(
        ['git', 'show', args.reference_revision + ':' + name], cwd=ROOT, text=True)
        for name in relative)
    for name in ('vector_read_address_add', 'parallel_prefix_add'):
        reference = re.sub(r'\b' + name + r'\b', name + '_reference', reference)
    simulation = out / 'four_state.sv'
    simulation.write_text(('\n'.join(path.read_text() for path in paths) + '\n' +
        reference + '\n' + BENCH).replace('parameter int unsigned', 'parameter integer')
        .replace('localparam int unsigned', 'localparam integer'))
    for command, label in ((['iverilog', '-g2012', '-s', 'tb', '-o', out / 'four_state.vvp', simulation], 'build'),
                           (['vvp', out / 'four_state.vvp'], 'four_state')):
        with (out / (label + '.log')).open('w') as stream:
            subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
    if 'ADDRESS_ARITHMETIC_PASS checks=200000' not in (out / 'four_state.log').read_text():
        raise RuntimeError('四态地址比较未完成')
    # 参考测量模块采用完整数学和，并保存与被测模块相同的输入、输出边沿。
    wrapper = ROOT / 'test/vector_read_address_phase/measure.sv'
    top = 'vector_read_address_measure'
    expected = out / 'expected.sv'
    expected.write_text(wrapper.read_text().split('  vector_read_address_add u_address')[0] +
        "  assign address={2'b00,base_q}+{2'b00,offset_q}+{18'd0,channel_q};\nendmodule\n")
    config = out / 'cases.json'
    config.write_text(json.dumps({'address': dict(top=top, sources=[str(wrapper), str(paths[0])],
        options=['-DSYNTHESIS=1'], configuration='完整34位地址和；输入输出各保存一拍')}, indent=2)+'\n')
    with (out / 'synthesis.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--source-root', str(source), '--case-config', str(config),
                        '--cases', 'address', '--out', str(out / 'synthesis')],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    mapped = out / 'synthesis/address/mapped.json'
    metrics = json.loads((mapped.parent / 'metrics.json').read_text())
    if not metrics['resources']['dsp48e1']:
        raise RuntimeError('地址部分和未推断 DSP')
    commands = [
        'read_slang --top '+top+' '+str(expected), 'prep -top '+top+' -flatten',
        'memory_map', 'async2sync', 'opt -full', 'rename -hide w:*',
        'rename -top reference', 'design -stash reference', 'read_json '+str(mapped),
        'delete =A:blackbox', 'read_verilog -overwrite +/xilinx/cells_sim.v',
        'hierarchy -top '+top, 'rename -top current', 'setattr -mod -unset keep_hierarchy',
        'flatten -wb', 'proc', 'memory_map', 'async2sync', 'opt -full',
        'rename -hide w:*', 'design -stash current',
        'design -copy-from reference -as reference reference',
        'design -copy-from current -as current current',
        'equiv_make reference current proof', 'hierarchy -top proof',
        'equiv_simple -seq 3', 'opt_clean', 'equiv_induct -seq 5', 'equiv_status -assert',
    ]
    script, log = out / 'mapped_equivalence.ys', out / 'mapped_equivalence.log'
    script.write_text('\n'.join(commands)+'\n')
    stage = run_stage(script, log, dict(os.environ))
    if not re.search(r'Of those cells 34 are proven and 0 are unproven', log.read_text()):
        raise RuntimeError('未完成全部34位地址和的时序证明')
    if hashes != {name: digest(source / name) for name in relative}:
        raise RuntimeError('检查期间源码发生变化')
    summary = dict(passed=True, source_sha256=hashes, reference_revision=args.reference_revision,
        four_state_comparisons=200000, mapped_output_bits=34, unbounded_equivalence=True,
        mapped_sha256=digest(mapped), resources=metrics['resources'],
        longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
        equivalence_stage=stage)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('ADDRESS_ARITHMETIC_TEST_PASS four_state=200000 mapped_output_bits=34')


if __name__ == '__main__':
    main()
