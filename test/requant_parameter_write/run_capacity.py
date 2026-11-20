#!/usr/bin/env python3
"""展开完整生产 NPU，比较 WS 写入改造前后的存储容量。"""
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
    parser.add_argument('--reference-rev', default='369a3ab')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    reference = out / 'reference_vec_requant.sv'
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
            runs[label] = {'passed': report['passed'], 'total_bits': state['total_bits'],
                           'is_parameter_bits': state['buffer_arrays_bits']['requant_is_cache'],
                           'ws_parameter_bits': state['register_arrays_bits']['requant_ws_parameters'],
                           'buffer_arrays_bits': state['buffer_arrays_bits'],
                           'register_arrays_bits': state['register_arrays_bits'],
                           'regfile_instances': state['module_instances']['REGFILE']}
            assert report['passed']
    finally:
        elaboration.source_files = source_files
    for field in ('total_bits', 'is_parameter_bits', 'ws_parameter_bits', 'buffer_arrays_bits', 'register_arrays_bits'):
        assert runs['reference'][field] == runs['bank_write'][field], field
    summary = {'passed': True, 'reference_rev': args.reference_rev,
               'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
               'source_sha256': hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
               'configuration': values, 'runs': runs}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
