#!/usr/bin/env python3
"""证明实际偏置准备阶段互斥，并检查每个缓存数据位的下一状态。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/bias_loader_buffer.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_update(text):
    begin = text.index('  for (genvar pair_i = 0; pair_i < READS_PER_BLOCK; pair_i++) begin : gen_ws_pair')
    end = text.index('  for (genvar lane = 0; lane < SIZE; lane++) begin : gen_ws_lane', begin)
    return begin, end, text[begin:end]


def controller_observer(text):
    """保留实际控制 RTL，仅将公开输出变为内部信号以消除未使用的数据存储。"""
    begin = text.index(') (') + 3
    end = text.index('\n);', begin)
    inputs, outputs = [], []
    for line in text[begin:end].splitlines():
        if line.strip().startswith('output '):
            outputs.append(re.sub(r'\boutput\s+', '', line).rstrip().rstrip(',') + ';')
        else:
            inputs.append(line)
    ports = '\n'.join(inputs).rstrip().rstrip(',')
    result = text[:begin] + '\n' + ports + '\n);\n' + '\n'.join(outputs) + text[end+3:]
    observer = '''
  always_comb begin
    if (rst_n && !init_cfg) begin
      assert(!(ws_loading && ws_busy));
      assert(!(ws_loading && ws_response_valid));
    end
  end
'''
    return result.replace('\nendmodule', observer + '\nendmodule', 1)


def next_state_module(reference, current):
    header = '''module bias_cache_next_state #(
    parameter integer SIZE=16, GROUP_BLOCKS_MAX=32,
    parameter integer RAM_WIDTH=64, RAM_BYTES=8,
    parameter integer READS_PER_BLOCK=(SIZE+1)/2,
    parameter integer BANK_WORDS=GROUP_BLOCKS_MAX*READS_PER_BLOCK,
    parameter integer BANK_ADDR_W=(BANK_WORDS>1)?$clog2(BANK_WORDS):1,
    parameter integer RAM_ADDR_W=BANK_ADDR_W+1,
    parameter integer READ_INDEX_W=(READS_PER_BLOCK>1)?$clog2(READS_PER_BLOCK):1
) (
    input logic init_cfg, load_start, is_mode, ws_loading, ws_response_valid,
    input logic [31:0] load_word_row_q,
    input logic [RAM_ADDR_W-1:0] write_address,
    input logic [RAM_BYTES-1:0] write_enable,
    input logic [READ_INDEX_W-1:0] ws_response_index,
    input logic [RAM_WIDTH-1:0] write_data, read_data,
    input logic [RAM_WIDTH-1:0] previous [READS_PER_BLOCK]
);
    logic [RAM_WIDTH-1:0] reference_next [READS_PER_BLOCK], current_next [READS_PER_BLOCK];
    logic [RAM_WIDTH-1:0] ws_cache_update_data;
    assign ws_cache_update_data = ws_loading ? write_data : read_data;
'''
    sections = []
    for name, text in [('reference', reference), ('current', current)]:
        block = cache_update(text)[2]
        block = block.replace('gen_ws_pair', name + '_pair').replace('gen_ws_byte', name + '_byte')
        block = block.replace('always_ff @(posedge clk) begin',
            'always_comb begin\n        ' + name + '_next[pair_i][byte_i*8 +: 8] = previous[pair_i][byte_i*8 +: 8];')
        block = block.replace('ws_cache_pair', name + '_next').replace('<=', '=')
        sections.append(block)
    footer = '''
    // 该互斥关系由同一源码中的实际控制器独立完成时序归纳证明。
    always_comb assume(!(ws_loading && ws_response_valid));
    for (genvar pair_i=0; pair_i<READS_PER_BLOCK; pair_i++) begin : g_compare
        always_comb assert(reference_next[pair_i] == current_next[pair_i]);
    end
endmodule
'''
    return header + '\n'.join(sections) + footer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='d8fb9581')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    c_start, c_end, _ = cache_update(current)
    r_start, r_end, _ = cache_update(reference)
    current_control = current[:c_start] + current[c_end:]
    current_control = current_control.replace('  logic [RAM_WIDTH-1:0] ws_cache_update_data;\n', '')
    current_control = current_control.replace(
        '  // DMA 装载与存储返回分别占用准备阶段，所有偏置数据对共用数据源选择。\n'
        '  assign ws_cache_update_data = ws_loading ? write_data : read_data;\n', '')
    if current_control != reference[:r_start] + reference[r_end:]:
        raise ValueError('Control, storage or public output logic differs')
    observer = out / 'control.sv'
    observer.write_text(controller_observer(current))
    next_state = out / 'next_state.sv'
    next_state.write_text(next_state_module(reference, current))
    memory = ROOT / 'rtl/common/REGFILE.v'
    report = {'passed': False, 'reference_ref': args.reference,
              'source_sha256': digest(ROOT / SOURCE), 'memory_sha256': digest(memory),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'control_and_storage_identical': True, 'external_inputs_constrained': False,
              'initial_reset_applied': True, 'runs': []}

    def run(name, commands):
        script, log_path = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log_path.open('w') as log:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=180)
        text = log_path.read_text()
        if result.returncode or 'SUCCESS' not in text:
            raise RuntimeError(text[-10000:])
        return {'passed': True, 'log_sha256': digest(log_path)}

    for size, bus, count, groups in [(4, 32, 1, 1), (16, 32, 12, 4),
                                    (16, 64, 28, 32), (16, 64, 32, 1)]:
        name = f's{size}_b{bus}_c{count}_g{groups}'
        control = run(name + '_control', [
            f'read_slang --top bias_loader_buffer -GSIZE={size} -GBUS_WIDTH={bus} '
            f'-GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups} ' +
            ' '.join(shlex.quote(str(path)) for path in (observer, memory)),
            'prep -top bias_loader_buffer -flatten', 'async2sync', 'opt -full',
            'memory_map', 'opt -full', 'chformal -lower',
            'sat -seq 3 -tempinduct -maxsteps 8 -set-at 1 rst_n 0 -prove-asserts -verify',
        ])
        update = run(name + '_update', [
            f'read_slang --top bias_cache_next_state -GSIZE={size} -GGROUP_BLOCKS_MAX={groups} ' +
            shlex.quote(str(next_state)),
            'prep -top bias_cache_next_state -flatten', 'opt -full', 'chformal -lower',
            'sat -set-assumes -prove-asserts -verify -show-inputs',
        ])
        item = {'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count, 'GROUP_BLOCKS_MAX': groups,
                'control_mutual_exclusion': control, 'cache_next_state': update,
                'cache_bits': ((size+1)//2)*64, 'passed': True}
        report['runs'].append(item)
        print(json.dumps(item), flush=True)
    if report['source_sha256'] != digest(ROOT / SOURCE) or report['memory_sha256'] != digest(memory):
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
