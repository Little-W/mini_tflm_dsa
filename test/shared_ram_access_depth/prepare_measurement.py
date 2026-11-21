#!/usr/bin/env python3
"""建立相同输入输出寄存器下的共享存储访问控制综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from run_formal import ROOT, SOURCE, channel


def wrappers(source: str, reference: bool) -> str:
    unit = channel(source, 'shared_access_unit')
    header = unit[:unit.index('\n);') + len('\n);')]
    ports = []
    for line in header.splitlines():
        match = re.match(r'\s*(input|output)\s+(?:wire\s+)?logic\s+'
                         r'(?:(\[[^\]]+\])\s+)?(\w+)(\s*\[[^\]]+\])?'
                         r'(?:\s*=\s*[^,]+)?\s*[,]?\s*$', line)
        if match:
            direction, width, name, dimensions = match.groups()
            ports.append((direction, width or '', name, dimensions or ''))
    if len(ports) != 20:
        raise ValueError(f'共享存储端口数量不一致: {len(ports)}')
    parameters = ', '.join(f'.{name}({name})' for name in (
        'p_shared_write_stage', 'p_bank_bytes', 'p_total_bytes', 'p_addr_width', 'p_bank_count_width'))
    connections = []
    declarations, updates = [], []
    measured_header = header.replace('module shared_access_unit #(', 'module measurement_top #(', 1)
    for direction, width, name, dimensions in ports:
        expression = name
        if reference and name == 'i_access_enable':
            continue
        if reference and name in ('i_ia_read_en', 'i_ia_write_en', 'i_ps_read_en', 'i_ps_write_en'):
            count = 2 if name.startswith('i_ia_') else 4
            expression = f'({name} & {{{count}{{i_access_enable}}}})'
        connections.append(f'.{name}({expression})')
    for direction, width, name, dimensions in ports:
        if name in ('clk', 'rst_n'):
            continue
        external = f'measure_{name}'
        measured_header = re.sub(r'\b' + re.escape(name) + r'\b', external, measured_header)
        declarations.append(f'  logic {width} {name}{dimensions};')
        updates.append(f'    {name} <= {external};' if direction == 'input' else
                       f'    {external} <= {name};')
    unit = header + f'\n  channel_impl #({parameters}) u_ram(\n    ' + ',\n    '.join(connections) + '\n  );\nendmodule\n'
    measure = measured_header + '\n' + '\n'.join(declarations) + '\n  always_ff @(posedge clk) begin\n' + \
        '\n'.join(updates) + '\n  end\n' + f'  shared_access_unit #({parameters}) u_impl(\n    ' + \
        ',\n    '.join(f'.{name}({name})' for _, _, name, _ in ports) + '\n  );\nendmodule\n'
    return unit + '\n' + measure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='dde5e7c9')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref], cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT).decode()
    current = (ROOT / SOURCE).read_text()
    cases = {}
    for name, source in (('reference', reference), ('current', current)):
        folder = out / name
        folder.mkdir(exist_ok=True)
        implementation, wrapper = folder / 'channel.sv', folder / 'measure.sv'
        implementation.write_text(channel(source, 'channel_impl'))
        wrapper.write_text(wrappers(current, reference=name == 'reference'))
        cases[name] = {'top': 'measurement_top', 'sources': [str(implementation), str(wrapper)],
                       'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1',
                                   '-Gp_bank_bytes=8192', '-Gp_total_bytes=57344', '-Gp_shared_write_stage=1'],
                       'configuration': '七个8192字节存储块，所有外部数据和控制具有相同测量寄存器'}
    snapshot = out / 'source'
    common = snapshot / 'rtl/common'
    common.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'rtl/common/regfile.v', common / 'regfile.v')
    shutil.copytree(ROOT / 'config', snapshot / 'config', dirs_exist_ok=True)
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    report = {'reference_revision': revision,
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'source_sha256': {SOURCE: hashlib.sha256(current.encode()).hexdigest(),
                                'rtl/common/regfile.v': hashlib.sha256((common / 'regfile.v').read_bytes()).hexdigest()},
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out / 'inputs.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
