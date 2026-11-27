#!/usr/bin/env python3
"""比较窗口预约控制修改前后的完整向量资源、寄存器路径和请求返回边界。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def boundary_paths(source, mapped):
    """在公开请求和返回端口增加测量边界，资源仍采用原始映射结果。"""
    module = json.loads((mapped / 'mapped.json').read_text())['modules']['vector_engine']
    for cell, origin in register_origins(source / 'pre_lut.il').items():
        if cell in module['cells']:
            module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
    index = 11000000
    for direction, names in (
        ('input', ('win_rsp_tag', 'win_rsp_error')),
        ('output', ('win_rsp_ready', 'win_req_valid')),
    ):
        for name in names:
            bits = module['ports'][name]['bits']
            extra = list(range(index, index + len(bits)))
            index += len(bits)
            cell = direction + '_boundary_' + name
            module['cells'][cell] = {
                'type': 'FDRE', 'parameters': {},
                'attributes': {'fpga_register_origin': direction + '_boundary.' + name},
                'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'CE': 'input', 'R': 'input'},
                'connections': {'D': extra if direction == 'input' else bits,
                                'Q': bits if direction == 'input' else extra,
                                'C': ['0'], 'CE': ['1'], 'R': ['0']},
            }
    return {name: connected_paths(module, limit=4, group_limit=2,
            sink_filter=lambda cell, info, port, name=name: cell == 'output_boundary_' + name)
            for name in ('win_rsp_ready', 'win_req_valid')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='f8dc8dd7ffdb8225b25573acb01fe871ccf92015')
    parser.add_argument('--summarize', action='store_true', help='从已生成网表重新提取报告')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    options = ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', '-GTILE=16', '-GBUS_WIDTH=64',
               '-GPE_COUNT=8', '-GWINDOW_LANES=8', '-GSHARED_STORAGE_ENABLE=1',
               '-GSHARED_QUANT_ENABLE=0', '-GSHARED_STORAGE_ADDR_WIDTH=12']
    if not args.summarize:
        reference = out / 'reference_address.sv'
        reference.write_text(subprocess.check_output(
            ['git', 'show', args.reference + ':rtl/npu/conv/vector_engine_address.sv'], cwd=ROOT, text=True))
        cases = {name: {'top': 'vector_engine',
                       'sources': [str(ROOT / 'rtl/npu/conv/vector_engine.sv'), str(source)],
                       'options': options,
                       'configuration': '16 通道、8 PE、64 位总线、共享存储、本地量化'}
                 for name, source in (('reference', reference),
                                      ('candidate', ROOT / 'rtl/npu/conv/vector_engine_address.sv'))}
        configuration = out / 'cases.json'
        configuration.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                        '--case-config', configuration, '--cases', 'reference', 'candidate',
                        '--out', out, '--through', 'pre_lut'], cwd=ROOT, check=True)
        for name in cases:
            subprocess.run([sys.executable, ROOT / 'scripts/fpga/remap_fpga_luts.py',
                            '--source', out / name, '--out', out / (name + '_mapped'),
                            '--mode', 'physical-cost', '--delay-target-ps', '6667',
                            '--wire-delay-ps', '300', '--max-lut-inputs', '8'], cwd=ROOT, check=True)
    report = {'reference': args.reference, 'production_options': options, 'results': {}}
    for name in ('reference', 'candidate'):
        mapped = out / (name + '_mapped')
        metrics = json.loads((mapped / 'metrics.json').read_text())
        report['results'][name] = {
            'resources': metrics['resources'], 'paths': metrics['paths'],
            'boundary_paths': boundary_paths(out / name, mapped),
            'manifest': json.loads((mapped / 'manifest.json').read_text()),
            'verification': json.loads((mapped / 'verification.json').read_text()),
        }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'logic_lut': value['resources']['logic_lut_cells'],
                            'longest_path': value['paths']['longest_register_path_cells']}
                      for name, value in report['results'].items()}))


if __name__ == '__main__':
    main()
