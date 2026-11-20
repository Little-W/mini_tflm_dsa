#!/usr/bin/env python3
"""固定输入银行共享前后的完整向量源码和生产参数。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3587da43')
    parser.add_argument('--reduction-revision', help='同时测量指定版本的归约 DSP 实现')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    manifest = {'reference': args.reference, 'source_sha256': {}}
    names = ['conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_config_check.sv',
             'vector_writeback.sv', 'vector_round_shift.sv', 'vector_scalar_multiplier.sv',
             'vector_pe.sv', 'vector_softmax.sv', 'vector_quant_params.sv', 'vector_engine.sv']
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        sources = []
        for name in names:
            relative = 'rtl/npu/conv/' + name
            data = (subprocess.check_output(['git', 'show', args.reference + ':' + relative], cwd=ROOT)
                    if label == 'reference' else (ROOT / relative).read_bytes())
            path = folder / name
            path.write_bytes(data)
            sources.append(str(path))
            manifest['source_sha256'][label + '/' + relative] = hashlib.sha256(data).hexdigest()
        cases['vector_' + label] = {'top': 'vector_engine',
            'options': ['-D', 'SYNTHESIS=1', '-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
            'sources': sources, 'configuration': 'TILE16, BUS64, DMA_SIZE64, eight vector PEs'}
    if args.reduction_revision:
        reduced = subprocess.check_output(['git', 'show', args.reduction_revision +
            ':rtl/npu/conv/vector_engine.sv'], cwd=ROOT, text=True)
        current = (out / 'current/vector_engine.sv').read_text()
        first = current.index('  logic [31:0] reduce_sum;')
        last = current.index('  localparam int POOL_SUM_WIDTH=', first)
        reduced_first = reduced.index('  logic signed [31:0] reduce_alu_i_lhs')
        reduced_last = reduced.index('  localparam int POOL_SUM_WIDTH=', reduced_first)
        folder = out / 'combined'
        folder.mkdir(exist_ok=True)
        (folder / 'vector_engine.sv').write_text(current[:first] +
            reduced[reduced_first:reduced_last] + current[last:])
        (folder / 'vector_pe.sv').write_bytes(subprocess.check_output(['git', 'show',
            args.reduction_revision + ':rtl/npu/conv/vector_pe.sv'], cwd=ROOT))
        combined = dict(cases['vector_current'])
        combined['sources'] = [str(folder / Path(p).name) if Path(p).name in
            ('vector_engine.sv', 'vector_pe.sv') else p for p in combined['sources']]
        combined['configuration'] = 'TILE16 BUS64 PE8 shared input banks and reduction DSP'
        cases['vector_combined'] = combined
        manifest['reduction_revision'] = args.reduction_revision
        for path in folder.iterdir():
            manifest['source_sha256']['combined/' + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
