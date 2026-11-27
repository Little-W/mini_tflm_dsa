#!/usr/bin/env python3
"""保存 Vivado 输入文件指纹，并从原生利用率与端点报告生成测量结果。"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from netlist_metrics import connected_paths

TARGET_PERIOD_NS = 1000.0 / 150.0
TARGET_PERIOD_EXACT = Fraction(1000, 150)
DEFAULT_MAX_SLICE_LUTS = 55000
DSP_REGISTERS = ('AREG', 'ACASCREG', 'BREG', 'BCASCREG', 'CREG', 'DREG',
                 'ADREG', 'MREG', 'PREG', 'INMODEREG', 'OPMODEREG', 'ALUMODEREG',
                 'CARRYINREG', 'CARRYINSELREG')
DSP_MODES = ('A_INPUT', 'B_INPUT', 'USE_MULT', 'USE_DPORT', 'USE_SIMD')


def all_confirmed(values):
    """分别保留不满足条件与缺少测量数据的状态。"""
    values = list(values)
    return False if False in values else None if None in values else True


def graph_parameter(value):
    value = value.strip()
    literal = re.fullmatch(r"(\d+)'([hHbBdD])([0-9a-fA-F_]+)", value)
    if literal:
        return int(literal[3].replace('_', ''), {'h': 16, 'b': 2, 'd': 10}[literal[2].lower()])
    if re.fullmatch(r'[0-9]+', value):
        return int(value)
    if re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
        return int(value, 16)
    return value


def connectivity(path):
    """读取全部原语引脚，核对导出数量后建立与开源综合相同的位级连接图。"""
    content = Path(path).read_text()
    if not content.endswith('\n'):
        raise ValueError('Connectivity export did not finish')
    records = list(csv.reader(content.splitlines(), delimiter='\t', quoting=csv.QUOTE_NONE))
    if not records or records[0] != ['format', 'vivado_connectivity_v1']:
        raise ValueError('Missing complete connectivity format header')
    if len(records[-1]) != 4 or records[-1][0] != 'complete':
        raise ValueError('Connectivity export did not finish')
    expected = tuple(map(int, records[-1][1:]))
    if len(records) < 4 or len(records[1]) != 5 or records[1][:2] != ['scope', 'soc_top']:
        raise ValueError('Missing complete SoC hierarchy scope')
    _, _, scope_kind, scope_name, outside_count = records[1]
    if scope_kind not in ('top', 'instance') or not scope_name or int(outside_count) < 0:
        raise ValueError('Invalid SoC hierarchy scope')
    if scope_kind == 'top' and (scope_name != 'soc_top' or int(outside_count) != 0):
        raise ValueError('Native connectivity must cover the entire soc_top design')
    cells, pins, ports = {}, {}, {}
    net_ids = {}

    def signal(name):
        if name not in net_ids:
            net_ids[name] = len(net_ids) + 2
        return net_ids[name]

    for row in records[2:-1]:
        if row[0] == 'cell' and len(row) == 5:
            _, name, kind, blackbox, count = row
            if scope_kind == 'instance' and not name.startswith(scope_name + '/') and kind not in ('VCC', 'GND'):
                raise ValueError('Primitive outside the declared SoC instance: ' + name)
            if name in cells or blackbox != '0' or not kind or int(count) < 1:
                raise ValueError('Invalid, duplicate or black-box cell: ' + name)
            cells[name] = {'type': kind, 'parameters': {}, 'connections': {},
                           'port_directions': {}, 'attributes': {'fpga_register_origin': name},
                           'expected_pin_count': int(count)}
            pins[name] = {}
        elif row[0] == 'parameter' and len(row) == 4:
            _, cell, name, value = row
            if cell not in cells or name in cells[cell]['parameters']:
                raise ValueError('Invalid or duplicate primitive parameter')
            cells[cell]['parameters'][name] = graph_parameter(value)
        elif row[0] == 'pin' and len(row) == 5:
            _, cell, name, direction, net = row
            if cell not in cells or name in pins[cell] or direction not in ('IN', 'OUT'):
                raise ValueError('Invalid, duplicate or bidirectional primitive pin')
            match = re.fullmatch(r'([^\[\]]+)(?:\[(\d+)\])?', name)
            if not match:
                raise ValueError('Unsupported primitive pin name: ' + name)
            pins[cell][name] = (match[1], int(match[2] or 0), direction,
                                signal(net or '@unconnected:' + cell + '/' + name))
        elif row[0] == 'port' and len(row) == 4:
            _, name, direction, net = row
            if name in ports or direction not in ('IN', 'OUT'):
                raise ValueError('Invalid, duplicate or bidirectional top port')
            ports[name] = {'direction': {'IN': 'input', 'OUT': 'output'}[direction],
                           'bits': [signal(net or '@unconnected-port:' + name)]}
        else:
            raise ValueError('Incomplete or unsupported connectivity record: ' + str(row[:2]))
    actual = (len(cells), sum(len(value) for value in pins.values()), len(ports))
    if actual != expected or not cells or not ports:
        raise ValueError(f'Connectivity inventory mismatch: expected {expected}, read {actual}')
    constants = {}
    drivers = {}
    primary_inputs = {bit for port in ports.values() if port['direction'] == 'input'
                      for bit in port['bits']}

    def require_pins(name, cell, inputs, outputs):
        for direction, expected_ports in (('input', inputs), ('output', outputs)):
            for port, width in expected_ports.items():
                if (cell['port_directions'].get(port) != direction or
                        len(cell['connections'].get(port, [])) != width):
                    raise ValueError('Primitive pin inventory is incomplete: ' + name + '/' + port)

    for name, cell in cells.items():
        if len(pins[name]) != cell.pop('expected_pin_count'):
            raise ValueError('Primitive pin inventory mismatch: ' + name)
        grouped = {}
        for port, index, direction, bit in pins[name].values():
            group = grouped.setdefault(port, {})
            if index in group:
                raise ValueError('Duplicate primitive bus bit: ' + name + '/' + port)
            group[index] = bit
            normalized = 'input' if direction == 'IN' else 'output'
            old_direction = cell['port_directions'].setdefault(port, normalized)
            if old_direction != normalized:
                raise ValueError('Primitive bus directions differ')
            if direction == 'OUT':
                if bit in drivers:
                    raise ValueError('Multiple drivers on a primitive output net')
                drivers[bit] = name
                if cell['type'] in ('VCC', 'GND'):
                    constants[bit] = '1' if cell['type'] == 'VCC' else '0'
        for port, values in grouped.items():
            if set(values) != set(range(max(values) + 1)):
                raise ValueError('Primitive bus has omitted bits: ' + name + '/' + port)
            cell['connections'][port] = [values[index] for index in range(len(values))]
        kind, parameters = cell['type'], cell['parameters']
        if re.fullmatch(r'LUT(?:[1-6]|6_2)', kind):
            width = 6 if kind == 'LUT6_2' else int(kind[-1])
            if not isinstance(parameters.get('INIT'), int) or not 0 <= parameters['INIT'] < (1 << (1 << width)):
                raise ValueError('Missing or invalid LUT truth table: ' + name)
            outputs = {'O5': 1, 'O6': 1} if kind == 'LUT6_2' else {'O': 1}
            require_pins(name, cell, {f'I{i}': 1 for i in range(width)}, outputs)
        if re.fullmatch(r'FD(?:RE|SE|CE|PE)(?:_1)?', kind):
            control = {'FDRE': 'R', 'FDSE': 'S', 'FDCE': 'CLR', 'FDPE': 'PRE'}[kind.removesuffix('_1')]
            require_pins(name, cell, {'C': 1, 'D': 1, 'CE': 1, control: 1}, {'Q': 1})
        if kind == 'CARRY4':
            require_pins(name, cell, {'CI': 1, 'CYINIT': 1, 'DI': 4, 'S': 4}, {'CO': 4, 'O': 4})
        if kind in ('MUXF7', 'MUXF8'):
            require_pins(name, cell, {'I0': 1, 'I1': 1, 'S': 1}, {'O': 1})
        if kind in ('VCC', 'GND'):
            require_pins(name, cell, {}, {'P' if kind == 'VCC' else 'G': 1})
        if kind == 'DSP48E1':
            for parameter in DSP_REGISTERS:
                if parameters.get(parameter) not in (0, 1, 2):
                    raise ValueError('Missing or invalid DSP register parameter: ' + name + '/' + parameter)
            if any(parameter not in parameters for parameter in DSP_MODES):
                raise ValueError('DSP mode inventory is incomplete: ' + name)
    # 每个已连接输入必须能回到导出的驱动单元或顶层输入，防止遗漏上游逻辑。
    for name, cell in cells.items():
        for pin, (_, _, direction, bit) in pins[name].items():
            if (direction == 'IN' and bit not in drivers and bit not in primary_inputs and
                    bit != net_ids.get('@unconnected:' + name + '/' + pin)):
                raise ValueError('Connected primitive input has no exported driver: ' + name + '/' + pin)
        for port, bits in cell['connections'].items():
            cell['connections'][port] = [constants.get(bit, bit) for bit in bits]
    for name, port in ports.items():
        for bit in port['bits']:
            if (port['direction'] == 'output' and bit not in drivers and bit not in primary_inputs and
                    bit != net_ids.get('@unconnected-port:' + name)):
                raise ValueError('Connected SoC output has no exported driver: ' + name)
    module = {'cells': cells, 'ports': ports,
              'netnames': {name: {'bits': [constants.get(bit, bit)]} for name, bit in net_ids.items()}}
    paths = connected_paths(module, limit=20, group_limit=20)
    paths['export_inventory'] = {'cells': actual[0], 'pins': actual[1], 'ports': actual[2],
                                 'counts_match': True, 'source_sha256': digest(path)}
    paths['design_scope'] = {'module': 'soc_top', 'kind': scope_kind, 'name': scope_name,
                             'outside_primitive_cells': int(outside_count),
                             'boundary_ports_complete': True}
    return paths


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def snapshot(inputs, output):
    entries = list(csv.reader(Path(inputs).read_text().splitlines(), delimiter='\t'))
    if any(len(row) != 2 for row in entries):
        raise ValueError('Each input record must contain a key and a value')
    metadata, paths = {}, set()
    for key, value in entries:
        if key == 'source':
            paths.add(Path(value).resolve())
        elif key == 'include_dir':
            directory = Path(value).resolve()
            if not directory.is_dir():
                raise ValueError(f'Include directory does not exist: {directory}')
            paths.update(path.resolve() for path in directory.rglob('*')
                         if path.suffix in ('.vh', '.svh') and path.is_file())
        else:
            if key in metadata:
                raise ValueError(f'Duplicate input property: {key}')
            metadata[key] = value
    if not paths:
        raise ValueError('No synthesis input files were recorded')
    root = Path(metadata['repository']).resolve()
    source = []
    for path in sorted(paths):
        if not path.is_file():
            raise ValueError(f'Synthesis input does not exist: {path}')
        try:
            relative_path = str(path.relative_to(root))
        except ValueError:
            relative_path = None
        source.append(dict(path=str(path), relative_path=relative_path,
                           sha256=digest(path), bytes=path.stat().st_size))
    git = {}
    for key, arguments in (('commit', ['rev-parse', 'HEAD']),
                           ('tree', ['rev-parse', 'HEAD^{tree}']),
                           ('worktree_status', ['status', '--porcelain=v1'])):
        result = subprocess.run(['git', '-C', str(root), *arguments],
                                text=True, capture_output=True, check=False)
        git[key] = result.stdout.strip() if result.returncode == 0 else None
    value = dict(schema_version=1, flow='Vivado native RTL', metadata=metadata,
                 git=git, inputs=source, input_records_sha256=digest(inputs))
    save(output, value)
    return value


def verify(manifest):
    value = json.loads(Path(manifest).read_text())
    changed = [row['path'] for row in value['inputs']
               if not Path(row['path']).is_file() or digest(row['path']) != row['sha256']]
    if changed:
        raise ValueError('Synthesis inputs changed during the run:\n' + '\n'.join(changed))
    return value


def number(text):
    value = float(text.replace(',', '').strip())
    if not math.isfinite(value):
        raise ValueError('Report values must be finite')
    return value


def utilization(text):
    rows = {}
    for line in text.splitlines():
        fields = [field.strip() for field in line.split('|')]
        if len(fields) < 4 or fields[0] or fields[-1]:
            continue
        label = re.sub(r'\s*\*\s*$', '', fields[1])
        if re.fullmatch(r'[0-9][0-9,.]*', fields[2]):
            rows[label] = number(fields[2])
    aliases = {
        'slice_luts': ('Slice LUTs', 'CLB LUTs'),
        'logic_luts': ('LUT as Logic',),
        'memory_luts': ('LUT as Memory',),
        'slice_registers': ('Slice Registers', 'CLB Registers'),
        'bram_tiles': ('Block RAM Tile',),
        'ramb36': ('RAMB36/FIFO', 'RAMB36'),
        'ramb18': ('RAMB18',),
        'dsps': ('DSPs', 'DSP48E1'),
    }
    result = {}
    for key, names in aliases.items():
        values = [rows[name] for name in names if name in rows]
        if not values:
            raise ValueError(f'Missing Vivado utilization field: {key}')
        result[key] = values[0] if key == 'bram_tiles' else int(values[0])
        if key != 'bram_tiles' and result[key] != values[0]:
            raise ValueError(f'Expected an integer utilization value: {key}')
    if result['logic_luts'] + result['memory_luts'] != result['slice_luts']:
        raise ValueError('Logic and memory LUT counts do not add up to total Slice LUTs')
    if result['ramb36'] + result['ramb18'] / 2 != result['bram_tiles']:
        raise ValueError('BRAM counts do not add up to Block RAM Tile utilization')
    return result


def endpoint_statistics(path):
    with Path(path).open() as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    result = {}
    for delay_type in ('max', 'min'):
        paths = []
        for row in rows:
            if row['delay_type'] != delay_type:
                continue
            slack = number(row['slack_ns'])
            levels = int(row['logic_levels'])
            if levels < 0:
                raise ValueError('Logic level count must be nonnegative')
            paths.append(dict(slack_ns=slack, logic_levels=levels, clock=row['clock'],
                              startpoint=row['startpoint'], endpoint=row['endpoint']))
        result[delay_type] = dict(sampled_paths=len(paths),
                                  maximum_observed_logic_levels=max(
                                      (row['logic_levels'] for row in paths), default=None),
                                  worst_sampled_path=min(paths, key=lambda row: row['slack_ns'],
                                                         default=None))
    return result


def timing_summary(text):
    """读取完整设计的建立、保持及脉宽统计。"""
    fields = ('wns_ns', 'tns_ns', 'failing_endpoints', 'endpoints')
    result = {kind: dict.fromkeys(fields) for kind in ('max', 'min', 'pulse')}
    section = re.search(r'^\s*\|\s*Design Timing Summary\s*$', text, re.MULTILINE)
    if not section:
        return result
    lines = text[section.end():].splitlines()
    for index, line in enumerate(lines):
        if 'WNS(ns)' not in line or 'TNS Failing Endpoints' not in line:
            continue
        if index + 2 >= len(lines):
            return result
        separators = list(re.finditer(r'-+', lines[index + 1]))
        headers = [('max', ('WNS(ns)', 'TNS(ns)', 'TNS Failing Endpoints', 'TNS Total Endpoints')),
                   ('min', ('WHS(ns)', 'THS(ns)', 'THS Failing Endpoints', 'THS Total Endpoints')),
                   ('pulse', ('WPWS(ns)', 'TPWS(ns)', 'TPWS Failing Endpoints', 'TPWS Total Endpoints'))]
        # 固定宽度保留缺失数据的空列。
        bounds = [(separators[i - 1].end() if i else 0, match.end())
                  for i, match in enumerate(separators)]
        for kind, names in headers:
            for field, name in zip(fields, names):
                position = line.find(name)
                column = next((i for i, (start, end) in enumerate(bounds)
                               if start <= position < end), None) if position >= 0 else None
                if column is None:
                    continue
                raw = lines[index + 2][bounds[column][0]:bounds[column][1]].strip()
                try:
                    value = number(raw)
                    if field in ('failing_endpoints', 'endpoints'):
                        if value < 0 or not value.is_integer():
                            continue
                        value = int(value)
                    result[kind][field] = value
                except ValueError:
                    pass
        break
    return result


def timing_checks(timing):
    result = {}
    for kind, row in timing.items():
        values = [row.get(key) for key in ('wns_ns', 'tns_ns', 'failing_endpoints', 'endpoints')]
        if any(value is None for value in values) or values[3] <= 0:
            result[kind] = None
        elif values[2] > values[3]:
            result[kind] = None
        else:
            result[kind] = values[0] >= 0 and values[1] == 0 and values[2] == 0
    return result


def positive_decimal(value):
    """保留工具文字的十进制精度，拒绝空值与无穷值。"""
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('Missing or malformed clock parameter') from error
    if not result.is_finite() or result <= 0:
        raise ValueError('Clock parameters must be finite and positive')
    return result


def period_matches_display(value, exact):
    """根据该字段实际显示的小数位核对舍入，不改变频率目标。"""
    shown = positive_decimal(value)
    quantum = Fraction(Decimal(1).scaleb(shown.as_tuple().exponent))
    return abs(Fraction(shown) - exact) <= quantum / 2


def core_clock(path):
    value = {'period_ns': None, 'within_150mhz_period': None}
    if not Path(path).is_file():
        return value
    with Path(path).open() as stream:
        rows = list(csv.DictReader(stream, delimiter='\t'))
    if len(rows) != 1 or not rows[0].get('clock') or not rows[0].get('object'):
        return value
    row = rows[0]
    try:
        shown = positive_decimal(row['period_ns'])
        value.update(clock=row['clock'], object=row['object'], period_ns=float(shown),
                     configuration=row)
        kind = row.get('clock_kind', '')
        if not kind:
            # 只有显示值时，用整个舍入区间判断；跨过目标的区间保持未确认。
            half_unit = Fraction(Decimal(1).scaleb(shown.as_tuple().exponent)) / 2
            lower, upper = Fraction(shown) - half_unit, Fraction(shown) + half_unit
            value.update(frequency_basis='reported_period_interval',
                         within_150mhz_period=True if upper <= TARGET_PERIOD_EXACT else
                         False if lower > TARGET_PERIOD_EXACT else None)
            return value
        if row.get('same_source') != '1' or not row.get('source_pin') or not row.get('soc_clock_pin'):
            raise ValueError('The SoC clock source was not uniquely verified')
        if kind == 'primary':
            frequency = Fraction(positive_decimal(row['definition_frequency_mhz']))
            literal = Fraction(positive_decimal(row['definition_period_ns']))
            exact = 1000 / frequency
            # Tcl 浮点除法的写出误差与报告的皮秒精度分别处理。
            if abs(literal - exact) > 2 * Fraction.from_float(math.ulp(float(exact))):
                raise ValueError('Applied primary clock period and frequency disagree')
            basis = 'applied_create_clock'
        elif kind == 'mmcm':
            if (row.get('source_ref') not in ('MMCME2_ADV', 'MMCME2_BASE') or
                    not row.get('source_cell') or not row.get('master_clock') or
                    row.get('master_is_generated') != '0'):
                raise ValueError('MMCM input clock configuration is incomplete')
            parameters = {key: Fraction(positive_decimal(row[key])) for key in (
                'mmcm_input_period_ns', 'mmcm_feedback_multiplier', 'mmcm_input_divider',
                'mmcm_output_divider', 'multiply_by', 'divide_by')}
            hardware_ratio = parameters['mmcm_feedback_multiplier'] / (
                parameters['mmcm_input_divider'] * parameters['mmcm_output_divider'])
            timing_ratio = parameters['multiply_by'] / parameters['divide_by']
            if hardware_ratio != timing_ratio:
                raise ValueError('Generated clock ratio and MMCM configuration disagree')
            if not period_matches_display(row['master_period_ns'], parameters['mmcm_input_period_ns']):
                raise ValueError('MMCM input period and master clock disagree')
            exact = parameters['mmcm_input_period_ns'] / hardware_ratio
            basis = 'mmcm_configuration'
        else:
            raise ValueError('Unsupported core clock configuration')
        if not period_matches_display(row['period_ns'], exact):
            raise ValueError('Reported core period and precise configuration disagree')
        value.update(frequency_basis=basis, configured_period_ns=float(exact),
                     configured_frequency_mhz=float(1000 / exact),
                     within_150mhz_period=exact <= TARGET_PERIOD_EXACT)
    except (KeyError, ValueError, OverflowError) as error:
        value['unavailable_reason'] = str(error)
    return value


def summarize(manifest, directory, stage, prefix='soc_top', max_slice_luts=DEFAULT_MAX_SLICE_LUTS,
              max_register_path_cells=10):
    if max_slice_luts < 1:
        raise ValueError('Maximum Slice LUT count must be positive')
    if max_register_path_cells < 0:
        raise ValueError('Maximum register path cell count must be nonnegative')
    inputs = verify(manifest)
    directory = Path(directory)
    resources = utilization((directory / f'{prefix}_utilization.rpt').read_text())
    sampled = endpoint_statistics(directory / f'{prefix}_endpoints.tsv')
    summary_path = directory / f'{prefix}_timing_summary.rpt'
    timing = timing_summary(summary_path.read_text() if summary_path.is_file() else '')
    for kind in sampled:
        timing[kind]['sample'] = sampled[kind]
    timing_pass = timing_checks(timing)
    clock = core_clock(directory / f'{prefix}_core_clock.tsv')
    graph_path = directory / f'{prefix}_connectivity.tsv'
    graph = {'graph_complete': False, 'longest_register_path_cells': None}
    try:
        graph = connectivity(graph_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        graph['unavailable_reason'] = str(error)
    graph_result_path = directory / f'{prefix}_connected_paths.json'
    save(graph_result_path, graph)
    path_limit_met = (graph['longest_register_path_cells'] <= max_register_path_cells
                      if graph['graph_complete'] else None)
    implementation = None
    if stage == 'routed':
        check_path = directory / 'implementation_checks.tsv'
        if check_path.is_file():
            with check_path.open() as stream:
                implementation = {row['check']: row['value'] for row in csv.DictReader(stream, delimiter='\t')}
    physical_pass = (all_confirmed([clock['within_150mhz_period'], *timing_pass.values(),
                     implementation.get('passed') == '1' if implementation else None])
                     if stage == 'routed' else None)
    resource_pass = resources['slice_luts'] <= max_slice_luts
    status = dict(slice_luts_within_limit=resource_pass,
                  all_connected_paths_within_limit=path_limit_met,
                  connectivity_complete=graph['graph_complete'],
                  core_clock_within_150mhz_period=clock['within_150mhz_period'],
                  setup_confirmed=timing_pass['max'] if stage == 'routed' else None,
                  hold_confirmed=timing_pass['min'] if stage == 'routed' else None,
                  pulse_width_confirmed=timing_pass['pulse'] if stage == 'routed' else None,
                  timing_150mhz_confirmed=physical_pass,
                  all_targets_met=all_confirmed([resource_pass, path_limit_met, physical_pass]))
    result = dict(schema_version=3, measurement_tool='Vivado', stage=stage,
                  source_manifest_sha256=digest(manifest), inputs_unchanged=True,
                  configuration=inputs['metadata'], git=inputs['git'], resources=resources,
                  timing=timing, core_clock=clock, implementation_checks=implementation,
                  requirements=dict(slice_luts_maximum=max_slice_luts, clock_period_ns_maximum=TARGET_PERIOD_NS,
                                    combinational_logic_levels_maximum=max_register_path_cells),
                  status=status, connectivity=graph,
                  timing_scope='建立、保持和脉宽使用原生完整设计统计；空值表示尚未确认。最差路径明细为有界样本。',
                  resource_scope='当前完整设计的总 Slice LUT，包含逻辑、分布式存储和移位寄存器。',
                  logic_level_scope='完整 soc_top 层次及其全部边界引脚导出后计算完整连通图，保留板级固定常量驱动；与开源网表分析共用寄存器、DSP内部寄存器和同步控制边界。样本路径不决定最大级数。',
                  connected_paths_sha256=digest(graph_result_path),
                  reports_sha256={path.name: digest(path) for path in sorted(directory.iterdir())
                                  if path.is_file() and path.suffix in ('.rpt', '.tsv')})
    save(directory / 'measurement.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    collect = commands.add_parser('snapshot')
    collect.add_argument('--inputs', required=True, type=Path)
    collect.add_argument('--out', required=True, type=Path)
    check = commands.add_parser('verify')
    check.add_argument('--manifest', required=True, type=Path)
    report = commands.add_parser('summarize')
    report.add_argument('--manifest', required=True, type=Path)
    report.add_argument('--directory', required=True, type=Path)
    report.add_argument('--stage', required=True, choices=('synthesized', 'routed'))
    report.add_argument('--prefix', choices=('soc_top', 'fpga_top'), default='soc_top')
    report.add_argument('--max-slice-luts', type=int, default=DEFAULT_MAX_SLICE_LUTS,
                        help='Maximum total Slice LUT count, including LUT RAM and SRL')
    report.add_argument('--max-register-path-cells', type=int, default=10)
    timing_command = commands.add_parser('check-timing')
    timing_command.add_argument('--report', type=Path, required=True)
    timing_command.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'snapshot':
        value = snapshot(args.inputs, args.out)
        print(json.dumps(dict(inputs=len(value['inputs']), manifest=str(args.out))))
    elif args.command == 'verify':
        value = verify(args.manifest)
        print(json.dumps(dict(inputs=len(value['inputs']), unchanged=True)))
    elif args.command == 'check-timing':
        timing = timing_summary(args.report.read_text())
        status = timing_checks(timing)
        result = dict(timing=timing, status=status, passed=all_confirmed(status.values()) is True,
                      report_sha256=digest(args.report))
        save(args.out, result)
        print(json.dumps(result))
        if not result['passed']:
            raise SystemExit(1)
    else:
        value = summarize(args.manifest, args.directory, args.stage, args.prefix,
                          args.max_slice_luts, args.max_register_path_cells)
        print(json.dumps(dict(resources=value['resources'], status=value['status'])))
        if args.stage == 'routed' and value['status']['all_targets_met'] is not True:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
