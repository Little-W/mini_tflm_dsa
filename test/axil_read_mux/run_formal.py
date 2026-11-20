#!/usr/bin/env python3
"""检查 AXI-Lite 读回选择与共享银行配置的完整状态等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/axi_top/npu_axil_reg_if.sv'
PACKAGE = ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c7088884')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    for label, content in (('reference', reference), ('current', current)):
        (out / f'{label}.sv').write_text(content)
    profiles = [
        ('default', {}),
        ('production', {'AXI_DATA_BITS': 64, 'CONV_IS_CAPABLE': 1,
                        'VECTOR_ENGINE_CAPABLE': 1, 'PS_CAPS': 17825823,
                        'SHARED_BANK_BYTES': 8192, 'SHARED_TOTAL_BYTES': 57344,
                        'SHARED_IA_BANK_MASK': 6}),
        ('count_width1', {'PS_CAPS': 16, 'SHARED_BANK_BYTES': 2048,
                          'SHARED_TOTAL_BYTES': 18432, 'SHARED_IA_BANK_MASK': 2}),
        ('count_width3', {'PS_CAPS': 16, 'SHARED_BANK_BYTES': 4096,
                          'SHARED_TOTAL_BYTES': 36864, 'SHARED_IA_BANK_MASK': 130}),
        ('count_width4', {'PS_CAPS': 16, 'SHARED_BANK_BYTES': 8192,
                          'SHARED_TOTAL_BYTES': 65536, 'SHARED_IA_BANK_MASK': 32770}),
        ('count_width5', {'PS_CAPS': 16, 'SHARED_BANK_BYTES': 2048,
                          'SHARED_TOTAL_BYTES': 16384, 'SHARED_IA_BANK_MASK': 2147483650}),
        ('wide_data', {'AXIL_DATA_WIDTH': 64, 'AXIL_ADDR_WIDTH': 20,
                       'PS_CAPS': 16, 'SHARED_BANK_BYTES': 8192,
                       'SHARED_TOTAL_BYTES': 57344, 'SHARED_IA_BANK_MASK': 4294967295}),
        ('small_address', {'AXIL_ADDR_WIDTH': 14, 'CONV_CAPABLE': 0,
                           'VECTOR_ENGINE_CAPABLE': 0, 'MATRIX_SIZE': 4}),
    ]
    results = []
    for name, parameters in profiles:
        flags = ' '.join(f'-G{key}=' + (f"32'h{value:08x}" if value >= (1 << 31) else str(value))
                         for key, value in parameters.items())
        commands = []
        for label in ('reference', 'current'):
            commands += [
                f'read_slang --top npu_axil_reg_if {flags} {PACKAGE} {out / (label + ".sv")}',
                'prep -top npu_axil_reg_if -flatten', 'async2sync', 'opt_clean',
                f'rename npu_axil_reg_if {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current proof', 'hierarchy -top proof',
                     'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = out / f'{name}.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = out / f'{name}.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        content = log.read_text()
        assert 'Equivalence successfully proven' in content
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', content)
        result = {'name': name, 'parameters': parameters, 'passed': True,
                  'equivalent_bits': int(match[1]),
                  'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        results.append(result)
        print(json.dumps(result), flush=True)
    assert current == (ROOT / SOURCE).read_text()
    report = {'passed': True, 'reference': args.reference, 'profiles': results,
              'inputs_constrained': False, 'all_public_outputs_compared': True,
              'common_internal_state_and_signals_compared': True,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'package_sha256': hashlib.sha256(PACKAGE.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
