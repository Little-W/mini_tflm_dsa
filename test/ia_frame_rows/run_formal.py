#!/usr/bin/env python3
"""证明提前保存的尾组行数及完整 IA 加载器逐周期等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source, read_rtl_source_group as read_rtl_source, shared_ia_options

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders')/(name+'.sv')
           for name in ('ia_loader_ctrl', 'ia_loader', 'ia_loader_cache_mgr')]
CASES = {
    'loader_production': ('ia_loader', ['-GSIZE=16', '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=32',
                                      '-GCOUNT_WIDTH=29', '-GORDERED_JOB=1']),
    'loader_full_count': ('ia_loader', ['-GSIZE=16', '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=32',
                                      '-GORDERED_JOB=1']),
    'loader_generic': ('ia_loader', ['-GSIZE=16', '-GBUS_WIDTH=32', '-GCACHE_BLOCKS=4',
                                   '-GCOUNT_WIDTH=8', '-GORDERED_JOB=0']),
    'loader_small_cache': ('ia_loader', ['-GSIZE=16', '-GBUS_WIDTH=32', '-GCACHE_BLOCKS=4',
                                  '-GCOUNT_WIDTH=8', '-GORDERED_JOB=1']),
    'loader_small': ('ia_loader', ['-GSIZE=16', '-GBUS_WIDTH=32', '-GCACHE_BLOCKS=4',
                                 '-GCOUNT_WIDTH=5', '-GORDERED_JOB=1']),
    'ctrl3': ('ia_loader_ctrl', ['-GSIZE=3', '-GBUS_WIDTH=32', '-GCACHE_BLOCKS=4']),
    'ctrl16': ('ia_loader_ctrl', ['-GSIZE=16', '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=32', '-GCOUNT_WIDTH=29']),
    'ctrl32': ('ia_loader_ctrl', ['-GSIZE=32', '-GBUS_WIDTH=64', '-GCACHE_BLOCKS=4']),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7ff66a59')
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(CASES))
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    snapshots_unchanged = True
    previous_path = out/'summary.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    for label in ('reference', 'current'):
        folder = out/label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in SOURCES:
            text = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT, text=True)
                    if label == 'reference' else read_current_source(ROOT/relative))
            if relative.name == 'ia_loader_ctrl.sv':
                # 完整保留派生复用数的各位，逐位检查其组合对应关系。
                text = text.replace('  count_t r_cur;', '  (* keep *) count_t r_cur;', 1)
            if label == 'reference' and relative.name == 'ia_loader_ctrl.sv' and 'cfg_frame_rows_last' not in text:
                # 闲置端口只用于对应新增输入；参考控制逻辑仍使用原始组合公式。
                text = text.replace('    // ---- 顶层握手 ----',
                                    "    input logic [31:0] cfg_frame_rows_last = '0,\n\n"
                                    '    // ---- 顶层握手 ----', 1)
            if label == 'reference' and relative.name == 'ia_loader.sv' and 'frame_last_rows_q' not in text:
                # 同名观察表达式直接描述已保存配置的尾组行数。
                observer = '''
    localparam int p_formal_count_width = COUNT_WIDTH > 0 ? COUNT_WIDTH : 1;
    (* keep *) wire [31:0] frame_last_rows_q =
        (32'(p_formal_count_width'(ia_reuse_num_act)) << LOG2_SIZE) -
        (32'(SIZE) - 32'(rsp_rows_last_tile));
'''
                declaration = '    logic [REG_WIDTH-1:0] rsp_rows_last_tile;'
                if declaration not in text:
                    raise RuntimeError('Cannot locate the saved tail-row declaration')
                text = text.replace(declaration, declaration+'\n'+observer, 1)
                text, count = re.subn(r'(\.rsp_rows_last_tile\s*\(rsp_rows_last_tile\),)',
                                      r'\1\n        .cfg_frame_rows_last(frame_last_rows_q),', text, count=1)
                if count != 1:
                    raise RuntimeError('Cannot connect the reference observation expression')
            path = folder/relative.name
            snapshots_unchanged &= path.exists() and path.read_text() == text
            path.write_text(text)
            snapshots[label].append(path)
    common = sorted(p for p in (ROOT/'rtl/common').glob('*') if p.suffix in ('.sv', '.v'))
    source_hashes = {str(p): digest(ROOT/p) for p in SOURCES}
    common_hashes = {str(p.relative_to(ROOT)): digest(p) for p in common}
    common_matches = previous.get('common_sha256') == common_hashes
    if 'common_sha256' not in previous:
        common_matches = subprocess.run(['git', 'diff', '--quiet', args.reference_rev, '--',
                                         'rtl/common'], cwd=ROOT).returncode == 0
    reusable = args.resume and snapshots_unchanged and common_matches and \
        previous.get('source_sha256') == source_hashes and \
        previous.get('reference_rev') == args.reference_rev
    old_runs = {row['name']: row for row in previous.get('runs', [])}
    summary = {'reference_rev': args.reference_rev, 'source_input_constraints': False,
               'source_sha256': source_hashes, 'common_sha256': common_hashes,
               'reference_observation': 'frame_last_rows_q', 'runs': []}
    for name in args.cases:
        top, options = CASES[name]
        commands = []
        for label in ('reference', 'current'):
            selected_options = (shared_ia_options(options, snapshots[label][1].read_text())
                                if top == 'ia_loader' else options)
            commands += [f'read_slang --top {top} '+' '.join(selected_options)+' '+
                         ' '.join(shlex.quote(str(p)) for p in snapshots[label]+common),
                         f'prep -top {top} -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename {top} {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = out/(name+'.ys')
        log = out/(name+'.log')
        script_text = '\n'.join(commands)+'\n'
        old = old_runs.get(name, {})
        cached = reusable and old.get('passed') and script.exists() and \
            script.read_text() == script_text and log.exists() and old.get('log_sha256') == digest(log)
        script.write_text(script_text)
        if cached:
            returncode = 0
        else:
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                         '--worker', str(script)], cwd=ROOT,
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            returncode = result.returncode
        text = log.read_text()
        count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'name': name, 'top': top, 'options': options,
               'passed': returncode == 0 and 'Equivalence successfully proven' in text,
               'equivalent_bits': int(count[1]) if count else None, 'log_sha256': digest(log)}
        summary['runs'].append(row)
        summary['passed'] = all(x['passed'] for x in summary['runs'])
        (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'Full-state comparison did not complete: {log}')
    if source_hashes != {str(p): digest(ROOT/p) for p in SOURCES}:
        raise RuntimeError('Sources changed during verification')


if __name__ == '__main__':
    main()
