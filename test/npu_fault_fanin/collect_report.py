#!/usr/bin/env python3
"""核对映射后的真值、全部输入路径与面积，并保存局部测量结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from extract_fault import ROOT, TOP, INPUTS, INPUT_BITS

sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, connected_paths


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(folder, truth):
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['fault_measure']
    starts = module['netnames']['captured_flags']['bits']
    outputs = module['ports']['o_flags']['bits']
    if len(starts) != INPUT_BITS or len(outputs) != 2:
        raise ValueError('The measurement boundary width changed')
    metrics = analyze(module)
    if not metrics['paths']['graph_complete']:
        raise ValueError('The mapped path graph is incomplete')
    paths = {}
    position = 0
    for name, width in INPUTS:
        for index in range(width):
            bit = starts[position]
            label = name if width == 1 else f'{name}[{index}]'
            paths[label] = {}
            for output, target in zip(('task_fault', 'arbiter_abort'), outputs):
                result = connected_paths(module, limit=2, group_limit=2,
                    root_filter=lambda n, c, p, b=bit: b in c['connections'].get('Q', []),
                    sink_filter=lambda n, c, p, b=target: b in c['connections'].get('Q', []))
                if not result['graph_complete']:
                    raise ValueError(f'The path graph for {label} to {output} is incomplete')
                paths[label][output] = result
            position += 1

    # 以输入寄存器的 Q 为任意输入，比较两个输出寄存器的实际 D。
    drivers, targets = {}, []
    for name, cell in module['cells'].items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'].get(port) == 'output':
                for index, bit in enumerate(bits):
                    if isinstance(bit, int):
                        if bit in drivers:
                            raise ValueError('A mapped bit has multiple drivers')
                        drivers[bit] = (name, port, index)
    for output in outputs:
        name, port, _ = drivers[output]
        cell = module['cells'][name]
        if cell['type'] != 'FDRE' or port != 'Q':
            raise ValueError('An output measurement register is missing')
        targets.append(cell['connections']['D'][0])
    for value, expected in enumerate(truth):
        values = {bit: (value >> index) & 1 for index, bit in enumerate(starts)}
        visiting = set()

        def read(bit):
            if bit in ('0', '1'):
                return int(bit)
            if bit in values:
                return values[bit]
            if bit in visiting:
                raise ValueError('A combinational loop was found')
            visiting.add(bit)
            name, port, _ = drivers[bit]
            cell = module['cells'][name]
            kind = cell['type']
            if kind == 'LUT6_2':
                width = 5 if port == 'O5' else 6
            elif re.fullmatch(r'LUT[1-6]', kind):
                width = int(kind[-1])
            else:
                raise ValueError('Unexpected cell in the fault combination: ' + kind)
            address = sum(read(cell['connections'][f'I{index}'][0]) << index for index in range(width))
            table = int(cell['parameters']['INIT'], 2)
            values[bit] = (table >> address) & 1
            visiting.remove(bit)
            return values[bit]

        actual = sum(read(bit) << index for index, bit in enumerate(targets))
        if actual != expected:
            raise AssertionError(f'Mapped result differs for input {value}: {actual} != {expected}')
    return {'mapped_sha256': digest(mapped), 'resources': metrics['resources'],
            'whole_block_paths': metrics['paths'], 'input_paths': paths,
            'truth_combinations': len(truth), 'truth_comparison_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'measurement.json')
    args = parser.parse_args()
    results = args.results.resolve()
    formal_path = results / 'formal/summary.json'
    formal = json.loads(formal_path.read_text())
    manifest = json.loads((results / 'inputs/manifest.json').read_text())
    source_hash = digest(ROOT / TOP)
    if not formal['passed'] or formal['source_sha256'][str(TOP)] != source_hash:
        raise ValueError('The formal result does not describe the current NPU source')
    if manifest['source_sha256']['current']['source_sha256'] != source_hash:
        raise ValueError('The mapping input does not describe the current NPU source')
    truth_file = results / 'formal/generic/reference_truth.hex'
    truth = [int(line, 16) for line in truth_file.read_text().splitlines()]
    if len(truth) != 1 << INPUT_BITS:
        raise ValueError('The exhaustive reference truth table is incomplete')
    report = {'source_sha256': {str(TOP): source_hash},
              'reference_commit': formal['reference_commit'],
              'formal': formal, 'formal_report_sha256': digest(formal_path),
              'reference_truth_sha256': digest(truth_file), 'mapping': {}}
    for mode in ('native', 'cost'):
        cases = {label: measure(results / mode / label, truth) for label in ('reference', 'current')}
        for label in cases:
            flow_manifest = results / mode / label / 'manifest.json'
            data = json.loads(flow_manifest.read_text())
            snapshot = results / 'inputs' / (label + '.sv')
            if data['sources_sha256'].get(str(snapshot)) != digest(snapshot):
                raise ValueError('The mapped result uses a different extracted source: ' + str(flow_manifest))
            if digest(snapshot) != manifest['source_sha256'][label]['measurement_sha256']:
                raise ValueError('The extracted measurement source changed')
            cases[label]['flow_manifest_sha256'] = digest(flow_manifest)
            cases[label]['lut_mapping'] = data.get('lut_mapping', {'mode': 'synth_xilinx'})
        old, new = cases['reference'], cases['current']
        if new['resources']['logic_lut_cells'] > old['resources']['logic_lut_cells']:
            raise AssertionError('The fault combination uses more LUT cells')
        deltas = {}
        for name, path_set in new['input_paths'].items():
            old_paths = old['input_paths'][name]
            deltas[name] = {}
            for output, path in path_set.items():
                deltas[name][output] = (path['longest_register_path_cells'] -
                                       old_paths[output]['longest_register_path_cells'])
            old_max = max(path['longest_register_path_cells'] for path in old_paths.values())
            new_max = max(path['longest_register_path_cells'] for path in path_set.values())
            deltas[name]['maximum_output_path'] = new_max - old_max
            if new_max > old_max:
                raise AssertionError(f'The maximum output path from {name} became longer')
            if deltas[name]['arbiter_abort'] > 0:
                raise AssertionError(f'The path from {name} to arbiter abort became longer')
        if new['input_paths']['dma_bus_error']['arbiter_abort']['longest_register_path_cells'] > 1:
            raise AssertionError('DMA bus error must reach arbiter abort within one combinational cell')
        report['mapping'][mode] = cases
        print(json.dumps({'mapping': mode, **{label: {
            'lut_cells': case['resources']['logic_lut_cells'],
            'max_depth': case['whole_block_paths']['longest_register_path_cells'],
            'dma_abort_depth': case['input_paths']['dma_bus_error']['arbiter_abort']['longest_register_path_cells'],
        } for label, case in cases.items()}}), flush=True)
        report['mapping'][mode]['path_depth_changes'] = deltas
    report['checks'] = {'maximum_output_path_of_each_input_no_longer': True,
                        'all_arbiter_abort_paths_no_longer': True, 'lut_cells_no_greater': True,
                        'dma_bus_error_to_abort_at_most_one_cell': True,
                        'mapped_truth_comparisons': 4 * len(truth), 'passed': True}
    report['measurement_scope'] = 'Actual extracted fault region and arbiter abort expression with measurement registers only'
    report['device_timing_measured'] = False
    report['verification_sources_sha256'] = {str(path.relative_to(ROOT)): digest(path)
        for path in sorted(Path(__file__).resolve().parent.glob('*.py'))}
    report['analysis_sources_sha256'] = {str(path.relative_to(ROOT)): digest(path)
        for path in (ROOT / 'scripts/fpga/netlist_metrics.py', ROOT / 'scripts/fpga/lut_dependencies.py')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
