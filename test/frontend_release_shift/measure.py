#!/usr/bin/env python3
"""测量完整前端中行释放加法和缓存移位两个寄存阶段。"""
import argparse
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from run_formal import ROOT, SOURCE, CACHE, REFERENCE, prepare, source_pair
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--bus-width', type=int, choices=(32, 64), default=32)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    contents, _ = source_pair(args.reference_ref)
    parameters = dict(SIZE=16, LANES=4, BUS_WIDTH=args.bus_width, CACHE_SETS=128,
                      CACHE_WAYS=2, LINE_BYTES=16, CACHE_POLICY=3)
    cases = {}
    for label in ('reference', 'current'):
        folder = out / 'sources' / label
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for path, pair in contents.items():
            saved = folder / Path(path).name
            saved.write_text(pair[label])
            paths.append(str(saved))
        cases[label] = dict(top='conv_im2col_frontend', parameters=parameters,
            options=['-j', '1', '-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1',
                     *(f'-G{name}={value}' for name, value in parameters.items())],
            sources=[*(str(ROOT / path) for path in prepare.DEPENDENCIES
                       if path != CACHE and not path.startswith('rtl/common/')), *paths],
            configuration='Complete frontend and cache; ordinary RTL arithmetic inference')
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    report = dict(reference_ref=args.reference_ref, extra_dsp_remapping=False,
        source_sha256={path: {label: prepare.digest(text) for label, text in pair.items()}
                       for path, pair in contents.items()}, runs={})

    def origin(cell):
        return cell.get('attributes', {}).get('fpga_register_origin', '')

    def metadata_register(cell_name, cell, port):
        name = origin(cell)
        if name.startswith('u_cache.g_window.u_window.offer_retire_q '):
            return True
        match = re.fullmatch(r'u_cache\.g_window\.u_window\.work_request \[(\d+)\]', name)
        return match is not None and 42 <= int(match[1]) < 74

    def producer_register(cell_name, cell, port):
        return origin(cell).startswith(('iy ', 'pfa_y ', 'pf0_y ', 'request_y_q ',
            'request_pending ', 'prefetch_retire_pfa_q ', 'retire_bias_q ', 'retire_compare_q ',
            'retire_all_bounded_q ', 'retire_no_bound_q ', 'retire_enabled_q ', 'retire_shift_q '))

    def metadata_endpoint(cell_name, cell, port):
        return metadata_register(cell_name, cell, port) or origin(cell).startswith(
            ('pf0_ref_retire ', 'pf1_retire '))

    for label in cases:
        folder = out / 'native' / label
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--case-config', str(config), '--cases', label, '--out', str(out / 'native')],
            cwd=ROOT, check=True)
        metrics = json.loads((folder / 'metrics.json').read_text())
        design = json.loads((folder / 'mapped.json').read_text())['modules']['conv_im2col_frontend']
        for cell, name in register_origins(folder / 'pre_lut.il').items():
            if cell in design['cells']:
                design['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = name
        stages = dict(
            producer_to_metadata=connected_paths(design, limit=8, group_limit=16,
                root_filter=producer_register, sink_filter=metadata_endpoint),
            metadata_to_storage=connected_paths(design, limit=8, group_limit=16,
                root_filter=metadata_register))
        if not metrics['paths']['graph_complete'] or metrics['paths']['combinational_cycle_nodes']:
            raise RuntimeError('完整前端的组合图分析未完成')
        if any(not result['graph_complete'] or not result['register_to_register_paths']
               for result in stages.values()):
            raise RuntimeError('行释放计算的寄存阶段分析未完成')
        report['runs'][label] = dict(parameters=parameters, resources=metrics['resources'],
            longest_register_path_cells=metrics['paths']['longest_register_path_cells'],
            release_stages=stages, graph_complete=True,
            metrics_sha256=prepare.digest((folder / 'metrics.json').read_bytes()),
            mapped_sha256=prepare.digest((folder / 'mapped.json').read_bytes()),
            synthesis_stages=json.loads((folder / 'stages.json').read_text()))
        for name in ('elaborated.il', 'pre_lut.il', 'mapped.json'):
            path = folder / name
            with path.open('rb') as src, gzip.open(str(path) + '.gz', 'wb', compresslevel=2) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(label, {name: value['longest_register_path_cells'] for name, value in stages.items()}, flush=True)
    before, after = (report['runs'][label] for label in ('reference', 'current'))
    report['resource_delta'] = {key: after['resources'][key] - before['resources'][key] for key in
        ('logic_lut_cells', 'flip_flops', 'dsp48e1', 'carry4', 'ramb18e1',
         'distributed_ram_lut_sites_nominal')}
    if any(prepare.digest((ROOT / path).read_bytes()) != pair['current']
           for path, pair in report['source_sha256'].items()):
        raise RuntimeError('Source changed during synthesis')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['resource_delta']), flush=True)


if __name__ == '__main__':
    main()
