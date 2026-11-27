#!/usr/bin/env python3
"""测量完整预取模块，并报告进入跨行起点寄存器的全部组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='92d1c609')
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    if not args.report_only:
        subprocess.run([sys.executable, ROOT/'test/frontend_address_arithmetic/measure.py',
            '--source-root', source, '--reference', args.reference,
            '--validation', args.validation.resolve(), '--out', out, '--cases', 'prefetch'],
            cwd=source, check=True)
    complete = json.loads((out/'measurement.json').read_text())
    for filename, expected in complete['source_sha256']['current'].items():
        if hashlib.sha256((source/filename).read_bytes()).hexdigest() != expected:
            raise RuntimeError('当前源码与预取模块映射输入不同：'+filename)
    report = dict(reference_commit=complete['reference_commit'],
                  source_sha256=complete['source_sha256'],
                  existing_prefetch_stages_unchanged=True, external_input_constraints=[], cases={})
    for name in ('prefetch_reference', 'prefetch_current'):
        folder = out/'mapped'/name
        module = json.loads((folder/'mapped.json').read_text())['modules']['measure']
        for cell, origin in register_origins(out/'pre'/name/'pre_lut.il', 'measure').items():
            if cell in module['cells']:
                module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
        paths = connected_paths(module, limit=4, group_limit=4,
            sink_filter=lambda name, cell, port:
                'prefetch_wrap_base_q' in cell.get('attributes', {}).get('fpga_register_origin', ''))
        metrics = complete['cases'][name]
        if not paths['graph_complete'] or not metrics['mapped_functional_verification']['passed']:
            raise RuntimeError('预取跨行起点路径或映射功能验证未完成')
        report['cases'][name] = dict(resources=metrics['resources'],
            complete_module_depth=metrics['complete_paths']['longest_register_path_cells'],
            complete_module_graph_verified=metrics['complete_paths']['graph_complete'],
            wrap_register_paths=paths, mapped_sha256=metrics['mapped_sha256'],
            mapping_functional_verification=metrics['mapped_functional_verification'])
        print(name, metrics['resources']['logic_lut_cells'], paths['longest_register_path_cells'], flush=True)
    report['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out/'wrap_measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
