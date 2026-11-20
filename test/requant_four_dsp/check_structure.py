#!/usr/bin/env python3
"""检查实际综合网表中的四个 DSP 寄存阶段、完整级联及低段输出寄存器。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, parameter, resources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    design = json.loads(args.mapped.read_text())
    module = design['modules']['registered_multiplier_s32']
    cells = module['cells']
    names = [f'g_dsp.g_partial[{index}].u_multiply.u_dsp' for index in range(4)]
    assert sum(cell['type'] == 'DSP48E1' for cell in cells.values()) == 4
    dsps = [cells[name] for name in names]
    assert [parameter(cell, 'MREG') for cell in dsps] == [0, 1, 1, 1]
    assert [parameter(cell, 'PREG') for cell in dsps] == [1, 0, 0, 1]
    assert len({parameter(cell, 'AREG') for cell in dsps}) == 1
    assert len({parameter(cell, 'BREG') for cell in dsps}) == 1
    modes = [int(''.join(reversed(cell['connections']['OPMODE'])), 2) for cell in dsps]
    assert modes == [5, 85, 21, 85]
    for index in range(1, 4):
        assert dsps[index]['connections']['PCIN'] == dsps[index - 1]['connections']['PCOUT']
    output = module['ports']['o_product']['bits']
    assert output[34:] == dsps[3]['connections']['P'][:30]
    registers = {cell['connections']['Q'][0]: cell for cell in cells.values() if cell['type'] == 'FDRE'}
    enable = module['ports']['i_en']['bits']
    for offset, dsp_index in ((0, 0), (17, 2)):
        for bit in range(17):
            cell = registers[output[offset + bit]]
            assert cell['connections']['D'] == [dsps[dsp_index]['connections']['P'][bit]]
            assert cell['connections']['CE'] == enable
    paths = connected_paths(module, limit=3, group_limit=0)
    assert paths['graph_complete']
    assert paths['longest_register_path_cells'] == 3
    report = {
        'passed': True,
        'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
        'resources': resources(cells),
        'direct_cascades': 3,
        'fabric_output_register_bits': 34,
        'dsp_registers': [
            {'name': name, **{key: parameter(cell, key) for key in ('AREG', 'BREG', 'MREG', 'PREG')}}
            for name, cell in zip(names, dsps)
        ],
        'paths': paths,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'dsp': 4, 'output_ff': 34,
                      'longest_register_path_cells': 3}))


if __name__ == '__main__':
    main()
