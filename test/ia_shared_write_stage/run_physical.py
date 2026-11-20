#!/usr/bin/env python3
"""使用相同 LUT 映射和位置配对设置比较两种共享写数据结构。"""
import argparse
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from helpers import ROOT
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_implementation import run_command
from placed_resources import placed_resources


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--xdc', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1',
               XC7_CARRY_TRIM_TAIL='1', XC7_LUT_COFACTOR='1',
               NEXTPNR_REFINE_MAX_ITERS='1', NEXTPNR_HEAP_MAX_ITERS='2')
    summary = dict(nextpnr_sha256=digest(args.nextpnr), chipdb_sha256=digest(args.chipdb),
                   xdc_sha256=digest(args.xdc), cases={})
    for name in ('reference', 'registered'):
        folder = out / name
        folder.mkdir(exist_ok=True)
        mapped = args.mapped.resolve() / name / 'mapped.json'
        stages, pairs = {}, {}

        def execute(label, command):
            stages[label] = run_command(command, folder, label, env)
            (folder / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
            print(name, label, stages[label]['elapsed_seconds'], flush=True)

        execute('01_pack', [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_implementation.py'),
            '--mapped', str(mapped), '--top', 'physical_context', '--nextpnr', str(args.nextpnr),
            '--chipdb', str(args.chipdb), '--xdc', str(args.xdc), '--out', str(folder / 'pack'),
            '--through', 'pack', '--allow-timing-failure'])
        packed, contents = folder / 'pack/packed.json', None
        for index, kind in enumerate(('packed', 'registered', 'mixed', 'carry'), 2):
            target = folder / ('paired.json' if kind == 'carry' else 'paired_' + kind + '.json')
            report = folder / ('pairing_' + kind + '.json')
            execute(f'{index:02d}_pair_{kind}', [sys.executable,
                str(ROOT / 'scripts/fpga' / f'pair_{kind}_luts.py'), '--packed', str(packed),
                '--out', str(target), '--report', str(report)])
            row = json.loads(report.read_text())
            assert row['cell_contents_preserved']
            pairs[kind] = row['pair_count']
            if contents is None:
                contents = row['functional_cells_sha256']
            assert contents == row['functional_cells_sha256']
            if packed.name != 'packed.json':
                with packed.open('rb') as source, gzip.open(str(packed) + '.gz', 'wb') as destination:
                    shutil.copyfileobj(source, destination)
                packed.unlink()
            packed = target
        execute('06_place', [str(args.nextpnr), '--chipdb', str(args.chipdb), '--freq', '150',
            '--seed', '1', '--strict-timing-graph', '--timing-allow-fail', '--json', str(packed),
            '--no-pack', '--no-route', '--write', str(folder / 'placed.json'),
            '--report', str(folder / 'timing.json')])
        design = json.loads((folder / 'placed.json').read_text())
        resources = placed_resources(next(iter(design['modules'].values())))
        del design
        gc.collect()
        assert resources['placement_complete'] and not resources['resource_errors'] and not resources['unplaced_cells']
        execute('07_pin_mapping', [sys.executable,
            str(ROOT / 'scripts/fpga/tests/check_lut_logical_pin_mapping.py'), '--packed', str(packed),
            '--physical', str(folder / 'placed.json'), '--out', str(folder / 'pin_mapping.json')])
        pin_mapping = json.loads((folder / 'pin_mapping.json').read_text())
        assert pin_mapping['passed']
        summary['cases'][name] = dict(resources=resources, pairs=pairs, stages=stages,
            pin_mapping_passed=True, mapped_sha256=digest(mapped), functional_cells_sha256=contents)
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(name, resources['physical_lut_positions'], flush=True)
        for path in folder.rglob('*.json'):
            if path.stat().st_size > 1000000:
                with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as destination:
                    shutil.copyfileobj(source, destination)
                path.unlink()
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
