#!/usr/bin/env python3
"""证明完整三十二位配置和偏移下的参数突发长度计算。"""
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


def arithmetic(source):
    full = source.split('module vec_requant_full #(', 1)[1]
    if 'logic     [32:0] remaining_words;' in full:
        declarations = '\n'.join(re.findall(r'^  logic[^;]*\b(?:remaining_words|chunk_words|burst_word_index)\s*;', full, re.M))
        first = full.index('  assign remaining_words =')
        end = full.index(';', full.index('  assign chunk_need_cur =', first)) + 1
        return declarations + '\n' + full[first:end]
    chunk = re.search(r'\bchunk_need_cur\s*=.*?;', full, re.S)[0]
    burst = re.search(r'\bburst_len_cur\s*=.*?;', full, re.S)[0]
    return 'always_comb begin\n' + chunk + '\n' + burst + '\nend\n'


def ports():
    return '''(
        input logic [31:0] quant_need_load_r, load_offset,
        output logic [31:0] chunk_need_cur,
        output logic [7:0] burst_len_cur
    );\n'''


def unchanged_logic(source):
    if 'logic     [32:0] remaining_words;' in source:
        source = re.sub(r'^  logic[^;]*\b(?:remaining_words|chunk_words|burst_word_index)\s*;',
                        '', source, flags=re.M)
        first = source.index('  assign remaining_words =')
        end = source.index(';', source.index('  assign chunk_need_cur =', first)) + 1
        source = source[:first] + source[end:]
    else:
        source = re.sub(r'\bchunk_need_cur\s*=.*?;', '', source, count=1, flags=re.S)
        source = re.sub(r'  always_comb begin\s+burst_len_cur\s*=.*?;\s+end',
                        '', source, count=1, flags=re.S)
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    return re.sub(r'\s+', '', source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='1d7c6b7')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    candidate = (ROOT / relative).read_text()
    reference = read_rtl_source(args.reference_rev + ':' + relative, cwd=ROOT, text=True)
    unchanged_outside_length = unchanged_logic(candidate) == unchanged_logic(reference)
    assert unchanged_outside_length, 'Source differs outside the proved length logic.'
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'unchanged_outside_length_logic': unchanged_outside_length,
               'inputs': 'Both 32-bit input words are unconstrained, including unsigned limits and every underflow case.',
               'runs': []}
    configurations = [(32, 1), (64, 1), (32, 3), (64, 3), (96, 3),
                      (32, 16), (64, 16), (96, 16), (128, 16),
                      (32, 32), (64, 256), (128, 1024)]
    for bus, lanes in configurations:
        folder = out / f'bus{bus}_lanes{lanes}'
        folder.mkdir(exist_ok=True)
        text = ''
        for name, source in [('reference', reference), ('candidate', candidate)]:
            text += 'module length_' + name + ports()
            text += f'localparam int BUS_WIDTH={bus}, VLEN={lanes}, VLEN_CNT_W=(VLEN<=1)?1:$clog2(VLEN+1);\n'
            text += arithmetic(source) + '\nendmodule\n'
        text += 'module length_compare ' + ports() + '''
            logic [31:0] reference_chunk;
            logic [7:0] reference_burst;
            length_reference u_reference(.*, .chunk_need_cur(reference_chunk), .burst_len_cur(reference_burst));
            length_candidate u_candidate(.*);
            always_comb assert({reference_chunk,reference_burst} == {chunk_need_cur,burst_len_cur});
            endmodule
        '''
        path = folder / 'comparison.sv'
        path.write_text(text)
        script = folder / 'run.ys'
        script.write_text('read_slang --top length_compare ' + shlex.quote(str(path)) +
                          '\nprep -top length_compare -flatten\nchformal -lower\nopt -full\n'
                          'sat -set-def-inputs -prove-asserts -verify\n')
        with (folder / 'formal.log').open('w') as log:
            completed = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                       stdout=log, stderr=subprocess.STDOUT)
        log = (folder / 'formal.log').read_text()
        result = {'bus_width': bus, 'lanes': lanes, 'compared_bits': 40,
                  'passed': completed.returncode == 0 and 'SUCCESS!' in log}
        summary['runs'].append(result)
        print(json.dumps(result), flush=True)
        if not result['passed']:
            print(log[-10000:])
            raise SystemExit(1)
    summary['passed'] = all(item['passed'] for item in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
