#!/usr/bin/env python3
"""使用普通 RTL 综合测量分段读取器及包含它的生产缓存。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_axi_span_reader.sv')
REFERENCE = '51c390c51884c686bc1a08e1b32f40f9047b7b1b'


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
    shared = ['rtl/npu/dma/cache/conv_read_cache.sv',
              'rtl/npu/dma/cache/conv_sdp_ram.sv', 'rtl/common/regfile.v']
    report = dict(reference_ref=args.reference_ref, extra_dsp_remapping=False, logic_depth_limit=9,
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  common_sha256={name: digest(ROOT / name) for name in shared}, runs={}, changes={})
    cases = {}
    for kind, top, parameters in [
            ('span', 'conv_axi_span_reader', dict(BUS_WIDTH=64, MAX_REQUEST_BYTES=16, DMA_MAX_BYTES=2048)),
            ('cache', 'conv_windowed_cache', dict(SETS=128, WAYS=2, LINE_BYTES=16, BUS_WIDTH=64,
                                                CACHE_POLICY=3, DEMAND_DEPTH=4))]:
        for label, source in snapshots.items():
            cases[f'{kind}_{label}'] = dict(top=top, parameters=parameters,
                    configuration='Production 64-bit bus, 16-byte cache line; ordinary RTL inference',
                    options=['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                             *(f'-G{k}={v}' for k, v in parameters.items())],
                    sources=[str(source), *(shared if kind == 'cache' else [])])
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
        # 每个配置完成后压缩可重建的大文件，使顺序测量的磁盘占用保持稳定。
        for filename in ('elaborated.il', 'pre_lut.il', 'mapped.json'):
            path = folder / filename
            with path.open('rb') as src, gzip.open(str(path) + '.gz', 'wb', compresslevel=2) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
    for kind in ('span', 'cache'):
        before, after = (report['runs'][f'{kind}_{label}'] for label in ('reference', 'current'))
        report['changes'][kind] = dict(resource_delta={key: after['resources'][key] - before['resources'][key]
                for key in ('logic_lut_cells', 'flip_flops', 'dsp48e1', 'ramb18e1', 'carry4',
                            'distributed_ram_lut_sites_nominal')},
                combinational_levels=[before['longest_combinational_path_cells'],
                                      after['longest_combinational_path_cells']])
    if digest(ROOT / SOURCE) != report['source_sha256']['current'] or any(
            digest(ROOT / name) != value for name, value in report['common_sha256'].items()):
        raise RuntimeError('Source changed during synthesis')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['changes']), flush=True)


if __name__ == '__main__':
    main()
