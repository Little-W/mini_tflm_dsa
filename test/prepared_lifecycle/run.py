#!/usr/bin/env python3
"""Verify persistent layer configurations across repeated complete TFLM Invoke calls."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BENCH = ROOT / 'test/model_benchmark'
sys.path.insert(0, str(BENCH))
from build_firmware import abi_fields, build_firmware, digest
from build_sim import run_sim
from model_data import MODELS, validate_model

spec = importlib.util.spec_from_file_location('lifecycle_network', BENCH / 'run.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

WRAPPED = ('dsa_prepare_conv_s8', 'dsa_prepare_matmul_s8', 'dsa_prepare_spatial_s8',
           'dsa_prepare_add_s8', 'dsa_prepared_execute', 'dsa_prepared_add_s8_execute')
ABI = (HERE / 'lifecycle_abi.h').read_text()
CONSTANTS = {key: int(value, 0) for key, value in re.findall(
    r'^#define LIFECYCLE_(\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)u?\s*$', ABI, re.M)}


def fields(name):
    match = re.search(r'#define LIFECYCLE_' + name + r'_FIELDS\(X\)(.*?)(?=\n\n)', ABI, re.S)
    if not match:
        raise ValueError('Missing lifecycle field list: ' + name)
    return re.findall(r'X\((\w+)\)', match.group(1))


def decode_words(raw):
    return [value for (value,) in struct.iter_unpack('<I', raw)]


def decode_record(words, names):
    if len(words) != len(names):
        raise ValueError('Incomplete lifecycle record')
    return dict(zip(names, words))


def decode_registry(raw):
    words = decode_words(raw)
    header = fields('REGISTRY')
    entry = fields('CONFIGURATION')
    if len(words) != len(header) + CONSTANTS['MAX_CONFIGURATIONS'] * len(entry):
        raise ValueError('Invalid registry byte count')
    result = decode_record(words[:len(header)], header)
    count = result['configurations']
    if count > CONSTANTS['MAX_CONFIGURATIONS']:
        raise ValueError('Configuration count exceeds registry capacity')
    result['entries'] = [decode_record(words[len(header)+i*len(entry):
                                            len(header)+(i+1)*len(entry)], entry)
                         for i in range(count)]
    return result


def create_case(out, prepared_dir, model, sample, policy, firmware_dir, firmware, repeats):
    case = bench.create_case(out, prepared_dir, model, sample, bench.HARDWARE_MODE,
                             firmware_dir, firmware, ps_force_raw=policy == 'raw')
    cfg = case['config']
    cfg['reserved'] = repeats
    bench.overlay(out / 'data.mem', [
        (cfg['model_address'], bench.checked_payload(prepared_dir, model['model'])),
        (cfg['input_address'], bench.checked_payload(prepared_dir, sample['input'])),
        (cfg['golden_address'], bench.checked_payload(prepared_dir, sample['output'])),
        (bench.constants()['CONFIG_ADDRESS'], struct.pack('<' + 'I'*len(abi_fields('CONFIG')),
          *[cfg[name] for name in abi_fields('CONFIG')]))])
    case.update(policy=policy, repeats=repeats,
                data_mem_sha256=digest(out/'data.mem'),
                cold_start='One simulator reset and one AllocateTensors followed by repeated Invoke')
    bench.write_json(out/'case.json', case)
    return case


def execute_case(binary, out, case, firmware, *, latency, cycle_limit, seconds_limit):
    cfg = case['config']
    header_fields, invoke_fields = fields('RESULT'), fields('INVOCATION')
    word_count = len(header_fields) + CONSTANTS['MAX_REPEATS'] * len(invoke_fields)
    simulator = run_sim(binary, out, Path(case['firmware_dir'])/'cpu.mem',
        data_mem=out/'data.mem', result_addr=firmware['symbols']['lifecycle_result'],
        result_words=word_count, output_addr_word=header_fields.index('output_address'),
        output_bytes_word=header_fields.index('output_bytes'),
        trace_addr=firmware['symbols']['full_network_trace'], ram_fixed_lat=latency,
        timeout_cycles=cycle_limit, timeout_seconds=seconds_limit,
        extra_plusargs=[f'+MODEL_ADDR={cfg["model_address"]:x}',
            f'+MODEL_BYTES={cfg["model_bytes"]}', f'+MODEL_FILE={out/"model_after.bin"}',
            f'+INPUT_ADDR={cfg["input_address"]:x}', f'+INPUT_BYTES={cfg["input_bytes"]}',
            f'+INPUT_FILE={out/"input_after.bin"}'])
    report = {name: case[name] for name in ('model_id', 'sample_index', 'policy', 'repeats',
                                            'firmware_elf_sha256', 'model')}
    report.update(passed=False, case_dir=str(out), ram_fixed_lat=latency,
                  simulator_sha256=digest(binary), simulator=simulator, checks={}, invocations=[])
    checks = report['checks']
    checks['simulator_completed'] = simulator['passed']
    try:
        words = simulator['result_words']
        if len(words) != word_count:
            raise ValueError('Incomplete lifecycle result')
        result = decode_record(words[:len(header_fields)], header_fields)
        report['result'] = result
        checks['firmware_success'] = (result['magic'] == CONSTANTS['MAGIC'] and
            result['version'] == CONSTANTS['VERSION'] and result['complete'] == 1 and
            result['error'] == 0 and result['repeats'] == case['repeats'])
        checks['allocated_once'] = result['allocate_calls'] == 1
        checks['planning_interval'] = 0 < result['planning_after_allocate'] <= result['init_cycles']
        checks['arena_usage'] = 0 < result['arena_after_allocate'] <= firmware['arena_bytes']

        snapshots = {}
        snapshot_records = []
        snapshot_locations = {
            CONSTANTS['ARENA_SNAPSHOT']: (firmware['arena_address'], firmware['arena_bytes']),
            CONSTANTS['REGISTRY_SNAPSHOT']: (firmware['symbols']['lifecycle_registry'],
                                              firmware['symbol_sizes']['lifecycle_registry']),
            CONSTANTS['MODEL_SNAPSHOT']: (cfg['model_address'], cfg['model_bytes']),
            CONSTANTS['OUTPUT_SNAPSHOT']: (result['output_address'], result['output_bytes'])}
        for ordinal, line in enumerate((out/'trace.txt').read_text().splitlines()):
            descriptor = decode_record([int(word, 16) for word in line.split()],
                                       firmware['trace_fields'])
            raw = (out/'tensors'/f'tensor_{ordinal}.bin').read_bytes()
            if (descriptor['magic'] != CONSTANTS['MAGIC'] or
                descriptor['version'] != CONSTANTS['VERSION'] or
                descriptor['ordinal'] != ordinal or descriptor['bytes'] != len(raw)):
                raise ValueError('Invalid snapshot descriptor')
            key = descriptor['operator_index'], descriptor['output_index']
            if snapshot_locations.get(descriptor['output_index']) != (descriptor['address'], descriptor['bytes']):
                raise ValueError('Snapshot address differs from the declared memory object')
            if key in snapshots:
                raise ValueError('Duplicate state snapshot')
            snapshots[key] = raw
            snapshot_records.append({'descriptor': descriptor,
                                     'sha256': hashlib.sha256(raw).hexdigest()})
        report['snapshots'] = snapshot_records
        checks['snapshot_count'] = len(snapshots) == 3 + 4*case['repeats']
        initial = 0xffffffff
        baseline_arena = snapshots[initial, CONSTANTS['ARENA_SNAPSHOT']]
        baseline_model = snapshots[initial, CONSTANTS['MODEL_SNAPSHOT']]
        registry = decode_registry(snapshots[initial, CONSTANTS['REGISTRY_SNAPSHOT']])
        report['registry_after_allocate'] = registry
        prepared_dir = Path(case['prepared_dir'])
        original_model = bench.checked_payload(prepared_dir, case['model'])
        golden = bench.checked_payload(prepared_dir, case['sample']['output'])
        checks['initial_arena_snapshot'] = len(baseline_arena) == firmware['arena_bytes']
        checks['initial_model_snapshot'] = baseline_model == original_model
        wrapped_jobs = case['expected_jobs']['jobs'] - case['expected_jobs']['softmax_jobs']
        checks['configuration_count'] = (registry['configurations'] == result['configurations'] ==
                                         wrapped_jobs and wrapped_jobs > 0)
        checks['preparation_complete'] = (registry['magic'] == CONSTANTS['MAGIC'] and
            registry['version'] == CONSTANTS['VERSION'] and registry['error'] == 0 and
            registry['in_invoke'] == 0 and registry['execute_calls'] == 0 and
            registry['prepare_failures'] == 0 and
            registry['prepare_calls'] == result['prepare_after_allocate'] == wrapped_jobs and
            all(entry['prepare_calls'] == 1 for entry in registry['entries']))
        checks['distinct_configuration_addresses'] = (
            len({entry['address'] for entry in registry['entries']}) == wrapped_jobs)
        arena_begin, arena_end = firmware['arena_address'], firmware['arena_end']
        checks['configurations_in_arena'] = all(
            arena_begin <= entry['address'] < entry['address'] + entry['bytes'] <= arena_end
            for entry in registry['entries'])

        def memory_span(arena, model, begin, end):
            if begin >= end:
                raise ValueError('Empty or reversed immutable memory span')
            if arena_begin <= begin < end <= arena_end:
                return arena[begin-arena_begin:end-arena_begin]
            model_begin = cfg['model_address']
            if model_begin <= begin < end <= model_begin + len(model):
                return model[begin-model_begin:end-model_begin]
            raise ValueError('Immutable memory span is outside arena and model')

        immutable = []
        for index, entry in enumerate(registry['entries']):
            immutable.append((index, 'configuration', entry['address'], entry['address']+entry['bytes']))
            if not 0 <= entry['readonly_count'] <= 4:
                raise ValueError('Invalid readonly span count')
            for number in range(entry['readonly_count']):
                immutable.append((index, f'readonly_{number}', entry[f'readonly_begin_{number}'],
                                  entry[f'readonly_end_{number}']))
        report['immutable_regions'] = [dict(configuration_index=index, kind=kind,
            begin=begin, end=end, bytes=end-begin,
            sha256=hashlib.sha256(memory_span(baseline_arena, baseline_model, begin, end)).hexdigest())
            for index, kind, begin, end in immutable]

        layers = [row for row in simulator['counters'] if row['scope'] == 'layer']
        totals = [row for row in simulator['counters'] if row['scope'] == 'boot']
        networks = [row for row in simulator['counters'] if row['scope'] == 'network']
        checks['invocation_counter_count'] = len(layers) == case['repeats']
        if len(totals) != 1 or len(networks) != 1 or len(layers) != case['repeats']:
            raise ValueError('Missing complete invocation intervals')
        total = totals[0]
        checks['hardware_totals'] = all(total[key] == count*case['repeats']
                                        for key, count in case['expected_jobs'].items())
        checks['hardware_completed'] = (total['jobs'] == total['done_jobs'] and
            total['axi_errors'] == total['npu_errors'] == total['capacity_retries'] == 0)
        report['network'] = networks[0]
        for iteration, counters in enumerate(layers):
            base = len(header_fields) + iteration*len(invoke_fields)
            invocation = decode_record(words[base:base+len(invoke_fields)], invoke_fields)
            arena = snapshots[iteration, CONSTANTS['ARENA_SNAPSHOT']]
            model = snapshots[iteration, CONSTANTS['MODEL_SNAPSHOT']]
            after = decode_registry(snapshots[iteration, CONSTANTS['REGISTRY_SNAPSHOT']])
            output = snapshots[iteration, CONSTANTS['OUTPUT_SNAPSHOT']]
            per_check = {}
            per_check['status'] = invocation['status'] == 0
            per_check['cycles'] = (0 < invocation['invoke_cycles'] < 2**32 and
                invocation['invoke_cycles'] ==
                ((invocation['end_cycle'] - invocation['start_cycle']) & 0xffffffff) and
                counters['cycles'] >= invocation['invoke_cycles'] >= counters['npu_busy_cycles'])
            per_check['planning_unchanged'] = (invocation['planning_before'] ==
                invocation['planning_after'] == result['planning_after_allocate'])
            per_check['arena_usage_unchanged'] = (invocation['arena_before'] ==
                invocation['arena_after'] == result['arena_after_allocate'])
            per_check['prepare_unchanged'] = (invocation['prepare_before'] ==
                invocation['prepare_after'] == registry['prepare_calls'] == after['prepare_calls'] and
                after['prepare_failures'] == 0)
            per_check['configuration_pointers_unchanged'] = (
                after['configurations'] == registry['configurations'] and
                all({k:v for k,v in a.items() if k != 'execute_calls'} ==
                    {k:v for k,v in b.items() if k != 'execute_calls'}
                    for a,b in zip(registry['entries'], after['entries'])))
            per_check['each_configuration_executed'] = (
                all(entry['execute_calls'] == iteration+1 for entry in after['entries']) and
                after['execute_calls'] == invocation['execute_after'] == wrapped_jobs*(iteration+1) and
                invocation['execute_before'] == wrapped_jobs*iteration)
            per_check['registry_status'] = after['error'] == after['in_invoke'] == 0
            per_check['configuration_and_constants_unchanged'] = all(
                memory_span(arena, model, begin, end) ==
                memory_span(baseline_arena, baseline_model, begin, end)
                for _, _, begin, end in immutable)
            per_check['model_unchanged'] = model == original_model
            per_check['output_equal'] = output == golden
            per_check['firmware_output_check'] = (invocation['mismatches'] == 0 and
                invocation['compared_outputs'] == len(golden) and
                invocation['output_fnv1a'] == bench.fnv1a(golden) and
                invocation['predicted_label'] == case['sample']['prediction'])
            per_check['hardware_commands'] = (counters['index'] == iteration and
                all(counters[key] == count for key, count in case['expected_jobs'].items()) and
                counters['jobs'] == counters['done_jobs'] and
                counters['axi_errors'] == counters['npu_errors'] == counters['capacity_retries'] == 0)
            item = {'index': iteration, 'result': invocation, 'checks': per_check,
                    'passed': all(per_check.values()), 'hardware': counters,
                    'output_sha256': hashlib.sha256(output).hexdigest()}
            report['invocations'].append(item)
            checks[f'invocation_{iteration}'] = item['passed']
        checks['final_output'] = (out/'output.bin').read_bytes() == golden
        checks['final_model'] = (out/'model_after.bin').read_bytes() == original_model
        checks['external_input_unchanged'] = digest(out/'input_after.bin') == case['sample']['input']['sha256']
        bench.verify_sources(firmware)
        checks['firmware_sources_current'] = True
        report['passed'] = all(checks.values())
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as error:
        report['failure'] = str(error)
    report['run_log_sha256'] = digest(out/'run.log')
    bench.write_json(out/'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gcc', default='riscv-none-elf-gcc')
    parser.add_argument('--object-cache', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--run-jobs', type=int, default=2)
    parser.add_argument('--models', choices=MODELS, nargs='+', default=list(MODELS))
    parser.add_argument('--samples', type=int, nargs='+', default=[0, 1])
    parser.add_argument('--policies', choices=['raw', 'adaptive'], nargs='+', default=['raw', 'adaptive'])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--latency', type=int, default=0)
    parser.add_argument('--cycle-limit', type=int, default=4000000000)
    parser.add_argument('--seconds-limit', type=int, default=7200)
    args = parser.parse_args()
    if not 1 <= args.repeats <= CONSTANTS['MAX_REPEATS'] or not 1 <= args.jobs <= 4 or args.run_jobs < 1:
        parser.error('repeats must be 1..8, jobs 1..4, and run-jobs positive')
    sim = args.sim.resolve()
    binary = sim/'obj/Vtb_model_benchmark'
    sim_manifest = json.loads((sim/'build.json').read_text())
    bench.verify_sources(sim_manifest)
    if (sim_manifest['returncode'] or not sim_manifest['sources_unchanged_during_build'] or
        digest(binary) != sim_manifest['binary_sha256']):
        raise RuntimeError('A successful current-source simulator build is required')
    if sim_manifest['configuration']['shared_total_bytes'] != 14336:
        raise RuntimeError('This suite uses the 14 KiB shared-memory configuration')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    firmware_dir = out/'firmware'
    firmware = build_firmware(firmware_dir, args.gcc, hardware=True, trace=False,
        jobs=args.jobs, object_cache=args.object_cache, ps_pool_bytes=12288,
        application_source=HERE/'firmware.cc',
        link_options=[f'-Wl,--wrap={symbol}' for symbol in WRAPPED])
    settings = {'repeats': args.repeats, 'models': args.models, 'samples': args.samples,
                'policies': args.policies, 'ram_fixed_lat': args.latency,
                'hardware_profile': sim_manifest['configuration'],
                'simulator_sha256': digest(binary), 'firmware_elf_sha256': firmware['elf_sha256'],
                'runner_sha256': digest(__file__),
                'timing': 'Instrumented CPU Invoke intervals; no memory snapshot or output comparison inside each interval',
                'wrapped_symbols': list(WRAPPED)}
    work = []
    for model_id in args.models:
        prepared_dir = args.prepared.resolve()/model_id
        validate_model(prepared_dir)
        model = json.loads((prepared_dir/'manifest.json').read_text())
        samples = [sample for sample in model['samples'] if sample['sample_index'] in args.samples]
        if len(samples) != len(set(args.samples)):
            raise ValueError('Selected samples are absent: ' + model_id)
        for sample in samples:
            for policy in args.policies:
                directory = out/'cases'/model_id/f'sample_{sample["sample_index"]:04d}'/policy
                case = create_case(directory, prepared_dir, model, sample, policy,
                                   firmware_dir, firmware, args.repeats)
                work.append((directory, case))
    reports = []

    def save():
        ordered = sorted(reports, key=lambda row: (row['model_id'], row['sample_index'], row['policy']))
        result = {'passed': len(reports) == len(work) and all(row['passed'] for row in reports),
                  'complete': len(reports) == len(work), 'expected_runs': len(work),
                  'completed_runs': len(reports),
                  'completed_invocations': sum(len(row['invocations']) for row in reports),
                  'settings': settings, 'runs': ordered}
        bench.write_json(out/'summary.json', result)
        return result

    save()
    with ThreadPoolExecutor(max_workers=args.run_jobs) as pool:
        futures = {pool.submit(execute_case, binary, directory, case, firmware,
                    latency=args.latency, cycle_limit=args.cycle_limit,
                    seconds_limit=args.seconds_limit): case for directory, case in work}
        for future in as_completed(futures):
            report = future.result()
            reports.append(report)
            save()
            print(json.dumps({'model': report['model_id'], 'sample': report['sample_index'],
                              'policy': report['policy'], 'passed': report['passed'],
                              'invoke_cycles': [row['result']['invoke_cycles']
                                                for row in report['invocations']],
                              'failure': report.get('failure')}), flush=True)
    result = save()
    print(json.dumps({'passed': result['passed'], 'runs': len(reports),
                      'invocations': result['completed_invocations'], 'out': str(out)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
