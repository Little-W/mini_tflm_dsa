#!/usr/bin/env python3
"""比较完整偏置缓冲区的银行末端保存和全部状态、同步存储端口。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUFFER = 'rtl/npu/loaders/bias_loader_buffer.sv'
HELPER = 'rtl/common/parallel_prefix_add.sv'
sys.path.insert(0, str(ROOT / 'test'))

spec = importlib.util.spec_from_file_location('bias_storage_formal', ROOT / 'test/bias_read_depth/common.py')
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arithmetic_reference(source):
    start = source.index('  logic [CNT_W:0] bank_end_i_a, bank_end_i_b, bank_end_o_sum;')
    end = source.index('  logic                         load_bank_q;', start)
    result = source[:start] + source[end:]
    marker = 'bank_end_q[load_bank] <= bank_end_o_sum;'
    assert result.count(marker) == 1
    return result.replace(marker, "bank_end_q[load_bank] <= {1'b0, load_block_idx} + {1'b0, load_blocks_count};")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, default=ROOT / BUFFER)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.candidate.read_text()
    reference = arithmetic_reference(current)
    helper = out / 'parallel_prefix_add.sv'
    helper.write_bytes((ROOT / HELPER).read_bytes())
    for label, content in [('reference', reference), ('current', current)]:
        (out / f'{label}.sv').write_text(storage.abstract_storage(content))
    report = {'passed': False, 'reference_definition': 'same buffer with ordinary extended-width addition for bank_end_q',
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'source': BUFFER, 'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'helper_source': HELPER, 'helper_sha256': digest(helper),
              'input_assumptions': [], 'memory_return': 'same arbitrary 64-bit input each cycle',
              'storage_ports_compared': ['read enable', 'read address', 'write enable', 'write address', 'write data', 'byte mask'],
              'profiles': []}
    for size, bus, count, groups in [(4, 32, 1, 1), (8, 32, 8, 3), (16, 32, 12, 4),
                                    (16, 64, 29, 32), (16, 64, 32, 64)]:
        for shared in [0, 1]:
            stem = f's{size}_b{bus}_c{count}_g{groups}_shared{shared}'
            script, log = out / (stem + '.ys'), out / (stem + '.log')
            commands = []
            for label in ['reference', 'current']:
                commands += [f'read_slang --top bias_loader_buffer -GSIZE={size} -GBUS_WIDTH={bus} '
                             f'-GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups} -Gp_share_load_index={shared} '
                             f'{shlex.quote(str(out / (label + ".sv")))} {shlex.quote(str(helper))}',
                             'prep -top bias_loader_buffer -flatten', 'memory_map', 'async2sync', 'opt_clean',
                             f'rename bias_loader_buffer {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                         '--worker', str(script)], cwd=ROOT, stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=180)
            text = log.read_text()
            assert result.returncode == 0 and 'Equivalence successfully proven' in text, text[-6000:]
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            row = {'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count, 'GROUP_BLOCKS_MAX': groups,
                   'p_share_load_index': shared, 'passed': True, 'equivalent_bits': int(match[1]),
                   'script_sha256': digest(script), 'log_sha256': digest(log)}
            report['profiles'].append(row)
            print(json.dumps(row), flush=True)
    assert current == args.candidate.read_text() and digest(ROOT / HELPER) == digest(helper)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
