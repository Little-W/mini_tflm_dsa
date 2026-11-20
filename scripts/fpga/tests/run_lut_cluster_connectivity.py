#!/usr/bin/env python3
"""验证 LUT 相对位置组的连通性、完整布局布线及所有输出函数。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_fpga_implementation import run_command
from open_fpga_synth import digest
from placed_resources import placed_resources
from check_json_init import logical_pins, module, names
from run_lut_output_implementation import check_split

ROOT = 'u_admission$LUT6'
CHILD = 'u_admission$LUT5'
FF = 'u_result'


def design(table, live_output, nested=False):
    live = 'lower' if live_output == 'O5' else 'upper' if live_output == 'O6' else 'state[0]'
    direct = 'i_data[0]' if nested else live
    return f'''module soc_top (
    input wire clk,
    input wire [4:0] i_data,
    output wire [1:0] o_data
);
    wire [4:0] state;
    // 保留两个输出网络，使未使用半部仍参与真实打包和相对位置约束。
    (* keep = 1 *) wire lower;
    (* keep = 1 *) wire upper;
    for (genvar index = 0; index < 5; index = index + 1) begin : g_state
        FDRE #(.INIT(1'b0)) u_state (
            .C(clk), .CE(1'b1), .R(1'b0), .D(i_data[index]), .Q(state[index])
        );
    end
    LUT6_2 #(.INIT(64'h{table:016x})) u_admission (
        .I0(state[0]), .I1(state[1]), .I2(state[2]), .I3(state[3]),
        .I4(state[4]), .I5(1'b1), .O5(lower), .O6(upper)
    );
    assign o_data[0] = {direct};
    FDRE #(.INIT(1'b0)) u_result (
        .C(clk), .CE(1'b1), .R(1'b0), .D({live}), .Q(o_data[1])
    );
endmodule
'''


def children(cell):
    return [name for name in cell.get('attributes', {}).get('CONSTR_CHILDREN', '').split(';') if name]


def functional_signature(m):
    return {name: {key: cell[key] for key in ('type', 'parameters', 'port_directions', 'connections')}
            for name, cell in m['cells'].items()}


def nested_constraints(original, destination, secondary):
    netlist = json.loads(original.read_text())
    m = next(item for item in netlist['modules'].values() if item.get('cells'))
    before = functional_signature(m)
    attributes_before = {name: dict(cell['attributes']) for name, cell in m['cells'].items()}
    cells = m['cells']
    assert children(cells[ROOT]) == [CHILD]
    assert cells[CHILD]['attributes']['CONSTR_PARENT'] == ROOT
    assert not children(cells[CHILD]) and not cells[FF]['attributes'].get('CONSTR_PARENT')
    assert cells[FF]['type'] == 'SLICE_FFX'
    # LUT5 位于 Z=1；O5 使用 Z=3 的 5FF，外部数据使用 Z=2 的主 FF。
    ff_z = 3 if secondary else 2
    cells[CHILD]['attributes']['CONSTR_CHILDREN'] = FF
    cells[FF]['attributes'].update(CONSTR_PARENT=CHILD, CONSTR_X='0' * 32,
                                  CONSTR_Y='0' * 32, CONSTR_Z=format(ff_z - 1, '032b'),
                                  CONSTR_ABS_Z='0' * 32)
    assert functional_signature(m) == before
    changed = {name: sorted(key for key in set(attributes_before[name]) | set(cell['attributes'])
                            if attributes_before[name].get(key) != cell['attributes'].get(key))
               for name, cell in cells.items()}
    changed = {name: keys for name, keys in changed.items() if keys}
    assert changed == {CHILD: ['CONSTR_CHILDREN'],
                       FF: ['CONSTR_ABS_Z', 'CONSTR_PARENT', 'CONSTR_X', 'CONSTR_Y', 'CONSTR_Z']}
    destination.write_text(json.dumps(netlist, indent=2) + '\n')
    return {'passed': True, 'functions_and_connections_preserved': True,
            'hierarchy': [ROOT, CHILD, FF], 'relative_z': [0, 1, ff_z],
            'changed_attributes': changed,
            'original_sha256': digest(original), 'constrained_sha256': digest(destination)}


def connectivity(m):
    drivers, users = defaultdict(list), defaultdict(list)
    for name, cell in m['cells'].items():
        for port, bits in cell['connections'].items():
            for bit in bits:
                (drivers if cell['port_directions'][port] == 'output' else users)[bit].append((name, port))
    result = {}
    for name in (ROOT, CHILD, FF):
        cell = m['cells'][name]
        meaningful = [(port, bit) for port, bits in cell['connections'].items() for bit in bits
                      if drivers[bit] and users[bit]]
        result[name] = {'direct_connectivity': bool(meaningful),
                        'logical_inputs': sorted(logical_pins(cell)),
                        'children': children(cell),
                        'parent': cell.get('attributes', {}).get('CONSTR_PARENT'),
                        'output_users': {port: sum(len(users[bit]) for bit in bits)
                                         for port, bits in cell['connections'].items()
                                         if cell['port_directions'][port] == 'output'}}
    return result


def check_output_connections(mapped, packed, live_output, nested=False):
    old = json.loads(mapped.read_text())['modules']['soc_top']
    new = module(packed)
    old_names, new_names = names(old), names(new)
    primitive = old['cells']['u_admission']
    assert primitive['connections']['I5'] == ['1']
    def pad_buffer(prefix, original_type):
        matches = [cell for name, cell in new['cells'].items() if name.startswith(prefix + '$')
                   and cell['attributes'].get('X_ORIG_TYPE') == original_type]
        assert len(matches) == 1, (prefix, original_type)
        return matches[0]

    output_buffers = [pad_buffer(f'o_data[{index}]', 'OBUF') for index in range(2)]
    ports = {}
    for output, name in (('O5', CHILD), ('O6', ROOT)):
        current = new['cells'][name]
        assert primitive['connections'][output] and current['connections'][output]
        old_bit, new_bit = primitive['connections'][output][0], current['connections'][output][0]
        users = [(n, p) for n, cell in new['cells'].items() for p, bits in cell['connections'].items()
                 if cell['port_directions'][p] == 'input' and new_bit in bits]
        assert bool(users) == (output == live_output), (output, users, live_output)
        if output == live_output:
            assert old['cells'][FF]['connections']['D'] == [old_bit]
            assert new['cells'][FF]['connections']['D'] == [new_bit]
            if not nested:
                assert old['ports']['o_data']['bits'][0] == old_bit
                assert output_buffers[0]['connections']['IN'] == [new_bit]
        else:
            assert old_names[old_bit] & new_names[new_bit], (name, output)
        ports[output] = {'used': bool(users), 'users': users,
                         'source_aliases': sorted(old_names[old_bit]),
                         'implementation_aliases': sorted(new_names[new_bit])}
    for index in range(5):
        ff = new['cells'][f'g_state[{index}].u_state']
        assert ff['connections']['D'] == pad_buffer(f'i_data[{index}]', 'IBUF')['connections']['OUT']
        assert ff['connections']['CK'] == new['cells'][FF]['connections']['CK']
    assert new['cells'][FF]['connections']['Q'] == output_buffers[1]['connections']['IN']
    if nested:
        assert output_buffers[0]['connections']['IN'] == pad_buffer('i_data[0]', 'IBUF')['connections']['OUT']
    if live_output is None:
        value = new['cells']['g_state[0].u_state']['connections']['Q']
        assert new['cells'][FF]['connections']['D'] == value
        if not nested:
            assert output_buffers[0]['connections']['IN'] == value
    return {'passed': True, 'fixed_i5': 1, 'outputs': ports, 'input_register_connections_checked': 5,
            'output_register_connection_checked': True}


def check_placement(packed, physical, nested, secondary):
    old, new = module(packed), module(physical)
    assert old['cells'].keys() <= new['cells'].keys()
    result = placed_resources(new)
    assert result['placement_complete'] and not result['resource_errors'] and not result['unplaced_cells']
    bels = {name: cell['attributes']['NEXTPNR_BEL'] for name, cell in new['cells'].items()}
    assert len(set(bels.values())) == len(bels)
    root_site, root_bel = bels[ROOT].split('/')
    child_site, child_bel = bels[CHILD].split('/')
    assert root_site == child_site and root_bel[0] == child_bel[0]
    assert root_bel.endswith('6LUT') and child_bel.endswith('5LUT')
    if nested:
        ff_site, ff_bel = bels[FF].split('/')
        assert ff_site == root_site and ff_bel == root_bel[0] + ('5FF' if secondary else 'FF')
    return {'passed': True, 'all_cells_have_unique_bels': True, 'cell_count': len(bels),
            'cluster_bels': {name: bels[name] for name in (ROOT, CHILD, FF)}, 'resources': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('nextpnr', 'chipdb', 'source', 'package-pins', 'tilegrid', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--with-output-regressions', action='store_true')
    parser.add_argument('--cases', nargs='+', help='选择独立案例；默认执行全部六项')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    environment = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_LUT_COFACTOR='1',
                       NEXTPNR_HEAP_MAX_ITERS='2', NEXTPNR_REFINE_MAX_ITERS='1')
    common = [str(args.nextpnr.resolve()), '--chipdb', str(args.chipdb.resolve()),
              '--freq', '150', '--seed', '1', '--strict-timing-graph', '--timing-allow-fail']
    cases = {
        'unused_o6_zero': (0x0000000069969669, 'O5', False),
        'unused_o6_one': (0xffffffff69969669, 'O5', False),
        'unused_o6_logic': (0xf0f0cc0069969669, 'O5', False),
        'unused_o5_logic': (0x966969960ff0f00f, 'O6', False),
        'unused_o6_nested_ff': (0x0000000069969669, 'O5', True),
        'only_grandchild_connected': (0x00000000ffffffff, None, True),
    }
    if args.cases:
        if len(set(args.cases)) != len(args.cases) or any(name not in cases for name in args.cases):
            parser.error('--cases requires distinct names from: ' + ', '.join(cases))
        cases = {name: cases[name] for name in args.cases}
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx'
    report = {'nextpnr_sha256': digest(args.nextpnr), 'chipdb_sha256': digest(args.chipdb),
              'packer_source_sha256': digest(args.source / 'pack.cc'),
              'placer_source_sha256': digest(args.source.parent / 'common/placer_heap.cc'),
              'placement_fixup_source_sha256': digest(args.source / 'arch_place.cc'),
              'fasm_source_sha256': digest(args.source / 'fasm.cc'),
              'primitive_models_sha256': {name: digest(library / name)
                                         for name in ('cells_sim.v', 'cells_xtra.v')},
              'checker_sha256': {name: digest(scripts / name) for name in
                                ('run_lut_output_implementation.py', 'check_json_init.py', 'check_emitted_fasm.py')},
              'runner_sha256': digest(Path(__file__)), 'cases_requested': list(cases), 'cases': {}}
    for name, (table, live_output, nested) in cases.items():
        folder = out / name
        folder.mkdir(exist_ok=True)
        source = folder / 'design.sv'
        source.write_text(design(table, live_output, nested))
        prepare = folder / 'prepare.ys'
        prepare.write_text('read_verilog -lib -specify +/xilinx/cells_sim.v\n'
                           'read_verilog -lib +/xilinx/cells_xtra.v\n'
                           f'read_verilog -sv {source}\nhierarchy -check -top soc_top\n'
                           'clean\ncheck -assert\nblackbox =A:whitebox\n'
                           f'write_json {folder}/mapped.json\n')
        stages = {'prepare': run_command(
            [sys.executable, str(scripts.parent / 'open_fpga_synth.py'), '--worker', str(prepare)],
            folder, '01_prepare', environment)}
        implementation = folder / 'implementation'
        command = [sys.executable, str(scripts.parent / 'open_fpga_implementation.py'),
                   '--mapped', str(folder / 'mapped.json'), '--nextpnr', str(args.nextpnr.resolve()),
                   '--chipdb', str(args.chipdb.resolve()), '--out', str(implementation),
                   '--through', 'pack', '--soc-package-pins', str(args.package_pins.resolve()),
                   '--allow-timing-failure']
        stages['pack'] = run_command(command, folder, '02_pack', environment)
        packed = implementation / 'packed.json'
        split_checks = check_split(folder / 'mapped.json', packed)
        output_checks = check_output_connections(folder / 'mapped.json', packed, live_output, nested)
        constraints = None
        if nested:
            constrained = folder / 'constrained.json'
            constraints = nested_constraints(packed, constrained, live_output == 'O5')
            packed = constrained
        connected = connectivity(module(packed))
        if name in ('unused_o6_zero', 'unused_o6_one', 'unused_o6_nested_ff'):
            assert not connected[ROOT]['direct_connectivity'] and connected[CHILD]['direct_connectivity']
            assert not connected[ROOT]['logical_inputs'] and connected[ROOT]['output_users']['O6'] == 0
        elif name == 'only_grandchild_connected':
            assert not connected[ROOT]['direct_connectivity'] and not connected[CHILD]['direct_connectivity']
            assert connected[FF]['direct_connectivity']
        else:
            assert connected[ROOT]['direct_connectivity']
        assert connected[ROOT]['children'] == [CHILD]
        stages['place'] = run_command(common + ['--json', str(packed), '--no-pack', '--no-route',
            '--write', str(folder / 'placed.json')], folder, '03_place', environment)
        placed_checks = check_placement(packed, folder / 'placed.json', nested, live_output == 'O5')
        stages['route'] = run_command(common + ['--json', str(folder / 'placed.json'), '--no-pack',
            '--no-place', '--write', str(folder / 'routed.json'), '--fasm', str(folder / 'design.fasm')],
            folder, '04_route', environment)
        routed_checks = check_placement(packed, folder / 'routed.json', nested, live_output == 'O5')
        routed_outputs = check_output_connections(folder / 'mapped.json', folder / 'routed.json', live_output, nested)
        stages['truth'] = run_command([sys.executable, str(scripts / 'check_json_init.py'),
            '--packed', str(packed), '--physical', str(folder / 'routed.json'),
            '--source', str(args.source.resolve()), '--out', str(folder / 'truth')],
            folder, '05_truth', environment)
        stages['fasm'] = run_command([sys.executable, str(scripts / 'check_emitted_fasm.py'),
            '--physical', str(folder / 'routed.json'), '--fasm', str(folder / 'design.fasm'),
            '--lut-init', str(folder / 'truth/physical_lut_init.json'),
            '--tilegrid', str(args.tilegrid.resolve()), '--out', str(folder / 'fasm_checks.json')],
            folder, '06_fasm', environment)
        truth = json.loads((folder / 'truth/summary.json').read_text())
        fasm = json.loads((folder / 'fasm_checks.json').read_text())
        assert truth['passed'] and fasm['passed']
        report['cases'][name] = {'passed': True, 'placement_complete': True, 'routing_complete': True,
            'init_hex': f'{table:016x}', 'live_output': live_output, 'nested_ff': nested,
            'split_checks': split_checks, 'output_connections': output_checks,
            'routed_output_connections': routed_outputs,
            'connectivity': connected, 'constraints': constraints,
            'placed_checks': placed_checks, 'routed_checks': routed_checks,
            'truth_checks': truth, 'fasm_checks': fasm, 'stages': stages,
            'source_sha256': digest(source), 'packed_sha256': digest(packed),
            'routed_sha256': digest(folder / 'routed.json'), 'fasm_sha256': digest(folder / 'design.fasm')}
        (folder / 'summary.json').write_text(json.dumps(report['cases'][name], ensure_ascii=False, indent=2) + '\n')
        print(name, 'passed', flush=True)
    if args.with_output_regressions:
        regression = out / 'independent_outputs'
        command = [sys.executable, str(scripts / 'run_lut_output_implementation.py')]
        for name in ('nextpnr', 'chipdb', 'source', 'package_pins', 'tilegrid'):
            command.extend(['--' + name.replace('_', '-'), str(getattr(args, name).resolve())])
        command.extend(['--out', str(regression)])
        run_command(command, out, '07_independent_outputs', environment)
        previous = json.loads((regression / 'summary.json').read_text())
        assert previous['passed'] and previous['nextpnr_sha256'] == report['nextpnr_sha256']
        report['independent_outputs'] = previous
    assert digest(args.nextpnr) == report['nextpnr_sha256']
    assert len(report['cases']) == len(cases)
    report['passed'] = all(case['passed'] for case in report['cases'].values())
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: value['passed'] for name, value in report['cases'].items()}), flush=True)


if __name__ == '__main__':
    main()
