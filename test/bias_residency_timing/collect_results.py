#!/usr/bin/env python3
"""核对正式验证与综合源文件并保存偏置加载器测量摘要。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ('bias_loader.sv', 'bias_loader_ctrl.sv', 'bias_loader_buffer.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    base = args.build.resolve()
    formal_path = base / 'formal_final/summary.json'
    numeric_path = base / 'numeric/result.json'
    formal = json.loads(formal_path.read_text())
    numeric = json.loads(numeric_path.read_text())
    if not formal['passed'] or not numeric['passed']:
        raise RuntimeError('Verification did not complete successfully')
    sources = {f'rtl/npu/loaders/{name}': digest(ROOT / 'rtl/npu/loaders' / name)
               for name in SOURCES}
    for name, value in sources.items():
        if formal['source_sha256'][name] != value or numeric['source_sha256'][name] != value:
            raise RuntimeError(f'Verification source differs: {name}')
    report = {
        'reference_rev': formal['reference_rev'], 'source_sha256': sources,
        'latency_change_cycles': 0, 'storage_capacity_change_bits': 0,
        'formal': {'passed': True, 'profiles': formal['profiles'],
                   'equivalent_bits_total': sum(p['equivalent_bits'] for p in formal['profiles']),
                   'inputs_constrained': False, 'summary_sha256': digest(formal_path)},
        'numeric': {'passed': True, 'case_count': numeric['case_count'],
                    'cycles': sum(p['cycles'] for p in numeric['cases']),
                    'dma_commands': sum(p['dma_commands'] for p in numeric['cases']),
                    'summary_sha256': digest(numeric_path),
                    'simulator_sha256': numeric['simulator_sha256']},
        'synthesis': {},
    }
    modes = {
        'native': ('native', 'rows_native'),
        'wide_alu_dsp_min8': ('dsp', 'rows_dsp'),
        'wide_alu_dsp_min8_physical_cost': ('dsp_physical', 'rows_dsp_physical'),
    }
    for mode, folders in modes.items():
        report['synthesis'][mode] = {}
        for label, folder in zip(('reference', 'current'), folders):
            path = base / folder / ('loader_' + label)
            metrics = json.loads((path / 'metrics.json').read_text())
            paths = json.loads((path / 'paths.json').read_text())
            manifest = json.loads((path / 'manifest.json').read_text())
            if not metrics['paths']['graph_complete']:
                raise RuntimeError(f'Timing graph is incomplete: {path}')
            expected = formal['snapshot_sha256'][label]
            for name in SOURCES:
                hashes = [value for key, value in manifest['sources_sha256'].items()
                          if Path(key).name == name]
                if hashes != [expected[name]]:
                    raise RuntimeError(f'Synthesis source differs: {path}/{name}')
            report['synthesis'][mode][label] = {
                'resources': metrics['resources'],
                'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
                'register_sink_paths': {key: value['longest_path_cells']
                                        for key, value in paths['register_sink_paths'].items()},
                'output_paths': {key: value['longest_path_cells']
                                 for key, value in paths['output_paths'].items()},
                'mapped_sha256': digest(path / 'mapped.json'),
                'metrics_sha256': digest(path / 'metrics.json'),
                'paths_sha256': digest(path / 'paths.json'),
                'manifest_sha256': digest(path / 'manifest.json'),
            }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_bits': report['formal']['equivalent_bits_total'],
                      'numeric': report['numeric']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
