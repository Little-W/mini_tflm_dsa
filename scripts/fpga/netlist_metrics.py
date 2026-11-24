#!/usr/bin/env python3
"""Report Xilinx resource use and connected register-to-register logic paths."""
from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path
import re

from lut_dependencies import LUT_PATTERN, lut_output_dependencies


RAM_LUT_SITES = {
    'RAM32M': 4, 'RAM64M': 4,
    'RAM32X1S': 1, 'RAM64X1S': 1, 'RAM32X2S': 1,
    'RAM32X1D': 2, 'RAM64X1D': 2,
    'RAM128X1S': 2, 'RAM256X1S': 4, 'RAM128X1D': 4,
    'RAMD32': 1, 'RAMS32': 1, 'RAMD64E': 1, 'RAMS64E': 1,
}
SRL_TYPES = {'SRL16E', 'SRLC32E', 'SRL16', 'SRLC16E'}
FF_PATTERN = re.compile(r'FD(?:RE|SE|CE|PE)(?:_1)?$')


def resources(cells):
    counts = collections.Counter(cell['type'] for cell in cells.values())
    logic = sum(count for kind, count in counts.items() if LUT_PATTERN.fullmatch(kind))
    dram = sum(counts[kind] * sites for kind, sites in RAM_LUT_SITES.items())
    srl = sum(counts[kind] for kind in SRL_TYPES)
    unknown = sorted(kind for kind in counts if kind.startswith('RAM')
                     and not kind.startswith('RAMB') and kind not in RAM_LUT_SITES)
    return {
        'logic_lut_cells': logic,
        'distributed_ram_lut_sites_nominal': dram,
        'shift_register_lut_sites_nominal': srl,
        'lut_sites_nominal_before_packing': logic + dram + srl,
        'physical_lut_sites_after_placement': None,
        'flip_flops': sum(count for kind, count in counts.items() if FF_PATTERN.fullmatch(kind)),
        'dsp48e1': counts['DSP48E1'],
        'ramb36e1': counts['RAMB36E1'], 'ramb18e1': counts['RAMB18E1'],
        'carry4': counts['CARRY4'],
        'unclassified_distributed_ram_types': unknown,
        'cell_counts': dict(sorted(counts.items())),
        'counting_method': 'Each LUT primitive is counted once before packing; LUT RAM and SRL use their architectural LUT storage requirements. Packing may combine compatible logic LUTs or insert routing LUTs. A placed design supplies physical_lut_sites_after_placement.',
    }


def parameter(cell, name, default=0):
    value = cell.get('parameters', {}).get(name, default)
    if isinstance(value, str):
        return int(value, 2) if re.fullmatch(r'[01]+', value) else default
    return int(value)


def boolean_parameter(cell, name, default=False):
    """读取 Vivado 布尔值和 Yosys 二进制参数，并保留非法值检查。"""
    value = cell.get('parameters', {}).get(name, default)
    if isinstance(value, (bool, int)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().upper()
        if value in ('TRUE', 'FALSE'):
            return value == 'TRUE'
        if re.fullmatch(r'[01]+', value) and int(value, 2) in (0, 1):
            return bool(int(value, 2))
    raise ValueError(f'Invalid boolean primitive parameter {name}: {value!r}')


def dsp_alu_low_bit_dependencies(cell):
    """识别无移位的 A:B 与 C 运算，进位在同一 SIMD 通道内向高位传播。"""
    settings = cell.get('parameters', {})
    required = {'USE_MULT': 'NONE', 'A_INPUT': 'DIRECT', 'B_INPUT': 'DIRECT'}
    if any(str(settings.get(key, default)).strip() != default for key, default in required.items()):
        return False
    if boolean_parameter(cell, 'USE_DPORT'):
        return False
    # 未声明的 USE_MULT 采用原语默认乘法模式，不能按纯 ALU 处理。
    if str(settings.get('USE_MULT', 'MULTIPLY')).strip() != 'NONE':
        return False
    if str(settings.get('USE_SIMD', 'ONE48')).strip() not in ('ONE48', 'FOUR12'):
        return False
    for name in ('OPMODEREG', 'INMODEREG', 'CARRYINSELREG'):
        if parameter(cell, name, 1):
            return False
    for name in ('IS_OPMODE_INVERTED', 'IS_INMODE_INVERTED'):
        if name in settings and parameter(cell, name, -1) != 0:
            return False
    for port, expected, width in (('OPMODE', 0b0110011, 7), ('INMODE', 0, 5), ('CARRYINSEL', 0, 3)):
        bits = cell['connections'].get(port, [])
        if len(bits) != width or any(bit not in ('0', '1') for bit in bits):
            return False
        if sum(int(bit) << index for index, bit in enumerate(bits)) != expected:
            return False
    return True


def net_names(module):
    aliases = collections.defaultdict(list)
    for name, net in module.get('netnames', {}).items():
        bits = net['bits']
        for index, bit in enumerate(bits):
            if isinstance(bit, int):
                aliases[bit].append(name if len(bits) == 1 else f'{name}[{index}]')
    return {bit: min(names, key=lambda n: (n.startswith('$'), len(n), n))
            for bit, names in aliases.items()}


def register_origins(path, top=None):
    """Expand saved register Q names through the complete retained RTL hierarchy."""
    modules, pending_attributes = {}, {}
    module = current = None

    def identifiers(line):
        fields = line.split('# ', 1)[0].split()
        comments = iter(part.strip() for part in line.split('# ')[1:])
        return [next(comments) if re.fullmatch(r'\$(?:pub|priv)@[0-9]+', field) else field
                for field in fields]

    def true_attribute(value):
        return bool(re.fullmatch(r"(?:[0-9]+')?0*1", value))

    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as source:
        for line in source:
            if line.startswith('attribute '):
                fields = line.split(maxsplit=2)
                pending_attributes[fields[1].lstrip('\\')] = fields[2].strip()
            elif line.startswith('module '):
                name = identifiers(line)[1].lstrip('\\')
                module = {'origins': {}, 'children': [], 'attributes': pending_attributes}
                modules[name] = module
                pending_attributes = {}
            elif line.startswith('  cell ') and module is not None:
                _, kind, name = identifiers(line)
                kind = kind.lstrip('\\')
                current = None
                if FF_PATTERN.fullmatch(kind):
                    current = name
                elif not kind.startswith('$_'):
                    module['children'].append((name, kind))
            elif current and line.startswith('    connect '):
                connection = (line.split('# ', 1)[1] if '# ' in line
                              else line.strip().removeprefix('connect '))
                if connection.startswith('\\Q '):
                    module['origins'][current] = connection.strip().removeprefix('\\Q ')
            elif line.startswith('  end'):
                current = None
            elif line.strip() == 'end':
                module = None
    active = {name: value for name, value in modules.items()
              if not any(true_attribute(value['attributes'].get(key, '0')) for key in ('blackbox', 'whitebox'))}
    if top is None:
        tops = [name for name, value in active.items() if true_attribute(value['attributes'].get('top', '0'))]
        if not tops:
            children = {kind for value in active.values() for _, kind in value['children']}
            tops = [name for name in active if name not in children]
        if len(tops) != 1:
            raise ValueError('A unique top module is required to expand register origins')
        top = tops[0]
    if top not in active:
        raise ValueError('Register-origin top module is missing: ' + top)
    origins = {}

    def flattened_name(instances, name):
        if not instances:
            return name.lstrip('\\')
        if name.startswith('$'):
            suffix = name.removeprefix('$flatten')
            return '$flatten' + '.'.join(instances) + '.' + suffix
        return '.'.join(part.lstrip('\\') for part in (*instances, name))

    def walk(name, instances, visiting):
        if name in visiting:
            raise ValueError('Recursive module hierarchy in register-origin input')
        value = active[name]
        prefix = '.'.join(part.lstrip('\\') for part in instances)
        for cell, signal in value['origins'].items():
            if prefix:
                signal = re.sub(r'\\[^\s{}]+|\$[^\s{}]+',
                                lambda match: prefix + '.' + match[0].lstrip('\\'), signal)
            origins[flattened_name(instances, cell)] = signal.lstrip('\\')
        for cell, kind in value['children']:
            if kind in active:
                walk(kind, (*instances, cell), visiting | {name})

    walk(top, (), set())
    return origins


def connected_paths(module, limit=20, group_limit=12, root_filter=None, sink_filter=None,
                    minimum_path_cells=0):
    """Find actual connected paths, respecting per-output carry and LUT6_2 dependencies."""
    if min(limit, group_limit, minimum_path_cells) < 0:
        raise ValueError('Path reporting limits must be nonnegative')
    cells = module['cells']
    names = net_names(module)
    incoming = collections.defaultdict(list)
    outgoing = collections.defaultdict(list)
    roots = {}
    root_prefixes = {}
    sinks = []
    nodes = set()
    unknown = collections.Counter()
    dsp_bypass = []
    internal_paths = []

    def origin(cell):
        attributes = cell.get('attributes', {})
        return {'source': attributes.get('src', ''),
                'register_origin': attributes.get('fpga_register_origin')}

    def root(bit, name, cell, port, detail='register output', arithmetic_registers=None, output_index=0):
        if root_filter is not None and not root_filter(name, cell, port):
            return
        if isinstance(bit, int):
            nodes.add(bit)
            if bit in roots:
                return
            roots[bit] = {'cell': name, 'type': cell['type'], 'port': port,
                          'net': names.get(bit, str(bit)), 'detail': detail, **origin(cell)}
            if arithmetic_registers:
                # 起点位于 DSP 内部寄存器，先经过同一 DSP 的组合运算再到输出端口。
                roots[bit].update(internal_register_parameters=arithmetic_registers,
                                  external_output_port=port, port='INTERNAL_REGISTER_OUTPUT', net=None,
                                  register_origin=name + '.internal_register_output')
                root_prefixes[bit] = {'cell': name, 'type': cell['type'],
                                     'input_port': 'INTERNAL_REGISTER_OUTPUT',
                                     'output_port': f'{port}[{output_index}]', 'input_net': None,
                                     'output_net': names.get(bit, str(bit)),
                                     'input_internal_registers': arithmetic_registers,
                                     'source': cell.get('attributes', {}).get('src', '')}

    def sink(bit, name, cell, port, category='data', arithmetic_registers=None, input_index=0):
        if sink_filter is not None and not sink_filter(name, cell, port):
            return
        if isinstance(bit, int):
            nodes.add(bit)
            endpoint = {'cell': name, 'type': cell['type'], 'port': port,
                        'net': names.get(bit, str(bit)), 'category': category, **origin(cell)}
            if arithmetic_registers:
                endpoint.update(internal_register_parameters=arithmetic_registers,
                                external_input_port=port, port='INTERNAL_REGISTER_INPUT', net=None,
                                register_origin=name + '.internal_register_input')
                endpoint['combinational_suffix'] = {
                    'cell': name, 'type': cell['type'], 'input_port': f'{port}[{input_index}]',
                    'output_port': 'INTERNAL_REGISTER_INPUT', 'input_net': names.get(bit, str(bit)),
                    'output_net': None, 'output_internal_registers': arithmetic_registers,
                    'source': cell.get('attributes', {}).get('src', '')}
            sinks.append((bit, endpoint))

    def arcs(name, cell, output, inputs, output_index=0):
        for oi, obit in enumerate(cell['connections'].get(output, [])):
            if not isinstance(obit, int):
                continue
            nodes.add(obit)
            for port, selected in inputs:
                for ii, ibit in selected:
                    if not isinstance(ibit, int):
                        continue
                    nodes.add(ibit)
                    edge = (ibit, obit, name, cell['type'], f'{port}[{ii}]', f'{output}[{oi + output_index}]')
                    incoming[obit].append(edge)
                    outgoing[ibit].append(edge)

    for name, cell in cells.items():
        kind = cell['type']
        ports = cell['connections']
        inputs = [(p, list(enumerate(bits))) for p, bits in ports.items()
                  if cell['port_directions'][p] == 'input']
        outputs = [p for p in ports if cell['port_directions'][p] == 'output']
        if FF_PATTERN.fullmatch(kind):
            for bit in ports.get('Q', []):
                root(bit, name, cell, 'Q')
            for port in ('D', 'CE', 'R', 'S', 'CLR', 'PRE'):
                for bit in ports.get(port, []):
                    sink(bit, name, cell, port, 'data' if port == 'D' else 'control')
        elif kind.startswith('RAMB'):
            for port in outputs:
                for bit in ports[port]:
                    root(bit, name, cell, port, 'synchronous block RAM output')
            for port, bits in inputs:
                if not port.startswith(('CLK', 'CASCADE')):
                    for _, bit in bits:
                        sink(bit, name, cell, port, 'data' if port.startswith(('DI', 'ADDR')) else 'control')
        elif kind == 'DSP48E1':
            low_bit_dependencies = dsp_alu_low_bit_dependencies(cell)
            input_stage = {'A': 'AREG', 'ACIN': 'AREG', 'B': 'BREG', 'BCIN': 'BREG',
                           'C': 'CREG', 'D': 'DREG', 'INMODE': 'INMODEREG',
                           'OPMODE': 'OPMODEREG', 'ALUMODE': 'ALUMODEREG',
                           'CARRYIN': 'CARRYINREG', 'CARRYINSEL': 'CARRYINSELREG'}
            preg = parameter(cell, 'PREG')
            mreg = parameter(cell, 'MREG')
            use_dport = boolean_parameter(cell, 'USE_DPORT')
            adreg = parameter(cell, 'ADREG') and use_dport
            internal_registers = [key for key in ('AREG', 'BREG', 'CREG', 'DREG', 'ADREG', 'MREG',
                                  'INMODEREG', 'OPMODEREG', 'ALUMODEREG', 'CARRYINREG', 'CARRYINSELREG')
                                  if parameter(cell, key) and (key not in ('ADREG', 'DREG') or use_dport)]
            input_mode = {key: str(cell.get('parameters', {}).get(key, 'DIRECT')).strip()
                          for key in ('A_INPUT', 'B_INPUT')}
            opmode_low = ports.get('OPMODE', [])[:2]
            ab_bypass = len(opmode_low) != 2 or all(bit != '0' for bit in opmode_low)
            combinational = []
            internal_register = bool(adreg)
            for port, bits in inputs:
                if port.startswith(('CLK', 'RST', 'CE')):
                    if not port.startswith('CLK'):
                        for _, bit in bits:
                            sink(bit, name, cell, port, 'control')
                    continue
                if ((port == 'A' and input_mode['A_INPUT'] == 'CASCADE')
                        or (port == 'ACIN' and input_mode['A_INPUT'] != 'CASCADE')
                        or (port == 'B' and input_mode['B_INPUT'] == 'CASCADE')
                        or (port == 'BCIN' and input_mode['B_INPUT'] != 'CASCADE')):
                    continue
                if port == 'D' and not use_dport:
                    continue
                registered = parameter(cell, input_stage.get(port, '')) > 0
                multiply_path = port in ('A', 'ACIN', 'B', 'BCIN', 'D', 'INMODE')
                preadder_path = port in ('A', 'ACIN', 'D', 'INMODE')
                internal_register |= registered or bool(multiply_path and mreg)
                input_boundary = ('ADREG' if adreg and port in ('A', 'ACIN', 'D', 'INMODE') else
                                  'MREG' if mreg and port in ('A', 'ACIN', 'B', 'BCIN', 'D', 'INMODE') else
                                  'PREG' if preg else None)
                if registered or input_boundary:
                    for index, bit in bits:
                        sink(bit, name, cell, port, arithmetic_registers=None if registered else [input_boundary],
                             input_index=index)
                arithmetic_cut = bool((multiply_path and mreg) or (preadder_path and adreg))
                direct_ab_path = port in ('A', 'ACIN', 'B', 'BCIN') and ab_bypass
                if not registered and (not arithmetic_cut or direct_ab_path):
                    combinational.append((port, bits))
            for port in outputs:
                cascade = {'ACOUT': ('ACIN' if input_mode['A_INPUT'] == 'CASCADE' else 'A', 'AREG'),
                           'BCOUT': ('BCIN' if input_mode['B_INPUT'] == 'CASCADE' else 'B', 'BREG')}.get(port)
                if cascade:
                    source_port, register_parameter = cascade
                    if parameter(cell, register_parameter):
                        for bit in ports[port]:
                            root(bit, name, cell, port, 'DSP cascade register output')
                    else:
                        arcs(name, cell, port, [(source_port, list(enumerate(ports.get(source_port, []))))])
                elif preg:
                    for index, bit in enumerate(ports[port]):
                        if port in ('OVERFLOW', 'UNDERFLOW'):
                            root(bit, name, cell, port, 'DSP pattern registers followed by status logic',
                                 arithmetic_registers=['PREG'], output_index=index)
                        else:
                            root(bit, name, cell, port, 'DSP output register')
                else:
                    if port != 'MULTSIGNOUT' or not mreg:
                        if low_bit_dependencies and port in ('P', 'PCOUT'):
                            lane_width = 12 if str(cell['parameters'].get('USE_SIMD', 'ONE48')).strip() == 'FOUR12' else 48
                            for index, bit in enumerate(ports[port]):
                                first_bit = index // lane_width * lane_width
                                selected = []
                                for input_port, bits in combinational:
                                    if input_port in ('A', 'B', 'C'):
                                        offset = 18 if input_port == 'A' else 0
                                        bits = [(position, value) for position, value in bits
                                                if first_bit <= position + offset <= index]
                                    selected.append((input_port, bits))
                                view = {**cell, 'connections': {**ports, port: [bit]}}
                                arcs(name, view, port, selected, index)
                        else:
                            arcs(name, cell, port, combinational)
                    if internal_register:
                        for index, bit in enumerate(ports[port]):
                            if port == 'MULTSIGNOUT' and mreg:
                                root(bit, name, cell, port, 'DSP multiplier register sign output')
                            else:
                                root(bit, name, cell, port, 'DSP internal register followed by unregistered arithmetic',
                                     arithmetic_registers=internal_registers, output_index=index)
            internal_segments = []
            if adreg:
                upstream = [key for key in ('AREG', 'DREG', 'INMODEREG') if key in internal_registers]
                if upstream:
                    internal_segments.append((upstream, 'ADREG'))
            if mreg:
                upstream = [key for key in ('AREG', 'BREG', 'DREG', 'ADREG', 'INMODEREG') if key in internal_registers]
                if upstream:
                    internal_segments.append((upstream, 'MREG'))
            if preg and internal_registers:
                internal_segments.append((internal_registers, 'PREG'))
            for upstream, target in internal_segments:
                if not any(isinstance(bit, int) for port in outputs if port not in ('ACOUT', 'BCOUT') for bit in ports[port]):
                    continue
                # 两个内部寄存边界之间的算术没有外部连线，仍形成一个完整寄存器间路径。
                if ((root_filter is None or root_filter(name, cell, 'INTERNAL_REGISTER_OUTPUT'))
                        and (sink_filter is None or sink_filter(name, cell, 'INTERNAL_REGISTER_INPUT'))):
                    internal_paths.append({
                        'combinational_cells': 1,
                        'startpoint': {'cell': name, 'type': kind, 'port': 'INTERNAL_REGISTER_OUTPUT', 'net': None,
                                      'detail': 'DSP internal register output', 'internal_register_parameters': upstream,
                                      **origin(cell), 'register_origin': name + '.internal_register_output'},
                        'endpoint': {'cell': name, 'type': kind, 'port': 'INTERNAL_REGISTER_INPUT', 'net': None,
                                     'category': 'data', 'internal_register_parameters': [target],
                                     **origin(cell), 'register_origin': name + '.internal_register_input'},
                        'path': [{'cell': name, 'type': kind, 'input_port': 'INTERNAL_REGISTER_OUTPUT',
                                  'output_port': 'INTERNAL_REGISTER_INPUT', 'input_net': None, 'output_net': None,
                                  'input_internal_registers': upstream, 'output_internal_registers': [target],
                                  'source': cell.get('attributes', {}).get('src', '')}]})
            if not preg:
                dsp_bypass.append(name)
        elif kind == 'CARRY4':
            for output in ('O', 'CO'):
                for index, bit in enumerate(ports.get(output, [])):
                    view = {**cell, 'connections': {**ports, output: [bit]}}
                    selected = []
                    for port in ('CI', 'CYINIT', 'S', 'DI'):
                        width = len(ports.get(port, []))
                        stop = index + (1 if output == 'CO' or port == 'S' else 0)
                        indices = range(width) if port in ('CI', 'CYINIT') else range(min(stop, width))
                        selected.append((port, [(i, ports[port][i]) for i in indices]))
                    arcs(name, view, output, selected, index)
        elif LUT_PATTERN.fullmatch(kind):
            for port in outputs:
                selected = [(p, [(index, bit)]) for p, index, bit in lut_output_dependencies(cell, port)]
                arcs(name, cell, port, selected)
        elif kind in ('INV', 'MUXF7', 'MUXF8', 'MUXF9', 'IBUF', 'OBUF'):
            for port in outputs:
                arcs(name, cell, port, inputs)
        elif kind in RAM_LUT_SITES or kind in SRL_TYPES:
            address = [(p, b) for p, b in inputs if re.fullmatch(r'ADDR[A-D]|A|A[0-9]+|ADR[0-9]+|DPRA|DPRA[0-9]+|RADR[0-9]+', p)]
            for port in outputs:
                selected = address
                if kind in ('RAM32M', 'RAM64M') and port.startswith('DO'):
                    selected = [(p, b) for p, b in address if p == 'ADDR' + port[-1]]
                elif port == 'DPO':
                    selected = [(p, b) for p, b in address if p.startswith('DPRA')]
                elif port == 'SPO':
                    selected = [(p, b) for p, b in address if p.startswith('A')]
                arcs(name, cell, port, selected)
                for bit in ports[port]:
                    root(bit, name, cell, port, 'stored data with asynchronous address selection')
            for port, bits in inputs:
                read_only = port.startswith(('DPRA', 'RADR'))
                read_only |= kind in SRL_TYPES and port.startswith('A')
                read_only |= kind in ('RAM32M', 'RAM64M') and port in ('ADDRA', 'ADDRB', 'ADDRC')
                if not port.startswith(('CLK', 'WCLK')) and not read_only:
                    for _, bit in bits:
                        sink(bit, name, cell, port, 'data' if port in ('D', 'I', 'DI', 'DIA', 'DIB', 'DIC', 'DID') else 'control')
        elif kind in ('BUFGCE', 'BUFGCE_1', 'BUFGCTRL', 'BUFHCE'):
            for port in ('CE', 'CE0', 'CE1', 'S0', 'S1'):
                for bit in ports.get(port, []):
                    sink(bit, name, cell, port, 'clock_enable')
        elif kind in ('BUFG', 'BUFH', 'VCC', 'GND'):
            pass
        else:
            unknown[kind] += 1

    degree = {node: len(incoming[node]) for node in nodes}
    ready = collections.deque(sorted(node for node in nodes if degree[node] == 0))
    depth = {node: (1 if node in root_prefixes else 0) if node in roots else -1 for node in nodes}
    predecessor = {}
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for edge in outgoing[node]:
            _, child, *_ = edge
            if depth[node] >= 0 and depth[node] + 1 > depth[child]:
                depth[child] = depth[node] + 1
                predecessor[child] = edge
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    cyclic = sorted(node for node, count in degree.items() if count)

    def trace(bit, endpoint):
        if bit < 0:
            return internal_paths[-bit - 1]
        steps = []
        seen = set()
        current = bit
        while current in predecessor:
            if current in seen:
                raise RuntimeError('Cycle encountered while reconstructing a combinational path')
            seen.add(current)
            start, end, name, kind, iport, oport = predecessor[current]
            steps.append({'cell': name, 'type': kind, 'input_port': iport, 'output_port': oport,
                          'input_net': names.get(start, str(start)), 'output_net': names.get(end, str(end)),
                          'source': cells[name].get('attributes', {}).get('src', '')})
            current = start
        if current in root_prefixes:
            steps.append(root_prefixes[current])
        steps.reverse()
        endpoint = dict(endpoint)
        suffix = endpoint.pop('combinational_suffix', None)
        if suffix:
            steps.append(suffix)
        return {'combinational_cells': len(steps), 'startpoint': roots.get(current),
                'endpoint': endpoint, 'path': steps}

    ranked = [(depth[bit] + int('combinational_suffix' in endpoint), bit, endpoint)
              for bit, endpoint in sinks if depth[bit] >= 0]
    ranked.extend((1, -index - 1, path['endpoint']) for index, path in enumerate(internal_paths))
    ranked.sort(key=lambda item: (-item[0], item[2]['cell'], item[2]['port'], item[1]))
    endpoint_depths = {}
    for length, _, endpoint in ranked:
        endpoint_depths.setdefault((endpoint['cell'], endpoint['port']), length)
    depth_histogram = collections.Counter(endpoint_depths.values())
    paths = []
    groups = []
    seen_endpoints = set()
    seen_groups = set()
    for length, bit, endpoint in ranked:
        if length < minimum_path_cells:
            break
        key = (endpoint['cell'], endpoint['port'])
        if key in seen_endpoints:
            continue
        seen_endpoints.add(key)
        path = trace(bit, endpoint)
        if len(paths) < limit:
            paths.append(path)
        endpoints = [path['startpoint'] or {}, endpoint]
        group_key = tuple(re.sub(r'\[\d+(?::\d+)?\]', '', point.get('register_origin') or point.get('source', '').split('|')[0]
                                or point.get('cell', '')) for point in endpoints)
        arithmetic = tuple(dict.fromkeys(step['source'].split('|')[0] for step in path['path']
                                         if step['type'] in ('CARRY4', 'DSP48E1')))
        if arithmetic:
            group_key = ('arithmetic', arithmetic)
        if group_key not in seen_groups and len(groups) < group_limit:
            seen_groups.add(group_key)
            groups.append(path)
        if len(paths) >= limit and len(groups) >= group_limit:
            break
    return {
        'register_to_register_paths': paths,
        'distinct_register_path_groups': groups,
        'longest_register_path_cells': ranked[0][0] if ranked else 0,
        'endpoint_port_maximum_depth_histogram': dict(sorted(depth_histogram.items())),
        'report_limits': {'paths': limit, 'groups': group_limit,
                          'minimum_combinational_cells': minimum_path_cells},
        'graph_nodes': len(nodes), 'visited_graph_nodes': visited,
        'combinational_cycle_nodes': [names.get(bit, str(bit)) for bit in cyclic[:20]],
        'unclassified_cell_types': dict(sorted(unknown.items())),
        'graph_complete': not unknown and not cyclic,
        'dsp_without_output_register': dsp_bypass,
        'path_method': 'Connected bit graph from clocked storage to synchronous data/control inputs. Each LUT output follows its INIT truth table after binding constants and repeated signals; unknown truth tables retain all possible dependencies. CARRY4 dependencies follow carry direction, and asynchronous memory outputs depend on read addresses. DSP register parameters define clocked boundaries. Arithmetic between an input port and an internal register, between internal registers, or between an internal register and an output port contributes one DSP cell for that connected segment. Direct registered outputs contribute zero arithmetic cells. Identified ONE48 and FOUR12 A:B/C ALU modes preserve low-to-high carry direction within each SIMD lane for P and PCOUT; other DSP dependencies remain conservative, including the A:B ALU bypass. Counts describe structural depth; primitive and routing delays require device timing analysis.',
    }


def register_path_requirement(paths, maximum=10):
    """分别保存完整路径图、实际组合单元数和指定结构限制。"""
    if maximum < 0:
        raise ValueError('The register path limit must be nonnegative')
    observed = paths['longest_register_path_cells']
    complete = paths['graph_complete']
    return {'maximum_combinational_cells': maximum, 'observed_combinational_cells': observed,
            'graph_complete': complete, 'met': observed <= maximum if complete else None,
            'scope': 'Clocked storage outputs to synchronous data and control inputs',
            'timing_frequency_validation': 'Requires primitive and routing delays for the target device'}


def analyze(module, maximum_register_path_cells=10, **path_options):
    paths = connected_paths(module, **path_options)
    return {'resources': resources(module['cells']), 'paths': paths,
            'register_path_requirement': register_path_requirement(paths, maximum_register_path_cells)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--top', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--register-origins', type=Path, help='pre_lut.il containing original register signal names')
    parser.add_argument('--path-limit', type=int, default=20)
    parser.add_argument('--group-limit', type=int, default=12)
    parser.add_argument('--max-register-path-cells', type=int, default=10,
                        help='Maximum permitted mapped combinational cells between clocked storage boundaries')
    parser.add_argument('--require-register-path-limit', action='store_true',
                        help='Return failure if the complete graph does not confirm the specified limit')
    parser.add_argument('--minimum-path-cells', type=int, default=0,
                        help='Filter reported paths; the complete graph still determines the maximum depth')
    args = parser.parse_args()
    with (gzip.open(args.netlist, 'rt') if args.netlist.suffix == '.gz' else args.netlist.open()) as source:
        design = json.load(source)
    module = design['modules'][args.top]
    if args.register_origins:
        for name, origin in register_origins(args.register_origins).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = analyze(module, maximum_register_path_cells=args.max_register_path_cells,
                     limit=args.path_limit, group_limit=args.group_limit,
                     minimum_path_cells=args.minimum_path_cells)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['resources'], indent=2))
    print('longest_register_path_cells', result['paths']['longest_register_path_cells'])
    if args.require_register_path_limit and result['register_path_requirement']['met'] is not True:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
