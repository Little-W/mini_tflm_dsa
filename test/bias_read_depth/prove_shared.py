#!/usr/bin/env python3
"""从实际控制器证明共享条件，并比较完整偏置加载器的状态和存储操作。"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from common import ROOT, REFERENCE, BUFFER, WRAPPER, CONTROL, HELPER, HELPERS, digest, snapshot, abstract_storage, abstract_wrapper

PROFILES = [(4, 32, 1, 1), (8, 32, 8, 3), (16, 32, 12, 4),
            (16, 64, 29, 32), (16, 64, 32, 64)]


def run(out, name, commands, success):
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=240)
    text = log.read_text()
    if result.returncode or success not in text:
        raise RuntimeError(text[-7000:])
    match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
    return {'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log),
            'equivalent_bits': int(match[1]) if match else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out / 'source', args.reference)
    source = (ROOT / CONTROL).read_text()
    assert source.count('endmodule') == 1
    control = out / 'control_observer.sv'
    control.write_text(source.replace('endmodule', '''
  // 命令消费阶段的索引关系由实际状态更新保证。
  always_comb begin
    if (state == S_CMD) assert(current_block_idx == load_block_idx);
  end
endmodule'''))
    models = {}
    for label in ['reference', 'current']:
        models[label] = []
        for name, transform in [(WRAPPER, abstract_wrapper), (BUFFER, abstract_storage)]:
            path = out / label / Path(name).name
            path.parent.mkdir(exist_ok=True)
            path.write_text(transform((out / 'source' / label / name).read_text()))
            models[label].append(path)
        models[label].append(out / 'source' / label / CONTROL)
        models[label].extend(out / 'source' / label / name for name in HELPERS)
    report = {'passed': False, 'inputs': inputs, 'external_input_assumptions': [],
              'invariant': 'state == S_CMD implies current_block_idx == load_block_idx',
              'invariant_initial_reset': True,
              'load_hit_consumption': 'load_block_valid and load_block_bank are consumed only in S_CMD',
              'memory_return': 'common arbitrary 64-bit data in every cycle',
              'memory_state_relation': 'same initial memory and equal read/write ports',
              'profiles': []}
    for size, bus, count, groups in PROFILES:
        folder = out / f's{size}_b{bus}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        options = f'-GSIZE={size} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups}'
        invariant = run(folder, 'invariant', [
            f'read_slang --top bias_loader_ctrl {options} {shlex.quote(str(control))} '
            f'{shlex.quote(str(out / "source" / "current" / HELPER))}',
            'prep -top bias_loader_ctrl -flatten', 'async2sync', 'opt -full', 'chformal -lower',
            'sat -seq 4 -tempinduct -maxsteps 16 -set-at 1 rst_n 0 -prove-asserts -verify'],
            'SUCCESS')
        commands = []
        hidden = ['ctrl_load_block_valid', 'ctrl_load_block_bank',
                  'u_ctrl.load_block_valid', 'u_ctrl.load_block_bank',
                  'u_buffer.load_block_valid', 'u_buffer.load_block_bank', 'u_buffer.load_window_hit']
        for label, sources in models.items():
            commands += [f'read_slang --top bias_loader {options} ' +
                         ' '.join(shlex.quote(str(path)) for path in sources),
                         'prep -top bias_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         'rename -hide ' + ' '.join('bias_loader/' + name for name in hidden),
                         f'rename bias_loader {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 12', 'equiv_status -assert']
        comparison = run(folder, 'equivalence', commands, 'Equivalence successfully proven')
        row = {'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count, 'GROUP_BLOCKS_MAX': groups,
               'control_invariant': invariant, 'complete_loader_equivalence': comparison, 'passed': True}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
