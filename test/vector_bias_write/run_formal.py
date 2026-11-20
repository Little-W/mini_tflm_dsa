#!/usr/bin/env python3
"""使用实际偏置存储和 REGFILE 源码证明所有状态转移相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def block_span(source):
    marker = '  // 每拍的连续偏置字分配到固定分组'
    if marker in source:
        first = source.index(marker)
    else:
        first = source.index('  for (genvar entry=0;entry<TILE;entry++) begin : g_parameter_write')
    end = source.index('  // DMA 参数写入按数据字分组', first)
    return first, end


def unchanged_logic(source):
    first, end = block_span(source)
    source = source[:first] + source[end:]
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    return re.sub(r'\s+', '', source)


def fragment(source, bus, tile, dma_size):
    first, end = block_span(source)
    state = re.search(r'typedef enum logic \[5:0\].*?state_t;', source, re.S)[0]
    load = re.search(r'typedef enum logic \[2:0\].*?load_t;', source, re.S)[0]
    return f'''module bias_store #(
      parameter int BUS_WIDTH={bus}, TILE={tile}, DMA_SIZE={dma_size},
      parameter int INPUT_INDEX_W=$clog2(DMA_SIZE),
      parameter int ACTIVE_COUNT_W=$clog2(TILE+1)
    ) (
      input logic clk, rst_n,
      input logic [5:0] state,
      input logic [2:0] load_kind,
      input logic rd_raw_valid,
      input logic [INPUT_INDEX_W-1:0] rd_col_base,
      input logic [ACTIVE_COUNT_W-1:0] active,
      input logic [BUS_WIDTH-1:0] rd_raw_data,
      output logic signed [31:0] bias_buf [TILE]
    );\n''' + state + '\n' + load + '\n' + source[first:end] + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='cd0455b')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/conv/vector_engine.sv'
    candidate = (ROOT / relative).read_text()
    reference = subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT, text=True)
    unchanged = unchanged_logic(candidate) == unchanged_logic(reference)
    assert unchanged, 'Source differs outside the proved bias storage.'
    regfile = ROOT / 'rtl/common/REGFILE.v'
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'regfile_sha256': hashlib.sha256(regfile.read_bytes()).hexdigest(),
               'unchanged_outside_bias_storage': unchanged,
               'inputs': 'All state encodings, load kinds, addresses, active counts, reset values and DMA words are unconstrained.',
               'runs': []}
    configurations = [(32,16,64),(64,16,64),(96,16,64),(128,16,64),
                      (32,1,16),(64,2,16),(128,32,128),(256,3,16)]
    for bus, tile, dma_size in configurations:
        folder = out / f'bus{bus}_tile{tile}_dma{dma_size}'
        folder.mkdir(exist_ok=True)
        stages = []
        for label, source in [('reference',reference),('candidate',candidate)]:
            path = folder / (label + '.sv')
            path.write_text(fragment(source,bus,tile,dma_size))
            stages.append('read_slang --top bias_store ' + shlex.quote(str(path)) + ' ' + shlex.quote(str(regfile)) +
                          '\nprep -top bias_store -flatten\nmemory_map\nopt -full\n' +
                          'rename bias_store ' + label + '\ndesign -stash ' + label + '\n')
        script = folder / 'run.ys'
        script.write_text(''.join(stages) + '''
          design -copy-from reference -as reference reference
          design -copy-from candidate -as candidate candidate
          equiv_make reference candidate comparison
          hierarchy -top comparison
          equiv_simple
          equiv_induct -seq 2
          equiv_status -assert
        ''')
        with (folder / 'formal.log').open('w') as log:
            completed = subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],
                                       stdout=log,stderr=subprocess.STDOUT)
        log = (folder / 'formal.log').read_text()
        result = {'bus_width':bus,'tile':tile,'dma_size':dma_size,'compared_state_bits':32*tile,
                  'passed':completed.returncode==0 and 'Equivalence successfully proven!' in log}
        summary['runs'].append(result)
        print(json.dumps(result),flush=True)
        if not result['passed']:
            print(log[-12000:])
            raise SystemExit(1)
    summary['passed'] = all(item['passed'] for item in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary,indent=2) + '\n')


if __name__ == '__main__':
    main()
