#!/usr/bin/env python3
"""核对源码与全部完成结果，生成 IA 请求比较测量记录。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    formal_path = build / 'formal/summary.json'
    numeric_path = build / 'interface/summary.json'
    formal = json.loads(formal_path.read_text())
    numeric = json.loads(numeric_path.read_text())
    if not formal['passed'] or len(formal['runs']) != 5 or len(formal['equality_runs']) != 7:
        raise RuntimeError('All formal configurations must complete successfully')
    if not numeric['passed'] or len(numeric['runs']) != 2 or not numeric['fpga_primitives_enabled']:
        raise RuntimeError('Both FPGA interface tests must complete successfully')
    hashes = formal['source_sha256']
    if hashes != numeric['source_sha256'] or any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError('Verified RTL sources differ')
    if any(digest(ROOT / name) != value for name, value in formal['common_sha256'].items()):
        raise RuntimeError('Verified common RTL sources differ')
    inputs = json.loads((build / 'inputs/input_manifest.json').read_text())
    if inputs['current'] != hashes:
        raise RuntimeError('Synthesis source snapshots differ from verified sources')
    formal['equivalent_bits'] = sum(row['equivalent_bits'] for row in formal['runs'])
    formal['summary_sha256'] = digest(formal_path)
    numeric['total_cycles'] = sum(row['cycles'] for row in numeric['runs'])
    numeric['total_value_checks'] = sum(row['value_checks'] for row in numeric['runs'])
    numeric['summary_sha256'] = digest(numeric_path)
    result = {'source_sha256': hashes, 'reference_revision': formal['reference_rev'],
              'registered_latency_changed': False, 'formal': formal,
              'numeric': numeric, 'synthesis': {}}
    for method in ('native', 'physical'):
        result['synthesis'][method] = {}
        for label in ('reference', 'current'):
            folder = build / method / ('loader_' + label)
            metrics_path = folder / 'metrics.json'
            paths_path = folder / 'paths.json'
            metrics = json.loads(metrics_path.read_text())
            paths = json.loads(paths_path.read_text())
            if paths['mapped_sha256'] != digest(folder / 'mapped.json'):
                raise RuntimeError('Measured mapped design differs: ' + str(folder))
            result['synthesis'][method][label] = {
                'directory': str(folder.relative_to(ROOT)), 'resources': metrics['resources'],
                'longest_register_path_cells': paths['complete_module']['longest_path_cells'],
                'all_registers_to_outputs': {name: data['longest_path_cells']
                                             for name, data in paths['output_paths'].items()},
                'frame_final_to_outputs': {name: data['longest_path_cells']
                                           for name, data in paths['frame_final_paths'].items()},
                'metrics_sha256': digest(metrics_path), 'paths_sha256': digest(paths_path),
                'mapped_sha256': paths['mapped_sha256'], 'pre_lut_sha256': paths['pre_lut_sha256'],
            }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'formal_bits': formal['equivalent_bits'],
                      'cycles': numeric['total_cycles'], 'values': numeric['total_value_checks']}))


if __name__ == '__main__':
    main()
