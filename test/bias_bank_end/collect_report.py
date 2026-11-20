#!/usr/bin/env python3
"""核对银行末端加法的完整状态、数值和生产参数映射结果。"""
import argparse
import json
from pathlib import Path
import re
from prove import ROOT, BUFFER, HELPER, digest


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['formal', 'four-state', 'reuse', 'inputs', 'mapped', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    formal, four = read(args.formal / 'summary.json'), read(args.four_state / 'summary.json')
    inputs, reuse = read(args.inputs / 'inputs.json'), read(args.reuse / 'result.json')
    assert formal['passed'] and len(formal['profiles']) == 10 and four['passed']
    assert formal['source_sha256'] == four['source_sha256'] == digest(ROOT / BUFFER)
    assert formal['helper_sha256'] == four['helper_sha256'] == inputs['helper_sha256'] == digest(ROOT / HELPER)
    assert reuse['passed'] and reuse['sources_unchanged'] and reuse['case_count'] == 392
    for row in inputs['sources']:
        assert row['current_sha256'] == digest(ROOT / row['source']) == reuse['source_sha256'][row['source']]
    assert reuse['source_sha256'][HELPER] == inputs['helper_sha256']
    warnings = re.findall(r'^%Warning-([^:]+):', (args.reuse / 'build.log').read_text(), re.M)
    assert not warnings, warnings
    mappings = []
    for label in ['reference', 'current']:
        folder = args.mapped / label
        summary, manifest = read(folder / 'summary.json'), read(folder / 'manifest.json')
        assert summary['functional_verification']['passed'] and 'wide_alu_mapping' not in manifest
        for row in inputs['sources']:
            assert row[label + '_sha256'] in manifest['sources_sha256'].values()
        assert manifest['sources_sha256'][HELPER] == inputs['helper_sha256']
        assert manifest['sources_sha256']['rtl/common/regfile.v'] == inputs['regfile_sha256']
        resources = summary['resources']
        mappings.append({'version': label,
                         **{key: resources[key] for key in ['logic_lut_cells', 'flip_flops', 'carry4',
                            'dsp48e1', 'ramb36e1', 'ramb18e1', 'distributed_ram_lut_sites_nominal',
                            'shift_register_lut_sites_nominal']},
                         'longest_register_path_cells': summary['longest_register_path_cells'],
                         'graph_complete': summary['register_path_requirement']['graph_complete'],
                         'mapping_verification': summary['functional_verification'],
                         'mapping_tools_sha256': manifest['mapping_tools_sha256'],
                         'summary_sha256': digest(folder / 'summary.json'),
                         'metrics_sha256': digest(folder / 'metrics.json'),
                         'peak_process_tree_rss_bytes': summary['mapping_stage']['peak_process_tree_rss_bytes']})
    reference, current = mappings
    assert current['graph_complete'] and current['longest_register_path_cells'] <= 9
    for key in ['flip_flops', 'dsp48e1', 'ramb36e1', 'ramb18e1', 'distributed_ram_lut_sites_nominal']:
        assert reference[key] == current[key]
    report = {'inputs': inputs,
              'behavior': {'state_updates_changed': False, 'external_latency_cycles_changed': False,
                           'full_extended_sum_preserved': True, 'bias_storage_bits': 32768, 'ws_cache_bits': 512},
              'formal': formal, 'four_state': four,
              'numeric_regression': {'passed': True, 'case_count': reuse['case_count'],
                                     'source_sha256': reuse['source_sha256'],
                                     'simulator_sha256': reuse['simulator_sha256'],
                                     'build_warnings': warnings,
                                     'report_sha256': digest(args.reuse / 'result.json'),
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
                      'longest_register_path_cells': current['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
