#!/usr/bin/env python3
"""核对源码摘要并汇总地址逻辑、协议和原生 FPGA 映射结果。"""
import argparse
import json
from pathlib import Path
from common import ROOT, WIDTHS, HELPER_PROFILES, digest
from prepare_measurement import PARAMETERS


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['formal', 'four-state', 'helpers-four-state', 'protocol-production',
                 'protocol-model', 'mapped-reference', 'mapped-current', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    formal = read(args.formal / 'summary.json')
    four = read(args.four_state / 'summary.json')
    helper_four = read(args.helpers_four_state / 'summary.json')
    assert formal['passed'] and len(formal['profiles']) == len(WIDTHS)
    assert len(formal['helper_profiles']) == len(HELPER_PROFILES)
    assert four['passed'] and helper_four['passed']
    assert formal['inputs'] == four['inputs'] == helper_four['inputs']
    production, model = formal['inputs']['sources']
    for row in [production, model]:
        assert digest(ROOT / row['source']) == row['current_sha256']
    expected = {(dw, dp, outstanding, latency, random) for dw in [32, 64]
                for dp, outstanding in [(1031, 4), (1024, 1), (1031, 3)]
                for latency in ([1, 2, 3, 8, 17] if (dp, outstanding) == (1031, 4) else [8])
                for random in [False, True]}
    protocols = []
    for label, folder, source in [('production', args.protocol_production, production),
                                   ('model', args.protocol_model, model)]:
        status = read(folder / 'modified_status.json')
        assert status['source_sha256'] == source['current_sha256']
        assert all(row['status'] == 'PASS' for row in status['runs'])
        keys = {(r['data_bits'], r['dp'], r['outstanding'], r['first_read_latency'], r['random'])
                for r in status['runs']}
        assert len(status['runs']) == 28 and keys == expected
        protocols.append({'implementation': label, 'passed': True, 'runs': len(status['runs']),
                          'source_sha256': status['source_sha256'],
                          'testbench_sha256': status['testbench_sha256'],
                          'simulator': status['simulator'], 'compile_jobs': status['compile_jobs'],
                          'report_sha256': digest(folder / 'modified_status.json'),
                          'profiles': [{k: v for k, v in row.items() if k not in ['warnings', 'log']}
                                       for row in status['runs']]})
    mapped = []
    mapping_modes = []
    for label, folder in [('reference', args.mapped_reference), ('current', args.mapped_current)]:
        manifest = read(folder / 'manifest.json')
        assert production[label + '_sha256'] in manifest['sources_sha256'].values()
        assert 'wide_alu_mapping' not in manifest
        for name, value in manifest['sources_sha256'].items():
            if name.startswith('rtl/common/'):
                assert digest(ROOT / name) == value
        if (folder / 'summary.json').is_file():
            summary = read(folder / 'summary.json')
            assert summary['functional_verification']['passed']
            resources = summary['resources']
            mapping_mode = 'physical-cost'
            verification = summary['functional_verification']
            depth = summary['longest_register_path_cells']
            graph_complete = summary['register_path_requirement']['graph_complete']
            stage = summary['mapping_stage']
            report_file = folder / 'summary.json'
        else:
            metrics = read(folder / 'metrics.json')
            stages = read(folder / 'stages.json')
            stage = stages['03_map_lut']
            assert digest(folder / 'mapped.json') == stage['output_sha256']
            assert digest(folder / stage['script']) == stage['script_sha256']
            assert 'check -assert' in (folder / stage['script']).read_text()
            resources = metrics['resources']
            mapping_mode = 'native-synth-xilinx'
            verification = {'passed': True, 'method': 'Yosys check -assert',
                            'script_sha256': stage['script_sha256']}
            depth = metrics['paths']['longest_register_path_cells']
            graph_complete = metrics['paths']['graph_complete']
            report_file = folder / 'stages.json'
        assert graph_complete
        mapping_modes.append(mapping_mode)
        mapped.append({'version': label, **{key: resources[key] for key in
                        ['logic_lut_cells', 'flip_flops', 'carry4', 'dsp48e1', 'ramb36e1', 'ramb18e1',
                         'distributed_ram_lut_sites_nominal', 'shift_register_lut_sites_nominal']},
                       'longest_register_path_cells': depth,
                       'graph_complete': graph_complete,
                       'mapping_verification': verification,
                       'manifest_sha256': digest(folder / 'manifest.json'),
                       'mapping_report_sha256': digest(report_file),
                       'metrics_sha256': digest(folder / 'metrics.json'),
                       'peak_process_tree_rss_bytes': stage['peak_process_tree_rss_bytes']})
    before, after = mapped
    assert len(set(mapping_modes)) == 1
    assert after['longest_register_path_cells'] <= 14
    for key in ['flip_flops', 'ramb36e1', 'ramb18e1', 'dsp48e1', 'distributed_ram_lut_sites_nominal']:
        assert before[key] == after[key]
    options = {'source_arithmetic': 'ordinary RTL', 'additional_dsp_replacement': False,
               'mode': mapping_modes[0], 'family': 'xc7'}
    if mapping_modes[0] == 'physical-cost':
        options.update(small_lut_area_cost=1.0, max_lut_inputs=6,
                       wire_delay_ps=500, delay_target_ps=6667)
    report = {'inputs': formal['inputs'], 'parameters': PARAMETERS,
              'behavior': {'external_latency_cycles_changed': False,
                           'sequential_logic_changed': False, 'storage_bits': PARAMETERS['DP'] * PARAMETERS['DW'],
                           'non_power_of_two_capacity_comparison': 'preserved'},
              'formal': formal, 'four_state': four, 'helpers_four_state': helper_four,
              'protocol': protocols, 'mapping': mapped,
              'mapping_options': options,
              'local_mapped_register_path_limit': {'maximum_cells': 14, 'passed': True},
              'physical_lut_positions': None, 'timing_150mhz_confirmed': None,
              'vivado_validation': 'not run; Vivado is unavailable in this environment',
              'scripts_sha256': {str(p.relative_to(ROOT)): digest(p)
                                 for p in sorted(Path(__file__).parent.glob('*.py'))},
              'protocol_runner_sha256': digest(ROOT / 'test/conv_soc_ram/run.py')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'protocol_runs': 56, 'formal_profiles': len(WIDTHS) + len(HELPER_PROFILES),
                      'logic_lut_cells': after['logic_lut_cells'],
                      'longest_register_path_cells': after['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
