#!/usr/bin/env python3
"""比较完整生产 IA 装载器的资源及寄存器之间的组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CTRL = Path('rtl/npu/loaders/ia_loader_ctrl.sv')
PARAMETERS = dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32, COUNT_WIDTH=29,
                  COMPACT_S8=0, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
                  p_dma_source_layout=1, p_shared_write_stage=1,
                  p_register_dma_request=1, p_zero_masked_write_data=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='f02e539e210161e285e595ec2271b0f1067450a6')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        control = out / (label + '_ctrl.sv')
        control.write_bytes(subprocess.check_output(['git', 'show', args.reference + ':' + str(CTRL)],
                                                     cwd=ROOT) if label == 'reference' else
                            (ROOT / CTRL).read_bytes())
        sources = resolve([ROOT / 'rtl/npu/loaders/ia_loader.sv', control], ROOT)
        hashes.update({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
        cases[label] = {
            'top': 'ia_loader', 'sources': list(map(str, sources)),
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in PARAMETERS.items()],
            'parameters': PARAMETERS, 'configuration': '完整生产输入装载器，保留全部端口',
        }
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                    '--case-config', config, '--cases', 'reference', 'current',
                    '--out', out / 'pre', '--through', 'pre_lut'], cwd=ROOT, check=True)
    report = {'reference_commit': args.reference, 'parameters': PARAMETERS,
              'source_sha256': hashes, 'cases': {}}
    for label in cases:
        mapped = out / (label + '_mapped')
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
                        '--source', out / 'pre' / label, '--out', mapped,
                        '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8',
                        '--small-lut-area-cost', '1', '--discard-abc9-temporaries'],
                       cwd=ROOT, check=True)
        report['cases'][label] = json.loads((mapped / 'metrics.json').read_text())
        report['cases'][label]['functional_verification'] = json.loads(
            (mapped / 'verification.json').read_text())
    for path, expected in hashes.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    (out / 'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
