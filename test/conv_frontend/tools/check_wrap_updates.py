#!/usr/bin/env python3
"""验证回绕标志的全部状态、并发事件、保持条件与四态优先级。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from check_state_context import Statements

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = Path('rtl/npu/conv/conv_im2col_frontend.sv')
FLAGS = {'row_wrap_q': 0, 'tap_wrap_q': 1, 'incoming_tap_wrap_q': 2}
INPUTS = {
    'rst_n': 1, 'cfg_valid': 1, 'cfg_ready': 1, 'tile_commit': 1,
    'commit_invalid': 1, 'commit_fast': 1, 'commit_position_update': 1,
    'state': 27, 'stream_response_error': 1, 'stream_operation_accept': 1,
    'chunk_reaches_end': 1, 'row_last_q': 1, 'past_active_q': 1,
    'active_after_chunk': 1, 'group_end_o_equal': 1, 'coordinate_address_valid': 1,
    'row_wrap': 1, 'tap_wrap': 1, 'p_fast_valid': 1, 'decode_index': 32,
    'p0': 32, 'tap0': 32, 'kernel_shape_o_valid': 1, 'kernel_w': 16,
    'row_wrap_candidate': 6, 'tap_wrap_candidate': 9, 'saved_value': 3,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(text, start, stop):
    begin = text.index(start)
    return text[begin:text.index(stop, begin)]


def model(current, reference):
    marker = '  // 保存前端配置、描述符和坐标状态。'
    reference_block = section(reference, marker, '  // 解码计数与坐标运算')
    counts = dict.fromkeys(FLAGS, 0)

    def selected(text):
        match = re.fullmatch(r'(\w+)\s*<=\s*(.*);', text, re.S)
        if match is None or match[1] not in FLAGS:
            return ''
        name, value = match[1], match[2].strip()
        counts[name] += 1
        bit = FLAGS[name]
        return f'begin expected_write[{bit}] = 1\'b1; expected_value[{bit}] = {value}; end'

    tree = Statements(reference_block[reference_block.index('begin'):],
                      select_assignment=selected).statement()
    current_block = section(current, marker, '  // 解码计数与坐标运算')

    def remaining(text):
        match = re.match(r'(\w+)\s*<=', text)
        if match is not None and match[1] in FLAGS:
            return ''
        return '' if text == ';' else text

    retained = [Statements(block[block.index('begin'):], select_assignment=remaining).statement()
                for block in (reference_block, current_block)]
    if retained[0] != retained[1]:
        raise ValueError('其余配置、描述符及坐标寄存器的赋值或条件发生变化')
    for name, count in counts.items():
        if count != len(re.findall(r'\b' + name + r'\s*<=', reference_block)):
            raise ValueError((name, count))
    candidate = section(current, '  // 各运行来源先准备回绕值与写入资格',
                        '  // 输出行和卷积核回绕标志保持原有写入边沿')
    actual_block = section(current, '  // 输出行和卷积核回绕标志保持原有写入边沿', marker)
    actual_counts = dict.fromkeys(FLAGS, 0)

    def actual_selected(text):
        match = re.fullmatch(r'(\w+)\s*<=\s*(.*);', text, re.S)
        if match is None or match[1] not in FLAGS:
            return ''
        name, value = match[1], match[2].strip()
        actual_counts[name] += 1
        bit = FLAGS[name]
        return f'begin actual_write[{bit}] = 1\'b1; actual_value[{bit}] = {value}; end'

    actual_tree = Statements(actual_block[actual_block.index('begin'):],
                             select_assignment=actual_selected).statement()
    for name in FLAGS:
        if actual_counts[name] != 2 or len(re.findall(r'\b' + name + r'\s*<=', current)) != 2:
            raise ValueError('回绕标志必须仅由已检查的寄存器组写入：' + name)
    helper = re.search(r'\(\* keep_hierarchy = "yes" \*\)\s*module conv_im2col_wrap_update_select\b.*?endmodule',
                       current, re.S).group()
    decl = ',\n'.join('input logic ' + (f'[{width-1}:0] ' if width > 1 else '') + name
                       for name, width in INPUTS.items())
    text = 'module proof(\n' + decl + ''',
output logic equivalent,
output logic [2:0] actual_write, expected_write, actual_value, expected_value
);
import conv_im2col_frontend_pkg::*;
typedef struct packed {logic invalid,fast,output_position_update;} tile_t;
typedef struct packed {logic[15:0] kernel_w;} cfg_t;
tile_t committing_tile;
cfg_t c;
assign committing_tile={commit_invalid,commit_fast,commit_position_update};
assign c=kernel_w;
logic[3:0][5:0] wrap_update_candidate;
logic[2:0] wrap_write,wrap_value;
logic wrap_cfg_fire,wrap_descriptor_check,wrap_running_state;
''' + candidate + '''
always_comb begin
 expected_write='0;
 expected_value=saved_value;
''' + tree + '''
end
always_comb begin
 actual_write='0;
 actual_value=saved_value;
''' + actual_tree + '''
end
assign equivalent={actual_write,actual_value}==={expected_write,expected_value};
endmodule
''' + helper + '\n'
    return text, counts


def bench():
    bits = sum(INPUTS.values())
    padded = (bits + 31) // 32 * 32
    declarations = '\n'.join('logic ' + (f'[{width-1}:0] ' if width > 1 else '') + name + ';'
                              for name, width in INPUTS.items())
    names = ','.join(INPUTS)
    ports = ','.join('.' + name + '(' + name + ')' for name in INPUTS)
    return f'''module tb;
{declarations}
logic equivalent;
logic[2:0]actual_write,expected_write,actual_value,expected_value;
logic[{padded-1}:0]sample_bits;
integer sample,word_index,seed=32'h64b9021f;
proof u_dut({ports},.equivalent(equivalent),.actual_write(actual_write),
 .expected_write(expected_write),.actual_value(actual_value),.expected_value(expected_value));
initial begin
 for(sample=0;sample<8192;sample=sample+1)begin
  for(word_index=0;word_index<{padded//32};word_index=word_index+1)
   sample_bits[word_index*32+:32]=$random(seed);
  if(sample<{2*bits})begin
   sample_bits[(sample/2)%{bits}]=sample%2?1'bz:1'bx;
  end else if(sample%4==1)sample_bits[$unsigned($random(seed))%{bits}]=1'bx;
  else if(sample%4==2)sample_bits[$unsigned($random(seed))%{bits}]=1'bz;
  {{{names}}}=sample_bits[{bits-1}:0];
  if(sample%4==0)state=27'b1<<(sample%27);
  #1;
  if(equivalent!==1'b1)$fatal(1,"Wrap mismatch sample=%0d actual=%b/%b expected=%b/%b",sample,actual_write,actual_value,expected_write,expected_value);
 end
 $display("WRAP_UPDATES_FOUR_STATE_PASS samples=8192");
 $finish;
end
endmodule
'''


def run(command, path):
    with path.open('w') as stream:
        subprocess.run([str(value) for value in command], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, reference, out = args.source_root.resolve(), args.reference_source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, original = root / FRONTEND, reference / FRONTEND
    package = root / 'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    hashes = {str(path): digest(path) for path in (source, original, package)}
    text, counts = model(source.read_text(), original.read_text())
    model_path, script, testbench, binary = [out / name for name in ('proof.sv','proof.ys','tb.sv','tb.vvp')]
    model_path.write_text(text)
    script.write_text(f'read_slang --top proof {package} {model_path}\n'
                      'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                      'prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1\n')
    run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py','--worker',script],out/'formal.log')
    testbench.write_text(bench())
    run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb','-o',binary,package,model_path,testbench],out/'compile.log')
    run([shutil.which('vvp') or 'vvp',binary],out/'four_state.log')
    binary.unlink()
    if hashes != {name:digest(name) for name in hashes}:
        raise RuntimeError('验证期间源文件发生变化')
    result={'passed':True,'free_input_bits':sum(INPUTS.values()),'output_bits':6,
            'four_state_checks':8192,'original_write_count':counts,'source_sha256':hashes,
            'checker_sha256':digest(__file__), 'parser_sha256':digest(Path(__file__).with_name('check_state_context.py')),
            'formal_log_sha256':digest(out/'formal.log'),'four_state_log_sha256':digest(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('WRAP_UPDATES_PASS',out/'summary.json',flush=True)


if __name__=='__main__':
    main()
