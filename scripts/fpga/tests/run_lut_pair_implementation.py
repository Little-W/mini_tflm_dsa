#!/usr/bin/env python3
"""运行普通 LUT 自动配对的打包、布局、布线及实际配置检查。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--tilegrid', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    lock = args.lock_file.open('a') if args.lock_file else None
    if lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
    environment = os.environ.copy()
    environment.update(XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1', XC7_CARRY_TRIM_TAIL='1')
    run_command([sys.executable, str(scripts / 'prepare_cases.py'), '--out', str(folder / 'inputs')],
                folder, '01_inputs', environment)
    result = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'placer_source_sha256': digest(args.source / 'arch_place.cc'),
              'pairing_script_sha256': digest(scripts.parent / 'pair_packed_luts.py'), 'cases': {}}
    for name, paired in (('shared_five', True), ('distinct_six', False),
                         ('repeated_six', False), ('repeated_three', True)):
        case = folder / name
        case.mkdir(exist_ok=True)
        common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()), '--freq', '150',
                  '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
        steps = {}
        steps['pack'] = run_command(common + ['--json', str(folder / 'inputs' / name / 'implementation.json'),
            '--xdc', str(folder / 'inputs' / name / 'pins.xdc'), '--pack-only', '--write', str(case / 'packed.json')],
            case, '02_pack', environment)
        steps['pair'] = run_command([sys.executable, str(scripts.parent / 'pair_packed_luts.py'), '--packed',
            str(case / 'packed.json'), '--out', str(case / 'paired.json'), '--report', str(case / 'pairing.json')],
            case, '03_pair', environment)
        pairing = json.loads((case / 'pairing.json').read_text())
        assert pairing['pair_count'] == int(paired) and pairing['cell_contents_preserved']
        steps['place'] = run_command(common + ['--json', str(case / 'paired.json'), '--no-pack', '--no-route',
            '--write', str(case / 'placed.json')], case, '04_place', environment)
        placed = json.loads((case / 'placed.json').read_text())
        resources = placed_resources(next(iter(placed['modules'].values())))
        assert resources['placement_complete'] and resources['physical_lut_positions'] == (1 if paired else 2)
        record = {'passed': True, 'pair_count': pairing['pair_count'],
                  'physical_lut_positions': resources['physical_lut_positions'], 'placement_complete': True,
                  'routing_complete': False, 'steps': steps, 'functional_cells_sha256': pairing['functional_cells_sha256']}
        if paired:
            steps['route'] = run_command(common + ['--json', str(case / 'placed.json'), '--no-pack', '--no-place',
                '--write', str(case / 'routed.json'), '--fasm', str(case / 'design.fasm')], case, '05_route', environment)
            steps['check_init'] = run_command([sys.executable, str(scripts / 'check_json_init.py'), '--packed',
                str(case / 'packed.json'), '--physical', str(case / 'routed.json'), '--source', str(args.source.resolve()),
                '--out', str(case / 'checks')], case, '06_check_init', environment)
            steps['check_fasm'] = run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'), '--physical',
                str(case / 'routed.json'), '--fasm', str(case / 'design.fasm'), '--lut-init',
                str(case / 'checks/physical_lut_init.json'), '--tilegrid', str(args.tilegrid.resolve()),
                '--out', str(case / 'fasm_checks.json')], case, '07_check_fasm', environment)
            checks = json.loads((case / 'checks/summary.json').read_text())
            assert checks['passed'] and json.loads((case / 'fasm_checks.json').read_text())['passed']
            record.update(routing_complete=True, checks=checks, routed_sha256=digest(case / 'routed.json'),
                          fasm_sha256=digest(case / 'design.fasm'))
        result['cases'][name] = record
        (folder / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    if lock:
        lock.close()
    print(json.dumps({name: item['passed'] for name, item in result['cases'].items()}), flush=True)


if __name__ == '__main__':
    main()
