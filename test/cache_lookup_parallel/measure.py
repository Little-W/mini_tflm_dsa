#!/usr/bin/env python3
"""测量完整窗口缓存的资源与请求、替换和预取选择路径。"""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='d7cb67be')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    reference_tree = out / 'reference_tree'
    initial = []
    for relative in ('rtl/npu/dma/cache/conv_windowed_cache.sv',
                     'rtl/npu/dma/cache/conv_cache_request_path.sv'):
        path = reference_tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(['git', 'show', args.reference + ':' + relative], cwd=ROOT))
        initial.append(path)
    reference_sources = []
    for path in resolver(initial, ROOT):
        if path.is_relative_to(reference_tree):
            reference_sources.append(path)
            continue
        relative = path.relative_to(ROOT)
        reference_data = subprocess.check_output(['git', 'show', args.reference + ':' + str(relative)], cwd=ROOT)
        # 公共算术由综合入口统一加入，核对其内容与参照提交一致。
        if relative.parts[:2] == ('rtl', 'common'):
            assert path.read_bytes() == reference_data, str(relative)
            reference_sources.append(path)
            continue
        saved = reference_tree / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(reference_data)
        reference_sources.append(saved)
    sources = dict(reference=reference_sources,
                   current=resolver([ROOT / 'rtl/npu/dma/cache/conv_windowed_cache.sv'], ROOT))
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for paths in sources.values() for path in paths}
    parameters = dict(SETS=16, WAYS=2, LINE_BYTES=128, BUS_WIDTH=64, READ_WIDTH=64, DEMAND_DEPTH=2)
    options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] + [f'-G{key}={value}' for key, value in parameters.items()]
    cases = {name: dict(top='conv_windowed_cache', sources=list(map(str, paths)),
                        options=options, configuration=parameters) for name, paths in sources.items()}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, indent=2) + '\n')
    subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                    '--source-root', ROOT, '--case-config', config, '--cases', *cases,
                    '--out', out / 'mapping', '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name in cases:
        source, cost = out / 'mapping' / name, out / 'cost' / name
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
                        '--source', source, '--out', cost, '--mode', 'physical-cost',
                        '--delay-target-ps', '6667', '--wire-delay-ps', '300',
                        '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        module = json.loads((cost / 'mapped.json').read_text())['modules']['conv_windowed_cache']
        for cell, origin in register_origins(source / 'pre_lut.il', 'conv_windowed_cache').items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        record = {item: json.loads((cost / (item + '.json')).read_text())
                  for item in ('manifest', 'summary')}
        record['directed'] = {}
        paths = (
            ('queue_to_snapshot', 'request_count', 'u_request_path.lookup_snapshot_valid'),
            ('fill_to_stage', 'fill_set', 'select_stage_valid'),
            ('demand_fill_to_stage', 'demand_fill_set', 'select_stage_valid'),
            ('slot_to_storage', 'pf_slot_map_q', 'u_prefetch_index.mem.'),
        )
        for label, origin, endpoint in paths:
            result = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda n, c, p, origin=origin:
                    (c.get('attributes', {}).get('fpga_register_origin') or '').split(' [')[0] == origin,
                sink_filter=lambda n, c, p, endpoint=endpoint: n.startswith(endpoint) or
                    (c.get('attributes', {}).get('fpga_register_origin') or '').split(' [')[0] == endpoint)
            if not result['graph_complete']:
                raise RuntimeError('路径分析图不完整：' + label)
            record['directed'][label] = result
        records[name] = record
        print(json.dumps(dict(case=name, resources=record['summary']['resources'],
                              paths={label: result['longest_register_path_cells']
                                     for label, result in record['directed'].items()})), flush=True)
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == value for path, value in hashes.items())
    report = dict(reference_commit=args.reference, parameters=parameters, source_sha256=hashes,
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), cases=records)
    (out / 'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
