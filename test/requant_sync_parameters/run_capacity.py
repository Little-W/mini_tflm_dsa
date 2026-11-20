#!/usr/bin/env python3
"""展开生产 NPU，验证参数容量与同步输入阶段的存储位数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='4ae43ade')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relatives = ('rtl/npu/writeback/vec_requant.sv',
                 'rtl/npu/conv/vector_scalar_multiplier.sv')
    reference_paths = {}
    hashes = {'reference': {}, 'candidate': {}}
    for relative in relatives:
        reference = out / ('reference_' + Path(relative).name)
        reference.write_bytes(subprocess.check_output(
            ['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT))
        reference_paths[ROOT / relative] = reference
        hashes['reference'][relative] = hashlib.sha256(reference.read_bytes()).hexdigest()
        hashes['candidate'][relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    values = config.selected_config(ROOT / 'config/npu_fpga.mk')
    source_files = elaboration.source_files
    runs = {}
    try:
        for label in ('reference', 'candidate'):
            elaboration.source_files = (
                (lambda: [reference_paths.get(path, path) for path in source_files()])
                if label == 'reference' else source_files)
            report = elaboration.measure(values, verilator=args.verilator, output_dir=out / label)
            state = report['elaborated_state']
            runs[label] = {
                'passed': report['passed'],
                'total_bits': state['total_bits'],
                'buffer_arrays_bits': state['buffer_arrays_bits'],
                'register_arrays_bits': state['register_arrays_bits'],
                'regfile_instances': state['module_instances']['REGFILE'],
                'report_sha256': hashlib.sha256((out / label / 'result.json').read_bytes()).hexdigest(),
            }
            assert report['passed']
    finally:
        elaboration.source_files = source_files
    for field in ('buffer_arrays_bits', 'register_arrays_bits'):
        assert runs['reference'][field] == runs['candidate'][field], field
    banks = values['NPU_AXI_DATA_WIDTH'] // 32
    bank_index_width = max(1, (banks - 1).bit_length())
    # 同步读结果、整张量参数、两个模式位及 bank 选择位构成新增阶段存储。
    expected_extra_bits = banks * 39 + 39 + 2 + bank_index_width
    assert runs['candidate']['total_bits'] - runs['reference']['total_bits'] == expected_extra_bits
    assert runs['candidate']['regfile_instances'] - runs['reference']['regfile_instances'] == banks * 2
    result = {'passed': True, 'reference_rev': args.reference_rev, 'source_sha256': hashes,
              'configuration': values, 'additional_pipeline_bits': expected_extra_bits, 'runs': runs}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
