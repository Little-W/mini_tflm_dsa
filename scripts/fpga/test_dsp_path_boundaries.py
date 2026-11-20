#!/usr/bin/env python3
"""用实际 Yosys DSP48E1 功能模型检查寄存器与组合运算的分界。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from netlist_metrics import connected_paths


REGISTERS = ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG', 'PREG',
             'ACASCREG', 'BCASCREG', 'INMODEREG', 'OPMODEREG',
             'ALUMODEREG', 'CARRYINREG', 'CARRYINSELREG')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(parameters, selected):
    settings = {name: 0 for name in REGISTERS}
    settings.update(USE_DPORT='FALSE', A_INPUT='DIRECT', B_INPUT='DIRECT')
    settings.update(parameters)
    formatted = ', '.join(f'.{name}({json.dumps(value)})' for name, value in settings.items())
    widths = {'P': 48, 'PCOUT': 48, 'ACOUT': 30, 'BCOUT': 18, 'MULTSIGNOUT': 1}
    declarations = '\n'.join(f'wire [{width - 1}:0] w_{name};' for name, width in widths.items())
    connected = ', '.join(f'.{name}(w_{name})' for name in widths)
    return f'''module top(input wire clk, input wire [29:0] a,
    input wire [17:0] b, input wire [47:0] c, input wire [24:0] d,
    output wire [{widths[selected] - 1}:0] observed, output wire captured);
wire q_a;
wire [29:0] a_registered = {{a[29:1], q_a}};
FDRE u_source (.C(clk), .CE(1'b1), .R(1'b0), .D(a[0]), .Q(q_a));
{declarations}
DSP48E1 #({formatted}) u_dsp (
    .CLK(clk), .A(a_registered), .ACIN(a_registered), .B(b), .BCIN(b), .C(c), .D(d),
    .PCIN(48'b0), .CARRYIN(1'b0), .CARRYCASCIN(1'b0), .MULTSIGNIN(1'b0),
    .OPMODE(7'b0000101), .ALUMODE(4'b0), .INMODE(5'b00100), .CARRYINSEL(3'b0),
    .CEA1(1'b1), .CEA2(1'b1), .CEB1(1'b1), .CEB2(1'b1), .CEC(1'b1), .CED(1'b1),
    .CEAD(1'b1), .CEM(1'b1), .CEP(1'b1), .CEINMODE(1'b1), .CECTRL(1'b1),
    .CEALUMODE(1'b1), .CECARRYIN(1'b1),
    .RSTA(1'b0), .RSTB(1'b0), .RSTC(1'b0), .RSTD(1'b0), .RSTM(1'b0), .RSTP(1'b0),
    .RSTINMODE(1'b0), .RSTCTRL(1'b0), .RSTALUMODE(1'b0), .RSTALLCARRYIN(1'b0),
    {connected});
assign observed = w_{selected};
FDRE u_capture (.C(clk), .CE(1'b1), .R(1'b0), .D(w_{selected}[0]), .Q(captured));
endmodule
'''


def register_cells(module):
    return {name: cell for name, cell in module['cells'].items()
            if cell['type'].startswith(('$dff', '$adff', '$sdff', '$aldff'))}


def combinational_distance(module, starts, targets):
    """只沿组合单元连接查找，内部时钟存储器的 Q 与 D 之间不建立边。"""
    targets = set(targets)
    queue = collections.deque((bit, 0) for bit in starts if isinstance(bit, int))
    seen = set()
    users = collections.defaultdict(list)
    registers = register_cells(module)
    for name, cell in module['cells'].items():
        if name in registers:
            continue
        inputs = [bit for port, bits in cell['connections'].items()
                  if cell['port_directions'][port] == 'input' for bit in bits]
        outputs = [bit for port, bits in cell['connections'].items()
                   if cell['port_directions'][port] == 'output' for bit in bits]
        for bit in inputs:
            if isinstance(bit, int):
                users[bit].extend(bit for bit in outputs if isinstance(bit, int))
    while queue:
        bit, distance = queue.popleft()
        if bit in targets:
            return distance
        if bit in seen:
            continue
        seen.add(bit)
        queue.extend((output, distance + 1) for output in users[bit] if output not in seen)
    return None


def internal_register(module, net):
    bits = set(module['netnames']['u_dsp.' + net]['bits'])
    found = [(name, cell) for name, cell in register_cells(module).items()
             if bits.intersection(cell['connections']['Q'])]
    if not found:
        raise AssertionError(f'No clocked register drives u_dsp.{net}')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    worker = Path(__file__).with_name('open_fpga_synth.py')
    cases = [
        ('input_registers', {'AREG': 1, 'BREG': 1, 'ACASCREG': 1, 'BCASCREG': 1}, 'P',
         'Ar2', 'output', 1),
        ('multiplier_register', {'MREG': 1}, 'P', 'Mr', 'output', 1),
        ('preadder_register', {'ADREG': 1, 'USE_DPORT': 'TRUE'}, 'P', 'ADr', 'output', 1),
        ('output_register', {'PREG': 1}, 'P', 'P', 'input', 1),
        ('internal_registers', {'AREG': 1, 'BREG': 1, 'PREG': 1}, 'P', 'Ar2', 'internal', 1),
        ('cascade_input', {'AREG': 1, 'A_INPUT': 'CASCADE'}, 'P', 'Ar2', 'output', 1),
        ('direct_a_cascade', {'AREG': 1}, 'ACOUT', 'Ar2', 'direct', 0),
        ('direct_multiplier_sign', {'MREG': 1}, 'MULTSIGNOUT', 'Mr', 'direct', 0),
        ('input_to_multiplier', {'AREG': 1, 'MREG': 1}, 'MULTSIGNOUT', 'Ar2', 'internal_m', 1),
    ]
    results = []
    for name, parameters, selected, register, direction, expected in cases:
        folder = args.out / name
        folder.mkdir(exist_ok=True)
        design = folder / 'design.v'
        design.write_text(source(parameters, selected))
        variants = {}
        for variant in ('primitive', 'expanded'):
            script = folder / (variant + '.ys')
            output = folder / (variant + '.json')
            command = ('read_verilog -lib ' if variant == 'primitive' else 'read_verilog -formal -sv -D VERIFIC ')
            commands = [command + shlex.quote(str(args.model)), 'read_verilog ' + shlex.quote(str(design)),
                        'hierarchy -top top']
            if variant == 'expanded':
                commands.extend(['proc', 'flatten', 'opt_expr', 'opt_clean'])
            else:
                commands.append('blackbox =A:whitebox')
            commands.append('write_json ' + shlex.quote(str(output)))
            script.write_text('\n'.join(commands) + '\n')
            with (folder / (variant + '.log')).open('w') as log:
                subprocess.run([sys.executable, str(worker), '--worker', str(script)],
                               env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT, check=True)
            variants[variant] = json.loads(output.read_text())['modules']['top']
        primitive = variants['primitive']
        # 未连接的输出不形成外部观察点，与综合网表的清理结果一致。
        for port in tuple(primitive['cells']['u_dsp']['connections']):
            if primitive['cells']['u_dsp']['port_directions'][port] == 'output' and port != selected:
                del primitive['cells']['u_dsp']['connections'][port]
        analysis = connected_paths(primitive,
                                   root_filter=(lambda name, _cell, _port: name == 'u_dsp')
                                   if direction == 'direct' else None,
                                   sink_filter=(lambda name, _cell, _port: name == 'u_capture')
                                   if direction == 'direct' else None)
        assert analysis['graph_complete']
        assert analysis['longest_register_path_cells'] == expected, (name, analysis)
        expanded = variants['expanded']
        registered = internal_register(expanded, register)
        q_bits = [bit for _, cell in registered for bit in cell['connections']['Q']]
        output_bits = expanded['netnames']['w_' + selected]['bits']
        if direction == 'input':
            starts = expanded['netnames']['q_a']['bits']
            targets = [bit for _, cell in registered for bit in cell['connections']['D']]
        elif direction in ('internal', 'internal_m'):
            starts = q_bits
            target_register = 'P' if direction == 'internal' else 'Mr'
            targets = [bit for _, cell in internal_register(expanded, target_register)
                       for bit in cell['connections']['D']]
        else:
            starts, targets = q_bits, output_bits
        distance = combinational_distance(expanded, starts, targets)
        assert distance is not None, name
        assert (distance == 0) == (direction == 'direct'), (name, distance)
        result = {'name': name, 'parameters': parameters, 'observed_output': selected,
                  'model_register': register, 'model_combination_nodes': distance,
                  'analysis_scope': 'DSP output to capture FF' if direction == 'direct' else 'All register boundaries',
                  'reported_register_path_cells': analysis['longest_register_path_cells'],
                  'model_connection_verified': True, 'model_output_sha256': digest(folder / 'expanded.json'),
                  'primitive_netlist_sha256': digest(folder / 'primitive.json'),
                  'paths': analysis['register_to_register_paths']}
        (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        results.append(result)
        print(name, 'passed', flush=True)
    summary = {'passed': True, 'case_count': len(results), 'model_kind': 'Yosys DSP48E1 functional model',
               'model_file': str(args.model), 'model_sha256': digest(args.model),
               'analyzer_sha256': digest(Path(__file__).with_name('netlist_metrics.py')),
               'test_sha256': digest(Path(__file__)), 'cases': results}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
