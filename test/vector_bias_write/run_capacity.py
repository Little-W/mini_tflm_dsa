#!/usr/bin/env python3
"""展开完整生产 NPU，核对偏置存储封装前后的容量相同。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='cd0455b')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/conv/vector_engine.sv'
    reference = out / 'reference_vector_engine.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT))
    values = config.selected_config(ROOT / 'config/npu_fpga.mk')
    source_files = elaboration.source_files
    runs = {}
    try:
        for label in ('reference', 'bank_write'):
            if label == 'reference':
                elaboration.source_files = lambda: [reference if path == ROOT / relative else path
                                                    for path in source_files()]
            else:
                elaboration.source_files = source_files
            report = elaboration.measure(values, verilator=args.verilator, output_dir=out / label)
            state = report['elaborated_state']
            storage = [item for item in state['sequential_declarations']
                       if '.u_bias_storage.' in item['path']]
            runs[label] = {'passed': report['passed'], 'total_bits': state['total_bits'],
                           'vector_buffer_bits': state['buffer_arrays_bits']['vector_buffers'],
                           'buffer_arrays_bits': state['buffer_arrays_bits'],
                           'register_arrays_bits': state['register_arrays_bits'],
                           'regfile_instances': state['module_instances']['REGFILE'],
                           'bias_regfile_bits': sum(item['bits'] for item in storage),
                           'bias_regfile_instances': len(storage)}
            assert report['passed']
    finally:
        elaboration.source_files = source_files
    for field in ('total_bits', 'vector_buffer_bits', 'buffer_arrays_bits', 'register_arrays_bits'):
        assert runs['reference'][field] == runs['bank_write'][field], field
    assert runs['bank_write']['bias_regfile_bits'] == 32 * values['SIZE']
    assert runs['bank_write']['bias_regfile_instances'] == values['SIZE']
    assert runs['bank_write']['regfile_instances'] - runs['reference']['regfile_instances'] == values['SIZE']
    summary = {'passed': True, 'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
               'source_sha256': hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
               'configuration': values, 'runs': runs}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
