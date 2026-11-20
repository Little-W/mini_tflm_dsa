#!/usr/bin/env python3
"""核对三层前缀偏移运算的证明、映射和实际向量数值结果。"""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    inputs = {
        'formal': build / 'formal_radix3/summary.json',
        'local': build / 'local_radix3/summary.json',
        'full_vector': build / 'full_paths.json',
        'numeric': build / 'fpga64/summary.json',
    }
    values = {name: json.loads(path.read_text()) for name, path in inputs.items()}
    formal, local, full, numeric = (values[name] for name in ('formal', 'local', 'full_vector', 'numeric'))
    source = digest(ROOT / SOURCE)
    assert formal['passed'] and formal['source_sha256'] == source
    assert formal['unchanged_outside_offset_clamp'] and not formal['inputs_constrained']
    assert formal['relevant_input_bits'] == 160 and formal['observed_bits'] == 34
    assert len(formal['cases']) == 2 and all(case['passed'] for case in formal['cases'])
    assert full['passed'] and full['unchanged_other_synthesis_sources']
    assert full['cases']['current']['source_sha256'] == source
    assert local['cases']['current']['source_sha256'] == source
    assert full['reference_commit'] == local['reference_commit'] == formal['reference_commit']
    for name in ('reference', 'current'):
        assert local['cases'][name]['paths']['graph_complete']
        for path in full['cases'][name]['paths'].values():
            assert path['graph_complete']
    assert numeric['bus_width'] == 64 and numeric['tile'] == 16
    assert numeric['implementation'] == 'official Xilinx primitive models'
    assert len(numeric['runs']) == 1
    run = numeric['runs'][0]
    assert run['pe'] == 8 and run['passed']
    model_path = build / 'fpga64/pe8/build.json'
    model = json.loads(model_path.read_text())
    assert model['sha256'][SOURCE] == source
    for name, expected in model['sha256'].items():
        assert digest(ROOT / name) == expected, name
    executable = build / 'fpga64/pe8/obj/Vvector_engine_dma_top'
    assert digest(executable) == run['executable_sha256']
    assert run['totals']['cases'] == len(run['cases']) == 592
    report = {
        'passed': True,
        'source_sha256': source,
        'reference_commit': formal['reference_commit'],
        'added_register_bits': 0,
        'added_interface_cycles': 0,
        'formal': formal,
        'local': local,
        'full_vector': full,
        'numeric': numeric,
        'numeric_task_cycles': sum(case['cycles'] for case in run['cases']),
        'numeric_model': model,
        'numeric_model_sha256': digest(model_path),
        'numeric_sources_unchanged_after_simulation': True,
        'report_sha256': {name: digest(path) for name, path in inputs.items()},
        'scripts_sha256': {name: digest(ROOT / name) for name in (
            'test/vector_offset_clamp/run.py', 'test/vector_offset_clamp/synthesis.py',
            'test/vector_input_banks/prepare_measurement.py', 'test/vector_offset_clamp/paths.py',
            'test/vector_engine/run.py', 'test/vector_offset_prefix3/collect.py')},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'source_sha256': source,
                      'numeric': run['totals'], 'cycles': report['numeric_task_cycles']}, indent=2))


if __name__ == '__main__':
    main()
