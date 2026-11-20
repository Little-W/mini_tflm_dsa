#!/usr/bin/env python3
"""综合完整向量引擎并记录舍入与限幅的资源和组合路径。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref')
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    folder = ROOT/'rtl/npu/conv'
    changed = ('vector_engine.sv', 'vector_round_shift.sv')
    packages = [folder/'conv_im2col_pkg.sv', folder/'vector_engine_pkg.sv']
    files = packages+[p for p in sorted(folder.glob('*.sv')) if p not in packages and p.name not in changed]
    cases = {}
    for label in (('reference', 'current') if args.reference_ref else ('current',)):
        sources = list(files)
        for name in changed:
            source = folder/name
            if label == 'reference':
                destination = out/('reference_'+name)
                destination.write_bytes(read_rtl_source(args.reference_ref+':'+str(source.relative_to(ROOT)), cwd=ROOT))
                source = destination
            sources.append(source)
        cases[label] = {'top': 'vector_engine', 'sources': list(map(str, sources)),
                        'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                                    '-GBUS_WIDTH=64', '-GTILE=16', '-GPE_COUNT=8'],
                        'configuration': 'TILE16 PE8 BUS64 XILINX_FPGA'}
    configuration = out/'cases.json'
    configuration.write_text(json.dumps(cases, indent=2)+'\n')
    command = [sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
               '--case-config', str(configuration), '--cases', *cases, '--out', str(out/'results')]
    if args.lock_file:
        command.extend(['--lock-file', str(args.lock_file)])
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
