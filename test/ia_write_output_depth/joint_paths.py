#!/usr/bin/env python3
"""检查实际 NPU 连接中的 IA 写入路径与字节加法 DSP 的寄存器隔离。"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from map_wide_alu import combinational_inputs, integer
from netlist_metrics import connected_paths, register_origins


def dsp_separation(module):
    cells = module['cells']
    added = [name for name, cell in cells.items() if cell['type'] == 'DSP48E1' and
             'u_ia_loader.u_cache_mgr.g_external_ram.g_compact_write' in name and
             '.u_compact_add.' in name]
    dsp_names = [name for name, cell in cells.items() if cell['type'] == 'DSP48E1' and
                 integer(cell['parameters'].get('PREG', 1)) == 0]
    indices = {name: index for index, name in enumerate(dsp_names)}
    sources, dependencies = {}, {}
    for name, cell in cells.items():
        for port, output_bits in cell['connections'].items():
            if cell['port_directions'][port] != 'output':
                continue
            outputs = [bit for bit in output_bits if isinstance(bit, int)]
            if cell['type'] == 'DSP48E1':
                if name in indices:
                    for bit in outputs:
                        sources[bit] = 1 << indices[name]
                continue
            inputs = combinational_inputs(cell, port)
            for bit in outputs:
                dependencies[bit] = inputs
    pending = {bit: set(inputs).intersection(dependencies) for bit, inputs in dependencies.items()}
    children = defaultdict(set)
    for bit, parents in pending.items():
        for parent in parents:
            children[parent].add(bit)
    ready = [bit for bit, parents in pending.items() if not parents]
    origins = dict(sources)
    visited = 0
    while ready:
        bit = ready.pop()
        value = 0
        for source in dependencies[bit]:
            value |= origins.get(source, 0)
        origins[bit] = value
        visited += 1
        for child in children[bit]:
            pending[child].remove(bit)
            if not pending[child]:
                ready.append(child)
    if visited != len(dependencies):
        raise RuntimeError('The DSP dependency graph contains a cycle')
    upstream = {}
    for name in dsp_names:
        mask = 0
        cell = cells[name]
        for port, input_bits in cell['connections'].items():
            if cell['port_directions'][port] == 'input':
                for bit in input_bits:
                    if isinstance(bit, int):
                        mask |= origins.get(bit, 0)
        upstream[name] = [source for source, index in indices.items() if mask & (1 << index)]
    result = []
    for name in added:
        registers = {key: integer(value) for key, value in cells[name]['parameters'].items()
                     if key.endswith('REG')}
        after = [sink for sink, sources in upstream.items() if name in sources]
        row = dict(cell=name, register_parameters=registers,
                   upstream_unregistered_dsps=upstream[name], downstream_unregistered_dsps=after)
        row['passed'] = all(value == 0 for value in registers.values()) and not upstream[name] and not after
        result.append(row)
    return dict(passed=len(result) == 8 and all(row['passed'] for row in result),
                added_dsp_count=len(result), total_unregistered_dsps=len(dsp_names),
                visited_combinational_bits=visited, runs=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folder = args.source.resolve()
    saved = json.loads((folder / 'summary.json').read_text())
    mapped = folder / 'mapped.json'
    pre_lut = Path(saved.get('pre_lut_source', folder / 'pre_lut.il'))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest(mapped) == saved['mapped_sha256']
    assert digest(pre_lut) == saved['pre_lut_sha256']
    module = json.loads(mapped.read_text())['modules']['npu_top']
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    removed = {item['cell'] for item in saved['interface_boundaries']}
    module['cells'] = {name: cell for name, cell in module['cells'].items()
                       if name not in removed and cell['type'] != '$scopeinfo'}
    start = re.compile(r'u_frontend\.u_cache\.g_window\.u_window\.response_queue_error\s*\[0\]$')
    paths = {}
    targets = {'174': ('data', 174), '127': ('data', 127),
               'write_en0': ('en', 0), 'write_en1': ('en', 1)}
    for name, (output, index) in targets.items():
        end = re.compile(r'u_ia_loader\.u_cache_mgr\.ram_port_wr_' + output + r' \[' + str(index) + r'\]$')
        result = connected_paths(module, limit=3, group_limit=3,
            root_filter=lambda n, c, p: bool(start.search(c.get('attributes', {}).get('fpga_register_origin', ''))),
            sink_filter=lambda n, c, p: bool(end.search(c.get('attributes', {}).get('fpga_register_origin', ''))))
        if not result['graph_complete'] or not result['register_to_register_paths']:
            raise RuntimeError('The target IA path is absent or incompletely classified')
        paths[name] = result
    separation = dsp_separation(module)
    report = dict(source_sha256=saved['source_sha256'],
        mapped_sha256=saved['mapped_sha256'], pre_lut_sha256=saved['pre_lut_sha256'],
        mapping_profile=saved.get('mapping_profile', {'mode': 'native-synth-xilinx'}),
        resources=saved['resources'], interface_boundaries=saved['interface_boundaries'],
        paths=paths, dsp_separation=separation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(paths={key: value['longest_register_path_cells'] for key, value in paths.items()},
        dsp_separation_passed=separation['passed'], added_dsp_count=separation['added_dsp_count'])))
    if not separation['passed']:
        raise RuntimeError('New compact-byte DSPs are not separated by registers')


if __name__ == '__main__':
    main()
