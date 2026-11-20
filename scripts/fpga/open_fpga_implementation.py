#!/usr/bin/env python3
"""Pack, place and route a mapped Xilinx SoC with saved implementation stages."""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import time

from open_fpga_synth import digest, process_tree_rss
from placed_resources import placed_resources


def chipdb_identity(path):
    """Read the device name and timing-table count in the nextpnr-xilinx database."""
    with path.open('rb') as source:
        header = 4 * struct.unpack('<i', source.read(4))[0]
        if header < 0 or header + 56 > path.stat().st_size:
            raise ValueError('Unsupported nextpnr-xilinx database header')
        source.seek(header)
        fields = source.read(56)
        version = struct.unpack_from('<i', fields, 8)[0]
        if version != 1:
            raise ValueError(f'Unsupported nextpnr-xilinx database version: {version}')
        name_offset = header + 4 * struct.unpack_from('<i', fields)[0]
        source.seek(name_offset)
        name = source.read(128).split(b'\0', 1)[0].decode('ascii')
        return {'device': name, 'format_version': version,
                'timing_table_count': struct.unpack_from('<i', fields, 48)[0]}


def write_soc_constraints(module, package_pins, path, frequency):
    """Assign the standalone SoC clock and data ports to legal package pins."""
    with package_pins.open() as source:
        pin_table = {row['pin']: row for row in csv.DictReader(source)}
    board_ports = {'clk': ('R4', 'LVCMOS15'), 'rst_n': ('U7', 'LVCMOS15'),
                   'uart_rx': ('E14', 'LVCMOS33'), 'uart_tx': ('D17', 'LVCMOS33')}
    used = {pin for name, (pin, _) in board_ports.items() if name in module['ports']}
    available = iter(row['pin'] for row in pin_table.values()
                     if row['bank'] == '34' and row['site'].startswith('IOB_') and row['pin'] not in used)
    lines = ['# 独立 soc_top 资源与布线测量使用的封装引脚。',
             '# clk 直接接收 SoC 时钟；开发板顶层另用 fpga_top 及其时钟生成配置。',
             f'create_clock -name soc_clk -period {1000.0 / frequency:.9f} [get_ports clk]']
    assignments = {}
    for name, port in module['ports'].items():
        for index in range(len(port['bits'])):
            target = name if len(port['bits']) == 1 else f'{name}[{index}]'
            if name in board_ports:
                if len(port['bits']) != 1:
                    raise ValueError(f'Expected scalar SoC port: {name}')
                pin, standard = board_ports[name]
            else:
                pin = next(available, None)
                if pin is None:
                    raise ValueError('The standalone SoC requires more pins than bank 34 provides')
                standard = 'LVCMOS15'
            if pin not in pin_table:
                raise ValueError(f'Package does not contain pin {pin}')
            assignments[target] = {'package_pin': pin, 'iostandard': standard}
            lines.append(f'set_property PACKAGE_PIN {pin} [get_ports {{{target}}}]')
            lines.append(f'set_property IOSTANDARD {standard} [get_ports {{{target}}}]')
    path.write_text('\n'.join(lines) + '\n')
    return assignments


def run_command(command, folder, label, env):
    start = time.monotonic()
    peak = 0
    current = 0
    last_saved = 0
    minimum_available = None
    log_path = folder / f'{label}.log'
    progress_path = folder / f'{label}.progress.json'
    (folder / f'{label}.command.json').write_text(json.dumps(command, indent=2) + '\n')

    def save_progress(state, return_code=None):
        nonlocal minimum_available
        available = None
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):
                    available = int(line.split()[1]) * 1024
                    minimum_available = available if minimum_available is None else min(minimum_available, available)
                    break
        except OSError:
            pass
        result = {'command': command, 'log': log_path.name, 'state': state, 'return_code': return_code,
                  'elapsed_seconds': round(time.monotonic() - start, 2),
                  'peak_process_tree_rss_bytes': peak, 'current_process_tree_rss_bytes': current,
                  'system_available_memory_bytes': available,
                  'minimum_observed_system_available_memory_bytes': minimum_available,
                  'memory_sample_interval_seconds': 0.2, 'progress_save_interval_seconds': 2}
        temporary = progress_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, indent=2) + '\n')
        temporary.replace(progress_path)
        return result

    with log_path.open('w') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        interrupted = False
        try:
            while process.poll() is None:
                current = process_tree_rss(process.pid)
                peak = max(peak, current)
                if time.monotonic() - last_saved >= 2:
                    save_progress('running')
                    last_saved = time.monotonic()
                time.sleep(0.2)
        except BaseException:
            interrupted = True
            process.terminate()
            process.wait()
            raise
        finally:
            # 持续保存资源采样，子进程结束后仍可读取最后状态和内存峰值。
            state = 'interrupted' if interrupted else 'complete' if process.returncode == 0 else 'failed'
            current = 0 if process.returncode is not None else current
            result = save_progress(state, process.returncode)
    if process.returncode:
        raise RuntimeError(f'{label} failed with status {process.returncode}; see {log_path}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--part', default='xc7a200tfbg484-3')
    parser.add_argument('--freq', type=float, default=150.0)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--refinement-iterations', type=int,
                        help='Maximum SA refinement iterations; complete placement checks still run')
    parser.add_argument('--through', choices=('pack', 'place', 'route'), default='route')
    constraints = parser.add_mutually_exclusive_group(required=True)
    constraints.add_argument('--xdc', type=Path)
    constraints.add_argument('--soc-package-pins', type=Path,
                             help='Target package_pins.csv for standalone soc_top measurement')
    parser.add_argument('--lock-file', type=Path)
    parser.add_argument('--allow-timing-failure', action='store_true',
                        help='Retain routed results when the reported frequency is below the target')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.freq <= 0:
        parser.error('--freq must be positive')
    if args.refinement_iterations is not None and args.refinement_iterations <= 0:
        parser.error('--refinement-iterations must be positive')
    if args.soc_package_pins and args.top != 'soc_top':
        parser.error('--soc-package-pins requires --top soc_top')
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    mapped = args.mapped.resolve()
    binary = args.nextpnr.resolve()
    chipdb = args.chipdb.resolve()
    database_identity = chipdb_identity(chipdb)
    if database_identity['device'] != args.part:
        parser.error(f'Chip database is for {database_identity["device"]}, requested {args.part}')
    lock_handle = None
    if args.lock_file:
        args.lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = args.lock_file.open('a')
        print(f'Waiting for implementation lock: {args.lock_file}', flush=True)
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        print('Implementation lock acquired', flush=True)
    design = json.loads(mapped.read_text())
    if args.top not in design['modules']:
        parser.error(f'Mapped JSON has no top module {args.top}')
    pin_assignments = None
    if args.soc_package_pins:
        xdc = folder / 'soc_measurement.xdc'
        pin_assignments = write_soc_constraints(design['modules'][args.top], args.soc_package_pins, xdc, args.freq)
        constraint_scope = 'Standalone soc_top with a direct SoC clock input and assigned package pins'
    else:
        xdc = args.xdc.resolve()
        constraint_scope = 'User-provided XDC'
    del design
    env = os.environ.copy()
    if args.refinement_iterations is not None:
        env['NEXTPNR_REFINE_MAX_ITERS'] = str(args.refinement_iterations)
    import pyosys
    library_directory = Path(pyosys.__file__).parent / 'share/xilinx'
    version = subprocess.run([str(binary), '--version'], env=env, capture_output=True, text=True, check=True)
    manifest = {
        'part': args.part, 'top': args.top, 'frequency_mhz': args.freq,
        'clock_period_ns': 1000.0 / args.freq, 'seed': args.seed,
        'mapped_json_sha256': digest(mapped), 'nextpnr_binary_sha256': digest(binary),
        'nextpnr_version': (version.stdout + version.stderr).strip(),
        'chipdb_sha256': digest(chipdb), 'xdc_sha256': digest(xdc),
        'chipdb_identity': database_identity,
        'xilinx_libraries_sha256': {name: digest(library_directory / name) for name in ('cells_sim.v', 'cells_xtra.v')},
        'implementation_environment': {key: value for key, value in sorted(env.items())
                                       if key.startswith(('XC7_', 'NEXTPNR_'))},
        'constraint_scope': constraint_scope, 'pin_assignments': pin_assignments,
        'allow_timing_failure': args.allow_timing_failure,
        'timing_graph_policy': 'All combinational dependencies must resolve',
        'timing_model': 'Project X-Ray database; complete target speed-grade, DSP and clock timing coverage must be supplied separately',
    }
    old_stages = {}
    manifest_path = folder / 'manifest.json'
    if args.resume and manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError('Implementation inputs differ from the saved manifest')
        if (folder / 'stages.json').exists():
            old_stages = json.loads((folder / 'stages.json').read_text())
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    prepared = folder / 'implementation.json'
    prepare_script = folder / '01_prepare.ys'
    prepare_script.write_text(
        f'read_json {shlex.quote(str(mapped))}\n'
        'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
        'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
        f'hierarchy -check -top {args.top}\n'
        'clkbufmap -buf BUFG O:I\nclean\ncheck -assert\nblackbox =A:whitebox\n'
        f'write_json {shlex.quote(str(prepared))}\n')
    helper = Path(__file__).with_name('open_fpga_synth.py')
    common = [str(binary), '--chipdb', str(chipdb), '--freq', str(args.freq), '--seed', str(args.seed),
              '--strict-timing-graph']
    if args.allow_timing_failure:
        common.append('--timing-allow-fail')
    steps = [
        ('01_prepare', [sys.executable, str(helper), '--worker', str(prepare_script)], prepared),
        ('02_pack', common + ['--json', str(prepared), '--xdc', str(xdc), '--pack-only',
                             '--write', str(folder / 'packed.json')], folder / 'packed.json'),
        ('03_place', common + ['--json', str(folder / 'packed.json'), '--no-pack', '--no-route',
                              '--write', str(folder / 'placed.json'), '--report', str(folder / 'placement_timing.json')], folder / 'placed.json'),
        ('04_route', common + ['--json', str(folder / 'placed.json'), '--no-pack', '--no-place',
                              '--write', str(folder / 'routed.json'), '--report', str(folder / 'routing_timing.json')], folder / 'routed.json'),
    ]
    stages = {}
    limit = {'pack': 2, 'place': 3, 'route': 4}[args.through]
    reusable_inputs = True
    for name, command, output in steps[:limit]:
        previous = old_stages.get(name, {})
        script_sha = digest(prepare_script) if name == '01_prepare' else None
        reusable = reusable_inputs and previous.get('command') == command and previous.get('script_sha256') == script_sha and output.exists() and previous.get('output_sha256') == digest(output)
        if reusable:
            stages[name] = previous
        else:
            reusable_inputs = False
            stages[name] = run_command(command, folder, name, env)
            stages[name]['output_sha256'] = digest(output)
            stages[name]['script_sha256'] = script_sha
        (folder / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
        print(name, json.dumps(stages[name]), flush=True)
        if name in ('03_place', '04_route'):
            placed = json.loads(output.read_text())
            modules = placed['modules']
            module = modules.get(args.top) if args.top in modules else next(iter(modules.values()))
            resources = placed_resources(module)
            if not resources['placement_complete']:
                (folder / 'resource_check.json').write_text(json.dumps(resources, indent=2) + '\n')
                raise RuntimeError('Incomplete physical placement; see resource_check.json')
            resources['routing_completed'] = name == '04_route'
            resources['frequency_mhz_target'] = args.freq
            resources['timing_150mhz_confirmed'] = None
            resources['timing_validation_status'] = 'Requires complete target-device timing coverage'
            (folder / ('placed_resources.json' if name == '03_place' else 'routed_resources.json')).write_text(json.dumps(resources, indent=2) + '\n')
            print('Physical LUT positions:', resources['physical_lut_positions'], flush=True)
    if digest(mapped) != manifest['mapped_json_sha256']:
        raise RuntimeError('Mapped input changed during implementation')


if __name__ == '__main__':
    main()
