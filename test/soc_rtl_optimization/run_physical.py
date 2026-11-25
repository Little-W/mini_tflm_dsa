#!/usr/bin/env python3
"""对完整 SoC 网表执行 LUT 配对、合法布局和物理资源检查。"""
import argparse
import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_implementation import run_command
from placed_resources import placed_resources


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--package-pins', type=Path, required=True)
    parser.add_argument('--freq', type=float, default=150.0)
    parser.add_argument('--max-lut-sites', type=int, default=50000,
                        help='完整 SoC 可使用的物理 LUT 位置总数上限')
    parser.add_argument('--through', choices=('pair', 'place'), default='place',
                        help='完成 LUT 配对后保存网表，或继续合法布局及资源检查')
    parser.add_argument('--resume', action='store_true', help='继续已保存且输入一致的实现阶段')
    args = parser.parse_args()
    if args.max_lut_sites < 1:
        parser.error('--max-lut-sites must be positive')
    source, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tools = out / 'tools'
    tools.mkdir(exist_ok=True)
    if not args.resume:
        for path in (ROOT / 'scripts/fpga').rglob('*.py'):
            target = tools / path.relative_to(ROOT / 'scripts/fpga')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1',
                       XC7_CARRY_TRIM_TAIL='1', XC7_LUT_COFACTOR='1',
                       NEXTPNR_REFINE_MAX_ITERS='1', NEXTPNR_HEAP_MAX_ITERS='2')
    manifest = {
        'mapped_source_sha256': digest(source / 'mapped.json'),
        'source_manifest_sha256': digest(source / 'manifest.json'),
        'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
        'tools_sha256': {str(p.relative_to(tools)): digest(p) for p in tools.rglob('*.py')},
        'frequency_mhz_target': args.freq, 'seed': 1,
        'physical_lut_positions_maximum': args.max_lut_sites,
        'placement_environment': {k: v for k, v in environment.items()
                                  if k.startswith(('XC7_', 'NEXTPNR_'))},
    }
    if args.resume:
        saved = json.loads((out / 'manifest.json').read_text())
        if any(saved.get(key) != value for key, value in manifest.items()):
            raise ValueError('当前输入与已保存的实现记录不一致')
        manifest = saved
    else:
        save(out / 'manifest.json', manifest)
    stages = json.loads((out / 'stages.json').read_text()) if args.resume else {}

    def execute(label, command):
        stages[label] = run_command(command, out, label, environment)
        save(out / 'stages.json', stages)
        print(label, stages[label]['elapsed_seconds'], flush=True)

    if args.resume:
        packed = out / 'paired.json'
        assert digest(packed) == manifest['paired_sha256']
    else:
        execute('01_pack', [sys.executable, str(tools / 'open_fpga_implementation.py'),
                '--mapped', str(source / 'mapped.json'), '--nextpnr', str(args.nextpnr),
                '--chipdb', str(args.chipdb), '--soc-package-pins', str(args.package_pins),
                '--out', str(out / 'pack'), '--through', 'pack', '--seed', '1',
                '--freq', str(args.freq), '--refinement-iterations', '1', '--allow-timing-failure'])
        packed = out / 'pack/packed.json'
        contents = None
        pairs = {}
        archives = {}
        for index, name in enumerate(('packed', 'registered', 'mixed', 'carry'), 2):
            target = out / ('paired.json' if name == 'carry' else f'paired_{name}.json')
            report = out / f'pairing_{name}.json'
            execute(f'{index:02d}_pair_{name}', [sys.executable, str(tools / f'pair_{name}_luts.py'),
                    '--packed', str(packed), '--out', str(target), '--report', str(report)])
            result = json.loads(report.read_text())
            assert result['cell_contents_preserved']
            if contents is None:
                contents = result['functional_cells_sha256']
            assert contents == result['functional_cells_sha256']
            pairs[name] = result['pair_count']
            if packed != out / 'pack/packed.json':
                archive = packed.with_suffix('.json.gz')
                expected = digest(packed)
                with packed.open('rb') as stream, gzip.open(archive, 'wb', compresslevel=1) as target_stream:
                    shutil.copyfileobj(stream, target_stream)
                with gzip.open(archive, 'rb') as stream:
                    assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected
                archives[packed.name] = {'archive': archive.name, 'uncompressed_sha256': expected}
                save(out / 'archives.json', archives)
                packed.unlink()
            packed = target
        manifest.update(pair_counts=pairs, paired_sha256=digest(packed), functional_cells_sha256=contents)
        save(out / 'manifest.json', manifest)
    if args.through == 'pair':
        return
    command = [str(args.nextpnr), '--chipdb', str(args.chipdb), '--freq', str(args.freq),
               '--seed', '1', '--strict-timing-graph', '--timing-allow-fail',
               '--json', str(packed), '--no-pack', '--no-route',
               '--write', str(out / 'placed.json'), '--report', str(out / 'placement_timing.json')]
    execute('06_place', command)
    design = json.loads((out / 'placed.json').read_text())
    resources = placed_resources(next(iter(design['modules'].values())))
    assert resources['placement_complete'] and not resources['resource_errors'] and not resources['unplaced_cells']
    del design
    gc.collect()
    execute('07_pin_mapping', [sys.executable, str(tools / 'tests/check_lut_logical_pin_mapping.py'),
            '--packed', str(packed), '--physical', str(out / 'placed.json'),
            '--out', str(out / 'pin_mapping.json')])
    mapping = json.loads((out / 'pin_mapping.json').read_text())
    assert mapping['passed'] and mapping['error_count'] == 0
    resources.update(routing_completed=False, frequency_mhz_target=args.freq,
                     timing_150mhz_confirmed=False, pin_mapping_passed=True,
                     lut_limit=args.max_lut_sites,
                     lut_limit_met=resources['physical_lut_positions'] <= args.max_lut_sites)
    save(out / 'resources.json', resources)
    print(json.dumps({k: resources[k] for k in
                      ('physical_lut_positions', 'placement_complete', 'lut_limit_met', 'pin_mapping_passed')}), flush=True)


if __name__ == '__main__':
    main()
