#!/usr/bin/env python3
"""测量完整偏置加载器以及执行存储体选择到后续寄存器的路径。"""
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
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='ee8e2fc6')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    previous_sources = []
    for filename in ('bias_loader_ctrl.sv', 'bias_loader_buffer.sv', 'bias_bank_readiness.sv'):
        previous = out/'reference'/filename
        previous.parent.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(subprocess.check_output([
            'git', 'show', reference+':rtl/npu/loaders/'+filename], cwd=ROOT))
        previous_sources.append(str(previous))
    parameters = {'SIZE': 16, 'DATA_WIDTH': 32, 'BUS_WIDTH': 64, 'REG_WIDTH': 32,
                  'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32}
    cases = {}
    for name in ('reference', 'current'):
        sources = [str(ROOT/'rtl/npu/loaders/bias_loader.sv')]
        if name == 'reference':
            sources = previous_sources + sources
        cases[name] = {'top': 'bias_loader', 'sources': sources, 'parameters': parameters,
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', *[f'-G{k}={v}' for k, v in parameters.items()]],
            'configuration': '16 元素偏置加载器、64 位总线、两个存储体、每个存储体 32 块'}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', config,
        '--cases', 'reference', 'current', '--out', out/'mapping', '--through', 'pre_lut'], check=True, cwd=ROOT)
    rows = {}
    for name in cases:
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py', '--source', source,
            '--out', cost, '--mode', 'physical-cost', '--delay-target-ps', '6667',
            '--wire-delay-ps', '300', '--max-lut-inputs', '8', '--discard-abc9-temporaries'], check=True, cwd=ROOT)
        module = json.loads((cost/'mapped.json').read_text())['modules']['bias_loader']
        for cell_name, origin in register_origins(source/'pre_lut.il', 'bias_loader').items():
            if cell_name in module['cells']:
                module['cells'][cell_name].setdefault('attributes', {})['fpga_register_origin'] = origin
        module['cells']['analysis_bias_valid'] = {'type': 'FDRE',
            'connections': {'D': module['ports']['bias_valid']['bits']},
            'port_directions': {'D': 'input'}, 'attributes': {}}
        rows[name] = {'manifest': json.loads((cost/'manifest.json').read_text()),
            'summary': json.loads((cost/'summary.json').read_text()),
            'active_bank_paths': connected_paths(module,
                root_filter=lambda name, cell, port: cell.get('attributes', {}).get('fpga_register_origin') == 'u_ctrl.active_bank',
                limit=4, group_limit=4),
            'current_block_to_valid': connected_paths(module,
                root_filter=lambda name, cell, port: str(cell.get('attributes', {}).get('fpga_register_origin', '')).startswith('u_ctrl.current_block_idx'),
                sink_filter=lambda name, cell, port: name == 'analysis_bias_valid',
                limit=4, group_limit=4),
            'mapped_sha256': hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()}
        print(name, rows[name]['summary']['resources']['lut_sites_nominal_before_packing'],
              rows[name]['summary']['longest_register_path_cells'], flush=True)
    (out/'measurement.json').write_text(json.dumps({'reference_commit': reference,
        'parameters': parameters, 'cases': rows}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
