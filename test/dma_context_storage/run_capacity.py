#!/usr/bin/env python3
"""展开生产配置，比较 DMA 描述符容量与同步读取状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration

SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='df8a9b2d')
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference_dma.sv'
    reference.write_bytes(read_rtl_source(args.reference_ref + ':' + SOURCE, cwd=ROOT))
    values = config.selected_config(ROOT / 'config/npu_fpga.mk')
    original_sources = elaboration.source_files
    original_hashes = elaboration.sources_sha256
    records = {}
    try:
        for label in ('reference', 'regfile'):
            elaboration.source_files = (
                lambda: [reference if path == ROOT / SOURCE else path for path in original_sources()]
            ) if label == 'reference' else original_sources
            def source_hashes():
                selected_sources = elaboration.source_files
                try:
                    elaboration.source_files = original_sources
                    hashes = original_hashes()
                finally:
                    elaboration.source_files = selected_sources
                if label == 'reference':
                    hashes[SOURCE] = hashlib.sha256(reference.read_bytes()).hexdigest()
                return hashes
            elaboration.sources_sha256 = source_hashes
            report = elaboration.measure(values, verilator=args.verilator, output_dir=out / label)
            assert report['passed']
            state = report['elaborated_state']
            storage = [item for item in state['sequential_declarations']
                       if (item['module'] == 'axi_linear_block_dma' and
                           item['name'] in ('rd_context', 'rd_context_tag_q')) or
                          (item['name'] == 'mem' and
                           any(part in item['path'] for part in
                               ('.u_linear.u_context_storage.', '.u_linear.u_context_base.')))]
            records[label] = {
                'passed': report['passed'], 'total_bits': state['total_bits'],
                'buffer_arrays_bits': state['buffer_arrays_bits'],
                'register_arrays_bits': state['register_arrays_bits'],
                'regfile_instances': state['module_instances']['regfile'],
                'descriptor_bits': sum(item['bits'] for item in storage),
                'descriptor_storage': storage,
            }
    finally:
        elaboration.source_files = original_sources
        elaboration.sources_sha256 = original_hashes
    assert records['reference']['descriptor_bits'] == records['regfile']['descriptor_bits'] == 616
    assert records['reference']['buffer_arrays_bits'] == records['regfile']['buffer_arrays_bits']
    # 三十二位同步读取结果和一个地址来源标志构成新增状态。
    assert records['regfile']['total_bits'] - records['reference']['total_bits'] == 33
    assert records['regfile']['regfile_instances'] == records['reference']['regfile_instances'] + 1
    summary = {
        'passed': True, 'reference_ref': args.reference_ref,
        'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest(),
        'configuration': values, 'runs': records,
    }
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'passed': True, 'descriptor_bits': records['regfile']['descriptor_bits'],
                      'total_bits': records['regfile']['total_bits']}))


if __name__ == '__main__':
    main()
