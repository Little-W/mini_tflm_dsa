#!/usr/bin/env python3
"""比较固定 IA 物理容量下的编译配置，并统计读出各段的组合深度。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_paths(folder):
    module = json.loads((folder / 'mapped.json').read_text())['modules']['ia_loader_cache_mgr']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    observed = copy.deepcopy(module)
    next_bit = 1 + max(bit for cell in module['cells'].values()
        for bits in cell['connections'].values() for bit in bits if isinstance(bit, int))
    for direction, port_name in [('input', 'ram_port_rd_data'), ('output', 'ia_out')]:
        for index, bit in enumerate(module['ports'][port_name]['bits']):
            name = f'observed_{direction}[{index}]'
            observed['cells'][name] = dict(type='FDRE', parameters={},
                attributes={'fpga_register_origin': f'{direction} {port_name}[{index}]'},
                port_directions={'D':'input', 'Q':'output'},
                connections={'D':[next_bit if direction == 'input' else bit],
                             'Q':[bit if direction == 'input' else next_bit]})
            next_bit += 1
    # 观察端点仅存在于路径分析图，保存的综合网表和资源统计保持原样。
    def origin(cell):
        return cell.get('attributes', {}).get('fpga_register_origin', '')
    filters = {
        'ram_to_output': (lambda name, cell, port: name.startswith('observed_input['),
                          lambda name, cell, port: name.startswith('observed_output[')),
        'ram_to_data_register': (lambda name, cell, port: name.startswith('observed_input['),
            lambda name, cell, port: 'g_read_register' in origin(cell) and 'data_q' in origin(cell)),
        'data_register_to_output': (
            lambda name, cell, port: 'g_read_register' in origin(cell) and 'data_q' in origin(cell),
            lambda name, cell, port: name.startswith('observed_output[')),
        'register_to_output': (lambda name, cell, port: not name.startswith('observed_'),
                               lambda name, cell, port: name.startswith('observed_output[')),
    }
    result = {}
    for label, (source, sink) in filters.items():
        paths = connected_paths(observed, limit=20, group_limit=20,
            root_filter=source, sink_filter=sink)
        if not paths['graph_complete']:
            raise RuntimeError('Incomplete connectivity graph: ' + str(folder))
        result[label] = dict(connected=bool(paths['register_to_register_paths']),
            longest_combinational_cells=paths['longest_register_path_cells'],
            paths=paths['register_to_register_paths'][:3])
    (folder / 'read_paths.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lock-file', type=Path)
    parser.add_argument('--reference-rev', default='caace947')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = out / 'reference_cache.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show',
        args.reference_rev + ':rtl/npu/loaders/ia_loader_cache_mgr.sv'], cwd=ROOT))
    reference_commit = subprocess.check_output(['git','rev-parse',args.reference_rev],
        cwd=ROOT, text=True).strip()
    common_options = ['-DSYNTHESIS=1', '-GSIZE=16', '-GDATA_WIDTH=16', '-GBUS_WIDTH=64',
        '-GCACHE_BLOCKS=32', '-GEXTERNAL_RAM=1', '-GRAM_WORD_ADDR_WIDTH=12',
        '-Gp_compact_offset_width=9', '-Gp_dma_source_layout=1', '-Gp_shared_write_stage=1',
        '-Gp_precomputed_slot_mask=1', '-Gp_indexed_slot_rows=1']
    cases = {}
    for lanes in (8, 16):
        for compact in (0, 1):
            cases[f'dma{lanes}_compact{compact}'] = dict(top='ia_loader_cache_mgr',
                options=common_options + [f'-GDMA_LANES={lanes}', f'-GCOMPACT_S8={compact}'],
                sources=['rtl/npu/loaders/ia_loader_cache_mgr.sv'],
                configuration=f'IA 16384 bytes, SIZE16 DATA16 BUS64 DMA{lanes} COMPACT{compact}')
    cases['reference_dma16_compact1'] = dict(top='ia_loader_cache_mgr',
        options=common_options + ['-GDMA_LANES=16', '-GCOMPACT_S8=1'],
        sources=[str(reference)], configuration='IA 16384 bytes, SIZE16 DATA16 BUS64 DMA16 COMPACT1')
    case_file = out / 'cases.json'
    case_file.write_text(json.dumps(cases, indent=2) + '\n')
    command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
        '--case-config', str(case_file), '--cases', *cases, '--out', str(out / 'mapped')]
    if args.lock_file:
        command.extend(['--lock-file', str(args.lock_file.resolve())])
    if args.resume:
        command.append('--resume')
    subprocess.run(command, cwd=ROOT, check=True)
    synthesized = json.loads((out / 'mapped/summary.json').read_text())
    summary = dict(reference_commit=reference_commit, reference_sha256=digest(reference),
        physical_ia_capacity_bytes=16384, external_data_ram_included=False,
        method='Yosys XC7 mapping before placement; connected combinational cell count',
        measured_scope='IA management and compact encoding/decoding logic',
        metadata_memory='slot_written_cols; reported RAMB18 belongs to row extent metadata', cases={})
    for name in cases:
        entry = synthesized['cases'][name]
        paths = read_paths(out / 'mapped' / name)
        summary['cases'][name] = dict(resources=entry['resources'],
            module_longest_register_path_cells=entry['longest_register_path_cells'],
            read_paths={label:{key:value for key,value in row.items() if key != 'paths'}
                for label,row in paths.items()}, sources_sha256=entry['sources_sha256'])
        print(json.dumps(dict(case=name, **summary['cases'][name])), flush=True)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
