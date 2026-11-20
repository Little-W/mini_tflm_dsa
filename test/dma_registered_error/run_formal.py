#!/usr/bin/env python3
"""证明默认模式及寄存错误上报模式的完整仲裁状态和 DMA 端口关系。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOP = 'axi_block_dma_arbiter'
RTL = 'rtl/npu/dma/axi_block_dma_arbiter.sv'
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def helper_module():
    spec = importlib.util.spec_from_file_location(
        'arbiter_ports', ROOT / 'test/dma_return_admission/run_arbiter_formal.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(out, name, commands):
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    return log


def wrap(expanded, output, register_error, reference):
    module = json.loads(expanded.read_text())['modules'][TOP]
    declarations = []
    connections = []
    for name, port in module['ports'].items():
        width = len(port['bits'])
        declarations.append(f"{port['direction']} wire [{width-1}:0] {name}")
        signal = name
        if register_error and reference:
            if name == 'abort':
                signal = 'feedback_abort'
            elif name == 'bus_error':
                signal = 'response_error_event'
        connections.append(f'.{name}({signal})')
    body = ''
    if register_error and reference:
        # 参考系统由原仲裁器、同周期错误反馈和一级上报寄存器组成。
        body = '''
wire response_error_event;
wire feedback_abort = abort || response_error_event;
reg reported_error;
always @(posedge clk) begin
  if (!rst_n) reported_error <= 1'b0;
  else reported_error <= response_error_event;
end
assign bus_error = reported_error;
'''
    output.write_text('module observed_arbiter(\n' + ',\n'.join(declarations) +
                      '\n);\n' + body + '\narbiter_core u_core(\n' +
                      ',\n'.join(connections) + '\n);\nendmodule\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    parser.add_argument('--cases', nargs='*')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ports_helper = helper_module()
    sources = (RTL, 'rtl/npu/dma/axi_dual_block_dma.sv', 'rtl/npu/conv/conv_im2col_pkg.sv')
    hashes = {path: digest(ROOT / path) for path in sources}
    snapshots = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in sources:
            data = (read_rtl_source(f'{args.reference_ref}:{relative}', cwd=ROOT)
                    if label == 'reference' else (ROOT / relative).read_bytes())
            if relative.endswith('/axi_dual_block_dma.sv'):
                source = data.decode()
                header_end = re.search(r'^\s*\);', source, re.M).end()
                data = (source[:header_end] + '\nendmodule\n').encode()
            path = folder / Path(relative).name
            path.write_bytes(data)
            snapshots[label].append(path)
    profiles = [(f'bus{bus}_quant{quant}_fpga', bus, quant, True)
                for bus in (32, 64, 128) for quant in (0, 1)]
    profiles.append(('bus64_quant1_asic', 64, 1, False))
    report = {'reference_ref': args.reference_ref, 'source_sha256': hashes,
              'source_inputs_constrained': False, 'dma_outputs_constrained': False,
              'reference_composition': 'Original arbiter with immediate bus-error abort feedback; '
                                       'one reporting register in registered mode',
              'scope': 'All arbiter state, all public outputs and every unchanged DMA port',
              'runs': [], 'passed': False}
    for profile, bus, quant, fpga in profiles:
        for register_error in (0, 1):
            name = profile + ('_registered' if register_error else '_direct')
            if args.cases and name not in args.cases:
                continue
            ports = {}
            for label in ('reference', 'current'):
                options = ['-GSIZE=16', '-GDMA_SIZE=64', '-GCACHE_BLOCKS=64',
                           f'-GBUS_WIDTH={bus}', f'-GENABLE_QUANT_CLIENT={quant}',
                           '-DXILINX_FPGA=1' if fpga else '-DASIC_SYNTHESIS=1']
                if label == 'current':
                    options.append(f'-Gp_register_bus_error={register_error}')
                raw = out / f'{name}_{label}.json'
                expanded = out / f'{name}_{label}_expanded.json'
                arbiter, dma, package = snapshots[label]
                run(out, f'{name}_{label}_elaborate', [
                    f'read_slang --keep-hierarchy --top {TOP} ' + ' '.join(options) + ' ' +
                    ' '.join(shlex.quote(str(p)) for p in (package, arbiter, dma)),
                    'blackbox axi_dual_block_dma*', f'prep -top {TOP} -flatten',
                    'memory_map', 'async2sync', 'opt_clean',
                    'write_json ' + shlex.quote(str(raw))])
                ports[label] = ports_helper.expand_dma_ports(raw, expanded)
                wrap(expanded, out / f'{name}_{label}_wrapper.v', register_error, label == 'reference')
            if ports['reference'] != ports['current']:
                raise RuntimeError('DMA boundary changed')
            commands = []
            for label in ('reference', 'current'):
                commands += [
                    'read_json ' + shlex.quote(str(out / f'{name}_{label}_expanded.json')),
                    f'rename {TOP} arbiter_core',
                    'read_verilog ' + shlex.quote(str(out / f'{name}_{label}_wrapper.v')),
                    'prep -top observed_arbiter -flatten', 'opt_clean',
                    # 两个内部连接分别处于报告寄存器前后；所有公开端口仍参与比较。
                    'rename -hide w:u_core.abort w:u_core.bus_error',
                    f'rename observed_arbiter {label}', f'design -stash {label}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                         'equiv_induct -seq 2', 'equiv_status -assert']
            log = run(out, name, commands)
            text = log.read_text()
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
                raise RuntimeError('Complete arbiter equivalence not established')
            row = {'case': name, 'bus_width': bus, 'quant_client': quant,
                   'xilinx': fpga, 'register_bus_error': bool(register_error),
                   'passed': True, 'equivalent_bits': int(match[1]),
                   'dma_ports': ports['current'], 'log_sha256': digest(log)}
            report['runs'].append(row)
            print(json.dumps({key: value for key, value in row.items() if key != 'dma_ports'}), flush=True)
    if not report['runs']:
        raise RuntimeError('No verification cases selected')
    if hashes != {path: digest(ROOT / path) for path in sources}:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
