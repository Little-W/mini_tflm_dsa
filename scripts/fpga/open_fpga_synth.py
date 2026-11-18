#!/usr/bin/env python3
"""Measure mapped Xilinx 7-series module resources with open-source Yosys."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    'array': {
        'top': 'ws_systolic_array',
        'options': ['-D', 'ASIC_SYNTHESIS', '-GSIZE=16', '-GDATA_IN_WIDTH=16', '-GWEIGHT_WIDTH=16'],
        'sources': ['rtl/npu/compute/ws_systolic_cell.sv', 'rtl/npu/compute/ws_systolic_array.sv'],
        'configuration': '16 x 16, signed 16-bit inputs and weights; identity weight-enable buffers',
    },
    'shared_ram': {
        'top': 'ia_ps_shared_ram',
        'options': ['-GBANK_BYTES=8192', '-GTOTAL_BYTES=57344'],
        'sources': ['rtl/npu/buffers/ia_ps_shared_ram.sv'],
        'configuration': '7 banks, 8192 bytes per bank',
    },
    'vector_writeback': {
        'top': 'vector_writeback',
        'options': ['-GTILE=16', '-GBUS_WIDTH=64'],
        'sources': ['rtl/npu/conv/vector_writeback.sv'],
        'configuration': '16 result lanes, 64-bit bus',
    },
    'conv_cache_ram': {
        'top': 'conv_sdp_ram',
        'options': ['-GDEPTH=256', '-GWRITE_WIDTH=64'],
        'sources': ['rtl/npu/dma/cache/conv_sdp_ram.sv'],
        'configuration': '256 32-bit words, 64-bit byte-enabled writes',
    },
    'vector_engine': {
        'top': 'vector_engine',
        'options': ['-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
        'sources': ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv',
                    'rtl/npu/conv/vector_config_check.sv', 'rtl/npu/conv/vector_writeback.sv',
                    'rtl/npu/conv/vector_round_shift.sv', 'rtl/npu/conv/vector_scalar_multiplier.sv',
                    'rtl/npu/conv/vector_pe.sv', 'rtl/npu/conv/vector_softmax.sv',
                    'rtl/npu/conv/vector_engine.sv'],
        'configuration': '16 result lanes, 8 vector processing elements, 64-bit bus',
    },
}
DEFAULT_CASES = tuple(CASES)
_packages = ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv']
_npu_sources = _packages + [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/npu').rglob('*.sv'))
                            if str(path.relative_to(ROOT)) not in _packages]
_npu_sources += [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'rtl/common').rglob('*.v'))]
CASES['npu_top'] = {
    'top': 'npu_top',
    'options': ['-GSIZE=16', '-GBUS_WIDTH=64', '-GSHARED_BANK_BYTES=8192', '-GSHARED_BANK_COUNT=7'],
    'sources': _npu_sources,
    'configuration': '16 x 16 NPU, 64-bit bus, 7 shared banks of 8 KiB',
    'lut1_model': True,
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def logic_depth(cells):
    # Distributed RAM and shift-register memories have asynchronous read ports.
    logic = {n: c for n, c in cells.items()
             if re.fullmatch(r'LUT[1-6]|CARRY4|MUXF[78]|INV|SRL16E|SRLC32E|RAM(?:32M|64M|32X1D|64X1D|128X1S|256X1S)', c['type'])}
    drivers = {}
    for name, cell in logic.items():
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for bit in bits:
                    if isinstance(bit, int):
                        drivers[bit] = name
    children = collections.defaultdict(set)
    parents = {}
    for name, cell in logic.items():
        parents[name] = {drivers[bit] for port, bits in cell['connections'].items()
                         if cell['port_directions'][port] == 'input'
                         and (not cell['type'].startswith(('RAM', 'SRL')) or re.fullmatch(r'ADDR[A-D]|A|A[0-9]+|DPRA[0-9]+', port))
                         for bit in bits if isinstance(bit, int) and bit in drivers}
        for parent in parents[name]:
            children[parent].add(name)
    degree = {name: len(items) for name, items in parents.items()}
    depth = {name: 1 for name in logic}
    predecessor = {}
    ready = collections.deque(name for name, count in degree.items() if count == 0)
    visited = 0
    while ready:
        name = ready.popleft()
        visited += 1
        for child in sorted(children[name]):
            if depth[name] + 1 > depth[child]:
                depth[child] = depth[name] + 1
                predecessor[child] = name
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    if visited != len(logic):
        raise RuntimeError('Combinational cycle in mapped design')
    if not depth:
        return []
    last = max(depth, key=lambda name: (depth[name], name))
    path = []
    while True:
        path.append({'cell': last, 'type': logic[last]['type']})
        if last not in predecessor:
            break
        last = predecessor[last]
    return list(reversed(path))

def worker(script):
    from pyosys import libyosys as yosys
    yosys.run_pass('script ' + shlex.quote(str(script)))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/open_fpga_synth')
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(DEFAULT_CASES))
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    from pyosys import libyosys as yosys
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = {'tool': yosys.yosys_maybe_version(), 'family': 'xc7', 'cases': {},
              'method': 'synth_xilinx -noiopad -noclkbuf -flatten; mapped combinational cell graph',
              'timing': 'Combinational cell depth is an indicator, not a delay or clock-frequency result; block RAM and DSP terminate paths.'}
    env = os.environ.copy()
    env['PATH'] = str(Path(pyosys.__file__).parent) + os.pathsep + env.get('PATH', '')
    for name in args.cases:
        case = CASES[name]
        folder = out / name
        folder.mkdir(exist_ok=True)
        source_hash = {f: digest(ROOT / f) for f in case['sources']}
        mapped = folder / 'mapped.json'
        script = folder / 'run.ys'
        opts = ' '.join(shlex.quote(x) for x in case['options'])
        sources = ' '.join(shlex.quote(str(ROOT / x)) for x in case['sources'])
        if case.get('lut1_model'):
            model = folder / 'xilinx_lut1.sv'
            model.write_text('module LUT1 #(parameter [1:0] INIT=0)(input wire I0, output wire O); assign O=INIT[I0]; endmodule\n')
            sources += ' ' + shlex.quote(str(model))
        top = case['top']
        script.write_text(f'read_slang --top {top} {opts} {sources}\n'
                          f'hierarchy -check -top {top}\n'
                          f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten\n'
                          'check -assert\nstat -tech xilinx\n'
                          f'write_json {shlex.quote(str(mapped))}\n')
        start = time.monotonic()
        with (folder / 'synthesis.log').open('w') as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(script)],
                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        if source_hash != {f: digest(ROOT / f) for f in case['sources']}:
            raise RuntimeError('Sources changed during synthesis: ' + name)
        design = json.loads(mapped.read_text())
        counts = collections.Counter(c['type'] for c in design['modules'][top]['cells'].values())
        path = logic_depth(design['modules'][top]['cells'])
        result['cases'][name] = {
            'top': top, 'configuration': case['configuration'], 'sources_sha256': source_hash,
            'elapsed_seconds': round(time.monotonic() - start, 2),
            'lut_cells': sum(v for k, v in counts.items() if re.fullmatch(r'LUT[1-6]', k)),
            'flip_flops': sum(v for k, v in counts.items() if k.startswith(('FDCE', 'FDPE', 'FDRE', 'FDSE'))),
            'ramb36': counts['RAMB36E1'], 'ramb18': counts['RAMB18E1'], 'dsp': counts['DSP48E1'],
            'carry4': counts['CARRY4'], 'longest_combinational_path_cells': len(path),
            'longest_combinational_path': path,
            'cell_counts': dict(sorted(counts.items())),
        }
        (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print(name, json.dumps({k: result['cases'][name][k] for k in
              ('lut_cells', 'flip_flops', 'ramb36', 'ramb18', 'dsp', 'longest_combinational_path_cells')}), flush=True)

if __name__ == '__main__':
    main()
