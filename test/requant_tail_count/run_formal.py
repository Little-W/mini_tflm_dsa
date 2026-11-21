#!/usr/bin/env python3
"""证明完整尺寸、复用组和块坐标下的量化计数及块位置计算。"""
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
    first = source.index('  logic [31:0] lane_start_cur;', module)
    end = source.index('  // 参数就绪拍锁存', first)
    return first, end


def arithmetic(source):
    first, end = block_span(source)
    match = re.search(r'  localparam bit p_direct_tail_count\s*=.*?;', source, re.S)
    parameter = match[0] if match else ''
    return parameter + '\n' + source[first:end] + '''
      assign progress = {tile_row_inc, tile_col_inc, next_tile_row_cur, next_tile_col_cur,
                         final_tile_cur, next_same_quant_group_cur, cur_last_row_tile,
                         cur_last_col_tile, cur_last_row_in_group, step_row_in_group,
                         step_col_in_group, step_next_group};
    '''


def header(name, reg_width, lanes):
    return f'''module {name} #(
      parameter int REG_WIDTH={reg_width}, VLEN={lanes},
      parameter int VLEN_SHIFT=$clog2(VLEN),
      parameter int VLEN_CNT_W=(VLEN<=1)?1:$clog2(VLEN+1),
      parameter int TILE_CNT_W=(REG_WIDTH<16)?REG_WIDTH:16
    ) (
      input logic [31:0] m_r, k_r, ia_reuse_num_r,
      input logic is_mode_r,
      input logic [TILE_CNT_W-1:0] tile_col, tile_row, ia_reuse_mask_tile_r,
      input logic [TILE_CNT_W-1:0] last_row_tile, last_col_tile,
      output logic [31:0] lane_need_cur, rows_need_cur, group_rows_need_cur,
      output logic [31:0] quant_need_cur, quant_tile_idx_cur,
      output logic [TILE_CNT_W-1:0] reuse_group_base_row, row_offset_in_group,
      output logic [4*TILE_CNT_W+7:0] progress
    );
      typedef logic [TILE_CNT_W-1:0] tile_idx_t;
    '''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='dde5e7c9')
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
    helper = ROOT / 'rtl/common/parallel_prefix_add.sv'
    reference = read_rtl_source(args.reference_rev + ':' + relative, cwd=ROOT, text=True)
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
               'scope': 'Actual tail-count arithmetic, tile progression, group indices and all related public results.',
               'inputs': 'Complete dimensions, tile coordinates, reuse-group configuration and mode are unconstrained.',
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
        outputs = ('lane_need_cur', 'rows_need_cur', 'group_rows_need_cur', 'quant_need_cur',
                   'quant_tile_idx_cur', 'reuse_group_base_row', 'row_offset_in_group', 'progress')
        text += header('tail_compare', reg_width, lanes)
        for index, name in enumerate(outputs):
            width = '31:0' if index < 5 else ('TILE_CNT_W-1:0' if index < 7 else '4*TILE_CNT_W+7:0')
            text += f'logic [{width}] reference_{name};\n'
        ports = ', '.join(f'.{name}(reference_{name})' for name in outputs)
        text += 'tail_reference u_reference(.*, ' + ports + ');\ntail_candidate u_candidate(.*);\n'
        text += ('always_comb assert({' + ','.join('reference_' + name for name in outputs) +
                 '} == {' + ','.join(outputs) + '});\nendmodule\n')
        path = folder / 'comparison.sv'
        path.write_text(text)
        script = folder / 'run.ys'
        script.write_text('read_slang --top tail_compare ' + shlex.quote(str(path)) + ' ' + shlex.quote(str(helper)) +
                          '\nprep -top tail_compare -flatten\nchformal -lower\nopt -full\n'
                          'sat -set-def-inputs -prove-asserts -verify\n')
        with (folder / 'formal.log').open('w') as log:
            completed = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                       stdout=log, stderr=subprocess.STDOUT)
        log = (folder / 'formal.log').read_text()
        result = {'reg_width': reg_width, 'lanes': lanes, 'compared_bits': 168 + 6 * min(reg_width, 16),
                  'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                  'log_sha256': hashlib.sha256((folder / 'formal.log').read_bytes()).hexdigest(),
                  'passed': completed.returncode == 0 and 'SUCCESS!' in log}
        summary['runs'].append(result)
        print(json.dumps(result), flush=True)
        if not result['passed']:
            print(log[-10000:])
            raise SystemExit(1)
    if (ROOT / relative).read_text() != candidate or \
            hashlib.sha256(helper.read_bytes()).hexdigest() != summary['helper_sha256']:
        raise RuntimeError('验证期间源文件发生变化')
    summary['passed'] = all(item['passed'] for item in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
