#!/usr/bin/env python3
"""Run complete trained networks on the production PicoRV32/NPU SoC."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import struct

from build_firmware import abi_fields, abi_constant
from build_sim import CPU_PROFILES, build_sim, run_sim

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARDWARE_MODE = abi_constant('MODE_HARDWARE')
MODE_NAMES = {0: 'software', HARDWARE_MODE: 'hardware'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def verify_sources(manifest):
    changed = [name for name, value in manifest['source_sha256'].items()
               if not (ROOT/name).is_file() or digest(ROOT/name) != value]
    changed.extend(name for name, value in manifest.get('external_dependency_sha256', {}).items()
                   if not Path(name).is_file() or digest(name) != value)
    if changed:
        raise RuntimeError('Source files differ from the recorded build: ' + ', '.join(changed))


def checked_payload(root, record):
    path = root/record['path']
    raw = path.read_bytes()
    if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
        raise RuntimeError('Prepared model or tensor differs: ' + str(path))
    return raw


def constants():
    return {name: int(value, 0) for name, value in re.findall(
        r'^#define FULL_NETWORK_(\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)u?\s*$',
        (HERE/'full_network_abi.h').read_text(), re.M)}


def overlay(path, regions):
    ordered = sorted(regions)
    previous_end = 0
    with path.open('w') as stream:
        for address, raw in ordered:
            if address & 3 or address < previous_end:
                raise ValueError('Memory regions require separate word-aligned allocations')
            data = raw + bytes((-len(raw)) % 4)
            stream.write(f'@{address//4:08x}\n')
            stream.writelines(f'{word:08x}\n' for (word,) in struct.iter_unpack('<I', data))
            previous_end = address + len(data)


def direct_pointwise(node):
    if node['op'] != 'CONV_2D':
        return False
    options = node['options']
    source, weights = node['input_shapes'][:2]
    output = node['output_shapes'][0]
    return (options['kernel_h'] == options['kernel_w'] == 1 and
            options['stride_h'] == options['stride_w'] == 1 and
            options.get('dilation_h_factor', 1) == options.get('dilation_w_factor', 1) == 1 and
            source[1:3] == output[1:3] and weights[-1] == source[-1])


def expected_jobs(prepared, mode):
    result = {name: 0 for name in ('conv_jobs', 'dw_jobs', 'pool_jobs', 'vector_jobs',
                                  'add_jobs', 'gemm_jobs', 'softmax_jobs')}
    if mode:
        for node in prepared['graph']['nodes']:
            op = node['op']
            if op == 'CONV_2D':
                result['gemm_jobs' if direct_pointwise(node) else 'conv_jobs'] += 1
            elif op == 'DEPTHWISE_CONV_2D':
                if node['options']['depth_multiplier'] != 1:
                    raise ValueError('This suite requires channel-multiplier-one depthwise layers')
                result['dw_jobs'] += 1
            elif op in ('AVERAGE_POOL_2D', 'MAX_POOL_2D'):
                if node['options']['kernel_h'] * node['options']['kernel_w'] > 256:
                    raise ValueError('Pool window exceeds the hardware limit')
                result['pool_jobs'] += 1
            elif op == 'ADD':
                if node['input_shapes'][0] != node['input_shapes'][1]:
                    raise ValueError('This suite requires equal-shape Add inputs')
                result['add_jobs'] += 1
            elif op == 'FULLY_CONNECTED':
                result['gemm_jobs'] += 1
            elif op == 'SOFTMAX':
                depth = node['input_shapes'][0][-1]
                if depth > 16:
                    raise ValueError('Softmax depth exceeds this hardware configuration')
                result['softmax_jobs'] += 1
    result['jobs'] = sum(result.values())
    return result


def create_case(out, prepared_dir, prepared, sample, mode, firmware_dir, firmware,
                *, ps_force_raw=False):
    out.mkdir(parents=True, exist_ok=True)
    c = constants()
    config = dict(magic=c['MAGIC'], version=c['VERSION'], mode=mode,
                  sample_index=sample['sample_index'], model_address=c['MODEL_ADDRESS'],
                  model_bytes=prepared['model']['bytes'], input_address=c['INPUT_ADDRESS'],
                  input_bytes=sample['input']['bytes'], golden_address=c['GOLDEN_ADDRESS'],
                  output_bytes=sample['output']['bytes'], label=sample['label'],
                  expected_operators=len(prepared['graph']['nodes']),
                  expected_conv_nodes=sum(n['op'] == 'CONV_2D' for n in prepared['graph']['nodes']),
                  expected_fc_nodes=sum(n['op'] == 'FULLY_CONNECTED' for n in prepared['graph']['nodes']),
                  flags=c['FLAG_PS_RAW'] if ps_force_raw else 0, reserved=0)
    fields = abi_fields('CONFIG')
    words = [config[name] for name in fields]
    overlay(out/'data.mem', [
        (c['MODEL_ADDRESS'], checked_payload(prepared_dir, prepared['model'])),
        (c['INPUT_ADDRESS'], checked_payload(prepared_dir, sample['input'])),
        (c['GOLDEN_ADDRESS'], checked_payload(prepared_dir, sample['output'])),
        (c['CONFIG_ADDRESS'], struct.pack('<'+'I'*len(words), *words))])
    case = {'model_id': prepared['name'], 'sample_index': sample['sample_index'],
            'mode': mode, 'mode_name': MODE_NAMES[mode],
            'kind': 'trace' if firmware['trace_enabled'] else 'perf',
            'prepared_dir': str(prepared_dir), 'sample': sample, 'config': config,
            'model': prepared['model'], 'expected_jobs': expected_jobs(prepared, mode),
            'prepared_sha256': digest(prepared_dir/'manifest.json'),
            'data_mem_sha256': digest(out/'data.mem'), 'firmware_dir': str(firmware_dir),
            'firmware_elf_sha256': firmware['elf_sha256'],
            'cold_start': 'New simulator process and reset for one complete Invoke'}
    write_json(out/'case.json', case)
    return case


def compare(actual, expected):
    positions = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
    first = positions[0] if positions else min(len(actual), len(expected))
    return {'passed': actual == expected, 'actual_bytes': len(actual), 'expected_bytes': len(expected),
            'mismatches': len(positions)+abs(len(actual)-len(expected)),
            'first_mismatch': None if actual == expected else first,
            'actual_sha256': hashlib.sha256(actual).hexdigest(),
            'expected_sha256': hashlib.sha256(expected).hexdigest()}


def fnv1a(raw):
    result = 2166136261
    for value in raw:
        result = ((result ^ value) * 16777619) & 0xffffffff
    return result


def window_checks(window_jobs, network, window_lanes):
    """按实际返回宽度检查窗口事务数、有效元素数和响应周期。"""
    if type(window_lanes) is not int or window_lanes <= 0:
        raise ValueError('窗口返回并行数必须来自实际仿真构建中的正整数参数')
    fields = ('requests', 'completions', 'peak_outstanding', 'response_beats',
              'requested_elements', 'response_elements', 'return_span_cycles',
              'consecutive_responses', 'request_response_overlap')
    checks = {}
    checks['window_counter_domains'] = all(
        type(row[key]) is int and row[key] >= 0 for row in window_jobs for key in fields)
    checks['window_completion_records'] = len(window_jobs) == network['dw_jobs'] + network['pool_jobs']
    checks['window_request_completion'] = all(row['requests'] == row['completions'] for row in window_jobs)
    checks['window_response_elements'] = all(row['requested_elements'] == row['response_elements'] for row in window_jobs)
    checks['window_outstanding_capacity'] = all(
        (1 <= row['peak_outstanding'] <= min(4, row['requests'])) if row['requests'] else row['peak_outstanding'] == 0
        for row in window_jobs)
    checks['window_request_count'] = sum(row['requests'] for row in window_jobs) == network['dw_windows']
    checks['depthwise_window_activity'] = all(row['requests'] > 0 and row['response_elements'] > 0
                                              for row in window_jobs if row['operation'] == 2)
    checks['window_response_counters'] = all(
        row['response_beats'] <= row['response_elements'] <= window_lanes * row['response_beats'] and
        row['response_beats'] <= row['return_span_cycles'] and
        0 <= row['consecutive_responses'] <= max(0, row['response_beats'] - 1) and
        0 <= row['request_response_overlap'] <= row['requests']
        for row in window_jobs)
    return checks


def execute_case(binary, out, case, firmware, *, latency, cycle_limit, seconds_limit, extra_plusargs=()):
    cfg = case['config']; fw = Path(case['firmware_dir']); prepared = Path(case['prepared_dir'])
    trace = case['kind'] == 'trace'
    fields = firmware['result_fields']
    simulator = run_sim(binary, out, fw/'cpu.mem', data_mem=out/'data.mem',
        result_addr=firmware['symbols']['full_network_result'], result_words=len(fields),
        output_addr_word=fields.index('output_address'), output_bytes_word=fields.index('output_bytes'),
        trace_addr=firmware['symbols']['full_network_trace'] if trace else 0,
        timeout_cycles=cycle_limit, timeout_seconds=seconds_limit, ram_fixed_lat=latency,
        extra_plusargs=[f'+MODEL_ADDR={cfg["model_address"]:x}', f'+MODEL_BYTES={cfg["model_bytes"]}',
                        f'+MODEL_FILE={out/"model_after.bin"}', f'+INPUT_ADDR={cfg["input_address"]:x}',
                        f'+INPUT_BYTES={cfg["input_bytes"]}', f'+INPUT_FILE={out/"input_after.bin"}', *extra_plusargs])
    build = json.loads((Path(binary).resolve().parents[1] / 'build.json').read_text())
    if build['binary_sha256'] != simulator['simulator_sha256']:
        raise RuntimeError('窗口参数记录与实际执行的仿真二进制不一致')
    return validate_case(out, case, firmware, simulator, latency=latency,
                         window_lanes=build['profile']['window_lanes'])


def validate_case(out, case, firmware, simulator, *, latency, window_lanes):
    """重读完整推理文件，并使用固定构建中的窗口参数检查运行结果。"""
    cfg = case['config']; prepared = Path(case['prepared_dir'])
    trace = case['kind'] == 'trace'
    fields = firmware['result_fields']
    value = {key: case[key] for key in ('model_id', 'sample_index', 'mode', 'mode_name', 'kind',
                                        'model', 'firmware_elf_sha256')}
    value['input_sha256'] = case['sample']['input']['sha256']
    value['ram_fixed_lat'] = latency
    value['window_response_lanes'] = window_lanes
    value['validation_source_sha256'] = {str(Path(__file__).relative_to(ROOT)): digest(__file__)}
    value.update(passed=False, case_dir=str(out), simulator=simulator, checks={}, trace=[])
    checks = value['checks']
    checks['simulator_completed'] = simulator['passed']
    checks['cpu_profile_matches_build'] = simulator['cpu_profile_matches_build']
    checks['dma_bursts_within_limit'] = simulator['dma_bursts_within_limit']
    try:
        if len(simulator['result_words']) != len(fields):
            raise ValueError('Incomplete firmware result')
        result = dict(zip(fields, simulator['result_words']))
        value['result'] = result
        checks['firmware_success'] = (result['magic'] == cfg['magic'] and result['version'] == cfg['version'] and
            result['complete'] == 1 and result['status'] == 0 and result['error'] == 0 and
            result['mode'] == case['mode'] and result['sample_index'] == case['sample_index'])
        checks['entire_model'] = result['operator_count'] == cfg['expected_operators']
        checks['trace_mode'] = result['trace_enabled'] == int(trace)
        checks['cycle_csr'] = (result['invoke_cycles'] > 0 and
            result['invoke_cycles'] == ((result['end_cycle'] - result['start_cycle']) & 0xffffffff))
        checks['planning_interval'] = result['planning_cycles'] <= result['init_cycles']
        output = (out/'output.bin').read_bytes()
        golden = checked_payload(prepared, case['sample']['output'])
        value['output_comparison'] = compare(output, golden)
        checks['complete_output'] = value['output_comparison']['passed']
        checks['firmware_output_check'] = (result['mismatches'] == 0 and
            result['output_bytes'] == result['compared_outputs'] == len(output) and
            result['output_fnv1a'] == fnv1a(output))
        signed = [x if x < 128 else x-256 for x in output]
        value['output_values'] = signed
        prediction = max(range(len(signed)), key=signed.__getitem__)
        checks['prediction'] = (prediction == result['predicted_label'] == case['sample']['prediction'] and
                                result['expected_label'] == case['sample']['label'])
        checks['input_length'] = result['input_bytes'] == cfg['input_bytes']
        checks['arena'] = (0 < result['arena_used_bytes'] <= firmware['arena_bytes'] and
            firmware['arena_address'] <= result['output_address'] and
            result['output_address'] + len(output) <= firmware['arena_end'])
        checks['model_unchanged'] = digest(out/'model_after.bin') == case['model']['sha256']
        checks['input_unchanged'] = digest(out/'input_after.bin') == case['sample']['input']['sha256']
        network = [row for row in simulator['counters'] if row['scope'] == 'network']
        total = [row for row in simulator['counters'] if row['scope'] == 'boot']
        if len(network) != 1 or len(total) != 1:
            raise ValueError('Expected one complete network and total observation')
        network, total = network[0], total[0]
        value['network'] = network
        checks['counter_window'] = (network['cycles'] >= result['invoke_cycles'] >= network['npu_busy_cycles'] and
                                    network['cycles'] < 2**32)
        checks['hardware_commands'] = all(network[key] == count for key, count in case['expected_jobs'].items())
        checks['completion_count'] = network['done_jobs'] == network['jobs'] == total['jobs'] == total['done_jobs']
        checks['operation_completion_counts'] = all(
            network[name+'_jobs'] == network[name+'_done'] == total[name+'_jobs'] == total[name+'_done']
            for name in ('conv', 'dw', 'pool', 'vector', 'add', 'gemm', 'softmax'))
        checks['axi_responses'] = total['axi_errors'] == 0
        checks['npu_errors'] = total['npu_errors'] == 0
        checks['window_clients'] = (
            (network['ia_windows'] + network['kernel_windows'] > 0) == (case['expected_jobs']['conv_jobs'] > 0) and
            (network['dw_windows'] == 0 or case['expected_jobs']['dw_jobs'] + case['expected_jobs']['pool_jobs'] > 0))
        window_jobs = simulator['window_jobs']
        checks.update(window_checks(window_jobs, network, window_lanes))
        if case['mode'] == 0:
            checks['cpu_only'] = all(total[key] == 0 for key in
                ('jobs', 'done_jobs', 'npu_busy_cycles', 'npu_read_bytes', 'npu_write_bytes',
                 'npu_read_bursts', 'npu_write_bursts', 'ia_windows', 'kernel_windows', 'dw_windows'))
        if trace:
            rows = (out/'trace.txt').read_text().splitlines()
            expected_rows = case['sample']['nodes']
            checks['trace_complete'] = len(rows) == len(expected_rows) == result['trace_records']
            for ordinal, (line, expected) in enumerate(zip(rows, expected_rows)):
                words = [int(v, 16) for v in line.split()]
                if len(words) != len(firmware['trace_fields']):
                    raise ValueError('Invalid tensor result descriptor')
                desc = dict(zip(firmware['trace_fields'], words))
                raw = (out/f'tensors/tensor_{ordinal}.bin').read_bytes()
                comparison = compare(raw, checked_payload(prepared, expected))
                passed = (desc['magic'] == cfg['magic'] and desc['version'] == cfg['version'] and
                    desc['ordinal'] == ordinal and desc['operator_index'] == expected['index'] and
                    desc['tensor_index'] == expected['tensor_index'] and desc['output_index'] == expected['output_index'] and
                    desc['bytes'] == expected['bytes'] and comparison['passed'] and
                    firmware['arena_address'] <= desc['address'] and desc['address'] + desc['bytes'] <= firmware['arena_end'])
                checks[f'tensor_{ordinal}'] = passed
                value['trace'].append({'descriptor': desc, 'op': expected['op'], 'comparison': comparison, 'passed': passed})
            layers = [row for row in simulator['counters'] if row['scope'] == 'layer']
            graph = json.loads((prepared/'manifest.json').read_text())['graph']['nodes']
            checks['layer_observation'] = ([row['index'] for row in layers] == [node['index'] for node in graph]
                                            and len(layers) == cfg['expected_operators'])
            for node, layer in zip(graph, layers):
                expected = expected_jobs({'graph': {'nodes': [node]}}, case['mode'])
                checks[f'layer_{node["index"]}_hardware'] = (
                    all(layer[key] == count for key, count in expected.items()) and
                    layer['jobs'] == layer['done_jobs'] and layer['axi_errors'] == layer['npu_errors'] == 0 and
                    all(layer[name+'_jobs'] == layer[name+'_done']
                        for name in ('conv', 'dw', 'pool', 'vector', 'add', 'gemm', 'softmax')))
            checks['layer_command_totals'] = all(
                sum(layer[key] for layer in layers) == network[key] for key in case['expected_jobs'])
            value['layers'] = layers
        else:
            checks['ordinary_firmware'] = result['trace_records'] == 0 and not (out/'trace.txt').exists()
        verify_sources(firmware)
        checks['firmware_sources_current'] = True
        value['passed'] = all(checks.values())
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as error:
        value['failure'] = str(error)
    write_json(out/'result.json', value)
    return value


def summarize(out):
    records = [json.loads(path.read_text()) for path in sorted((out/'cases').glob('*/*/*/result.json'))]
    comparisons = []
    by_key = {(r['model_id'], r['sample_index'], r['mode']): r for r in records
              if r['passed'] and r['kind'] == 'perf'}
    for model, sample in sorted({(k[0], k[1]) for k in by_key}):
        for reference in (0,):
            old, new = by_key.get((model, sample, reference)), by_key.get((model, sample, HARDWARE_MODE))
            if old and new:
                if (old['simulator']['simulator_sha256'] != new['simulator']['simulator_sha256'] or
                    old['ram_fixed_lat'] != new['ram_fixed_lat'] or
                    old['model']['sha256'] != new['model']['sha256'] or
                    old['input_sha256'] != new['input_sha256']):
                    raise RuntimeError('Cycle comparison requires identical hardware, RAM timing, model and input')
                a, b = old['result']['invoke_cycles'], new['result']['invoke_cycles']
                comparisons.append({'model_id': model, 'sample_index': sample, 'reference_mode': reference,
                    'reference_cycles': a, 'accelerated_cycles': b, 'speedup': a/b,
                    'cycle_reduction': 1-b/a, 'software_elf_sha256': old['firmware_elf_sha256'],
                    'hardware_elf_sha256': new['firmware_elf_sha256']})
    aggregate = []
    for model in sorted({r['model_id'] for r in comparisons}):
        for reference in (0,):
            pairs = [p for p in comparisons if p['model_id'] == model and p['reference_mode'] == reference]
            if pairs:
                a = sum(p['reference_cycles'] for p in pairs);b = sum(p['accelerated_cycles'] for p in pairs)
                aggregate.append({'model_id': model, 'reference_mode': reference, 'samples': len(pairs),
                                  'reference_cycles': a, 'accelerated_cycles': b, 'speedup': a/b,
                                  'cycle_reduction': 1-b/a})
    report = {'passed': bool(records) and all(r['passed'] for r in records),
              'performance_runs': sum(r['kind'] == 'perf' for r in records),
              'trace_runs': sum(r['kind'] == 'trace' for r in records),
              'comparisons': comparisons, 'aggregate': aggregate, 'runs': records}
    write_json(out/'summary.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--simulator', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--skip-sim-build', action='store_true')
    parser.add_argument('--samples', type=int, nargs='+')
    parser.add_argument('--modes', type=int, nargs='+', choices=MODE_NAMES, default=None)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--run-jobs', type=int, default=1)
    parser.add_argument('--icache', type=int, choices=[0, 1], default=1)
    parser.add_argument('--cpu-profile', choices=CPU_PROFILES, default='performance')
    parser.add_argument('--first-read-latency',type=int,default=8)
    parser.add_argument('--bus-width', type=int, choices=(32,64), default=64)
    parser.add_argument('--pe-count', type=int, choices=[4, 8], default=8)
    parser.add_argument('--ram-words', type=int, default=524288)
    parser.add_argument('--latency', type=int, default=0)
    parser.add_argument('--cycle-limit', type=int, default=4000000000)
    parser.add_argument('--seconds-limit', type=int, default=7200)
    args = parser.parse_args()
    if args.jobs < 1 or args.run_jobs < 1:
        parser.error('Job counts must be positive')
    out = args.out.resolve();prepared_dir = args.prepared.resolve();fw_dir = args.firmware.resolve()
    prepared = json.loads((prepared_dir/'manifest.json').read_text())
    firmware = json.loads((fw_dir/'firmware.json').read_text())
    if not firmware['passed'] or not set(firmware['supported_modes']).issubset(MODE_NAMES):
        raise RuntimeError('Firmware does not support the required NMSIS modes')
    verify_sources(firmware)
    for name, key in [('cpu.elf', 'elf_sha256'), ('cpu.mem', 'mem_sha256')]:
        if digest(fw_dir/name) != firmware[key]:
            raise RuntimeError('Firmware payload differs: ' + name)
    binary = build_sim(args.simulator, args.verilator, args.jobs, skip=args.skip_sim_build,
                       icache=args.icache, ram_words=args.ram_words, pe_count=args.pe_count,
                       cpu_profile=args.cpu_profile,bus_width=args.bus_width,first_read_latency=args.first_read_latency)
    samples = [s for s in prepared['samples'] if args.samples is None or s['sample_index'] in args.samples]
    if not samples:
        parser.error('No prepared samples selected')
    work = []
    for sample in samples:
        for mode in (args.modes or firmware['supported_modes']):
            if mode not in firmware['supported_modes']:
                raise ValueError('Selected mode is not compiled into this firmware')
            directory = out/'cases'/prepared['name']/f'sample_{sample["sample_index"]:04d}'/f'{"trace" if firmware["trace_enabled"] else "perf"}_{mode}'
            if (directory/'result.json').exists():
                raise RuntimeError('Run already exists: ' + str(directory))
            case = create_case(directory, prepared_dir, prepared, sample, mode, fw_dir, firmware)
            work.append((directory, case))
    def execute(item):
        directory, case = item
        return execute_case(binary, directory, case, firmware, latency=args.latency,
                            cycle_limit=args.cycle_limit, seconds_limit=args.seconds_limit)
    with ThreadPoolExecutor(max_workers=args.run_jobs) as pool:
        for future in as_completed([pool.submit(execute, item) for item in work]):
            result = future.result(); summarize(out)
            print(json.dumps({'model': result['model_id'], 'sample': result['sample_index'],
                'mode': result['mode'], 'kind': result['kind'], 'passed': result['passed'],
                'cycles': result.get('result', {}).get('invoke_cycles'),
                'failed_checks': [k for k, v in result['checks'].items() if not v],
                'failure': result.get('failure')}), flush=True)
    return 0 if summarize(out)['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
