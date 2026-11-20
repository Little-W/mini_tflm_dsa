#!/usr/bin/env python3
"""固定偏置存储和完整向量引擎的综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run_formal import fragment
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='cd0455b')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/conv/vector_engine.sv'
    reference = read_rtl_source(args.reference_rev + ':' + relative, cwd=ROOT, text=True)
    candidate = (ROOT / relative).read_text()
    dependencies = ['conv_im2col_pkg.sv','vector_engine_pkg.sv','vector_config_check.sv',
                    'vector_writeback.sv','vector_round_shift.sv','vector_scalar_multiplier.sv',
                    'vector_pe.sv','vector_softmax.sv','vector_quant_params.sv']
    dependencies = [ROOT / 'rtl/npu/conv' / name for name in dependencies]
    reference_checker = out / 'reference_checker.sv'
    reference_checker.write_bytes(read_rtl_source(args.reference_rev +
        ':rtl/npu/conv/vector_config_check.sv', cwd=ROOT))
    cases = {}
    for label, source in [('reference',reference),('bank_write',candidate)]:
        storage_path = out / (label + '_storage.sv')
        storage_path.write_text(fragment(source,64,16,64))
        vector_path = out / (label + '_vector.sv')
        vector_path.write_text(source)
        cases['storage_' + label] = {'top':'bias_store','options':[],
                                    'sources':[str(storage_path)],
                                    'configuration':'All 512 bias bits, BUS64, TILE16, DMA_SIZE64'}
        cases['vector_' + label] = {'top':'vector_engine',
                                   'options':['-D','SYNTHESIS=1','-GTILE=16','-GBUS_WIDTH=64','-GPE_COUNT=8'],
                                   'sources':[str(reference_checker) if label == 'reference' and
                                              p.name == 'vector_config_check.sv' else str(p)
                                              for p in dependencies] + [str(vector_path)],
                                   'configuration':'Production vector engine: TILE16, PE8, BUS64, all public outputs'}
    (out / 'cases.json').write_text(json.dumps(cases,indent=2) + '\n')
    manifest = {'reference_rev':args.reference_rev,
                'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
                'source_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
                'reference_checker_sha256':hashlib.sha256(reference_checker.read_bytes()).hexdigest(),
                'dependencies_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in dependencies + [ROOT/'rtl/common/regfile.v']}}
    (out / 'input_manifest.json').write_text(json.dumps(manifest,indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
