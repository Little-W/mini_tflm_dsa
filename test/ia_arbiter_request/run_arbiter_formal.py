#!/usr/bin/env python3
"""证明完整仲裁状态与所有 DMA 端口在任意请求和响应下逐周期等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
TOP = 'axi_block_dma_arbiter'
RTL = 'rtl/npu/dma/axi_block_dma_arbiter.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(out, name, commands):
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    return log


def expand_dma_ports(path, output):
    design = json.loads(path.read_text())
    module = design['modules'][TOP]
    candidates = [(name, cell) for name, cell in module['cells'].items()
                  if cell['type'].startswith('axi_dual_block_dma')]
    if len(candidates) != 1:
        raise RuntimeError('Expected one complete DMA port boundary')
    name, dma = candidates[0]
    del module['cells'][name]
    description = []
    for port, bits in dma['connections'].items():
        direction = dma['port_directions'][port]
        name = 'formal_dma_' + port
        # DMA 响应的全部位成为共同输入，发送到 DMA 的全部位成为比较输出。
        connected = list(dict.fromkeys(bit for bit in bits if isinstance(bit, int)))
        if direction == 'output' and not connected:
            continue
        selected = connected if direction == 'output' else bits
        module['ports'][name] = {'direction': 'input' if direction == 'output' else 'output',
                                 'bits': selected}
        module['netnames'][name] = {'hide_name': 0, 'bits': selected, 'attributes': {}}
        description.append({'port': port, 'direction_at_dma': direction, 'bits': len(selected)})
    # 五个两位计数使用相同的比较端口，覆盖两种寄存器声明形式的全部状态位。
    for index in range(5):
        candidates = (f'rd_client_inflight[{index}]', f'g_client_inflight[{index}].count_q')
        names = [name for name in candidates if name in module['netnames']]
        if len(names) != 1:
            raise RuntimeError('Expected one exact client counter state: ' + str(index))
        bits = module['netnames'][names[0]]['bits']
        if len(bits) != 2:
            raise RuntimeError('Expected a two-bit client counter: ' + str(index))
        name = f'formal_client_count_{index}'
        module['ports'][name] = {'direction': 'output', 'bits': bits}
        module['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    design['modules'] = {TOP: module}
    output.write_text(json.dumps(design) + '\n')
    return description


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='437a8d81')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut_models.v'
    blocks = []
    for primitive in ('LUT6', 'LUT6_2'):
        block = re.search(r'^module '+primitive+r'\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
        blocks.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S))
    model.write_text('\n\n'.join(blocks) + '\n')
    snapshots = {}
    sources = (RTL, 'rtl/npu/dma/axi_dual_block_dma.sv', 'rtl/npu/conv/conv_im2col_pkg.sv')
    source_hashes = {name: digest(ROOT / name) for name in sources}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in sources:
            data = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else (ROOT / relative).read_bytes())
            if relative.endswith('/axi_dual_block_dma.sv'):
                text = data.decode()
                header_end = re.search(r'^\s*\);', text, re.M).end()
                data = (text[:header_end] + '\nendmodule\n').encode()
            path = folder / Path(relative).name
            path.write_bytes(data)
            snapshots[label].append(path)
    report = {'reference_revision': args.reference_rev, 'source_sha256': source_hashes,
              'source_input_constraints': False, 'dma_outputs_constrained': False,
              'scope': 'Complete arbiter state, all ten per-client counter bits, and every port of its unchanged DMA instance',
              'primitive_library_sha256': digest(library), 'primitive_model_sha256': digest(model),
              'runs': [], 'passed': False}
    profiles = [('fpga_bus' + str(bus) + '_quant' + str(quant), bus, quant, True)
                for bus in (32, 64, 128) for quant in (0, 1)]
    profiles.append(('asic_bus64', 64, 1, False))
    for name, bus, quant, fpga in profiles:
        options = ['-GSIZE=16', '-GDMA_SIZE=64', '-GCACHE_BLOCKS=64', f'-GBUS_WIDTH={bus}',
                   f'-GENABLE_QUANT_CLIENT={quant}',
                   '-DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1']
        ports = {}
        for label in ('reference', 'current'):
            raw = out / (name + '_' + label + '.json')
            expanded = out / (name + '_' + label + '_expanded.json')
            arbiter, dma, package = snapshots[label]
            commands = [f'read_slang --keep-hierarchy --top {TOP} ' + ' '.join(options) + ' ' +
                        ' '.join(shlex.quote(str(path)) for path in (package, arbiter, dma, model)),
                        'blackbox axi_dual_block_dma*', f'prep -top {TOP} -flatten',
                        'memory_map', 'async2sync', 'opt_clean', 'write_json ' + shlex.quote(str(raw))]
            run(out, name + '_' + label + '_elaborate', commands)
            ports[label] = expand_dma_ports(raw, expanded)
        if ports['reference'] != ports['current']:
            raise RuntimeError('DMA port boundaries differ')
        commands = []
        for label in ('reference', 'current'):
            path = out / (name + '_' + label + '_expanded.json')
            commands += ['read_json ' + shlex.quote(str(path)), f'prep -top {TOP}',
                         f'rename {TOP} {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        log = run(out, name, commands)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        passed = match is not None and int(match[2]) == 0 and 'Equivalence successfully proven' in text
        row = {'name': name, 'bus_width': bus, 'quant_client': quant, 'xilinx': fpga,
               'passed': passed, 'equivalent_bits': int(match[1]) if match else None,
               'dma_ports': ports['current'], 'log_sha256': digest(log)}
        report['runs'].append(row)
        report['passed'] = len(report['runs']) == len(profiles) and all(row['passed'] for row in report['runs'])
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key != 'dma_ports'}), flush=True)
        if not passed:
            raise RuntimeError('Arbiter state comparison did not complete')
    if source_hashes != {name: digest(ROOT / name) for name in sources}:
        raise RuntimeError('RTL sources changed during verification')


if __name__ == '__main__':
    main()
