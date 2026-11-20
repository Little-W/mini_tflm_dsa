#!/usr/bin/env python3
"""用生产 DMA 和两个完整向量引擎逐周期比较全部公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def output_names(source):
    header = source.split(') (', 1)[1].split(');', 1)[0]
    direction = None
    result = []
    for token in header.split(','):
        token = token.strip()
        if token.startswith(('input ', 'output ')):
            direction = token.split()[0]
        match = re.search(r'(\w+)\s*(?:\[[^\]]+\]\s*)*$', token)
        if match and direction == 'output':
            result.append(match[1])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e03a7421')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--bus-width', type=int, default=64)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overlay = out/'sources'
    overlay.mkdir(exist_ok=True)
    directories = ('rtl/common', 'rtl/npu/conv', 'rtl/npu/dma', 'test/vector_engine', 'test/monitors')
    for relative in directories:
        shutil.copytree(ROOT/relative, overlay/relative, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    extra = Path('test/conv_npu/simulator.vlt')
    (overlay/extra).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/extra, overlay/extra)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    original = subprocess.check_output(['git', 'show', revision+':'+str(SOURCE)], cwd=ROOT, text=True)
    reference = original[:original.index('endmodule')+len('endmodule')]
    reference = reference.replace('module vector_engine #(', 'module vector_engine_reference #(', 1)
    (overlay/'rtl/npu/conv/vector_engine_reference.sv').write_text(reference+'\n')
    outputs = output_names(original)
    declarations, checks, bindings = [], [], []
    arrays = {'dma_range_base': '[31:0]', 'dma_range_end': '[32:0]'}
    for name in outputs:
        other = 'comparison_'+name
        bindings.append('.'+name+'('+other+')')
        if name in arrays:
            declarations.append('logic '+arrays[name]+' '+other+' [4];')
            checks.append('for (int lane=0;lane<4;lane++) assert('+name+'[lane] === '+other+
                          '[lane]) else $fatal(1,"公开输出 '+name+' 不同");')
        else:
            dtype = 'conv_im2col_pkg::conv_cfg_t' if name == 'dma_conv_cfg' else 'logic [$bits('+name+')-1:0]'
            declarations.append(dtype+' '+other+';')
            checks.append('assert('+name+' === '+other+') else $fatal(1,"公开输出 '+name+' 不同");')
    block = '\n'.join(declarations)+'''
  vector_engine_reference #(.TILE(TILE),.DMA_SIZE(DMA_SIZE),.PE_COUNT(PE_COUNT),.BUS_WIDTH(BUS_WIDTH))
  comparison_engine ('''+','.join(bindings)+''',.*);
  always_ff @(posedge clk) begin
    if (rst_n) begin
'''+ '\n'.join(checks)+'''
    end
  end
'''
    top = overlay/'test/vector_engine/vector_engine_dma_top.sv'
    top_source = top.read_text()
    marker = '  vector_engine #(.TILE(TILE),.DMA_SIZE(DMA_SIZE),.PE_COUNT(PE_COUNT),.BUS_WIDTH(BUS_WIDTH)) engine(.*);'
    if top_source.count(marker) != 1:
        raise RuntimeError('向量测试顶层的引擎实例数量不同')
    top.write_text(top_source.replace(marker, marker+'\n'+block, 1))
    run = overlay/'test/vector_engine/run.py'
    command = [sys.executable, str(run), '--out', str(out/'numeric'), '--verilator', args.verilator,
               '--bus-width', str(args.bus_width), '--pes', '8', '--jobs', '1', '--xilinx']
    with (out/'run.log').open('w') as stream:
        subprocess.run(command, cwd=overlay, stdout=stream, stderr=subprocess.STDOUT, check=True)
    numeric = json.loads((out/'numeric/summary.json').read_text())
    summary = {'passed': all(item['passed'] for item in numeric['runs']),
               'reference_revision': revision, 'public_outputs_compared': outputs,
               'all_outputs_checked_each_clock': True,
               'bus_width': args.bus_width, 'numeric': numeric['runs'],
               'source_sha256': {str(SOURCE): digest(ROOT/SOURCE),
                                 str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__).resolve())},
               'comparison_top_sha256': digest(top), 'reference_engine_sha256': hashlib.sha256(reference.encode()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': summary['passed'], 'public_output_ports': len(outputs),
                      'totals': [item['totals'] for item in numeric['runs']]}), flush=True)


if __name__ == '__main__':
    main()
