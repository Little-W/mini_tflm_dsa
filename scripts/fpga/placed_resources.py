#!/usr/bin/env python3
"""Count physical LUT positions from a complete nextpnr placement."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re


LUT_BEL = re.compile(r'^(.*[/\.])([A-D])([56])LUT$')


def placed_resources(module):
    """Combine the 5LUT and 6LUT BELs that occupy one physical LUT position."""
    cells = module['cells']
    positions = collections.defaultdict(list)
    bel_owners = {}
    unplaced = []
    problems = []
    kinds = collections.Counter()
    for name, cell in cells.items():
        kind = cell['type']
        kinds[kind] += 1
        attributes = cell.get('attributes', {})
        bel = attributes.get('NEXTPNR_BEL')
        if not bel:
            unplaced.append(name)
            continue
        if bel in bel_owners:
            problems.append(f'BEL {bel} is assigned to both {bel_owners[bel]} and {name}')
        bel_owners[bel] = name
        if kind != 'SLICE_LUTX':
            if re.fullmatch(r'LUT[1-6](?:_2)?|RAM(?:32|64|128|256).*|SRL.*', kind):
                problems.append(f'Unpacked LUT resource {name}: {kind}')
            continue
        match = LUT_BEL.fullmatch(bel)
        if not match:
            problems.append(f'Unrecognized LUT BEL {bel}: {name}')
            continue
        # nextpnr 使用属性是否存在来标记存储单元，JSON 字符串可能带空格。
        dram = 'X_LUT_AS_DRAM' in attributes
        srl = 'X_LUT_AS_SRL' in attributes
        if dram and srl:
            problems.append(f'LUT {name} has both RAM and SRL attributes')
        category = 'distributed_ram' if dram else 'shift_register' if srl else 'logic'
        position = match.group(1) + match.group(2)
        positions[position].append({'cell': name, 'bel': bel, 'use': category})

    by_use = collections.Counter()
    shared = 0
    storage_with_logic = 0
    for position, occupants in positions.items():
        uses = {item['use'] for item in occupants}
        if 'distributed_ram' in uses and 'shift_register' in uses:
            problems.append(f'RAM and SRL occupy the same LUT position: {position}')
        category = 'distributed_ram' if 'distributed_ram' in uses else 'shift_register' if 'shift_register' in uses else 'logic'
        by_use[category] += 1
        shared += len(occupants) > 1
        storage_with_logic += category != 'logic' and 'logic' in uses

    step = module.get('attributes', {}).get('step')
    complete = step in ('place', 'route') and not unplaced and not problems
    return {
        'implementation_step': step,
        'placement_complete': complete,
        'physical_lut_positions': len(positions) if complete else None,
        'physical_lut_positions_by_use': {key: by_use[key] for key in ('logic', 'distributed_ram', 'shift_register')},
        'placed_lut_bel_instances': kinds['SLICE_LUTX'] - sum(cells[name]['type'] == 'SLICE_LUTX' for name in unplaced),
        'shared_lut_positions': shared,
        'storage_positions_with_logic_output': storage_with_logic,
        'occupied_slice_sites': len({position.rsplit('/', 1)[0] for position in positions}),
        'placed_cell_counts': dict(sorted(kinds.items())),
        'unplaced_cells': sorted(unplaced),
        'resource_errors': problems,
        'counting_method': 'One physical LUT position is the common site and letter of its 5LUT and 6LUT BELs. Positions containing RAM or SRL are assigned to that storage category; all other positions are logic. The three categories are disjoint.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--top')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    design = json.loads(args.netlist.read_text())
    modules = design['modules']
    if args.top:
        module = modules[args.top]
    elif len(modules) == 1:
        module = next(iter(modules.values()))
    else:
        parser.error('--top is required when the JSON contains multiple modules')
    report = placed_resources(module)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('implementation_step', 'placement_complete', 'physical_lut_positions', 'physical_lut_positions_by_use')}, indent=2))
    if not report['placement_complete']:
        raise SystemExit('A complete placement with unique BEL assignments is required')


if __name__ == '__main__':
    main()
