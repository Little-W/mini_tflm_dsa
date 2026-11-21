#!/usr/bin/env python3
"""从完整 RTL 提取输入槽就绪寄存器，证明全部控制状态下的更新关系。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
CONTROL_INPUTS = ('state', 'compute_index', 'active', 'global_pool', 'spatial',
                  'window_response_fire', 'read_bank', 'writeback_busy',
                  'dw_shared_inflight', 'in_bounds', 'dw_group_last')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='dde5e7c9')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = args.source_root.resolve()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT)
    current = (root / SOURCE).read_bytes()
    packages = [root / 'rtl/npu/conv/conv_im2col_pkg.sv', root / 'rtl/npu/conv/vector_engine_pkg.sv']
    dependencies = packages + [p for p in sorted((root / 'rtl/npu/conv').glob('*.sv'))
                               if p not in packages and p != root / SOURCE]
    dependencies += [p for p in sorted((root / 'rtl/common').iterdir()) if p.suffix in ('.v', '.sv')]
    hashes = {str(p.relative_to(root)): digest(p) for p in [root / SOURCE, *dependencies]}
    registered_relation = None
    if b'compute_group_last_q' in current:
        proof_folder = out / 'group_consumption'
        subprocess.run([sys.executable, Path(__file__).with_name('run_group_formal.py'),
            '--source-root', root, '--out', proof_folder, '--profiles',
            '4:4:0:0', '16:8:0:0', '16:8:1:0', '16:16:0:1'], cwd=ROOT, check=True)
        registered_relation = json.loads((proof_folder / 'summary.json').read_text())
        if not registered_relation['passed'] or registered_relation['source_sha256'][str(SOURCE)] != hashes[str(SOURCE)]:
            raise RuntimeError('通道组结束条件与当前源码的关系尚未证明')
        # 先证明真实状态机中的消费关系，再用该恒等式检查任意输入槽控制组合。
        expression = b'(state == EXECUTE_COMMIT && compute_group_last_q && !global_pool && spatial)'
        replacement = b'(state == EXECUTE_COMMIT && compute_index + 32\'(PE_COUNT) >= active && !global_pool && spatial)'
        if current.count(expression) != 1:
            raise RuntimeError('输入槽释放表达式与已证明的消费位置不一致')
        current = current.replace(expression, replacement, 1)
    snapshots = {}
    for name, data in [('reference', reference), ('candidate', current)]:
        path = out / (name + '.sv')
        path.write_bytes(data)
        snapshots[name] = path
    report = dict(passed=False, reference=args.reference,
                  reference_sha256=hashlib.sha256(reference).hexdigest(), source_sha256=hashes,
                  scope='完整 RTL 的输入槽更新关系；提交判断使用已由真实状态机证明的寄存值恒等式',
                  registered_relation_proof=registered_relation,
                  arbitrary_control_inputs=list(CONTROL_INPUTS), inputs_constrained=False, runs=[])
    for tile, pes, storage, quant in ((4, 4, 0, 0), (16, 8, 0, 0), (16, 8, 1, 0), (16, 16, 0, 1)):
        name = f't{tile}_p{pes}_s{storage}_q{quant}'
        folder = out / name
        folder.mkdir(exist_ok=True)
        options = (f'-GTILE={tile} -GPE_COUNT={pes} -GBUS_WIDTH=64 -GWINDOW_LANES=8 '
                   f'-GSHARED_STORAGE_ENABLE={storage} -GSHARED_QUANT_ENABLE={quant}')
        commands = []
        for label, source in snapshots.items():
            commands += ['read_slang --top vector_engine ' + options + ' ' +
                         shlex.join(map(str, [*dependencies, source])),
                         'prep -top vector_engine -flatten',
                         'delete -output vector_engine/w:*',
                         'expose vector_engine/w:input_ready',
                         'expose -input ' + ' '.join('vector_engine/w:' + x for x in CONTROL_INPUTS),
                         'setattr -unset keep vector_engine/w:* vector_engine/c:*',
                         'opt_clean -purge', 'memory_map', 'async2sync', 'opt -full',
                         'check -assert', f'write_json {shlex.quote(str(folder / (label + ".json")))}',
                         f'rename vector_engine {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate comparison', 'hierarchy -top comparison',
                     'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = dict(name=name, passed=result.returncode == 0 and 'Equivalence successfully proven' in text,
                   compared_bits=int(match[1]) if match else None,
                   script_sha256=digest(script), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'输入槽就绪更新检查未完成：{log}')
    if hashes != {str(p.relative_to(root)): digest(p) for p in [root / SOURCE, *dependencies]}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
