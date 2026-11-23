#!/usr/bin/env python3
"""Increase equivalent standard-cell drive strengths using OpenSTA slew reports."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from run_opensta import sha256


def blocks(text: str, group: str):
    pattern = re.compile(r'\b' + group + r'\s*\(([^)]*)\)\s*\{')
    for match in pattern.finditer(text):
        depth, quoted, escaped = 1, False, False
        for index in range(match.end(), len(text)):
            char = text[index]
            if escaped:
                escaped = False
            elif char == '\\' and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                depth += int(char == '{') - int(char == '}')
                if depth == 0:
                    yield match[1].strip(), text[match.end():index]
                    break
        else:
            raise ValueError('Unterminated Liberty group: ' + group)


def attribute(text: str, name: str, default=None):
    match = re.search(r'\b' + name + r'\s*:\s*("(?:[^"\\]|\\.)*"|[^;]+)\s*;', text)
    return match[1].strip().strip('"') if match else default


def library_cells(path: Path) -> dict:
    text = re.sub(r'/\*.*?\*/', '', path.read_text(), flags=re.DOTALL)
    cells = {}
    for name, body in blocks(text, 'cell'):
        pins = {}
        for pin, pin_body in blocks(body, 'pin'):
            pins[pin.strip('"')] = {
                'direction': attribute(pin_body, 'direction'),
                'function': re.sub(r'\s+', '', attribute(pin_body, 'function', '')),
                'three_state': re.sub(r'\s+', '', attribute(pin_body, 'three_state', '')),
            }
        sequential = {kind: [(re.sub(r'\s+', '', header), re.sub(r'\s+', '', contents))
                              for header, contents in blocks(body, kind)]
                      for kind in ('ff', 'latch')}
        signature = {'pins': pins, 'sequential': sequential}
        cells[name.strip('"')] = {
            'area': float(attribute(body, 'area')),
            'drive_strength': float(attribute(body, 'drive_strength', '0')),
            'pins': pins, 'signature': signature,
            'signature_sha256': hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest(),
            'sequential': any(sequential.values()),
        }
    if not cells:
        raise ValueError('Liberty contains no cells')
    return cells


def instances(text: str, library: dict) -> dict:
    result = {}
    identifier = r'(?:\\[^\s]+|[A-Za-z_][\w$]*)'
    pattern = re.compile(r'^\s*(' + identifier + r')\s+(' + identifier +
                         r')\s*\(\s*\n(.*?)^\s*\);', re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(text):
        cell, name, body = match.groups()
        if cell not in library:
            continue
        name = name.lstrip('\\')
        if name in result:
            raise ValueError('Duplicate mapped instance: ' + name)
        pins = {pin: re.sub(r'\s+', ' ', value.strip())
                for pin, value in re.findall(r'\.([A-Za-z_][\w$]*)\s*\(([^()]*)\)', body)}
        if not set(pins).issubset(library[cell]['pins']):
            raise ValueError('Mapped instance contains an unknown Liberty pin: ' + name)
        result[name] = {'cell': cell, 'pins': pins, 'type_span': match.span(1)}
    if not result:
        raise ValueError('No standard-cell instances found')
    return result


def connectivity_digest(text: str, cells: dict) -> str:
    parts, position = [], 0
    for item in sorted(cells.values(), key=lambda item: item['type_span']):
        start, end = item['type_span']
        parts.extend((text[position:start], '<LIBERTY_CELL>'))
        position = end
    parts.append(text[position:])
    return hashlib.sha256(''.join(parts).encode()).hexdigest()


def stronger_cell(name: str, library: dict) -> str:
    family = re.sub(r'_X\d+$', '', name)
    original = library[name]
    choices = [candidate for candidate, cell in library.items()
               if re.sub(r'_X\d+$', '', candidate) == family
               and cell['drive_strength'] > original['drive_strength']
               and cell['signature'] == original['signature']]
    if not choices:
        raise RuntimeError('No stronger functionally identical Liberty cell for ' + name)
    return min(choices, key=lambda candidate: (library[candidate]['drive_strength'],
                                              library[candidate]['area'], candidate))


def affected_drivers(violations: list, cells: dict, library: dict) -> list[str]:
    drivers = {}
    for name, item in cells.items():
        for pin, net in item['pins'].items():
            if library[item['cell']]['pins'][pin]['direction'] == 'output':
                drivers.setdefault(net, []).append(name)
    selected = set()
    for violation in violations:
        name, pin = violation['pin'].rsplit('/', 1)
        item = cells[name]
        direction = library[item['cell']]['pins'][pin]['direction']
        if direction == 'output':
            selected.add(name)
        elif direction == 'input':
            net_drivers = drivers.get(item['pins'][pin], [])
            if len(net_drivers) != 1:
                raise RuntimeError('A slew violation needs one internal driver: ' + violation['pin'])
            selected.add(net_drivers[0])
        else:
            raise RuntimeError('Unsupported direction on violating pin: ' + violation['pin'])
    return sorted(selected)


def export_json(liberty: Path, netlist: Path, top: str, output: Path):
    from pyosys import libyosys
    design = libyosys.Design()
    for path in (liberty, netlist, output):
        if not re.fullmatch(r'[-A-Za-z0-9_./:+@=]+', str(path)):
            raise ValueError('Use portable filename characters for Yosys inputs')
    for command in [f'read_liberty -lib {liberty}', f'read_verilog {netlist}',
                    f'hierarchy -top {top}', 'check -assert -mapped', f'write_json {output}']:
        libyosys.run_pass(command, design)


def area_record(cells: dict, library: dict) -> dict:
    counts = Counter(item['cell'] for item in cells.values())
    return {'cell_area_library_units': sum(count * library[name]['area'] for name, count in counts.items()),
            'standard_cell_count': sum(counts.values()),
            'sequential_cell_count': sum(count for name, count in counts.items() if library[name]['sequential']),
            'cell_counts': dict(sorted(counts.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta', default='sta')
    parser.add_argument('--liberty', type=Path, required=True)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--netlist-json', type=Path)
    parser.add_argument('--top', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--clock-port', default='clk')
    parser.add_argument('--reset-port', default='rst_n')
    parser.add_argument('--report-output', action='append', default=[])
    parser.add_argument('--max-iterations', type=int, default=8)
    parser.add_argument('--export-json-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.liberty, args.netlist, args.out = args.liberty.resolve(), args.netlist.resolve(), args.out.resolve()
    if args.export_json_worker:
        export_json(args.liberty, args.netlist, args.top, args.out)
        return
    if args.max_iterations < 1:
        parser.error('--max-iterations must be positive')
    args.out.mkdir(parents=True, exist_ok=True)
    library = library_cells(args.liberty)
    original_text = args.netlist.read_text()
    original_cells = instances(original_text, library)
    original_connectivity = connectivity_digest(original_text, original_cells)
    tracked = [Path(__file__).resolve(), Path(__file__).with_name('run_opensta.py').resolve(),
               args.netlist, args.liberty]
    if args.netlist_json:
        args.netlist_json = args.netlist_json.resolve()
        tracked.append(args.netlist_json)
        original_design = json.loads(args.netlist_json.read_text())['modules'][args.top]
        assert Counter(cell['type'] for cell in original_design['cells'].values()) == Counter(
            cell['cell'] for cell in original_cells.values()), 'Mapped Verilog and JSON cell counts differ'
    original_hashes = {str(path): sha256(path) for path in tracked}
    text = original_text
    changes = []
    iterations = []
    for iteration in range(args.max_iterations + 1):
        directory = args.out/f'iteration_{iteration:02d}'
        directory.mkdir(exist_ok=True)
        netlist = directory/'mapped.v'
        mapped_json = directory/'mapped.json'
        netlist.write_text(text)
        command = [sys.executable, str(Path(__file__).resolve()), '--export-json-worker',
                   '--liberty', str(args.liberty), '--netlist', str(netlist),
                   '--top', args.top, '--out', str(mapped_json)]
        with (directory/'read_netlist.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        cells = instances(text, library)
        assert connectivity_digest(text, cells) == original_connectivity
        design = json.loads(mapped_json.read_text())['modules'][args.top]
        assert Counter(cell['type'] for cell in design['cells'].values()) == Counter(
            cell['cell'] for cell in cells.values()), 'Re-read netlist has different cell counts'
        command = [sys.executable, str(Path(__file__).with_name('run_opensta.py').resolve()),
                   '--sta', args.sta, '--liberty', str(args.liberty), '--netlist', str(netlist),
                   '--netlist-json', str(mapped_json), '--top', args.top,
                   '--clock-port', args.clock_port, '--reset-port', args.reset_port,
                   '--out', str(directory/'sta')]
        for endpoint in args.report_output:
            command += ['--report-output', endpoint]
        with (directory/'sta_runner.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = json.loads((directory/'sta/summary.json').read_text())
        iterations.append({'iteration': iteration, 'directory': str(directory),
                           'transition_violation_count': len(result['transition_violations']),
                           'setup_met': result['setup_met'], 'hold_met': result['hold_met'],
                           **area_record(cells, library)})
        if result['max_transition_met']:
            break
        if iteration == args.max_iterations:
            raise RuntimeError('The drive-strength iteration limit was reached')
        replacements = []
        for name in affected_drivers(result['transition_violations'], cells, library):
            item = cells[name]
            target = stronger_cell(item['cell'], library)
            changes.append({'iteration': iteration + 1, 'instance': name,
                            'from_cell': item['cell'], 'to_cell': target,
                            'functional_signature_sha256': library[target]['signature_sha256'],
                            'pins': item['pins']})
            replacements.append((*item['type_span'], target))
        for start, end, target in sorted(replacements, reverse=True):
            text = text[:start] + target + text[end:]
        print(f'{args.top}: iteration {iteration + 1}, resized {len(replacements)} drivers', flush=True)
    else:
        raise RuntimeError('Drive-strength optimization did not terminate')
    assert original_hashes == {str(path): sha256(path) for path in tracked}
    raw = json.loads((args.out/'iteration_00/sta/summary.json').read_text())
    assert result['clock'] == raw['clock'] and result['interfaces'] == raw['interfaces']
    assert result['wire_model'] == raw['wire_model']
    for group, path in raw['path_groups'].items():
        if path['setup'].get('met', False):
            assert result['path_groups'][group]['setup']['met'], 'A passing setup group must remain passing'
    assert iterations[-1]['standard_cell_count'] == iterations[0]['standard_cell_count']
    assert iterations[-1]['sequential_cell_count'] == iterations[0]['sequential_cell_count']
    report = {'optimization_completed': True,
              'method': 'STA-guided replacement by higher-drive cells with identical Liberty pin functions and sequential definitions',
              'top': args.top, 'connectivity_unchanged': True,
              'connectivity_sha256': original_connectivity, 'constraints_unchanged': True,
              'all_replacements_functionally_identical': True,
              'input_sha256': original_hashes, 'changes': changes, 'iterations': iterations,
              'raw_timing_result': str(args.out/'iteration_00/sta/summary.json'),
              'optimized_timing_result': str(directory/'sta/summary.json'),
              'optimized_netlist': str(netlist), 'optimized_netlist_json': str(mapped_json),
              'optimized_artifact_sha256': {'mapped.v': sha256(netlist), 'mapped.json': sha256(mapped_json)},
              'raw_area': area_record(original_cells, library), 'optimized_area': area_record(cells, library),
              'setup_met': result['setup_met'], 'hold_met': result['hold_met'],
              'max_transition_met': result['max_transition_met']}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ['optimization_completed', 'top', 'setup_met',
                                                'hold_met', 'max_transition_met']}, indent=2))


if __name__ == '__main__':
    main()
