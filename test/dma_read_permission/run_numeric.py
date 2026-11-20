#!/usr/bin/env python3
"""使用官方 FPGA 原语检查完整 DMA 的 BUS32 和 BUS64 事务行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    names = ('LUT1', 'LUT6', 'LUT6_2', 'MUXF7', 'MUXF8', 'DSP48E1', 'FDRE', 'CARRY4')
    models = []
    for name in names:
        match = re.search(r'^module ' + name + r'\b.*?^endmodule', library.read_text(), re.M | re.S)
        if match is None:
            raise RuntimeError('Cannot find primitive model: ' + name)
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', match[0], flags=re.S))
    model = out / 'xilinx_primitives.sv'
    model.write_text('\n\n'.join(models) + '\n')
    executable = shutil.which(args.verilator)
    if executable is None:
        raise RuntimeError('Cannot locate Verilator: ' + args.verilator)
    common = [str(path) for path in sorted((ROOT / 'rtl/common').glob('*.sv'))]
    wrapper = out / 'verilator_xilinx'
    wrapper.write_text('#!' + sys.executable + '\nimport os, sys\n' +
                       'arguments = sys.argv[1:]\n' +
                       'common = ' + repr(common) + '\n' +
                       'arguments += [path for path in common if path not in arguments]\n' +
                       'command = ' + repr([executable, '-DSYNTHESIS=1', '-DXILINX_FPGA=1', str(model)]) +
                       ' + arguments\nos.execv(command[0], command)\n')
    wrapper.chmod(0o755)
    sources = ('rtl/npu/dma/axi_dual_block_dma.sv', 'rtl/npu/conv/conv_axi_read_guard.sv',
               'rtl/npu/conv/conv_axi_read_mux.sv')
    hashes = {name: digest(ROOT / name) for name in sources}
    report = {'source_sha256': hashes, 'primitive_library_sha256': digest(library),
              'primitive_models_sha256': digest(model), 'runs': [], 'passed': False}
    for bus in (32, 64):
        folder = out / ('bus' + str(bus))
        command = [sys.executable, str(ROOT / 'test/dma_abort/run_read_arbiter.py'),
                   '--out', str(folder), '--verilator', str(wrapper), '--bus-width', str(bus)]
        with (out / ('bus' + str(bus) + '.log')).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        summary = folder / 'summary.json'
        data = json.loads(summary.read_text())
        if not data['passed'] or any(data['source_sha256'][name] != value for name, value in hashes.items()):
            raise RuntimeError('Verified read connection source differs')
        data['summary_sha256'] = digest(summary)
        report['runs'].append(data)
        report['passed'] = len(report['runs']) == 2 and all(row['passed'] for row in report['runs'])
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in data.items()
                          if key not in ('source_sha256', 'compile_command', 'run_command')}), flush=True)
    if hashes != {name: digest(ROOT / name) for name in sources}:
        raise RuntimeError('Read connection source changed during verification')


if __name__ == '__main__':
    main()
