#!/usr/bin/env python3
"""将六输入函数及其零余因子合并为具有共同真值表的 LUT6_2。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function_key(table, inputs):
    """按照净信号编号排序，并从真值表中去掉无关输入。"""
    ordered = sorted(inputs)
    normalized = 0
    for address in range(1 << len(inputs)):
        values = {bit: (address >> index) & 1 for index, bit in enumerate(ordered)}
        original = sum(values[bit] << index for index, bit in enumerate(inputs))
        normalized |= ((table >> original) & 1) << address
    used = [index for index in range(len(ordered))
            if any(((normalized >> address) ^ (normalized >> (address | (1 << index)))) & 1
                   for address in range(1 << len(ordered)) if not address & (1 << index))]
    reduced = 0
    for address in range(1 << len(used)):
        original = sum(((address >> index) & 1) << position for index, position in enumerate(used))
        reduced |= ((normalized >> original) & 1) << address
    return tuple(ordered[index] for index in used), reduced


def lut_info(cell):
    match = re.fullmatch(r'LUT([1-6])', cell.get('type', ''))
    if not match:
        return None, 'other_cell'
    width = int(match.group(1))
    if set(cell.get('parameters', {})) != {'INIT'}:
        return None, 'parameters'
    # 仅改变普通逻辑单元；物理位置、保持和其他专用属性由原有流程处理。
    if set(cell.get('attributes', {})) - {'src', 'module_not_derived'}:
        return None, 'attributes'
    ports = cell.get('connections', {})
    if set(ports) != {'O'} | {f'I{index}' for index in range(width)}:
        return None, 'ports'
    if any(len(bits) != 1 or not isinstance(bits[0], int) for bits in ports.values()):
        return None, 'constant_or_disconnected_port'
    inputs = [ports[f'I{index}'][0] for index in range(width)]
    if len(set(inputs)) != width:
        return None, 'repeated_input'
    if ports['O'][0] in inputs:
        return None, 'feedback'
    directions = cell.get('port_directions', {})
    if directions != {'O': 'output'} | {f'I{index}': 'input' for index in range(width)}:
        return None, 'port_directions'
    value = cell['parameters']['INIT']
    if not isinstance(value, str) or len(value) != 1 << width or not re.fullmatch('[01]+', value):
        return None, 'truth_table'
    return {'width': width, 'inputs': inputs, 'output': ports['O'][0], 'table': int(value, 2)}, None


class CombinationalDependencies:
    """保守检查组合可达关系，并在每次融合后更新共享单元的依赖。"""

    def __init__(self, cells, users):
        self.successors = defaultdict(set)
        self.predecessors = defaultdict(set)
        for name, cell in cells.items():
            kind = cell['type']
            if re.fullmatch(r'FD(?:RE|SE|CE|PE)(?:_1)?', kind) or kind.startswith('RAMB'):
                continue
            for port, bits in cell.get('connections', {}).items():
                if cell.get('port_directions', {}).get(port) != 'output':
                    continue
                if kind == 'DSP48E1':
                    parameter = {'ACOUT': 'AREG', 'BCOUT': 'BREG'}.get(port, 'PREG')
                    value = cell.get('parameters', {}).get(parameter, 0)
                    registered = int(value, 2) if isinstance(value, str) else value
                    if registered:
                        continue
                for bit in bits:
                    for user, _ in users.get(bit, []):
                        if user != name:
                            self.successors[name].add(user)
                            self.predecessors[user].add(name)

    def reachable(self, start, target):
        pending = [start]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(self.successors.get(current, ()))
        return False

    def independent(self, upper, lower):
        return not self.reachable(upper, lower) and not self.reachable(lower, upper)

    def merge(self, upper, lower):
        # 合并后的单元共用输入，后续候选必须使用更新后的组合连接。
        assert self.independent(upper, lower)
        before = self.predecessors.pop(lower, set())
        after = self.successors.pop(lower, set())
        for source in before:
            self.successors[source].discard(lower)
            self.successors[source].add(upper)
        for target in after:
            self.predecessors[target].discard(lower)
            self.predecessors[target].add(upper)
        self.predecessors[upper].update(before)
        self.successors[upper].update(after)


def fuse_module(module, maximum_pairs=None):
    cells = module['cells']
    users = defaultdict(list)
    drivers = defaultdict(list)
    observed = set()
    for port in module.get('ports', {}).values():
        if port['direction'] == 'output':
            observed.update(port['bits'])
    for name, cell in cells.items():
        for port, bits in cell.get('connections', {}).items():
            direction = cell.get('port_directions', {}).get(port)
            for bit in bits:
                if direction == 'input':
                    users[bit].append((name, port))
                elif direction == 'output':
                    drivers[bit].append((name, port))
    dependencies = CombinationalDependencies(cells, users)
    eligible = {}
    skipped = Counter()
    for name, cell in sorted(cells.items()):
        info, reason = lut_info(cell)
        if reason:
            skipped[reason] += 1
            continue
        output = info['output']
        if drivers[output] != [(name, 'O')]:
            skipped['multiple_drivers'] += 1
            continue
        if not users[output] and output not in observed:
            skipped['unobserved_output'] += 1
            continue
        if any(re.fullmatch(r'CARRY4|MUXF[789]|RAM.*|SRL.*', cells[user]['type'])
               for user, _ in users[output]):
            skipped['dedicated_consumer'] += 1
            continue
        eligible[name] = info
    lower_by_function = defaultdict(list)
    for name, info in eligible.items():
        if info['width'] <= 5:
            lower_by_function[function_key(info['table'], info['inputs'])].append(name)
    pairs = []
    used_lower = set()
    comparisons = 0
    for upper_name, upper in eligible.items():
        if upper['width'] != 6:
            continue
        if maximum_pairs is not None and len(pairs) >= maximum_pairs:
            break
        choices = []
        for selected in range(6):
            remaining = [bit for index, bit in enumerate(upper['inputs']) if index != selected]
            low_table = 0
            for address in range(32):
                original = (address & ((1 << selected) - 1)) | ((address >> selected) << (selected + 1))
                low_table |= ((upper['table'] >> original) & 1) << address
            key = function_key(low_table, remaining)
            for lower_name in lower_by_function.get(key, []):
                if lower_name in used_lower:
                    continue
                lower = eligible[lower_name]
                if not set(lower['inputs']).issubset(remaining) or lower['output'] in upper['inputs']:
                    continue
                common_prefix = 0
                for left, right in zip(upper_name.split('.'), lower_name.split('.')):
                    if left != right:
                        break
                    common_prefix += 1
                choices.append((-common_prefix, lower_name, selected, remaining))
        if not choices:
            continue
        chosen = None
        for choice in sorted(choices):
            if dependencies.independent(upper_name, choice[1]):
                chosen = choice
                break
            skipped['combinational_dependency'] += 1
        if chosen is None:
            continue
        _, lower_name, selected, remaining = chosen
        lower = eligible[lower_name]
        reordered = remaining + [upper['inputs'][selected]]
        merged_table = 0
        # 对原上半函数的 64 种输入逐项比较，同时验证 O5 与所选零余因子相等。
        for address in range(64):
            values = {bit: (address >> index) & 1 for index, bit in enumerate(reordered)}
            original = sum(values[bit] << index for index, bit in enumerate(upper['inputs']))
            upper_value = (upper['table'] >> original) & 1
            merged_table |= upper_value << address
        for address in range(64):
            values = {bit: (address >> index) & 1 for index, bit in enumerate(reordered)}
            lower_address = sum(values[bit] << index for index, bit in enumerate(lower['inputs']))
            assert (lower['table'] >> lower_address) & 1 == (merged_table >> (address & 31)) & 1
            original = sum(values[bit] << index for index, bit in enumerate(upper['inputs']))
            assert (upper['table'] >> original) & 1 == (merged_table >> address) & 1
            comparisons += 2
        original_upper, original_lower = cells[upper_name], cells[lower_name]
        attributes = dict(original_upper.get('attributes', {}))
        sources = list(dict.fromkeys(cell.get('attributes', {}).get('src', '')
                                    for cell in (original_upper, original_lower)))
        if any(sources):
            attributes['src'] = '|'.join(value for value in sources if value)
        cells[upper_name] = {
            **original_upper, 'type': 'LUT6_2', 'attributes': attributes,
            'parameters': {'INIT': f'{merged_table:064b}'},
            'port_directions': {f'I{index}': 'input' for index in range(6)} | {'O5': 'output', 'O6': 'output'},
            'connections': {f'I{index}': [bit] for index, bit in enumerate(reordered)} |
                           {'O5': [lower['output']], 'O6': [upper['output']]},
        }
        del cells[lower_name]
        dependencies.merge(upper_name, lower_name)
        used_lower.add(lower_name)
        pairs.append({'upper': upper_name, 'lower': lower_name, 'selected_original_input': f'I{selected}',
                      'sixth_input_net': reordered[5], 'common_input_nets': remaining,
                      'upper_output_net': upper['output'], 'lower_output_net': lower['output'],
                      'original_upper_init': f"{upper['table']:064b}",
                      'original_lower_init': original_lower['parameters']['INIT'],
                      'merged_init': f'{merged_table:064b}', 'output_comparisons': 128})
    return {'pair_count': len(pairs), 'eligible_lut6': sum(info['width'] == 6 for info in eligible.values()),
            'eligible_small_luts': sum(info['width'] <= 5 for info in eligible.values()),
            'excluded_cells': dict(sorted(skipped.items())), 'pairs': pairs,
            'output_comparisons': comparisons, 'all_pair_truth_tables_verified': True,
            'combinational_dependencies_checked': True,
            'dependency_method': 'Conservative cell connectivity with clocked output boundaries; direct and indirect dependencies are excluded and the graph is updated after each merge',
            'physical_lut_savings': None,
            'physical_validation': 'Requires completed legal placement and routed configuration checks',
            'implementation_environment_required': {'XC7_LUT_COFACTOR': '1'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--report', type=Path, required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--out', type=Path)
    output.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--maximum-pairs', type=int)
    args = parser.parse_args()
    if args.maximum_pairs is not None and args.maximum_pairs < 0:
        parser.error('--maximum-pairs must be nonnegative')
    design = json.loads(args.mapped.read_text())
    report = fuse_module(design['modules'][args.top], args.maximum_pairs)
    report.update(mapped_sha256=digest(args.mapped), tool_sha256=digest(Path(__file__)), top=args.top)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(args.out.suffix + '.tmp')
        temporary.write_text(json.dumps(design, separators=(',', ':')) + '\n')
        temporary.replace(args.out)
        report['output_sha256'] = digest(args.out)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('pair_count', 'eligible_lut6', 'eligible_small_luts',
                                                  'output_comparisons', 'all_pair_truth_tables_verified')}))


if __name__ == '__main__':
    main()
