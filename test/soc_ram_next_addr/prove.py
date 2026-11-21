#!/usr/bin/env python3
"""对实际地址推进函数证明全部地址、size 与 burst 的二态等价。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from common import ROOT, REFERENCE, WIDTHS, HELPER_PROFILES, digest, snapshot, miter, helper_miter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    functions, inputs = snapshot(out / 'inputs', args.reference, args.source_root, args.reference_root)
    model = out / 'miter.sv'
    model.write_text(miter(*functions))
    rows = []
    for aw in WIDTHS:
        script = out / f'aw{aw}.ys'
        log = script.with_suffix('.log')
        script.write_text(f'read_verilog -formal -sv {model}\n'
                          f'chparam -set AW {aw} address_miter\n'
                          'prep -top address_miter -flatten\n'
                          'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        rows.append({'address_width': aw, 'result_width': aw + 1, 'passed': True,
                     'log_sha256': digest(log)})
    helper_model = out / 'helper_miter.sv'
    helper_model.write_text(helper_miter(args.reference, args.source_root, args.reference_root))
    helper_rows = []
    for aw, dw, dp in HELPER_PROFILES:
        script = out / f'aw{aw}_dw{dw}_dp{dp}.ys'
        log = script.with_suffix('.log')
        script.write_text(f'read_verilog -formal -sv {helper_model}\n'
                          f'chparam -set AW {aw} -set DW {dw} -set DP {dp} helper_miter\n'
                          'prep -top helper_miter -flatten\n'
                          'sat -verify -prove correct 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        helper_rows.append({'address_width': aw, 'data_width': dw, 'memory_words': dp,
                            'passed': True, 'log_sha256': digest(log)})
    report = {'passed': True, 'inputs': inputs, 'domain': 'all two-state inputs',
              'input_assumptions': [], 'all_size_and_burst_encodings': True,
              'extended_overflow_address_bit_compared': True,
              'miter_sha256': digest(model), 'profiles': rows,
              'helper_miter_sha256': digest(helper_model), 'helper_profiles': helper_rows}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'profiles': len(rows), 'helper_profiles': len(helper_rows)}))


if __name__ == '__main__':
    main()
