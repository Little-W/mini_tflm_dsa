#!/usr/bin/env python3
"""检查四态进位函数已从确定输入的综合结构中消除。"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import re
import shlex
import subprocess
import sys
from support import ROOT, RTL, HELPER, digest, arithmetic_unit


def output_graph(module):
    """忽略单元编号，按输入位和实际连接计算组合输出结构摘要。"""
    inputs, drivers, memo = {}, {}, {}
    for name, port in module['ports'].items():
        if port['direction'] == 'input':
            for index, bit in enumerate(port['bits']):
                inputs[bit] = (name, index)
    for name, cell in module['cells'].items():
        for port, direction in cell['port_directions'].items():
            if direction == 'output':
                for index, bit in enumerate(cell['connections'][port]):
                    if isinstance(bit, int):
                        drivers[bit] = (name, port, index)

    def signature(bit):
        if isinstance(bit, str):
            return 'constant:' + bit
        if bit in inputs:
            return 'input:' + repr(inputs[bit])
        if bit not in memo:
            name, port, index = drivers[bit]
            cell = module['cells'][name]
            connections = {p: [signature(value) for value in cell['connections'][p]]
                           for p in sorted(cell['connections']) if cell['port_directions'][p] == 'input'}
            payload = [cell['type'], cell['parameters'], port, index, connections]
            memo[bit] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return memo[bit]

    return {name: [signature(bit) for bit in port['bits']]
            for name, port in module['ports'].items() if port['direction'] == 'output'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out, root = args.out.resolve(), args.source_root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = arithmetic_unit(root / RTL, 'candidate')
    candidate = out / 'candidate.sv'
    candidate.write_text(source)
    first = source.index('    // 位级进位传递')
    last = source.index('  end else begin : g_generic_load_command_compare', first)
    expected = source[:first] + '''    assign cmd_has_more_prepare =
        !remaining_words[32] && remaining_words[31:0] > 32'(VLEN);
''' + source[last:]
    deterministic = out / 'deterministic.sv'
    deterministic.write_text(expected)
    ranges = [(source[:match.start()].count('\n') + 1, source[:match.end()].count('\n') + 1)
              for match in re.finditer(r'function automatic.*?endfunction', source, re.S)]
    report = {'passed': False, 'function_lines': sum(b - a + 1 for a, b in ranges), 'variants': {}}
    graphs = {}
    for label, path in [('candidate', candidate), ('deterministic', deterministic)]:
        target, script, log = out / (label + '.json'), out / (label + '.ys'), out / (label + '.log')
        script.write_text('read_slang --top arithmetic_candidate -D SYNTHESIS=1 ' +
                          shlex.join(map(str, [path, root / HELPER])) +
                          '\nprep -top arithmetic_candidate -flatten\nopt -full\nwrite_json ' +
                          shlex.quote(str(target)) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        module = json.loads(target.read_text())['modules']['arithmetic_candidate']
        histogram = dict(sorted(collections.Counter(cell['type'] for cell in module['cells'].values()).items()))
        functions = []
        if label == 'candidate':
            for name, cell in module['cells'].items():
                for location in cell.get('attributes', {}).get('src', '').split('|'):
                    match = re.search(r'(?:^|/)candidate\.sv:(\d+)\.\d+-(\d+)\.\d+', location)
                    if match and any(a <= int(match[1]) <= b for a, b in ranges):
                        functions.append(name)
        graphs[label] = output_graph(module)
        report['variants'][label] = {'cells': len(module['cells']), 'cell_types': histogram,
                                    'function_cells': functions, 'netlist_sha256': digest(target),
                                    'output_graph_sha256': hashlib.sha256(json.dumps(graphs[label], sort_keys=True).encode()).hexdigest()}
    if report['variants']['candidate']['function_cells']:
        raise RuntimeError('四态函数仍含综合单元')
    if graphs['candidate'] != graphs['deterministic']:
        raise RuntimeError('确定输入组合输出的综合连接不同')
    if report['variants']['candidate']['cell_types'] != report['variants']['deterministic']['cell_types']:
        raise RuntimeError('确定输入综合单元不同')
    report.update(passed=True, source_sha256=digest(root / RTL), helper_sha256=digest(root / HELPER))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'function_lines': report['function_lines'],
                      'cells': report['variants']['candidate']['cells'],
                      'function_cells': report['variants']['candidate']['function_cells']}))


if __name__ == '__main__':
    main()
