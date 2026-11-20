#!/usr/bin/env python3
"""汇总预取描述存储的功能、引脚连接与局部资源检查。"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--behavior', type=Path, required=True)
    parser.add_argument('--measurement', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    behavior = json.loads((args.behavior / 'summary.json').read_text())
    measured = json.loads((args.measurement / 'summary.json').read_text())
    assert behavior['passed'] and measured['passed']
    source = 'rtl/npu/dma/cache/conv_read_cache.sv'
    assert behavior['source_sha256'] == measured['source_sha256']['current'][source]
    results = {}
    for label, item in measured['results'].items():
        kinds = sorted({cell['type'] for cell in item['payload_cells'].values()})
        results[label] = {key: item[key] for key in (
            'resources', 'longest_register_path_cells', 'peak_process_tree_rss_bytes')}
        results[label]['payload_cell_types'] = {
            kind: sum(cell['type'] == kind for cell in item['payload_cells'].values()) for kind in kinds}
        results[label]['abc_functional_verification'] = item['mapped_summary']['functional_verification']
    metrics = {'logic_lut_cells': 'logic_lut_cells',
               'ram_lut_sites': 'distributed_ram_lut_sites_nominal',
               'lut_sites_before_packing': 'lut_sites_nominal_before_packing',
               'flip_flops': 'flip_flops', 'ramb18e1': 'ramb18e1',
               'ramb36e1': 'ramb36e1', 'dsp48e1': 'dsp48e1'}
    report = {'passed': True, 'reference_ref': behavior['reference_ref'],
        'source_sha256': behavior['source_sha256'],
        'logical_storage': {'entries': 8, 'bits_per_entry': 65, 'total_bits': 520,
                            'retire_bits': 32, 'index_and_valid_bits': 33},
        'behavior': behavior, 'mapping_parameters': measured['parameters'],
        'mapping_options': measured['mapping'],
        'synthesis_sources_sha256': measured['source_sha256'], 'results': results,
        'retire_bram_port_check': measured['retire_bram_port_check'],
        'net_change': {key: results['current']['resources'][metric] -
                           results['reference']['resources'][metric] for key, metric in metrics.items()},
        'physical_placement_performed': False,
        'test_script_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in Path(__file__).parent.glob('*.py')}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['net_change']))


if __name__ == '__main__':
    main()
