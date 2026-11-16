#!/usr/bin/env python3
"""Execute complete TFLM models and compare every observed tensor on Gemmini."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import struct

from build_firmware import load_network_builder
from build_sim import run_sim

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODELS = ('mnist_cnn', 'mobilenet_v1_vww', 'resnet8_cifar10', 'ds_cnn_kws')
ABI = load_network_builder()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def checked_payload(root, spec):
    raw = (root / spec['path']).read_bytes()
    if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
        raise ValueError('Prepared payload differs: ' + str(root / spec['path']))
    return raw


def compare(actual, expected):
    mismatches = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
    return dict(passed=actual == expected, actual_bytes=len(actual), expected_bytes=len(expected),
        mismatches=len(mismatches) + abs(len(actual) - len(expected)),
        first_mismatch=mismatches[0] if mismatches else None,
        actual_sha256=hashlib.sha256(actual).hexdigest(),
        expected_sha256=hashlib.sha256(expected).hexdigest())


def verify_sources(firmware):
    sources = {str(ROOT / path): value for path, value in firmware['source_sha256'].items()}
    sources.update(firmware.get('external_dependency_sha256', {}))
    changed = [path for path, value in sources.items() if not Path(path).is_file() or digest(path) != value]
    if changed:
        raise ValueError('Firmware inputs changed: ' + ', '.join(changed))


def create_case(directory, prepared, model, sample, firmware_directory, firmware, mode):
    directory.mkdir(parents=True, exist_ok=True)
    constant = ABI.abi_constant
    config = dict(magic=constant('MAGIC'), version=constant('VERSION'), mode=mode,
        sample_index=sample['sample_index'], model_address=constant('MODEL_ADDRESS'),
        model_bytes=model['model']['bytes'], input_address=constant('INPUT_ADDRESS'),
        input_bytes=sample['input']['bytes'], golden_address=constant('GOLDEN_ADDRESS'),
        output_bytes=sample['output']['bytes'], label=sample['label'],
        expected_operators=len(model['graph']['nodes']),
        expected_conv_nodes=sum(node['op'] == 'CONV_2D' for node in model['graph']['nodes']),
        expected_fc_nodes=sum(node['op'] == 'FULLY_CONNECTED' for node in model['graph']['nodes']),
        flags=0, reserved=0)
    fields = ABI.abi_fields('CONFIG')
    regions = [(config['model_address'], checked_payload(prepared, model['model'])),
               (config['input_address'], checked_payload(prepared, sample['input'])),
               (config['golden_address'], checked_payload(prepared, sample['output'])),
               (constant('CONFIG_ADDRESS'), struct.pack('<' + 'I' * len(fields),
                   *[config[field] for field in fields]))]
    with (directory / 'data.mem').open('w') as stream:
        for address, raw in sorted(regions):
            stream.write(f'@{address // 4:08x}\n')
            stream.writelines(f'{word:08x}\n' for (word,) in
                struct.iter_unpack('<I', raw + bytes((-len(raw)) % 4)))
    case = dict(model_id=model['name'], sample_index=sample['sample_index'], mode=mode,
        convolution_policy=firmware['convolution_policy'],
        kind='trace' if firmware['trace_enabled'] else 'perf', config=config, sample=sample,
        model=model['model'], graph=model['graph'], prepared_dir=str(prepared),
        firmware_dir=str(firmware_directory), firmware_elf_sha256=firmware['elf_sha256'],
        prepared_sha256=digest(prepared / 'manifest.json'),
        data_mem_sha256=digest(directory / 'data.mem'),
        timing='CPU rdcycle around one complete MicroInterpreter::Invoke after initialization')
    write_json(directory / 'case.json', case)
    return case


def execute(binary, directory, case, firmware, latency, cycle_limit, seconds_limit):
    cfg = case['config']
    fields = firmware['result_fields']
    trace = case['kind'] == 'trace'
    simulation = run_sim(binary, directory, Path(case['firmware_dir']) / 'cpu.mem',
        data_mem=directory / 'data.mem', result_addr=firmware['symbols']['full_network_result'],
        result_words=len(fields), output_addr_word=fields.index('output_address'),
        output_bytes_word=fields.index('output_bytes'),
        trace_addr=firmware['symbols']['full_network_trace'] if trace else 0,
        timeout_cycles=cycle_limit, timeout_seconds=seconds_limit, ram_fixed_lat=latency,
        extra_plusargs=[f'+MODEL_ADDR={cfg["model_address"]:x}', f'+MODEL_BYTES={cfg["model_bytes"]}',
            f'+MODEL_FILE={directory / "model_after.bin"}', f'+INPUT_ADDR={cfg["input_address"]:x}',
            f'+INPUT_BYTES={cfg["input_bytes"]}', f'+INPUT_FILE={directory / "input_after.bin"}'])
    report = {name:case[name] for name in ('model_id','sample_index','mode','kind','model',
                                        'firmware_elf_sha256','convolution_policy')}
    report.update(passed=False, ram_fixed_lat=latency, case_dir=str(directory),
        input_sha256=case['sample']['input']['sha256'], simulator=simulation,
        checks=dict(simulator_completed=simulation['passed'],
            cpu_profile_matches_build=simulation['cpu_profile_matches_build'],
            dma_bursts_within_limit=simulation['dma_bursts_within_limit']), trace=[])
    checks = report['checks']
    prepared = Path(case['prepared_dir'])
    try:
        result = dict(zip(fields, simulation['result_words']))
        report['result'] = result
        checks['firmware_success'] = (len(result) == len(fields) and result['magic'] == cfg['magic'] and
            result['version'] == cfg['version'] and result['status'] == result['error'] == 0 and
            result['complete'] == 1 and result['mode'] == cfg['mode'] and
            result['sample_index'] == cfg['sample_index'])
        checks['entire_model'] = result['operator_count'] == cfg['expected_operators']
        checks['trace_mode'] = result['trace_enabled'] == int(trace)
        checks['cycle_csr'] = result['invoke_cycles'] > 0 and result['invoke_cycles'] == (
            (result['end_cycle'] - result['start_cycle']) & 0xffffffff)
        output = (directory / 'output.bin').read_bytes()
        report['output_comparison'] = compare(output, checked_payload(prepared, case['sample']['output']))
        checks['complete_output'] = report['output_comparison']['passed']
        checks['firmware_output'] = result['mismatches'] == 0 and result['compared_outputs'] == len(output)
        report['output_values'] = [value if value < 128 else value - 256 for value in output]
        checks['prediction'] = result['predicted_label'] == case['sample']['prediction']
        checks['arena'] = 0 < result['arena_used_bytes'] <= firmware['arena_bytes'] and (
            firmware['arena_address'] <= result['output_address'] and
            result['output_address'] + len(output) <= firmware['arena_end'])
        checks['model_unchanged'] = digest(directory / 'model_after.bin') == case['model']['sha256']
        checks['input_unchanged'] = digest(directory / 'input_after.bin') == case['sample']['input']['sha256']
        network = [row for row in simulation['counters'] if row['scope'] == 'network']
        boot = [row for row in simulation['counters'] if row['scope'] == 'boot']
        checks['counter_windows'] = len(network) == len(boot) == 1
        report['network'] = network[0]
        checks['axi_responses'] = boot[0]['axi_errors'] == boot[0]['npu_errors'] == 0
        checks['hardware_activity'] = (network[0]['commands'] > 0) if case['mode'] else network[0]['commands'] == 0
        if trace:
            rows = (directory / 'trace.txt').read_text().splitlines()
            expected = case['sample']['nodes']
            checks['trace_complete'] = len(rows) == len(expected) == result['trace_records']
            for ordinal, (line, wanted) in enumerate(zip(rows, expected)):
                descriptor = dict(zip(firmware['trace_fields'], [int(word, 16) for word in line.split()]))
                comparison = compare((directory / f'tensors/tensor_{ordinal}.bin').read_bytes(),
                    checked_payload(prepared, wanted))
                valid = (descriptor['magic'] == cfg['magic'] and descriptor['version'] == cfg['version'] and
                    descriptor['ordinal'] == ordinal and descriptor['operator_index'] == wanted['index'] and
                    descriptor['tensor_index'] == wanted['tensor_index'] and
                    descriptor['output_index'] == wanted['output_index'] and descriptor['bytes'] == wanted['bytes'] and
                    comparison['passed'])
                report['trace'].append(dict(descriptor=descriptor, op=wanted['op'], comparison=comparison, passed=valid))
                checks[f'tensor_{ordinal}'] = valid
            layers = [row for row in simulation['counters'] if row['scope'] == 'layer']
            graph = case['graph']['nodes']
            checks['layer_order'] = [row['index'] for row in layers] == [node['index'] for node in graph]
            report['layers'] = [dict(row, op=node['op'], input_shapes=node['input_shapes'],
                output_shapes=node['output_shapes']) for row, node in zip(layers, graph)]
            for node, row in zip(graph, layers):
                accelerated = case['mode'] and node['op'] in ('CONV_2D','DEPTHWISE_CONV_2D','FULLY_CONNECTED')
                checks[f'layer_{node["index"]}_activity'] = row['commands'] > 0 if accelerated else row['commands'] == 0
                if node['op'] == 'DEPTHWISE_CONV_2D' and accelerated:
                    checks[f'layer_{node["index"]}_depthwise'] = row['dwconv_cycles'] > 0
            for layer in report['layers']:
                index = layer['index']
                node = graph[index]
                if layer['op'] == 'DEPTHWISE_CONV_2D':
                    layer['execution_path'] = 'optimized_dwconv'
                elif layer['op'] == 'FULLY_CONNECTED':
                    layer['execution_path'] = 'ws_gemm'
                elif layer['op'] == 'CONV_2D':
                    options = node['options']
                    pointwise = options['kernel_h'] == options['kernel_w'] == options['stride_h'] == options['stride_w'] == 1
                    layer['execution_path'] = 'ws_gemm' if pointwise else (
                        'independent_im2col' if layer['im2col_requests'] else 'native_loopconv')
                    if case['convolution_policy'] == 'im2col' and not pointwise and options['kernel_h'] == options['kernel_w']:
                        checks[f'layer_{index}_im2col'] = layer['im2col_requests'] > 0 and layer['im2col_responses'] > 0
                else:
                    layer['execution_path'] = 'software'
        else:
            checks['ordinary_firmware'] = result['trace_records'] == 0
        verify_sources(firmware)
        checks['firmware_sources_current'] = True
        report['passed'] = all(checks.values())
    except (OSError, ValueError, KeyError, IndexError) as error:
        report['failure'] = str(error)
    write_json(directory / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--simulator', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--trace-firmware', type=Path)
    parser.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    parser.add_argument('--samples', type=int, nargs='+', default=[0,1])
    parser.add_argument('--kind', choices=['perf','trace','both'], default='both')
    parser.add_argument('--mode', type=int, choices=[0,9,63], default=63)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--ram-fixed-lat', type=int, default=0)
    parser.add_argument('--cycle-limit', type=int, default=1000000000)
    parser.add_argument('--seconds-limit', type=int, default=7200)
    args = parser.parse_args()
    tasks = []
    for kind in (('perf','trace') if args.kind == 'both' else (args.kind,)):
        fw_directory = args.firmware if kind == 'perf' else args.trace_firmware
        if fw_directory is None:
            parser.error('--trace-firmware is required for tensor verification')
        firmware = json.loads((fw_directory / 'firmware.json').read_text())
        verify_sources(firmware)
        for name in args.models:
            prepared = args.prepared / name
            model = json.loads((prepared / 'manifest.json').read_text())
            for sample in model['samples']:
                if sample['sample_index'] not in args.samples:
                    continue
                directory = args.out / name / f'{sample["sample_index"]:04d}' / kind
                case = create_case(directory, prepared, model, sample, fw_directory, firmware, args.mode)
                tasks.append((directory, case, firmware))
    reports = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(execute, args.simulator, directory, case, firmware,
            args.ram_fixed_lat, args.cycle_limit, args.seconds_limit):directory
            for directory, case, firmware in tasks}
        for future in as_completed(futures):
            value = future.result()
            reports.append(value)
            print(json.dumps({key:value.get(key) for key in ('model_id','sample_index','kind','passed','failure')} |
                {'invoke_cycles':value.get('result',{}).get('invoke_cycles')}), flush=True)
    reports.sort(key=lambda value:(value['model_id'], value['sample_index'], value['kind']))
    summary = dict(passed=bool(reports) and all(value['passed'] for value in reports),
        timing='Actual complete TFLM Invoke on performance-profile PicoRV32; preparation is measured separately',
        run_count=len(reports), runs=reports)
    write_json(args.out / 'summary.json', summary)
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
