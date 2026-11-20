#!/usr/bin/env python3
"""使用实际 Xilinx LUT 模型比较 IA 加载器的所有公开输出。"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from models import prepare_models

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='75f9862e')
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model, info = prepare_models(out)
    verilator = shutil.which(args.verilator)
    if verilator is None:
        raise RuntimeError('Cannot locate Verilator: ' + args.verilator)
    wrapper = out / 'verilator_fpga'
    wrapper.write_text('#!' + sys.executable + '\nimport os, sys\n' +
                       'args = sys.argv[1:]\n' +
                       "if '--getenv' not in args and '--version' not in args:\n" +
                       "    args += ['-DXILINX_FPGA=1', " + repr(str(model)) + ']\n' +
                       'os.execv(' + repr(verilator) + ', [' + repr(verilator) + '] + args)\n')
    wrapper.chmod(0o755)
    subprocess.run([sys.executable, str(ROOT / 'test/ia_timing/run_interface.py'),
                    '--out', str(out), '--reference-rev', args.reference_rev,
                    '--verilator', str(wrapper), '--cases', 'prefetch_ordered', 'grouped32'],
                   cwd=ROOT, check=True)
    summary = out / 'summary.json'
    data = json.loads(summary.read_text())
    data['primitive_models'] = info
    data['fpga_primitives_enabled'] = True
    summary.write_text(json.dumps(data, indent=2) + '\n')


if __name__ == '__main__':
    main()
