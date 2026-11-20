#!/usr/bin/env python3
"""证明完整尺寸和块坐标下的量化尾部通道、行数计算。"""
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


def block_span(source):
    module = source.index('module vec_requant_full #(')
    first = source.index('    lane_start_cur =', module)
    end = source.index('    reuse_group_base_row =', first)
    return first, end


def arithmetic(source):
    first, end = block_span(source)
    match = re.search(r'  localparam bit p_direct_tail_count\s*=.*?;', source, re.S)
    parameter = match[0] if match else ''
    return parameter + '\n' + '''
      logic [31:0] lane_start_cur, row_start_cur;
      logic [31:0] lane_remaining_cur, rows_remaining_cur;
      always_comb begin
    ''' + source[first:end] + '\nend\n'


def unchanged_logic(source):
    first, end = block_span(source)
    source = source[:first] + source[end:]
    source = re.sub(r'  localparam bit p_direct_tail_count\s*=.*?;', '', source, flags=re.S)
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    return re.sub(r'\s+', '', source)


def header(name, reg_width, lanes):
    return f'''module {name} #(
      parameter int REG_WIDTH={reg_width}, VLEN={lanes},
      parameter int VLEN_SHIFT=$clog2(VLEN),
      parameter int VLEN_CNT_W=(VLEN<=1)?1:$clog2(VLEN+1),
      parameter int TILE_CNT_W=(REG_WIDTH<16)?REG_WIDTH:16
    ) (
      input logic [31:0] m_r, k_r,
      input logic [TILE_CNT_W-1:0] tile_col, tile_row,
      output logic [31:0] lane_need_cur, rows_need_cur
    );\n'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='2e17beb')
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
    unchanged = unchanged_logic(candidate) == unchanged_logic(reference)
    assert unchanged, 'Source differs outside the proved tail-count logic.'
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'unchanged_outside_tail_count_logic': unchanged,
               'inputs': 'Both 32-bit dimensions and both complete tile coordinates are unconstrained.',
               'runs': []}
    configurations = [(32, 1), (32, 2), (32, 3), (32, 7), (32, 16), (32, 32),
                      (32, 1024), (32, 65536), (32, 131072), (32, 1073741824),
                      (16, 16), (4, 16), (16, 65536), (64, 16), (64, 131072)]
    for reg_width, lanes in configurations:
        folder = out / f'width{reg_width}_lanes{lanes}'
        folder.mkdir(exist_ok=True)
        text = ''
        for name, source in [('reference', reference), ('candidate', candidate)]:
            text += header('tail_' + name, reg_width, lanes) + arithmetic(source) + '\nendmodule\n'
        text += header('tail_compare', reg_width, lanes) + '''
          logic [31:0] reference_lanes, reference_rows;
          tail_reference u_reference(.*, .lane_need_cur(reference_lanes), .rows_need_cur(reference_rows));
          tail_candidate u_candidate(.*);
          always_comb assert({reference_lanes,reference_rows} == {lane_need_cur,rows_need_cur});
          endmodule
        '''
        path = folder / 'comparison.sv'
        path.write_text(text)
        script = folder / 'run.ys'
        script.write_text('read_slang --top tail_compare ' + shlex.quote(str(path)) +
                          '\nprep -top tail_compare -flatten\nchformal -lower\nopt -full\n'
                          'sat -set-def-inputs -prove-asserts -verify\n')
        with (folder / 'formal.log').open('w') as log:
            completed = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                       stdout=log, stderr=subprocess.STDOUT)
        log = (folder / 'formal.log').read_text()
        result = {'reg_width': reg_width, 'lanes': lanes, 'compared_bits': 64,
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
