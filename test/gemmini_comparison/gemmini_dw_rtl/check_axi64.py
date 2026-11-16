#!/usr/bin/env python3
"""Verify native 64-bit DMA, 256-beat transactions, page splits and byte strobes."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import subprocess
import memory_service


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--build-manifest', type=Path, required=True)
    parser.add_argument('--params-header', type=Path, required=True)
    parser.add_argument('--gemmini-tests', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    memory_service.add_arguments(parser)
    args = parser.parse_args()
    build = json.loads(args.build_manifest.read_text())
    selected_memory = memory_service.configuration(build['memory_service'], args)
    read_interval = selected_memory['read_beat_interval_cycles']
    if build['configuration']['dma_bus_bits'] != 64 or build['configuration']['dma_max_bytes'] != 2048:
        raise ValueError('The protocol test requires native AXI64 and 256 full-width beats')
    if digest(args.sim) != build['simulator_sha256'] or digest(args.params_header) != build['params_header_sha256']:
        raise ValueError('Hardware files differ from their build manifest')
    output = args.output.resolve()
    assets = output / 'trace_source'
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'sim/dma_trace.c', assets / 'trace.c')
    shutil.copyfile(ROOT.parent / 'gemmini_command_trace/xcustom.h', assets / 'xcustom.h')
    spec = importlib.util.spec_from_file_location('shared_trace', ROOT.parent / 'gemmini_command_trace/generate.py')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    generator.HERE = assets
    compiler = generator.build(output / 'generator', args.gemmini_tests.resolve(),
                               args.params_header.resolve(), 'hardware-generated', 'gcc')
    if compiler['config']['max_bytes'] != 2048:
        raise ValueError('The command generator uses a different DMA transaction size')
    results = []
    memory_base = 0x10000
    cases = [('aligned_2048', 0x800, 0x2800, 2048, 1),
             ('page_crossing_2048', 0xfc0, 0x2fe0, 2048, 1),
             ('partial_strobes_13', 0x403, 0x2403, 13, 1),
             ('outstanding_rows_4', 0x800, 0x2800, 512, 4)]
    for name, input_offset, output_offset, columns, rows in cases:
        length = columns * rows
        directory = output / name
        directory.mkdir(parents=True, exist_ok=True)
        memory = bytearray(random.Random(0x64).randbytes(0x5000))
        expected = bytes(memory[input_offset:input_offset + length])
        memory[output_offset:output_offset + length] = bytes([0xa5]) * length
        (directory / 'memory.bin').write_bytes(memory)
        (directory / 'expected.bin').write_bytes(expected)
        subprocess.run([compiler['binary'], str(memory_base + input_offset),
                        str(memory_base + output_offset), str(columns),
                        str(directory / 'commands.txt'), str(rows)], check=True)
        result_path = directory / 'result.json'
        command = [str(args.sim.resolve()), str(directory / 'memory.bin'), str(memory_base),
                   str(directory / 'commands.txt'), str(memory_base + output_offset), str(length),
                   str(directory / 'expected.bin'), '2', str(result_path),
                   *memory_service.simulator_arguments(selected_memory)]
        with (directory / 'run.log').open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = json.loads(result_path.read_text())
        memory_service.validate_result(result, selected_memory)
        if not result['passed'] or digest(result_path.with_suffix('.output.bin')) != digest(directory / 'expected.bin'):
            raise ValueError(name + ': output differs from the source bytes')
        if result['axi_data_bits'] != 64 or result['axi_strobe_bits'] != 8:
            raise ValueError(name + ': observed interface differs from AXI64')
        if result['first_r_cycle'] - result['first_ar_cycle'] != selected_memory['first_read_latency_cycles']:
            raise ValueError(name + ': initial read response differs from the selected request latency')
        if name == 'aligned_2048' and (result['max_read_burst_beats'] != 256 or result['max_write_burst_beats'] != 256):
            raise ValueError('The aligned case must exercise 256 beats in both directions')
        if name == 'aligned_2048' and (
                result['read_requests'] != 1 or result['write_requests'] != 1 or
                result['last_r_cycle'] - result['first_r_cycle'] != 255 * read_interval):
            raise ValueError('The aligned case must sustain the selected read beat interval')
        if name == 'page_crossing_2048' and (result['read_requests'] < 2 or result['write_requests'] < 2):
            raise ValueError('The page-crossing case must use separate transactions')
        if name == 'outstanding_rows_4':
            expected_outstanding = selected_memory.get('read_outstanding_limit', 4)
            if result['max_read_outstanding_observed'] != expected_outstanding or result['read_requests'] != 4:
                raise ValueError('The four-row case must exercise the selected outstanding read limit')
            if selected_memory['response_mode'] == 'request_deadline' and expected_outstanding == 4 and (
                    result['matured_request_switches'] != 3 or
                    result['matured_request_switch_gap_min'] != selected_memory['inter_burst_read_gap_cycles'] or
                    result['matured_request_switch_gap_max'] != selected_memory['inter_burst_read_gap_cycles']):
                raise ValueError('Mature requests must use the configured burst-switch interval')
        result.update(name=name, command=command, expected_sha256=digest(directory / 'expected.bin'),
                      observed_sha256=digest(result_path.with_suffix('.output.bin')),
                      commands_sha256=digest(directory / 'commands.txt'))
        result_path.write_text(json.dumps(result, indent=2) + '\n')
        results.append(result)
        print(name, 'PASS', 'cycles=' + str(result['cycles']),
              'read_beats=' + str(result['read_beats']), 'write_beats=' + str(result['write_beats']), flush=True)
    (output / 'results.json').write_text(json.dumps({
        'passed': True, 'build_manifest_sha256': digest(args.build_manifest),
        'memory_service': selected_memory,
        'params_header_sha256': digest(args.params_header),
        'generator': compiler, 'cases': results}, indent=2) + '\n')


if __name__ == '__main__':
    main()
