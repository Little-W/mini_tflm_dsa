#!/usr/bin/env python3
"""检查编译开关消除紧凑硬件，以及 RAM 返回数据的寄存器边界。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/rtl'))
from source_files import input_files, with_dependencies


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ram_reaches_output(module):
    reached = {bit for name, port in module['ports'].items()
        if name.startswith('ram_port_rd_data') for bit in port['bits'] if isinstance(bit, int)}
    remaining = list(module['cells'].values())
    while remaining:
        next_cells = []
        changed = False
        for cell in remaining:
            cell_type = cell['type'].lower()
            if any(token in cell_type for token in ('dff', 'latch', 'mem')):
                continue
            inputs = {bit for port, bits in cell['connections'].items()
                if cell['port_directions'][port] == 'input' for bit in bits if isinstance(bit, int)}
            if inputs & reached:
                reached.update(bit for port, bits in cell['connections'].items()
                    if cell['port_directions'][port] == 'output' for bit in bits if isinstance(bit, int))
                changed = True
            else:
                next_cells.append(cell)
        if not changed:
            break
        remaining = next_cells
    return any(bit in reached for name, port in module['ports'].items()
        if name.startswith('ia_out') for bit in port['bits'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = with_dependencies([ROOT / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'], ROOT)
    sources = input_files([Path(__file__), ROOT / 'scripts/rtl/source_files.py', *rtl], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    cases = []
    for compact in (0, 1):
        netlist = out / f'compact_{compact}.json'
        script = out / f'compact_{compact}.ys'
        log = out / f'compact_{compact}.log'
        script.write_text('\n'.join([
            'read_slang --top ia_loader_cache_mgr -GEXTERNAL_RAM=1 '
            '-GBUS_WIDTH=64 -GDMA_LANES=8 -Gp_compact_offset_width=9 '
            f'-GCOMPACT_S8={compact} ' + ' '.join(shlex.quote(str(path)) for path in rtl),
            'prep -top ia_loader_cache_mgr', 'opt',
            'write_json ' + shlex.quote(str(netlist)),
        ]) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        module = json.loads(netlist.read_text())['modules']['ia_loader_cache_mgr']
        names = module['netnames']
        local_ram_names = [name for name in (*names, *module['cells']) if 'g_local_ram' in name]
        assert not local_ram_names, local_ram_names
        register_bits = sum(len(net['bits']) for name, net in names.items()
            if 'g_read_register' in name and name.endswith('.data_q'))
        restore_lanes = sum(1 for name in names if 'g_read_register' in name and name.endswith('.restore_sum'))
        slot_bits = len(module['ports']['wr_slot']['bits'])
        direct_path = ram_reaches_output(module)
        compact_input_users = {}
        for port in ('compact_mode', 'compact_offset'):
            bits = set(module['ports'][port]['bits'])
            compact_input_users[port] = sum(1 for cell in module['cells'].values()
                if any(bits.intersection(values) for name, values in cell['connections'].items()
                    if cell['port_directions'][name] == 'input'))
        assert register_bits == (256 if compact else 0), register_bits
        assert restore_lanes == (16 if compact else 0), restore_lanes
        assert slot_bits == (3 if compact else 2), slot_bits
        assert direct_path == (not compact), direct_path
        if not compact:
            assert names['compact_active']['bits'] == ['0']
            assert not any('u_restore' in name for name in names)
            assert not any(compact_input_users.values())
        case = dict(compact_enabled=compact, external_ram=True, local_data_ram_instances=0,
            data_register_bits=register_bits,
            restore_lanes=restore_lanes, slot_address_bits=slot_bits,
            ram_to_output_combinational_path=direct_path, compact_input_users=compact_input_users,
            netlist_sha256=digest(netlist),
            log_sha256=digest(log))
        cases.append(case)
        print(json.dumps(case), flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('Sources changed during structure checks')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True,
        source_sha256=hashes, cases=cases), indent=2) + '\n')


if __name__ == '__main__':
    main()
