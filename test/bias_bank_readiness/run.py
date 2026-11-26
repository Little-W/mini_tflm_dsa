#!/usr/bin/env python3
"""验证双存储体偏置资格的全部输入、四态传播和完整缓冲区状态。"""
from __future__ import annotations

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
WIDTHS = (1, 2, 3, 5, 8, 17, 32)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='1470a963')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([ROOT/'rtl/npu/loaders/bias_bank_readiness.sv'], ROOT)
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    proof = out/'proof.sv'
    proof.write_text('''module proof #(parameter W=5)(
input wire[2*W-1:0] bank_block,input wire[W-1:0] current_block,cache_block,
input wire[1:0] resident,input wire cache_valid,cache_bank,active_bank,is_mode,
output wire equivalent,output wire[1:0] actual,expected);
wire[1:0][W-1:0] bank=bank_block;
wire equal;
add_equal #(.p_width(W),.p_preserve_bits(1)) u_reference(
 .i_a(cache_block),.i_b(bank[active_bank]),.i_target(current_block),.i_carry_in(1'b0),.o_equal(equal));
assign expected[0]=cache_valid && cache_bank==active_bank && equal;
assign expected[1]=resident[active_bank] && (is_mode || expected[0]);
bias_bank_readiness #(.p_block_width(W)) u_current(
 .i_bank_block(bank),.i_current_block(current_block),.i_cache_block(cache_block),
 .i_resident(resident),.i_cache_valid(cache_valid),.i_cache_bank(cache_bank),
 .i_active_bank(active_bank),.i_is_mode(is_mode),.o_cache_hit(actual[0]),.o_bias_valid(actual[1]));
assign equivalent=(actual===expected);
endmodule
''')
    tb = out/'tb.sv'
    tb.write_text('''module tb;
parameter W=5;
localparam BITS=4*W+6;
reg[BITS-1:0] values,known;
wire equal;wire[1:0] actual,expected;
proof #(.W(W)) u_test(.bank_block(values[0+:2*W]),.current_block(values[2*W+:W]),
 .cache_block(values[3*W+:W]),.resident(values[4*W+:2]),.cache_valid(values[4*W+2]),
 .cache_bank(values[4*W+3]),.active_bank(values[4*W+4]),.is_mode(values[4*W+5]),
 .equivalent(equal),.actual(actual),.expected(expected));
integer seed=32'h650b4291,choice,checks=0;
task check;
begin #1;checks++;if(actual!==expected)$fatal(1,"W=%0d values=%h expected=%b actual=%b",W,values,expected,actual);end
endtask
initial begin
 for(integer sample=0;sample<8192;sample++)begin
  for(integer bit_index=0;bit_index<BITS;bit_index++)begin
   choice=$unsigned($random(seed))%(sample<4096?2:4);
   case(choice)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  end
  check();
 end
 for(integer sample=0;sample<64;sample++)begin
  for(integer bit_index=0;bit_index<BITS;bit_index++)known[bit_index]=$random(seed);
  for(integer bit_index=0;bit_index<BITS;bit_index++)begin
   values=known;values[bit_index]=1'bx;check();values=known;values[bit_index]=1'bz;check();
  end
 end
 $display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
    rows = []
    for width in WIDTHS:
        for synthesis in (False, True):
            name = f'w{width}_s{int(synthesis)}'
            definitions = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            script, log = out/(name+'.ys'), out/(name+'_formal.log')
            script.write_text('read_slang --top proof '+shlex.join([
                *(definitions or ['-USYNTHESIS', '-UXILINX_FPGA']), f'-GW={width}',
                *map(str, sources), str(proof)])+'\nsetattr -mod -unset keep_hierarchy\n'+
                'setattr -unset keep_hierarchy\nprep -top proof -flatten\ncheck -assert\n'+
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                    cwd=ROOT, check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
            assert 'SUCCESS!' in log.read_text()
            binary = out/(name+'.vvp')
            with (out/(name+'_compile.log')).open('w') as stream:
                subprocess.run(['iverilog', '-g2012', '-s', 'tb', f'-Ptb.W={width}', *definitions,
                    '-o', str(binary), *map(str, sources), str(proof), str(tb)], check=True,
                    stdout=stream, stderr=subprocess.STDOUT)
            result = subprocess.check_output(['vvp', binary], text=True, timeout=180)
            (out/(name+'_four_state.log')).write_text(result)
            match = re.search(r'PASS comparisons=(\d+)', result)
            assert match
            binary.unlink()
            rows.append({'width': width, 'synthesis': synthesis, 'inputs_constrained': False,
                'passed': True, 'four_state_comparisons': int(match[1]), 'formal_log_sha256': digest(log)})
            print(name, 'PASS', match[1], flush=True)
    subprocess.run([sys.executable, ROOT/'test/bias_scalar_word_match/run.py', '--full-only',
        '--reference', reference, '--out', out/'complete_buffer'], check=True, cwd=ROOT)
    complete = json.loads((out/'complete_buffer/summary.json').read_text())
    assert complete['passed'] and len(complete['complete_modules']) == 8
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in sources}
    report = {'passed': True, 'reference_commit': reference, 'source_sha256': hashes,
        'profiles': rows, 'four_state_comparisons': sum(row['four_state_comparisons'] for row in rows),
        'complete_buffer': complete, 'test_sha256': digest(Path(__file__))}
    (out/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
