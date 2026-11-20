#!/usr/bin/env python3
"""在已证明的来源归属条件下，比较全部输入存储项的写使能和十六位数据。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def section(source):
    first = source.index('  for (genvar bank=0;bank<BUS_BYTES;bank++) begin : g_input_bank_data') if \
        'begin : g_input_bank_data' in source else source.index('  for (genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input_write')
    last = source.index('  // 每拍的连续偏置字', first)
    return first, last


def normalized(source):
    source = source.replace('  logic signed [15:0] input_bank_data [BUS_BYTES];\n', '')
    first, last = section(source)
    source = source[:first] + source[last:]
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S))


def fragment(source, label, bus, tile, dma):
    first, last = section(source)
    block = source[first:last]
    update = 'always_ff @(posedge clk) if (rst_n && write_enable) input_buf[entry] <= write_value;'
    assert block.count(update) == 1
    block = block.replace(update, 'assign o_enable[entry] = rst_n && write_enable;\n'
                          '    assign o_data[entry] = write_enable ? write_value : 16\'sd0;')
    block = block.replace("assign input_buf[entry]=16'sd0;", "assign o_enable[entry]=1'b0;\n"
                          "      assign o_data[entry]=16'sd0;")
    ports = f'''#(parameter int BUS_WIDTH={bus}, TILE={tile}, DMA_SIZE={dma},
  BUS_BYTES=BUS_WIDTH/8, INPUT_INDEX_W=$clog2(DMA_SIZE), BUS_SHIFT=$clog2(BUS_BYTES),
  POOL_ROW_W=INPUT_INDEX_W>BUS_SHIFT ? INPUT_INDEX_W-BUS_SHIFT : 1)(
  input logic rst_n, global_pool,
  input vector_engine_pkg::vector_engine_cfg_t c,
  input logic dma_input_write_valid[BUS_BYTES],
  input logic [INPUT_INDEX_W-1:0] dma_input_write_index[BUS_BYTES],
  input logic signed [15:0] rd_data[BUS_BYTES],
  input logic [3:0] window_bank_valid,
  input logic [INPUT_INDEX_W-1:0] window_bank_index[4],
  input logic signed [15:0] window_bank_data[4],
  input logic [BUS_BYTES-1:0] pool_bank_valid,
  input logic [POOL_ROW_W-1:0] pool_bank_row[BUS_BYTES],
  input logic signed [15:0] pool_bank_data[BUS_BYTES],
  output logic [DMA_SIZE-1:0] o_enable,
  output logic signed [15:0] o_data[DMA_SIZE],
  output logic o_owner
);
  import vector_engine_pkg::*;
  logic spatial;
  logic signed [15:0] input_bank_data[BUS_BYTES];
  logic [BUS_BYTES-1:0] dma_valid_packed;
  assign spatial=c.op<=MINPOOL_S8;
  for(genvar lane=0;lane<BUS_BYTES;lane++) assign dma_valid_packed[lane]=dma_input_write_valid[lane];
  assign o_owner=(!global_pool || spatial) && ((dma_valid_packed==0) || !spatial) &&
    ((window_bank_valid==0) || (spatial && !global_pool)) &&
    ((pool_bank_valid==0) || (spatial && global_pool));
'''
    return 'module input_write_' + label + ports + block + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3587da43')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    source = ROOT / 'rtl/npu/conv/vector_engine.sv'
    current = source.read_text()
    reference = read_rtl_source(revision + ':rtl/npu/conv/vector_engine.sv', cwd=ROOT, text=True)
    assert normalized(current) == normalized(reference)
    report = {'reference_revision': revision, 'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'outside_input_write_unchanged': True,
              'condition': 'Source ownership proven by actual vector control and actual window queue.',
              'scope': 'All address bits, all INT16 data bits, every storage write enable; state recurrence unchanged.',
              'runs': []}
    configs = [(32,16,64), (64,16,64), (128,16,64), (64,32,128), (64,3,16), (32,1,4)]
    packages = [ROOT / 'rtl/npu/conv' / name for name in ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv')]
    for bus, tile, dma in configs:
        folder = out / f'bus{bus}_tile{tile}_dma{dma}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, content in (('reference', reference), ('current', current)):
            path = folder / (label + '.sv')
            path.write_text(fragment(content, label, bus, tile, dma))
            commands += ['read_slang --top input_write_' + label + ' ' +
                         ' '.join(shlex.quote(str(p)) for p in packages + [path]),
                         'prep -top input_write_' + label + ' -flatten', 'opt -full',
                         'design -stash ' + label]
        commands += ['design -copy-from reference input_write_reference',
                     'design -copy-from current input_write_current',
                     'miter -equiv -make_outputs -flatten input_write_reference input_write_current comparison',
                     'hierarchy -top comparison', 'opt -full',
                     'sat -verify -set gold_o_owner 1 -set gate_o_owner 1 -prove trigger 0 -show-inputs -show-outputs']
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=90)
        if result.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log) + '\n' + log.read_text()[-6000:])
        report['runs'].append({'bus_width': bus, 'tile': tile, 'dma_size': dma, 'passed': True,
                               'compared_stored_bits': 16*min(dma,2*tile),
                               'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    assert current == source.read_text()
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
