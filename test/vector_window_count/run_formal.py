#!/usr/bin/env python3
"""证明窗口有效元素计数和接收累计值在全部输入下保持相同。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
ADDRESS = Path('rtl/npu/conv/vector_engine_address.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fragment(source, name, lanes):
    source = re.sub(r'\bp_window_lanes\b', 'WINDOW_LANES', source)
    body = f'''module {name} #(
      parameter int WINDOW_LANES={lanes}
    ) (
      input logic [WINDOW_LANES-1:0] win_rsp_mask,
      input logic [31:0] window_received,
      output logic [$clog2(WINDOW_LANES+1)-1:0] window_response_count,
      output logic [31:0] next_count
    );
    '''
    if 'window_count_tree' in source:
        for signal in ('p_window_count_width', 'p_window_count_leaves'):
            match = re.search(r'^\s*localparam\s+int\s+(?:unsigned\s+)?'+signal+r'\s*=\s*([^\n]+)',
                              source, re.M)
            if match is None:
                raise RuntimeError('缺少窗口计数信号：'+signal)
            body += 'localparam int '+signal+' = '+match[1].strip().rstrip(',;')+';\n'
        body += re.search(r'^\s*logic\b[^;\n]*\bwindow_count_tree\b[^;\n]*;',
                          source, re.M)[0]+'\n'
        first = source.index('  assign window_count_tree[0]')
        end = source.index('  always_comb begin', first)
        body += source[first:end]
        body += '''logic [31:0] window_count_i_value, window_count_i_increment, window_count_o_sum;
                   logic window_count_i_carry, unused_window_count_carry;
        '''
        for signal in ('window_count_i_value', 'window_count_i_increment', 'window_count_i_carry'):
            body += re.search(r'  assign ' + signal + r'\s*=.*?;', source, re.S)[0] + '\n'
        if 'window_count_low_sum' in source:
            first = source.index('  logic [p_window_count_width:0] window_count_low_sum;')
            end = source.index('  logic next_window_valid', first)
            body += source[first:end]
        elif 'vector_window_count_add' in source:
            body += re.search(r'\bvector_window_count_add\s*#\(.*?\)\s*u_window_count_sum\s*\(.*?\);',
                              source, re.S)[0]
        else:
            body += re.search(r'  parallel_prefix_add\s*#\(\.p_width\(32\)\) u_window_count_sum\s*\(.*?\);',
                              source, re.S)[0]
        expression = 'window_count_o_sum'
    else:
        body += re.search(r'  always_comb begin\s*window_response_count=0;.*?\n  end', source, re.S)[0]
        expression = re.search(r'window_received\s*<=\s*(window_received\+32\x27\(window_response_count\))\s*;', source)[1]
    return body + '\nassign next_count = ' + expression + ';\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = ADDRESS if (ROOT/ADDRESS).exists() else SOURCE
    current = (ROOT/current_path).read_bytes()
    reference = None
    for path in (ADDRESS, SOURCE):
        result = subprocess.run(['git', 'show', f'{args.reference}:{path}'], cwd=ROOT,
                                capture_output=True)
        if result.returncode == 0:
            reference = result.stdout
            break
    if reference is None:
        raise RuntimeError('参考提交缺少窗口接收计数模块')
    reader = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    helpers = reader['with_dependencies']([ROOT/HELPER,ROOT/'rtl/npu/conv/vector_window_count_add.sv'],ROOT)
    source_paths = [ROOT/current_path]+helpers
    hashes = {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in source_paths}
    report = dict(passed=False, reference=args.reference, source_sha256=hashes,
                  reference_sha256=digest(reference), inputs_constrained=False, runs=[])
    for lanes in (1, 3, 4, 8, 16, 31, 32):
        folder = out / f'lanes{lanes}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, data in (('reference', reference), ('candidate', current)):
            path = folder / f'{label}.sv'
            path.write_text(fragment(data.decode(), label, lanes))
            commands += ['read_slang --top ' + label + ' ' +
                         ' '.join(shlex.quote(str(p)) for p in helpers+[path]),
                         'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                         'prep -top ' + label + ' -flatten', 'opt -full', 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate comparison', 'hierarchy -top comparison',
                     'equiv_simple', 'equiv_status -assert']
        script = folder / 'run.ys'
        log = folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        row = dict(lanes=lanes, passed=result.returncode == 0 and 'Equivalence successfully proven' in text,
                   log_sha256=digest(log.read_bytes()))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(text[-8000:])
    if hashes != {str(path.relative_to(ROOT)): digest(path.read_bytes()) for path in source_paths}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
