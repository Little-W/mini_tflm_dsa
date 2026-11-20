#!/usr/bin/env python3
"""让一个 LUT 与触发器组和独立组合 LUT 共用物理位置。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from pair_packed_luts import candidates as ordinary_candidates, functional_digest
from pair_registered_luts import candidates as registered_candidates


def select_pairs(registered, ordinary, maximum_pairs=None):
    by_input = collections.defaultdict(set)
    for name, item in ordinary.items():
        for bit in item['variable_inputs']:
            by_input[bit].add(name)
    active = set(ordinary)
    pairs = []
    for first in sorted(registered, key=lambda name: (-len(registered[name]['inputs']), name)):
        if maximum_pairs is not None and len(pairs) >= maximum_pairs:
            break
        left = registered[first]
        neighbors = set().union(*(by_input[bit] for bit in left['variable_inputs'])) if left['variable_inputs'] else set()
        possible = []
        for second in neighbors & active:
            right = ordinary[second]
            if (len(left['inputs'] | right['inputs']) > 5 or
                    left['output'] in right['inputs'] or right['output'] in left['inputs']):
                continue
            shared = len(left['variable_inputs'] & right['variable_inputs'])
            possible.append((-shared, -len(right['inputs']), second))
        if possible:
            second = min(possible)[2]
            active.remove(second)
            pairs.append((first, second))
    return pairs


def constrain_pairs(module, registered, ordinary, pairs):
    current_registered, _ = registered_candidates(module)
    current_ordinary, _ = ordinary_candidates(module)
    used = set()
    for first, second in pairs:
        if first in used or second in used or first == second:
            raise ValueError('Each LUT can belong to one new group')
        if (first not in current_registered or second not in current_ordinary or
                registered[first] != current_registered[first] or ordinary[second] != current_ordinary[second]):
            raise ValueError('The inspected group or ordinary LUT has changed')
        left, right = registered[first], ordinary[second]
        if (len(left['inputs'] | right['inputs']) > 5 or not left['variable_inputs'] & right['variable_inputs'] or
                left['output'] in right['inputs'] or right['output'] in left['inputs']):
            raise ValueError('LUT inputs are incompatible')
        upper = module['cells'][first]['attributes']
        lower = module['cells'][second].setdefault('attributes', {})
        # 寄存结果使用 O6/FF，组合结果使用 O5/OUTMUX，保留原有触发器相对位置。
        upper['CONSTR_CHILDREN'] = ';'.join((left['register'], second))
        lower.update(CONSTR_PARENT=first, CONSTR_X=f'{0:032b}', CONSTR_Y=f'{0:032b}',
                     CONSTR_Z=f'{1:032b}', CONSTR_ABS_Z=f'{0:032b}')
        used.update((first, second))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--top')
    parser.add_argument('--maximum-pairs', type=int)
    args = parser.parse_args()
    if args.packed.resolve() == args.out.resolve():
        parser.error('Use a separate output file')
    if args.maximum_pairs is not None and args.maximum_pairs < 0:
        parser.error('--maximum-pairs must be nonnegative')
    design = json.loads(args.packed.read_bytes())
    modules = design['modules']
    if args.top is None and len(modules) != 1:
        parser.error('Specify --top for multiple modules')
    if args.top is not None and args.top not in modules:
        parser.error('The requested top is absent')
    module = modules[args.top] if args.top else next(iter(modules.values()))
    if module.get('attributes', {}).get('step') != 'pack':
        parser.error('The input must be a packed design')
    registered, registered_excluded = registered_candidates(module)
    ordinary, ordinary_excluded = ordinary_candidates(module)
    pairs = select_pairs(registered, ordinary, args.maximum_pairs)
    before = functional_digest(module)
    constrain_pairs(module, registered, ordinary, pairs)
    if functional_digest(module) != before:
        raise RuntimeError('Logical contents changed during constraint grouping')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(design, separators=(',', ':')) + '\n')
    result = {'candidate_registered_groups': len(registered), 'candidate_ordinary_luts': len(ordinary),
              'pair_count': len(pairs), 'registered_excluded': registered_excluded, 'ordinary_excluded': ordinary_excluded,
              'functional_cells_sha256': before, 'cell_contents_preserved': True,
              'pairs': [{'upper': first, 'lower': second, 'register': registered[first]['register'],
                         'unique_inputs': len(registered[first]['inputs'] | ordinary[second]['inputs']),
                         'shared_variable_inputs': len(registered[first]['variable_inputs'] & ordinary[second]['variable_inputs'])}
                        for first, second in pairs],
              'physical_lut_positions': None, 'placement_complete': False,
              'method': '输入并集至多五个且至少共享一个非常量输入；寄存器组使用O6/FF，独立组合LUT使用O5/OUTMUX。原有触发器位置关系和全部逻辑保持，实际面积由合法布局统计。'}
    for label, path in [('source_packed_sha256', args.packed), ('output_packed_sha256', args.out)]:
        with path.open('rb') as source:
            result[label] = hashlib.file_digest(source, 'sha256').hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('candidate_registered_groups', 'candidate_ordinary_luts', 'pair_count', 'cell_contents_preserved')}))


if __name__ == '__main__':
    main()
