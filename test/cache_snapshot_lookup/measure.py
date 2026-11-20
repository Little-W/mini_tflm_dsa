#!/usr/bin/env python3
"""使用普通 RTL 综合比较生产缓存的资源和完整组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / (label + '.sv')
        content = (read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT)
                   if label == 'reference' else (ROOT / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    parameters = dict(SETS=128, WAYS=2, LINE_BYTES=16, BUS_WIDTH=64,
                      CACHE_POLICY=3, DEMAND_DEPTH=4)
    common = ['rtl/npu/dma/cache/conv_sdp_ram.sv', 'rtl/npu/conv/conv_axi_span_reader.sv',
              'rtl/common/regfile.v']
    cases = {label: {'top': 'conv_windowed_cache', 'parameters': parameters,
                     'configuration': '128 sets, 2 ways, 16-byte lines, 64-bit bus, 4 demand entries; ordinary RTL inference',
                     'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                                 *(f'-G{k}={v}' for k, v in parameters.items())],
                     'sources': [str(source), *common]} for label, source in snapshots.items()}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
               '--case-config', str(config), '--cases', 'reference', 'current', '--out', str(out / 'native')]
    subprocess.run(command, cwd=ROOT, check=True)
    report = {'reference_ref': args.reference_ref, 'parameters': parameters,
              'extra_dsp_remapping': False, 'logic_depth_limit': 9,
              'source_sha256': {label: digest(path) for label, path in snapshots.items()}, 'runs': {}}
    for label in snapshots:
        folder = out / 'native' / label
        metrics = json.loads((folder / 'metrics.json').read_text())
        paths = metrics['paths']
        if not paths['graph_complete'] or paths['combinational_cycle_nodes']:
            raise RuntimeError('A complete acyclic graph is required')
        report['runs'][label] = {
            'resources': metrics['resources'],
            'longest_combinational_path_cells': paths['longest_register_path_cells'],
            'logic_depth_limit_met': paths['longest_register_path_cells'] <= 9,
            'graph_complete': True,
            'longest_path': paths['register_to_register_paths'][0],
            'metrics_sha256': digest(folder / 'metrics.json'),
            'mapped_sha256': digest(folder / 'mapped.json'),
            'stages': json.loads((folder / 'stages.json').read_text()),
        }
    before, after = (report['runs'][label]['resources'] for label in ('reference', 'current'))
    report['resource_delta'] = {key: after[key] - before[key] for key in
                               ('logic_lut_cells', 'flip_flops', 'dsp48e1', 'ramb18e1',
                                'distributed_ram_lut_sites_nominal')}
    if digest(ROOT / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during synthesis')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'resource_delta': report['resource_delta'],
                      'depth': {name: row['longest_combinational_path_cells']
                                for name, row in report['runs'].items()}}))


if __name__ == '__main__':
    main()
