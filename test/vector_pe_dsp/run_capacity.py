#!/usr/bin/env python3
"""核对生产 NPU 的阵列数量、缓存容量和通用实现的操作数状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.capacity import config, elaboration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='d9abf98')
    parser.add_argument('--verilator',default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    relative = 'rtl/npu/conv/vector_engine.sv'
    reference = out/'reference_vector_engine.sv'
    reference.write_bytes(subprocess.check_output(['git','show',args.reference_rev+':'+relative],cwd=ROOT))
    values = config.selected_config(ROOT/'config/npu_fpga.mk')
    original_files = elaboration.source_files
    runs = {}
    try:
        for label in ['reference','registered']:
            if label == 'reference':
                elaboration.source_files = lambda: [reference if path == ROOT/relative else path
                                                    for path in original_files()]
            else:
                elaboration.source_files = original_files
            report = elaboration.measure(values,verilator=args.verilator,output_dir=out/label)
            state = report['elaborated_state']
            counts = state['module_instances']
            runs[label] = {'passed':report['passed'],'total_state_bits':state['total_bits'],
                           'buffer_arrays_bits':state['buffer_arrays_bits'],
                           'register_arrays_bits':state['register_arrays_bits'],
                           'vector_pe_instances':counts.get('vector_pe',0),
                           'registered_vector_pe_instances':counts.get('registered_vector_pe',0),
                           'systolic_cell_instances':counts.get('ws_systolic_cell',0)}
            assert report['passed']
    finally:
        elaboration.source_files = original_files
    for field in ['total_state_bits','buffer_arrays_bits','register_arrays_bits',
                  'vector_pe_instances','systolic_cell_instances']:
        assert runs['reference'][field] == runs['registered'][field],field
    assert runs['registered']['registered_vector_pe_instances'] == min(values['SIZE'],8)
    report = {'passed':True,'reference_rev':args.reference_rev,
              'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest(),
              'source_sha256':hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(),
              'pe_sha256':hashlib.sha256((ROOT/'rtl/npu/conv/vector_pe.sv').read_bytes()).hexdigest(),
              'configuration':values,'runs':runs}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
