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
from requant_test_utils import controller_module

ROOT = Path(__file__).resolve().parents[2]


def block_span(source):
    """从通道起点声明读取到保存有效通道数的时序块之前。"""
    controller = controller_module(source)
    offset = source.index(controller)
    # 注释与字符串保持原长度，结构位置可以直接用于原文切片。
    code = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                  lambda match: re.sub(r'[^\n]', ' ', match[0]), controller, flags=re.S)
    first = re.search(r'\blogic\s*\[\s*31\s*:\s*0\s*\]\s*lane_start_cur\s*;', code)
    if first is None:
        raise ValueError('量化控制模块缺少通道起点声明')
    assignment = re.search(r'\blane_need_q\s*<=', code[first.end():])
    if assignment is None:
        raise ValueError('量化控制模块缺少有效通道数保存语句')
    before_assignment = code[first.end():first.end() + assignment.start()]
    blocks = list(re.finditer(r'\balways(?:_ff)?\s*@', before_assignment))
    if len(blocks) != 1:
        raise ValueError('有效通道数保存语句需要对应一个独立时序块')
    return offset + first.start(), offset + first.end() + blocks[0].start()


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


def local_helpers(source, block, suffix):
    """复制算术块实际调用的完整辅助模块，并隔离两份定义的名称。"""
    controller = controller_module(source)
    definitions = {}
    for match in re.finditer(r'^module\s+(\w+)\b.*?^endmodule\b', source, re.M | re.S):
        if match[0] != controller:
            definitions[match[1]] = match[0]
    required = set()
    pending = [block]
    while pending:
        content = pending.pop()
        for name, definition in definitions.items():
            if name not in required and re.search(r'\b' + re.escape(name) + r'\b', content):
                required.add(name)
                pending.append(definition)
    text = '\n'.join(definitions[name] for name in sorted(required))
    for name in sorted(required, key=len, reverse=True):
        pattern = r'\b' + re.escape(name) + r'\b'
        block = re.sub(pattern, name + '_' + suffix, block)
        text = re.sub(pattern, name + '_' + suffix, text)
    return block, text, sorted(required)


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
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-rev', default='2297cb12')
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    source_root = args.source_root.resolve()
    candidate = (source_root / relative).read_text()
    helper = source_root / 'rtl/common/parallel_prefix_add.sv'
    reference_path = args.reference_root.resolve() / relative if args.reference_root else None
    reference = reference_path.read_text() if reference_path else \
        read_rtl_source(args.reference_rev + ':' + relative, cwd=ROOT, text=True)
    fragments = {name: local_helpers(source, arithmetic(source), name)
                 for name, source in [('reference', reference), ('candidate', candidate)]}
    summary = {'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
               'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
               'local_helper_modules': {name: item[2] for name, item in fragments.items()},
               'common_helper_modules': re.findall(r'^module\s+(\w+)\b', helper.read_text(), re.M),
               'synthesis_definitions': ['SYNTHESIS=1'],
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
        for name, (block, definitions, _) in fragments.items():
            text += header('tail_' + name, reg_width, lanes) + block + '\nendmodule\n' + definitions + '\n'
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
        script.write_text('read_slang -DSYNTHESIS=1 --top tail_compare ' + shlex.quote(str(path)) + ' ' + shlex.quote(str(helper)) +
                          '\nhierarchy -check -top tail_compare\n'
                          'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                          'prep -top tail_compare -flatten\nchformal -lower\nopt -full\n'
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
    if (source_root / relative).read_text() != candidate or \
            hashlib.sha256(helper.read_bytes()).hexdigest() != summary['helper_sha256']:
        raise RuntimeError('验证期间源文件发生变化')
    if reference_path is not None and reference_path.read_text() != reference:
        raise RuntimeError('验证期间参考源码发生变化')
    summary['passed'] = all(item['passed'] for item in summary['runs'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
