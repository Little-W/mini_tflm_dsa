#!/usr/bin/env python3
"""使用普通 RTL 综合比较写入分页模块的资源和完整组合路径。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_write_page_guard.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT)
                   if label == 'reference' else (ROOT / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    report = dict(reference_ref=args.reference_ref, extra_dsp_remapping=False, logic_depth_limit=9,
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  runs={}, changes={})
    cases = {}
    for width in (32, 64):
        parameters = dict(ADDR_W=32, DATA_W=width, WRITE_OUTSTANDING=4)
        for label, source in snapshots.items():
            cases[f'data{width}_{label}'] = dict(top='axi_write_page_guard', parameters=parameters,
                    configuration='Four outstanding writes; ordinary RTL arithmetic inference',
                    options=['-D', 'SYNTHESIS=1', *(f'-G{k}={v}' for k, v in parameters.items())],
                    sources=[str(source)])
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    for name in cases:
        command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                   '--case-config', str(config), '--cases', name, '--out', str(out / 'native')]
        subprocess.run(command, cwd=ROOT, check=True)
        folder = out / 'native' / name
        metrics = json.loads((folder / 'metrics.json').read_text())
        paths = metrics['paths']
        if not paths['graph_complete'] or paths['combinational_cycle_nodes']:
            raise RuntimeError('Complete acyclic mapped graph required')
        report['runs'][name] = dict(parameters=cases[name]['parameters'], resources=metrics['resources'],
            longest_combinational_path_cells=paths['longest_register_path_cells'],
            logic_depth_limit_met=paths['longest_register_path_cells'] <= 9,
            longest_path=paths['register_to_register_paths'][0], graph_complete=True,
            metrics_sha256=digest(folder / 'metrics.json'), mapped_sha256=digest(folder / 'mapped.json'),
            stages=json.loads((folder / 'stages.json').read_text()))
        for filename in ('elaborated.il', 'pre_lut.il', 'mapped.json'):
            path = folder / filename
            with path.open('rb') as src, gzip.open(str(path) + '.gz', 'wb', compresslevel=2) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
    for width in (32, 64):
        before, after = (report['runs'][f'data{width}_{label}'] for label in ('reference', 'current'))
        report['changes'][str(width)] = dict(resource_delta={key: after['resources'][key] - before['resources'][key]
                for key in ('logic_lut_cells', 'flip_flops', 'dsp48e1', 'ramb18e1', 'carry4',
                            'distributed_ram_lut_sites_nominal')},
                combinational_levels=[before['longest_combinational_path_cells'],
                                      after['longest_combinational_path_cells']])
    if digest(ROOT / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during synthesis')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['changes']), flush=True)


if __name__ == '__main__':
    main()
