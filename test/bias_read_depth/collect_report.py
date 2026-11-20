#!/usr/bin/env python3
"""核对偏置范围比较的源码、状态证明、数值回归和普通 RTL 映射结果。"""
import argparse
import json
from pathlib import Path
import re
import sys

from common import ROOT, PARAMETERS, digest

sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['formal-default', 'formal-shared', 'four-state', 'reuse',
                 'mapped-reference', 'mapped-current', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    formal = read(args.formal_default / 'summary.json')
    shared = read(args.formal_shared / 'summary.json')
    four = read(args.four_state / 'summary.json')
    assert formal['passed'] and shared['passed'] and four['passed']
    assert len(formal['profiles']) == 6 and len(shared['profiles']) == 5
    inputs = formal['inputs']
    assert shared['inputs'] == inputs == four['inputs']
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    reuse = read(args.reuse / 'result.json')
    assert reuse['passed'] and reuse['sources_unchanged'] and reuse['case_count'] == 392
    for row in inputs['sources']:
        assert reuse['source_sha256'][row['source']] == row['current_sha256']
    warnings = re.findall(r'^%Warning-([^:]+):', (args.reuse / 'build.log').read_text(), re.M)
    assert not warnings, warnings
    mappings = []
    for label, folder in [('reference', args.mapped_reference), ('current', args.mapped_current)]:
        summary, manifest = read(folder / 'summary.json'), read(folder / 'manifest.json')
        assert manifest['top'] == 'bias_loader' and 'wide_alu_mapping' not in manifest
        assert summary['functional_verification']['passed']
        for row in inputs['sources']:
            assert row[label + '_sha256'] in manifest['sources_sha256'].values()
        for name, value in manifest['sources_sha256'].items():
            if name.startswith('rtl/common/'):
                assert digest(ROOT / name) == value
        module = read(folder / 'mapped.json')['modules']['bias_loader']
        paths = connected_paths(module, limit=2, group_limit=2,
                                sink_filter=lambda _name, cell, port:
                                cell['type'].startswith('RAMB') and port.startswith('ADDR'))
        assert paths['graph_complete']
        path_file = folder / 'storage_address_paths.json'
        path_file.write_text(json.dumps(paths, indent=2) + '\n')
        resources = summary['resources']
        mappings.append({'version': label,
                         **{key: resources[key] for key in
                            ['logic_lut_cells', 'flip_flops', 'carry4', 'dsp48e1', 'ramb36e1', 'ramb18e1',
                             'distributed_ram_lut_sites_nominal', 'shift_register_lut_sites_nominal']},
                         'longest_register_path_cells': summary['longest_register_path_cells'],
                         'storage_address_path_cells': paths['longest_register_path_cells'],
                         'graph_complete': summary['register_path_requirement']['graph_complete'],
                         'mapping_verification': summary['functional_verification'],
                         'sources_sha256': manifest['sources_sha256'],
                         'mapping_tools_sha256': manifest['mapping_tools_sha256'],
                         'summary_sha256': digest(folder / 'summary.json'),
                         'metrics_sha256': digest(folder / 'metrics.json'),
                         'storage_address_paths_sha256': digest(path_file),
                         'peak_process_tree_rss_bytes': summary['mapping_stage']['peak_process_tree_rss_bytes']})
    reference, current = mappings
    assert current['storage_address_path_cells'] <= 9
    assert current['logic_lut_cells'] < reference['logic_lut_cells']
    for name in ['dsp48e1', 'ramb36e1', 'ramb18e1', 'distributed_ram_lut_sites_nominal']:
        assert reference[name] == current[name]
    report = {'inputs': inputs, 'parameters': PARAMETERS,
              'behavior': {'external_latency_cycles_changed': False, 'sequential_logic_changed': False,
                           'bias_storage_bits': 2 * 32 * 16 * 32,
                           'ws_cache_bits': 16 * 32,
                           'buffer_default_independent_indices': True,
                           'integrated_request_sharing': 'enabled only by bias_loader; S_CMD index equality is derived from actual control state'},
              'formal_default_buffer': formal, 'formal_complete_loader': shared, 'four_state': four,
              'numeric_regression': {'passed': True, 'case_count': reuse['case_count'],
                                     'source_sha256': reuse['source_sha256'],
                                     'simulator_sha256': reuse['simulator_sha256'],
                                     'build_warnings': warnings,
                                     'report_sha256': digest(args.reuse / 'result.json'),
                                     'build_log_sha256': digest(args.reuse / 'build.log'),
                                     'run_log_sha256': digest(args.reuse / 'run.log')},
              'mapping': mappings,
              'mapping_options': {'source_arithmetic': 'ordinary RTL', 'additional_dsp_replacement': False,
                                  'mode': 'physical-cost', 'small_lut_area_cost': 1.0,
                                  'max_lut_inputs': 6, 'wire_delay_ps': 500, 'delay_target_ps': 6667},
              'physical_lut_positions': None, 'timing_150mhz_confirmed': None,
              'vivado_validation': 'not run; Vivado is unavailable in this environment',
              'scripts_sha256': {str(p.relative_to(ROOT)): digest(p)
                                 for p in sorted(Path(__file__).parent.glob('*.py'))}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'logic_lut_cells': current['logic_lut_cells'],
                      'storage_address_path_cells': current['storage_address_path_cells'],
                      'longest_register_path_cells': current['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
