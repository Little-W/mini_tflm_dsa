#!/usr/bin/env python3
"""汇总帧调度准备阶段的完整状态证明、命令检查与普通 RTL 测量。"""
import argparse
import json
from pathlib import Path
import re
import sys
from prove import ROOT, SOURCE, HELPERS, digest

sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['formal', 'four-state', 'numeric', 'source-checks', 'inputs', 'mapped', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    formal, four = read(args.formal / 'summary.json'), read(args.four_state / 'summary.json')
    numeric, inputs = read(args.numeric / 'summary.json'), read(args.inputs / 'inputs.json')
    source_checks = read(args.source_checks / 'summary.json')
    assert source_checks['passed'] and len(source_checks['checks']) == 4
    assert source_checks['source_sha256'] == digest(ROOT / SOURCE)
    for row in source_checks['checks']:
        assert row['entry_sha256'] == digest(ROOT / row['entry'])
    assert formal['passed'] and len(formal['profiles']) == 5 and four['passed']
    assert formal['source_sha256'] == four['source_sha256'] == inputs['current_sha256'] == digest(ROOT / SOURCE)
    assert formal['reference_sha256'] == four['reference_sha256'] == inputs['reference_sha256']
    assert formal['helper_sha256'] == four['helper_sha256'] == inputs['helper_sha256']
    assert numeric['passed'] and numeric['cases'] == 975
    for label, report in numeric['tests'].items():
        assert report['source_sha256'][str(ROOT / SOURCE)] == inputs['current_sha256']
        assert report['undefined_behavior_sanitizer']
        for name in HELPERS:
            assert report['source_sha256'][str(ROOT / name)] == inputs['helper_sha256'][name] == digest(ROOT / name)
        warnings = re.findall(r'^%Warning-([^:]+): ([^\n]+)',
                              (args.numeric / label / 'compile.log').read_text(), re.M)
        assert all(kind == 'UNOPTFLAT' and '/onehot_check.sv:' in text for kind, text in warnings), warnings
        report['compile_warnings'] = [{'kind': kind, 'source': text} for kind, text in warnings]
    mappings = []
    for label in ['reference', 'current']:
        folder = args.mapped / label
        summary, manifest = read(folder / 'summary.json'), read(folder / 'manifest.json')
        assert manifest['top'] == 'ps_window_scheduler' and 'wide_alu_mapping' not in manifest
        assert summary['functional_verification']['passed']
        assert inputs[label + '_sha256'] in manifest['sources_sha256'].values()
        for name in HELPERS:
            assert manifest['sources_sha256'][name] == inputs['helper_sha256'][name]
        assert manifest['sources_sha256']['rtl/common/regfile.v'] == inputs['regfile_sha256']
        module = read(folder / 'mapped.json')['modules']['ps_window_scheduler']
        origins = register_origins(Path(manifest['pre_lut_origin']['directory']) / 'pre_lut.il')
        assert origins
        for name, origin in origins.items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        groups = {}
        for name in ['phase', 'target', 'prepare_rows', 'row_base', 'command_buffer_row']:
            paths = connected_paths(module, limit=1, group_limit=1,
                sink_filter=lambda _name, cell, _port, name=name:
                    str(cell.get('attributes', {}).get('fpga_register_origin', '')).startswith(name + ' '))
            assert paths['graph_complete']
            groups[name] = {'longest_register_path_cells': paths['longest_register_path_cells'],
                            'path': paths['register_to_register_paths'][:1]}
        resources = summary['resources']
        mappings.append({'version': label,
                         **{key:resources[key] for key in ['logic_lut_cells','flip_flops','carry4',
                            'dsp48e1','ramb36e1','ramb18e1','distributed_ram_lut_sites_nominal',
                            'shift_register_lut_sites_nominal']},
                         'longest_register_path_cells': summary['longest_register_path_cells'],
                         'graph_complete': summary['register_path_requirement']['graph_complete'],
                         'prepared_state_paths': groups,
                         'mapping_verification': summary['functional_verification'],
                         'mapping_tools_sha256': manifest['mapping_tools_sha256'],
                         'summary_sha256': digest(folder / 'summary.json'),
                         'metrics_sha256': digest(folder / 'metrics.json'),
                         'peak_process_tree_rss_bytes': summary['mapping_stage']['peak_process_tree_rss_bytes']})
    reference, current = mappings
    assert current['longest_register_path_cells'] < reference['longest_register_path_cells']
    for key in ['dsp48e1','ramb36e1','ramb18e1','distributed_ram_lut_sites_nominal']:
        assert current[key] == reference[key]
    report = {'inputs': inputs,
              'behavior': {'external_latency_cycles_changed': False, 'state_transition_sequence_changed': False,
                           'all_public_outputs_compared_every_cycle': True,
                           'target_consumption_phases': ['OPENING','SWEEPING','DRAINING'],
                           'frame_metadata_bits': 688, 'frame_k_bits': 448,
                           'frame_count': 16, 'metadata_read_ports': 2},
              'formal': formal, 'four_state': four, 'numeric_regression': numeric,
              'source_elaboration': source_checks,
              'mapping': mappings,
              'mapping_options': {'source_arithmetic': 'ordinary RTL', 'additional_dsp_replacement': False,
                                  'mode': 'physical-cost', 'small_lut_area_cost': 1.0,
                                  'max_lut_inputs': 6, 'wire_delay_ps': 500, 'delay_target_ps': 6667},
              'physical_lut_positions': None, 'timing_150mhz_confirmed': None,
              'vivado_validation': 'not run; Vivado is unavailable in this environment',
              'scripts_sha256': {str(path.relative_to(ROOT)): digest(path)
                                 for path in sorted(Path(__file__).parent.glob('*.py'))}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'logic_lut_cells': current['logic_lut_cells'],
                      'longest_register_path_cells': current['longest_register_path_cells'],
                      'prepared_state_paths': {name:row['longest_register_path_cells']
                                               for name,row in current['prepared_state_paths'].items()}}))


if __name__ == '__main__':
    main()
