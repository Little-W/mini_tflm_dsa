#!/usr/bin/env python3
"""Verify and compare DMA64, 64 KiB NPU and DWConv Gemmini operator results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shlex


ROOT = Path(__file__).resolve().parents[2]
MEMORY_KEYS = {
    'read_request_queue_depth': ('read_request_queue', 16),
    'first_read_latency_cycles': ('read_first_beat_latency_idle', 3),
    'read_beat_interval_cycles': ('read_beat_interval_cycles', 2),
    'inter_burst_read_gap_cycles': ('read_burst_transition_interval_min', 3),
    'write_outstanding': ('write_active_transactions_max', 1),
    'aw_to_first_w_min_cycles': ('write_first_beat_after_aw_min', 1),
    'last_w_to_b_min_cycles': ('write_response_after_last_w_min', 1),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def artifact(path: Path) -> dict:
    return {'path': str(path.resolve()), 'sha256': digest(path)}


def indexed(rows: list[dict]) -> dict[str, dict]:
    result = {row['name']: row for row in rows}
    require(len(result) == len(rows), 'Duplicate workload names')
    return result


def records(text: str, prefix: str) -> list[dict]:
    return [{key: int(value) for key, value in re.findall(r'(\w+)=(-?\d+)', line)}
            for line in text.splitlines() if line.startswith(prefix)]


def memory_segment(path: Path, address: int, count: int) -> bytes:
    result, assigned = bytearray(count), bytearray(count)
    index = 0
    for token in path.read_text().split():
        if token.startswith('@'):
            index = int(token[1:], 16)
            continue
        start = index * 4
        if start < address + count and start + 4 > address:
            word = int(token, 16).to_bytes(4, 'little')
            for lane in range(4):
                offset = start + lane - address
                if 0 <= offset < count:
                    result[offset], assigned[offset] = word[lane], 1
        index += 1
    require(all(assigned), f'Output bytes missing from {path}')
    return bytes(result)


class Comparison:
    AXI_DATA_BITS = 32
    DMA_MAX_BYTES = 64

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.read_beat_cycles = getattr(args, 'read_beat_cycles', 2)
        self.first_read_latency = getattr(args, 'first_read_latency', 3)
        self.inter_burst_gap = getattr(args, 'inter_burst_gap', 3)
        self.sources: dict[str, dict] = {}
        self.documents: dict[str, dict] = {}
        for key in ('npu_gemm', 'npu_conv', 'gemmini_gemm', 'gemmini_native',
                    'gemmini_im2col', 'gemmini_build'):
            path = getattr(args, key)
            self.sources[key] = artifact(path)
            self.documents[key] = load(path)
        self.original_root = Path(self.documents['npu_gemm']['source_repository']).parent
        self.npu_builds = {}
        for group in ('gemm', 'conv'):
            summary = self.documents['npu_' + group]
            path = getattr(args, 'npu_' + group).parent / 'sim/build.json'
            require(digest(path) == summary['build_manifest_sha256'], 'NPU build manifest changed')
            self.sources['npu_' + group + '_build'] = artifact(path)
            self.npu_builds[group] = load(path)

    def resolve_recorded(self, path: str) -> Path:
        original = Path(path)
        if original.exists():
            return original
        try:
            return self.args.data_root / original.relative_to(self.original_root)
        except ValueError:
            return original

    def verify_conditions(self) -> dict:
        ng, nc = (self.documents['npu_' + name] for name in ('gemm', 'conv'))
        require(ng['passed'] and nc['passed'], 'An NPU result group did not pass')
        np = ng['profile']
        for profile in (np, nc['profile']):
            for key, value in {'array': [16, 16], 'external_operand_bits': 8,
                               'accumulator_bits': 32, 'bus_bits': self.AXI_DATA_BITS,
                               'dma_max_bytes': self.DMA_MAX_BYTES,
                               'ia_cache_blocks': 8, 'ps_frames': 16, 'ps_storage_rows': 720,
                               's16_output_banks_max': 4, 'read_outstanding': 4,
                               'write_outstanding': 4}.items():
                require(profile[key] == value, 'Unexpected NPU parameter: ' + key)
        expected_buffers = {'ia': 4096, 'kernel': 1024, 'partial_sum': 46080,
                            'output_s8': 8192, 'output_s16': 2048}
        require(np['declared_main_buffer_bytes'] == expected_buffers,
                'Unexpected NPU RAM allocation')
        require(np['declared_main_buffer_total_bytes'] == sum(expected_buffers.values()),
                'NPU RAM total differs from its components')
        cache_bytes = nc['profile']['cache_sets'] * nc['profile']['cache_ways'] * nc['profile']['cache_line_bytes']
        require(cache_bytes == np['window_cache_data_bytes'] == 4096, 'Unexpected window-cache capacity')
        require(sum(expected_buffers.values()) + cache_bytes == 65536, 'NPU data RAM must total 64 KiB')
        require(nc['profile']['windowed_input'] and nc['profile']['input_prefetch'],
                'The spatial tests require windowed input and prefetch')
        require(np['memory']['random_wait'] is False and np['memory']['read_write_independent'],
                'Unexpected external-memory service')
        for build in self.npu_builds.values():
            require(build['returncode'] == 0 and build['sources_unchanged_during_build'],
                    'An NPU build was not verified')
            for key in ('dma_max_bytes', 'ia_cache_blocks', 'ps_frames', 'ps_storage_rows', 's16_output_banks_max'):
                require(build[key] == np[key], 'NPU build and result parameters differ: ' + key)
        memory_source = 'test/conv_npu/axi_memory.sv'
        memory_hashes = {build['source_sha256'][memory_source] for build in self.npu_builds.values()}
        require(len(memory_hashes) == 1, 'NPU GEMM and Conv use different memory models')
        for name, value in self.npu_builds['gemm']['source_sha256'].items():
            if name.startswith('rtl/'):
                require(self.npu_builds['conv']['source_sha256'].get(name) == value,
                        'NPU GEMM and Conv RTL differs: ' + name)
        build = self.documents['gemmini_build']
        expected_gemmini = {'array_rows': 16, 'array_columns': 16, 'input_bits': 8,
                            'weight_bits': 8, 'accumulator_bits': 32,
                            'scratchpad_bytes': 32768, 'accumulator_bytes': 32768,
                            'dma_bus_bits': self.AXI_DATA_BITS, 'dma_max_bytes': self.DMA_MAX_BYTES,
                            'dma_outstanding_per_direction': 4, 'spad_read_delay': 1,
                            'has_im2col': True, 'has_dwconv_dataflow': True}
        for key, value in expected_gemmini.items():
            require(build['configuration'][key] == value, 'Unexpected Gemmini parameter: ' + key)
        require(build['configuration']['scratchpad_bytes'] + build['configuration']['accumulator_bytes'] == 65536,
                'Gemmini data RAM must total 64 KiB')
        simulator = self.resolve_recorded(build['simulator'])
        require(digest(simulator) == build['simulator_sha256'], 'Gemmini simulator changed')
        memory_service = dict(build['memory_service'], read_beat_interval_cycles=self.read_beat_cycles,
                              first_read_latency_cycles=self.first_read_latency,
                              inter_burst_read_gap_cycles=self.inter_burst_gap)
        for group in ('gemmini_gemm', 'gemmini_native', 'gemmini_im2col'):
            data = self.documents[group]
            require(data.get('passed', True), 'A Gemmini result group did not pass')
            require(data['build_manifest_sha256'] == self.sources['gemmini_build']['sha256'],
                    'Gemmini groups must use the same generated hardware')
            require(data['configuration'] == build['configuration'], 'Gemmini hardware configurations differ')
            require(data['memory_service'] == memory_service, 'Gemmini memory service differs')
            for gemmini_key, (npu_key, value) in MEMORY_KEYS.items():
                if gemmini_key == 'read_beat_interval_cycles':
                    value = self.read_beat_cycles
                elif gemmini_key == 'first_read_latency_cycles':
                    value = self.first_read_latency
                elif gemmini_key == 'inter_burst_read_gap_cycles':
                    value = self.inter_burst_gap
                require(data['memory_service'][gemmini_key] == np['memory'][npu_key] == value,
                        'External-memory timings differ: ' + gemmini_key)
        for group, policy in (('gemmini_native', 'native'), ('gemmini_im2col', 'im2col')):
            data = self.documents[group]
            exporter = data['exporter_build']
            require(exporter['vendor']['convolution_policy'] == policy, 'Unexpected convolution policy')
            require(exporter['binary_sha256'] == data['exporter_sha256'], 'Exporter checksum differs')
        return {
            'physical_dma_bus_bits': self.AXI_DATA_BITS, 'physical_dma_max_bytes': self.DMA_MAX_BYTES,
            'main_data_ram_bytes_each': 65536,
            'npu_main_ram_bytes': expected_buffers, 'npu_window_cache_bytes': cache_bytes,
            'gemmini_main_ram_bytes': {'scratchpad': 32768, 'accumulator': 32768},
            'gemmini_spad_read_delay': 1,
            'npu_matrix_operand_datapath_bits': np['activation_datapath_bits'],
            'gemmini_matrix_operand_datapath_bits': build['configuration']['input_bits'],
            'npu_depthwise_multiplier_count': nc['profile']['depthwise_vector_pes'],
            'matrix_mac_peak_per_cycle': 256,
            'external_memory': memory_service,
            'npu_memory_source_sha256': next(iter(memory_hashes)),
            'cold_start': True, 'output_type': 'int8', 'scale': 0.03125,
            'rounding': 'nearest_even', 'zero_points': 0,
            'memory_scope': 'Main data RAM including the NPU window cache; parameter tables, PE registers and control queues are separate.',
            'timing_scope': {
                'npu': 'Accepted calc_start through done_valid, after all AXI responses.',
                'gemmini': 'First timed configuration command through the final fence and all AXI responses.',
                'host': 'CPU instruction execution, layout preparation and schedule search are outside these independent-operator measurements.',
            },
            'gemmini_repositories': build['repositories'],
        }

    def verify_npu(self, row: dict, group: str, output_bytes: int) -> dict:
        directory = getattr(self.args, 'npu_' + group).parent / 'cases' / row['name']
        require(row['passed'] and row['returncode'] == 0, 'NPU case did not pass: ' + row['name'])
        require('+NO_RANDOM_WAIT' in row['command'], 'NPU memory has random wait states')
        require(digest(self.resolve_recorded(row['command'][0])) == self.documents['npu_' + group]['binary_sha256'],
                'NPU simulator changed')
        for name, expected in row['files'].items():
            require(digest(directory / name) == expected, 'NPU payload changed: ' + str(directory / name))
        golden = memory_segment(directory / 'golden.mem', row['addresses']['c'], output_bytes)
        require(hashlib.sha256(golden).hexdigest() == row['output_sha256'], 'NPU golden tensor checksum differs')
        log = (directory / 'run.log').read_text()
        prefix = 'CONV_TASK_PASS' if group == 'gemm' else 'COMMON_CONV_PASS'
        require(records(log, prefix) == [row['measurement']], 'NPU measured values differ from the RTL log')
        require(records(log, 'COMMON_TIMING') == [row['timing']], 'NPU timing values differ from the RTL log')
        measured, timing = row['measurement'], row['timing']
        require(measured['cycles'] == timing['done'], 'NPU completion counters disagree')
        require(timing['first_r'] - timing['first_ar'] == self.first_read_latency,
                'NPU initial memory response differs')
        require(max(timing['read_burst_bytes_max'], timing['write_burst_bytes_max']) <= self.DMA_MAX_BYTES,
                f'NPU physical DMA transaction exceeds {self.DMA_MAX_BYTES} bytes')
        require(timing['last_r'] <= timing['done'] and timing['last_b'] <= timing['done'],
                'NPU completed with pending memory responses')
        require(measured['write_bytes'] == output_bytes, 'NPU output byte count differs')
        require(measured['ar_requests'] == timing['read_commands'], 'NPU read transaction counts disagree')
        return {'log': artifact(directory / 'run.log'), 'golden_memory': artifact(directory / 'golden.mem'),
                'golden_tensor_sha256': row['output_sha256'], 'observed_output_check': 'RTL compares complete memory with golden memory'}

    def verify_gemmini(self, row: dict, group: str, output_bytes: int) -> dict:
        require(row['passed'] and row['output_mismatches'] == 0 and row['outside_output_mismatches'] == 0,
                'Gemmini case did not pass: ' + row['name'])
        require(row['memory_drained'] and row['output_bytes'] == output_bytes, 'Gemmini output completion differs')
        require(row['read_beat_interval'] == self.read_beat_cycles and
                row['first_r_cycle'] - row['first_ar_cycle'] == self.first_read_latency,
                'Gemmini memory response differs')
        require(max(row['max_read_burst_bytes'], row['max_write_burst_bytes']) <= self.DMA_MAX_BYTES,
                f'Gemmini physical DMA transaction exceeds {self.DMA_MAX_BYTES} bytes')
        require(row['last_r_cycle'] <= row['cycles'] and row['last_b_cycle'] <= row['cycles'],
                'Gemmini completed with pending memory responses')
        require(row['write_bytes'] == output_bytes, 'Gemmini output byte count differs')
        root = getattr(self.args, group).parent
        result_file = root / (row['name'] + '.json') if group == 'gemmini_gemm' else root / row['name'] / 'result.json'
        require(load(result_file) == row, 'Gemmini summary differs from individual result')
        output_file = result_file.with_suffix('.output.bin')
        require(digest(output_file) == row['expected_output_sha256'], 'Gemmini observed output checksum differs')
        if group == 'gemmini_gemm':
            directory = self.args.gemmini_gemm_traces / row['name']
            meta_path = directory / 'metadata.json'
            require(digest(meta_path) == row['trace_metadata_sha256'], 'GEMM trace metadata changed')
            metadata = load(meta_path)
            require(row['dataflow'] == metadata['emission']['dataflow'] == 'ws',
                    'GEMM comparison requires the WS dataflow')
            require(row['operand_storage_transpose'] == metadata['transpose'] == 'none',
                    'GEMM comparison requires the fixed row-major operand layout')
            require(row['explicit_tile'] == metadata['emission']['explicit_tile'] == [0, 0, 0],
                    'GEMM comparison requires the upstream automatic tiler')
            require('selected_schedule' not in metadata and 'selected_schedule' not in row,
                    'GEMM comparison must use the fixed automatic scheduling procedure')
            for filename, checksum in [('memory_file', 'memory_sha256'), ('commands_file', 'commands_sha256'),
                                       ('expected_output_file', 'expected_output_sha256')]:
                require(digest(directory / metadata[filename]) == metadata[checksum], 'GEMM trace payload changed')
            memory = (directory / metadata['memory_file']).read_bytes()
            for name, tensor in metadata['tensors'].items():
                value = memory[tensor['offset']:tensor['offset'] + tensor['bytes']]
                require(hashlib.sha256(value).hexdigest() == tensor['initial_sha256'], 'GEMM memory tensor changed')
                if name != 'output':
                    require(tensor['initial_sha256'] == row['tensor_sha256'][name], 'GEMM input tensor differs')
            source = self.resolve_recorded(metadata['workload_manifest'])
            require(digest(source) == row['workload_manifest_sha256'], 'GEMM workload definition changed')
            require(metadata['scale'] == 0.03125 and metadata['output_type'] == 'int8', 'GEMM quantization differs')
        else:
            directory = root / row['name'] / 'int8'
            metadata = row['metadata']
            require(metadata['hardware_output_scale'] == 0.03125 and
                    metadata['hardware_rounding'] == 'nearest_even' and metadata['output_format'] == 'int8',
                    'Convolution hardware output quantization differs')
            require(digest(directory / 'memory.bin') == metadata['memory_sha256'], 'Convolution memory changed')
            require(digest(directory / 'commands.txt') == metadata['commands_sha256'], 'Convolution commands changed')
            require(digest(directory / 'expected.bin') == row['expected_output_sha256'], 'Convolution reference changed')
        return {'result': artifact(result_file), 'observed_output': artifact(output_file)}

    def verify_workload(self, path: Path, npu: dict, gemmini: dict) -> None:
        require(npu['workload_manifest_sha256'] == gemmini['workload_manifest_sha256'] == digest(path),
                'Logical workloads differ')
        source = load(path)
        require(source['scale'] == 0.03125 and not any(source['zero_points'].values()),
                'Workloads must use zero points 0 and scale 1/32')
        for name, tensor in source['tensors'].items():
            require(digest(path.parent / tensor['path']) == tensor['sha256'], 'Logical tensor changed: ' + name)
            require(npu['input_tensor_sha256'][name] == tensor['sha256'], 'NPU logical tensor differs: ' + name)
        gemmini_inputs = gemmini.get('tensor_sha256', gemmini.get('input_tensor_sha256'))
        for name, value in gemmini_inputs.items():
            require(npu['input_tensor_sha256'][name] == value, 'Input tensor checksums differ: ' + name)
        require(npu['output_sha256'] == gemmini['expected_output_sha256'] == source['tensors']['c_s8']['sha256'],
                'INT8 output tensors differ')


def npu_metrics(row: dict, macs: int, depthwise: bool = False,
                read_beat_cycles: int = 2, bus_bits: int = 32) -> dict:
    m, t = row['measurement'], row['timing']
    cycles = m['cycles']
    peak = 8 if depthwise else 256
    hits, misses = m.get('hits', 0), m.get('misses', 0)
    return {
        'cycles': cycles, 'logical_macs_per_cycle': macs / cycles,
        'engine_peak_macs_per_cycle': peak, 'equivalent_engine_utilization': macs / (peak * cycles),
        'normalized_to_256_macs_per_cycle': macs / (256 * cycles),
        'read_bytes': m['ar_bytes'], 'read_requests': m['ar_requests'],
        'write_bytes': m['write_bytes'], 'write_requests': t['write_commands'],
        'read_beats': t['read_beats'], 'write_beats': t['write_beats'],
        'read_bus_lane_bytes': t['read_beats'] * (bus_bits // 8),
        'write_bus_lane_bytes': t['write_beats'] * (bus_bits // 8),
        'average_read_bytes_per_request': m['ar_bytes'] / m['ar_requests'],
        'average_write_bytes_per_request': m['write_bytes'] / t['write_commands'],
        'max_read_burst_bytes': t['read_burst_bytes_max'], 'max_write_burst_bytes': t['write_burst_bytes_max'],
        'read_outstanding_observed': t['read_outstanding_max'],
        'write_outstanding_observed': t['write_outstanding_max'],
        'cache_hits': hits, 'cache_misses': misses,
        'cache_lookup_hit_rate': hits / (hits + misses) if hits + misses else None,
        'dataflow': row.get('dataflow', 'depthwise'), 'tile': row.get('tiling'),
        'physical_layout': row.get('physical_layout', row.get('physical_rhs_layout')),
        'controller_counters': row.get('controller'), 'utilization_counters': row.get('utilization'),
        'vector_compute_cycles': m.get('vector_compute'), 'vector_dma_wait_cycles': m.get('vector_dma_wait'),
        'timing': t,
        'timed_start_to_first_ar_cycles': t['first_ar'],
        'first_ar_to_complete_cycles': cycles - t['first_ar'],
        'first_ar_to_last_b_cycles': t['last_b'] - t['first_ar'],
        'last_b_to_complete_cycles': cycles - t['last_b'],
        'observed_traffic_bandwidth_lower_bound_cycles':
            max(t['read_beats'] * read_beat_cycles, t['write_beats']),
    }


def gemmini_metrics(row: dict, macs: int, read_beat_cycles: int = 2, bus_bits: int = 32) -> dict:
    read_beats = row.get('read_beats', row['read_bytes'] / (bus_bits // 8))
    write_beats = row.get('write_beats', row['write_bytes'] / (bus_bits // 8))
    result = {key: row[key] for key in ('cycles', 'read_bytes', 'read_requests', 'write_bytes',
        'write_requests', 'max_read_burst_bytes', 'max_write_burst_bytes', 'load_busy_cycles',
        'execute_busy_cycles', 'store_busy_cycles', 'independent_im2col_requests',
        'independent_im2col_responses', 'loop_conv_launches', 'loop_depthwise_launches',
        'dwconv_active_cycles')}
    result.update(logical_macs_per_cycle=macs / row['cycles'], engine_peak_macs_per_cycle=256,
        equivalent_engine_utilization=macs / (256 * row['cycles']),
        normalized_to_256_macs_per_cycle=macs / (256 * row['cycles']),
        average_read_bytes_per_request=row['read_bytes'] / row['read_requests'],
        average_write_bytes_per_request=row['write_bytes'] / row['write_requests'],
        tile=row.get('metadata', {}).get('tile', row.get('explicit_tile')),
        read_beats=read_beats, write_beats=write_beats,
        read_bus_lane_bytes=read_beats * (bus_bits // 8),
        write_bus_lane_bytes=write_beats * (bus_bits // 8),
        observed_traffic_bandwidth_lower_bound_cycles=max(read_beats * read_beat_cycles, write_beats),
        timing={key: row[key] for key in ('first_ar_cycle', 'first_r_cycle', 'last_r_cycle',
                                         'first_aw_cycle', 'first_w_cycle', 'last_w_cycle', 'last_b_cycle')},
        timed_start_to_first_ar_cycles=row['first_ar_cycle'],
        first_ar_to_complete_cycles=row['cycles'] - row['first_ar_cycle'],
        first_ar_to_last_b_cycles=row['last_b_cycle'] - row['first_ar_cycle'],
        last_b_to_complete_cycles=row['cycles'] - row['last_b_cycle'])
    for key in ('first_launch_cycle', 'launch_to_complete_cycles',
                'read_latency_min', 'read_latency_max', 'matured_request_switch_gap_min',
                'matured_request_switch_gap_max', 'max_read_outstanding_observed',
                'max_write_outstanding_observed'):
        if key in row:
            result[key] = row[key]
    return result


def aggregate(rows: list[dict], gemmini_key: str = 'gemmini') -> dict:
    ratios = [row[gemmini_key]['cycles'] / row['npu']['cycles'] for row in rows]
    macs = sum(row['logical_macs'] for row in rows)
    result = {'case_count': len(rows), 'npu_faster_count': sum(value > 1 for value in ratios),
              'equal_count': sum(value == 1 for value in ratios),
              'gemmini_faster_count': sum(value < 1 for value in ratios),
              'geometric_mean_speedup': math.exp(sum(map(math.log, ratios)) / len(ratios)),
              'logical_macs': macs, 'npu': {}, 'gemmini': {}}
    for source, destination in (('npu', 'npu'), (gemmini_key, 'gemmini')):
        values = result[destination]
        for key in ('cycles', 'read_bytes', 'read_requests', 'write_bytes', 'write_requests',
                    'timed_start_to_first_ar_cycles', 'first_ar_to_complete_cycles',
                    'first_ar_to_last_b_cycles', 'last_b_to_complete_cycles'):
            values[key] = sum(row[source][key] for row in rows)
        values['logical_macs_per_cycle'] = macs / values['cycles']
        values['normalized_to_256_macs_per_cycle'] = macs / (256 * values['cycles'])
        values['average_read_bytes_per_request'] = values['read_bytes'] / values['read_requests']
        values['average_write_bytes_per_request'] = values['write_bytes'] / values['write_requests']
        values['max_read_burst_bytes'] = max(row[source]['max_read_burst_bytes'] for row in rows)
        values['max_write_burst_bytes'] = max(row[source]['max_write_burst_bytes'] for row in rows)
    result['aggregate_cycle_speedup'] = result['gemmini']['cycles'] / result['npu']['cycles']
    return result


def timing_sensitivity(rows: list[dict], gemmini_key: str = 'gemmini') -> dict:
    def winner(npu: int, gemmini: int) -> str:
        return 'npu' if gemmini > npu else 'gemmini' if npu > gemmini else 'equal'
    result = {}
    for key in ('cycles', 'first_ar_to_complete_cycles', 'first_ar_to_last_b_cycles'):
        npu = sum(row['npu'][key] for row in rows)
        gemmini = sum(row[gemmini_key][key] for row in rows)
        ratios = [row[gemmini_key][key] / row['npu'][key] for row in rows]
        result[key] = {
            'npu_cycles': npu, 'gemmini_cycles': gemmini,
            'aggregate_cycle_speedup': gemmini / npu,
            'geometric_mean_speedup': math.exp(sum(map(math.log, ratios)) / len(ratios)),
            'npu_faster_count': sum(value > 1 for value in ratios),
            'winner_changed_cases': [row['name'] for row in rows
                if winner(row['npu']['cycles'], row[gemmini_key]['cycles']) !=
                   winner(row['npu'][key], row[gemmini_key][key])],
        }
    return result


def make_report(args: argparse.Namespace, comparison_type: type[Comparison] = Comparison) -> dict:
    comparison = comparison_type(args)
    conditions = comparison.verify_conditions()
    metric_options = {'read_beat_cycles': comparison.read_beat_cycles, 'bus_bits': comparison.AXI_DATA_BITS}
    documents = comparison.documents
    npu_gemm, npu_conv = (indexed(documents['npu_' + name]['cases']) for name in ('gemm', 'conv'))
    gemmini_gemm = indexed(documents['gemmini_gemm']['cases'])
    native, im2col = (indexed(documents[name]['cases']) for name in ('gemmini_native', 'gemmini_im2col'))
    require(set(npu_gemm) == set(gemmini_gemm) and len(npu_gemm) == 31, 'Expected the same 31 GEMM workloads')
    require(set(npu_conv) == set(native) == set(im2col) and len(npu_conv) == 5,
            'Expected the same five Conv/DW workloads')
    catalogue = load(args.conv_workloads / 'workloads.json')
    require(digest(args.conv_workloads / 'workloads.json') == documents['npu_conv']['workload_catalogue_sha256'],
            'Convolution catalogue changed')
    conv_manifests = {entry['name']: args.conv_workloads / entry['manifest'] for entry in catalogue['cases']}
    gemm, convolutions = [], []
    for name, n in npu_gemm.items():
        g = gemmini_gemm[name]
        require(all(n[key] == g[key] for key in ('m', 'n', 'k')), 'GEMM dimensions differ')
        macs, output_bytes = n['m'] * n['n'] * n['k'], n['m'] * n['n']
        require(macs == n['dense_macs'] == g['macs'], 'GEMM multiplication counts differ')
        metadata = load(args.gemmini_gemm_traces / name / 'metadata.json')
        source = comparison.resolve_recorded(metadata['workload_manifest'])
        comparison.verify_workload(source, n, g)
        verification = {'npu': comparison.verify_npu(n, 'gemm', output_bytes),
                        'gemmini': comparison.verify_gemmini(g, 'gemmini_gemm', output_bytes),
                        'workload': artifact(source), 'inputs_sha256': g['tensor_sha256']}
        gemm.append({'name': name, 'shape': {key: n[key] for key in ('m', 'n', 'k')},
                     'operation': 'gemm', 'logical_macs': macs, 'output_bytes': output_bytes,
                     'npu': npu_metrics(n, macs, **metric_options),
                     'gemmini': gemmini_metrics(g, macs, **metric_options),
                     'speedup': g['cycles'] / n['measurement']['cycles'], 'verification': verification})
    for name, n in npu_conv.items():
        ng, ig = native[name], im2col[name]
        macs, output_bytes = n['useful_macs'], n['output_elements']
        depthwise = ng['operation'] == 'dw'
        require(n['conv'] == ng['conv'] == ig['conv'], 'Convolution dimensions differ')
        require(macs == ng['useful_macs'] == ig['useful_macs'], 'Convolution multiplication counts differ')
        verification = {'npu': comparison.verify_npu(n, 'conv', output_bytes),
                        'workload': artifact(conv_manifests[name]),
                        'inputs_sha256': n['input_tensor_sha256']}
        for g, group in ((ng, 'gemmini_native'), (ig, 'gemmini_im2col')):
            comparison.verify_workload(conv_manifests[name], n, g)
            verification[group] = comparison.verify_gemmini(g, group, output_bytes)
            if depthwise:
                require(g['loop_depthwise_launches'] > 0 and g['dwconv_active_cycles'] > 0,
                        'Dedicated DWConv hardware did not execute')
            elif group == 'gemmini_im2col':
                require(g['metadata']['independent_im2col'] and g['independent_im2col_requests'] > 0 and
                        g['independent_im2col_responses'] > 0, 'Independent Im2Col did not execute')
            else:
                require(g['loop_conv_launches'] > 0, 'Native LoopConv did not execute')
        convolutions.append({'name': name, 'operation': 'depthwise' if depthwise else 'convolution',
            'shape': n['conv'], 'logical_macs': macs, 'output_bytes': output_bytes,
            'npu': npu_metrics(n, macs, depthwise, **metric_options),
            'gemmini_native': gemmini_metrics(ng, macs, **metric_options),
            'gemmini_im2col': gemmini_metrics(ig, macs, **metric_options),
            'speedup_native': ng['cycles'] / n['measurement']['cycles'],
            'speedup_im2col': ig['cycles'] / n['measurement']['cycles'], 'verification': verification})
    combined_native = gemm + [dict(row, gemmini=row['gemmini_native']) for row in convolutions]
    combined_im2col = gemm + [dict(row, gemmini=row['gemmini_im2col']) for row in convolutions]
    reproduction = ['python3', 'test/gemmini_comparison/compare_fair_operators.py',
                    '--data-root', str(args.data_root)]
    for key in ('npu_gemm', 'npu_conv', 'gemmini_gemm', 'gemmini_native', 'gemmini_im2col',
                'gemmini_build', 'gemmini_gemm_traces', 'conv_workloads'):
        reproduction.extend(['--' + key.replace('_', '-'), str(getattr(args, key))])
    not_faster = []
    for group, rows, target in (('gemm', gemm, 'gemmini'),
                                ('conv_native', convolutions, 'gemmini_native'),
                                ('conv_im2col', convolutions, 'gemmini_im2col')):
        for row in rows:
            npu_cycles, gemmini_cycles = row['npu']['cycles'], row[target]['cycles']
            if npu_cycles >= gemmini_cycles:
                not_faster.append({'group': group, 'name': row['name'],
                    'npu_cycles': npu_cycles, 'gemmini_cycles': gemmini_cycles,
                    'speedup': gemmini_cycles / npu_cycles,
                    'npu_extra_cycles': npu_cycles - gemmini_cycles,
                    'npu_extra_fraction': npu_cycles / gemmini_cycles - 1})
    return {'format_version': 1, 'passed': True, 'generator': artifact(Path(__file__)),
        'reproduction_command': reproduction,
        'sources': comparison.sources, 'conditions': conditions,
        'speedup_definition': 'Gemmini cycles / NPU cycles; values greater than one mean the NPU is faster.',
        'utilization_definition': 'Logical MAC count / selected engine peak MACs per cycle / complete operator cycles. This is a throughput-derived ratio, not a sampled count of active PEs. Padding MACs remain in the logical convolution count.',
        'statistics': {'gemm': aggregate(gemm), 'conv_native': aggregate(convolutions, 'gemmini_native'),
                       'conv_im2col': aggregate(convolutions, 'gemmini_im2col'),
                       'all_native': aggregate(combined_native), 'all_im2col': aggregate(combined_im2col)},
        'timing_sensitivity': {'gemm': timing_sensitivity(gemm),
            'conv_native': timing_sensitivity(convolutions, 'gemmini_native'),
            'conv_im2col': timing_sensitivity(convolutions, 'gemmini_im2col')},
        'npu_not_faster_cases': not_faster, 'gemm': gemm, 'convolution': convolutions}


def render_markdown(report: dict) -> str:
    s, conditions = report['statistics'], report['conditions']
    lines = ['# DMA64、64 KiB 数据 RAM 的独立算子比较', '',
        '本报告比较 mini_tflm_dsa 与第三方 DWConv Gemmini。所有输入、权重、偏置和 INT8 输出使用共同张量；'
        '两者的物理 DMA 事务上限为 64 B，主要数据 RAM 均为 65,536 B。'
        '31 项 GEMM 和 5 项 Conv/DW 均通过逐元素输出检查。普通卷积分别测量 `LoopConv` 与独立硬件 `Im2Col` 两种调度，'
        'DW 均使用第三方专用数据流。原始结果及 SHA-256 列于文末。[^npu_gemm][^npu_conv][^gemmini_gemm][^gemmini_native][^gemmini_im2col]', '',
        '参考硬件与软件版本分别为 '
        f"[`dwconv/gemmini-dwconv`](https://github.com/dwconv/gemmini-dwconv) `{conditions['gemmini_repositories']['gemmini']['commit']}` 和 "
        f"[`dwconv/gemmini-rocc-tests-dwconv`](https://github.com/dwconv/gemmini-rocc-tests-dwconv) `{conditions['gemmini_repositories']['gemmini_rocc_tests']['commit']}`。"
        '第三方 RTL 源文件直接参与构建，配置和依赖版本由构建清单记录。[^gemmini_build]', '',
        '## 1. 比较条件与计时范围', '',
        '| 项目 | mini_tflm_dsa | DWConv Gemmini |', '|---|---|---|',
        '| 矩阵阵列 | 16 × 16 | 16 × 16 |',
        '| 外部输入、权重、输出 | INT8、INT8、INT8 | INT8、INT8、INT8 |',
        '| 内部矩阵乘法输入位宽 | INT16 | INT8 |',
        '| 累加结果 | INT32 | INT32 |',
        '| 数据 RAM | 65,536 B，包含 4,096 B window cache | SP 32 KiB + ACC 32 KiB |',
        '| AXI 数据宽度与最大事务 | 32 bit，64 B | 32 bit，64 B |',
        '| 配置的读、写并发请求上限 | 每方向 4 | 每方向 4 |',
        '| 空闲状态下首个读响应 | 3 周期 | 3 周期 |',
        '| 连续读数据拍间隔 | 2 周期 | 2 周期 |',
        '| 相邻读突发转换间隔 | 最少 3 周期 | 最少 3 周期 |',
        '| 内存服务同时处理的写事务 | 1 | 1 |',
        '| AW 至首个 W，末个 W 至 B | 各至少 1 周期 | 各至少 1 周期 |',
        '| Scratchpad 读延迟 | 由 NPU RAM 结构决定 | 1 周期 |',
        '| DW 计算资源 | 8 个向量乘法器 | 16 × 16 阵列的 DWConv 数据流 |',
        '| 输出量化 | ×1/32，最近偶数舍入 | ×1/32，最近偶数舍入 |', '',
        '每次测试重新启动仿真并复位加速器。NPU 从 `calc_start` 被接受时计时；Gemmini 从第一个计时配置命令开始，'
        '经过最终 `FENCE` 结束。二者均计入数据搬运、硬件输入重排、计算、量化和写回，并等待全部内存响应。'
        'CPU 指令执行、主机预排布和调度搜索位于本组独立算子计时之外；完整模型测试另行包含这些软件成本。'
        '[^npu_gemm][^npu_conv][^gemmini_build]', '',
        'NPU 的 RAM 分配为 IA 4,096 B、kernel 1,024 B、partial sum 46,080 B、INT8 输出 8,192 B、'
        'INT16 输出 2,048 B、window cache 4,096 B。参数表、PE 寄存器、控制队列与地址元数据单独统计。'
        'Gemmini 的独立 Im2Col 复用 SP，具有 16 B 数据寄存器；DW PE 的 256 个 INT20 部分和寄存器共 640 B，'
        '这些寄存器不计入 SP/ACC RAM。[^npu_gemm][^gemmini_build]', '',
        '定义相对加速比为 `Gemmini 周期 / NPU 周期`，大于 1 表示 NPU 更快。'
        '表中等效利用率按逻辑 MAC 数除以峰值 MAC/cycle 和完整算子周期计算，包含 DMA 等待与写回。'
        'GEMM、普通 Conv 的峰值取 256 MAC/cycle；NPU DW 的峰值取 8，Gemmini DW 的物理阵列峰值取 256。'
        '该指标由总吞吐量计算，逐周期 PE 活跃率需通过额外的硬件计数测量。卷积逻辑 MAC 数保留边缘填充项。', '',
        '## 2. 汇总结果', '',
        '| 算子集合 | NPU 周期合计 | Gemmini 周期合计 | 周期合计比 | 加速比几何平均 | NPU 更快数量 |',
        '|---|---:|---:|---:|---:|---:|']
    for key, title in [('gemm', '31 项 GEMM'), ('conv_native', '5 项 Conv/DW，LoopConv'),
                       ('conv_im2col', '5 项 Conv/DW，独立 Im2Col'),
                       ('all_native', '31 GEMM + 5 Conv/DW，LoopConv'),
                       ('all_im2col', '31 GEMM + 5 Conv/DW，独立 Im2Col')]:
        v = s[key]
        lines.append(f"| {title} | {v['npu']['cycles']:,} | {v['gemmini']['cycles']:,} | "
                     f"{v['aggregate_cycle_speedup']:.6f}× | {v['geometric_mean_speedup']:.6f}× | "
                     f"{v['npu_faster_count']}/{v['case_count']} |")
    lines += ['', '合计对应表内每个独立算子各执行一次。模型形状 GEMM 与空间卷积属于不同测试任务，'
              '这里的合计用于比较该算子集合；完整网络时延由模型测试给出。', '',
              '### 启动区间的辅助核查', '',
              '为量化两种启动方式的影响，使用原始总线时间戳另行计算 `first_AR → complete` 和 '
              '`first_AR → last_B` 两个区间。区间长度为末端周期减去起始周期。上述主表保留完整任务计时；'
              '下面的统计仅移除启动至首个读请求的区间，第二个辅助区间还移除末个写响应至任务完成的区间。', '',
              '| 31 项 GEMM 的计时区间 | NPU 周期合计 | Gemmini 周期合计 | 周期合计比 | 几何平均 | NPU 更快数量 |',
              '|---|---:|---:|---:|---:|---:|']
    for key, title in [('cycles', '完整任务'), ('first_ar_to_complete_cycles', 'first_AR → complete'),
                       ('first_ar_to_last_b_cycles', 'first_AR → last_B')]:
        v = report['timing_sensitivity']['gemm'][key]
        lines.append(f"| {title} | {v['npu_cycles']:,} | {v['gemmini_cycles']:,} | "
                     f"{v['aggregate_cycle_speedup']:.6f}× | {v['geometric_mean_speedup']:.6f}× | "
                     f"{v['npu_faster_count']}/31 |")
    nstart = s['gemm']['npu']['timed_start_to_first_ar_cycles']
    gstart = s['gemm']['gemmini']['timed_start_to_first_ar_cycles']
    changed = set().union(*(set(value['winner_changed_cases'])
                            for value in report['timing_sensitivity']['gemm'].values()))
    change_text = '两个辅助区间均未改变任何一项的快慢关系。' if not changed else \
        '辅助区间改变快慢关系的算子为：' + '、'.join(sorted(changed)) + '。'
    lines += ['', f"31 项 GEMM 的启动至首个 AR 区间分别合计 {nstart:,} 周期与 {gstart:,} 周期，"
              f"相差 {gstart-nstart:,} 周期。{change_text}逐项辅助周期以及 Conv/DW 的对应统计保存在 JSON 中。"
              '[^npu_gemm][^gemmini_gemm]', '',
              '## 3. 全部 31 项 GEMM', '',
              '| 算子 | M × N × K | NPU 周期 | Gemmini 周期 | 相对加速比 | NPU 等效利用率 | Gemmini 等效利用率 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for row in report['gemm']:
        n, g, d = row['npu'], row['gemmini'], row['shape']
        lines.append(f"| `{row['name']}` | {d['m']} × {d['n']} × {d['k']} | {n['cycles']:,} | {g['cycles']:,} | "
                     f"{row['speedup']:.4f}× | {n['equivalent_engine_utilization']:.2%} | {g['equivalent_engine_utilization']:.2%} |")
    lines += ['', 'NPU 的 WS/IS 数据流、复用参数和输入物理排布由当前成本模型选择。Gemmini 使用固定第三方软件版本的'
              '自动 WS 分块调度；全部 31 项固定使用 `flow=ws`、`transpose=none`，显式 tile 参数为 `[0,0,0]`，'
              '由该版本的软件自动选择分块。Gemmini 组没有根据实测 RTL 周期逐项搜索调度或布局；'
              'NPU 的选择也由运行前的成本模型完成。各项实际选择和原始输入 SHA-256 保存在 JSON 中。'
              '[^npu_gemm][^gemmini_gemm]', '',
              '## 4. Conv/DW 的两种 Gemmini 调度', '',
              '| 算子 | NPU 周期 | Gemmini LoopConv/DW 周期 | 相对加速比 | Gemmini Im2Col/DW 周期 | 相对加速比 |',
              '|---|---:|---:|---:|---:|---:|']
    for row in report['convolution']:
        n, g, i = row['npu'], row['gemmini_native'], row['gemmini_im2col']
        lines.append(f"| `{row['name']}` | {n['cycles']:,} | {g['cycles']:,} | {row['speedup_native']:.4f}× | "
                     f"{i['cycles']:,} | {row['speedup_im2col']:.4f}× |")
    lines += ['', '### 实际硬件活动与分块', '',
              '| 算子 | LoopConv/DW 分块 H × W × C | Im2Col/DW 分块 H × W × C | 独立 Im2Col 请求/响应 | 专用 DW 启动次数 |',
              '|---|---:|---:|---:|---:|']
    for row in report['convolution']:
        g, i = row['gemmini_native'], row['gemmini_im2col']
        tile = lambda value: ' × '.join(map(str, value))
        lines.append(f"| `{row['name']}` | {tile(g['tile'])} | {tile(i['tile'])} | "
                     f"{i['independent_im2col_requests']:,}/{i['independent_im2col_responses']:,} | {i['loop_depthwise_launches']} |")
    lines += ['', '普通卷积的独立 Im2Col 组均有实际请求与响应。DW 的请求经过 function 29，使用专用 DWConv 数据流。'
              '独立 Im2Col 直接从 SP 原始图像生成阵列输入；每次 compute 的输入行数为 16，输出描述符选择有效行，'
              '并在权重更新组之间等待完成。[^gemmini_native][^gemmini_im2col]', '',
              '### Conv/DW 吞吐量与等效利用率', '',
              '| 算子 | NPU MAC/cycle | LoopConv/DW MAC/cycle | Im2Col/DW MAC/cycle | NPU 等效利用率 | LoopConv/DW 等效利用率 | Im2Col/DW 等效利用率 |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for row in report['convolution']:
        values = [row[key] for key in ('npu', 'gemmini_native', 'gemmini_im2col')]
        rates = ' | '.join(f"{value['logical_macs_per_cycle']:.3f}" for value in values)
        utilization = ' | '.join(f"{value['equivalent_engine_utilization']:.2%}" for value in values)
        lines.append(f"| `{row['name']}` | {rates} | {utilization} |")
    lines += ['', '## 5. 外部访存统计', '',
              '| 算子集合/实现 | 读字节数 | 读事务数 | 平均读事务 B | 写字节数 | 写事务数 | 平均写事务 B |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for group, label in [('gemm', 'GEMM'), ('conv_native', 'Conv/DW LoopConv'), ('conv_im2col', 'Conv/DW Im2Col')]:
        for engine in ('npu', 'gemmini'):
            v = s[group][engine]
            lines.append(f"| {label} / {engine} | {v['read_bytes']:,} | {v['read_requests']:,} | "
                         f"{v['average_read_bytes_per_request']:.2f} | {v['write_bytes']:,} | {v['write_requests']:,} | "
                         f"{v['average_write_bytes_per_request']:.2f} |")
    lines += ['', '所有运行中观察到的 AR/AW 事务均不超过 64 B。下面同时列出字节数与事务数，'
              '便于区分传输量和短突发开销。', '',
              '| 算子/实现 | 读 B / 事务 | 写 B / 事务 | 最大读/写事务 B | NPU cache 命中率 |',
              '|---|---:|---:|---:|---:|']
    for row in report['convolution']:
        for key, label in [('npu', 'NPU'), ('gemmini_native', 'LoopConv/DW'), ('gemmini_im2col', 'Im2Col/DW')]:
            v = row[key]
            hit_rate = f"{v['cache_lookup_hit_rate']:.4%}" if key == 'npu' else '—'
            lines.append(f"| `{row['name']}` / {label} | {v['read_bytes']:,} / {v['read_requests']:,} | "
                         f"{v['write_bytes']:,} / {v['write_requests']:,} | {v['max_read_burst_bytes']} / "
                         f"{v['max_write_burst_bytes']} | {hit_rate} |")
    by_gemm = {row['name']: row for row in report['gemm']}
    by_conv = {row['name']: row for row in report['convolution']}
    v = by_gemm['model_m1_n64_k784']; n, g = v['npu'], v['gemmini']
    lines += ['', '## 6. NPU 尚未领先的算子', '', '### 6.1 1 × 64 × 784 GEMM：短向量读取事务', '',
        f"NPU 为 {n['cycles']:,} 周期，Gemmini 为 {g['cycles']:,} 周期，NPU 多 {n['cycles']-g['cycles']:,} 周期，"
        f"约 {n['cycles']/g['cycles']-1:.2%}。两者读取量均为 {n['read_bytes']:,} B，写回均为 64 B。"
        f"读事务分别为 {n['read_requests']} 与 {g['read_requests']}，相差 {n['read_requests']-g['read_requests']} 次。"
        f"NPU 的最后读响应在第 {n['timing']['last_r']:,} 周期，Gemmini 在第 {g['timing']['last_r_cycle']:,} 周期。[^npu_gemm][^gemmini_gemm]", '',
        '由矩阵尺寸和分块可计算：权重为 50,176 B，偏置为 256 B，输入向量为 784 B。'
        '按 K=16 分块读取向量需要 49 个 16 B 事务，按最大 64 B 合并需要 13 个事务，差值恰为 36。'
        '据此可优先实现最多 64 B 的向量预读缓冲，再以每次 16 B 向阵列交付；实际周期收益需要重新仿真测量。', '',
        '### 6.2 32 × 32、C16、O16 的 3×3 Conv：阵列分块衔接', '']
    v = by_conv['conv3x3_32_c16_o16']; n, g = v['npu'], v['gemmini_native']; counters = n['controller_counters'][0]
    lines += [f"NPU 为 {n['cycles']:,} 周期，LoopConv 为 {g['cycles']:,} 周期。读取量分别为 "
        f"{n['read_bytes']:,} B 与 {g['read_bytes']:,} B，相差 {n['read_bytes']/g['read_bytes']-1:.2%}；"
        f"总周期相差 {n['cycles']/g['cycles']-1:.2%}。该算子的逻辑 MAC 数为 {v['logical_macs']:,}，"
        f"256 MAC/cycle 对应 {v['logical_macs']//256:,} 周期；Gemmini 的 `execute_busy_cycles` 为 {g['execute_busy_cycles']:,}。"
        '[^npu_conv][^gemmini_native]', '',
        f"NPU 共启动 {counters['weight_trig']} 次阵列分块，`weight_data_stall`={counters['weight_data_stall']:,}、"
        f"`ia_done_wait`={counters['ia_done_wait']:,}、`tail_pending`={counters['tail_pending']:,}。"
        '这些并发状态计数在时间上有重叠，不能相加作为总周期。优先优化方向是提前装入下一组权重、'
        '将下一组输入请求与前一组计算排空重叠，以及降低短分块的完成握手开销。当前读流量差异较小，'
        '阵列分块之间的等待需要优先分析。', '',
        '### 6.3 48 × 48、C8、stride 1 的 DW：命中后的数据交付与 MAC 调度', '']
    v = by_conv['dw3x3_s1_48_c8']; n, g = v['npu'], v['gemmini_native']
    lines += [f"NPU 为 {n['cycles']:,} 周期，Gemmini 为 {g['cycles']:,} 周期。NPU 读流量 "
        f"{n['read_bytes']:,} B，Gemmini 读流量 {g['read_bytes']:,} B；NPU 少读 {1-n['read_bytes']/g['read_bytes']:.2%}。"
        f"NPU cache 的 {n['cache_hits']:,} 次命中与 {n['cache_misses']} 次未命中对应 {n['cache_lookup_hit_rate']:.4%} 命中率。"
        '[^npu_conv][^gemmini_native]', '',
        f"双方均写回 {n['write_bytes']:,} B，均使用 {n['write_requests']:,} 个写事务，平均每个事务 "
        f"{n['average_write_bytes_per_request']:.0f} B。NPU 的向量 MAC 活动计数为 {n['vector_compute_cycles']:,}，"
        f"平均每次活动对应 {n['cycles']/n['vector_compute_cycles']:.3f} 个总周期。"
        f"Gemmini 的执行忙碌计数为 {g['execute_busy_cycles']:,} 周期。两种 DW 数据流的计算资源不同："
        'NPU 使用 8 个乘法器，Gemmini 还在阵列中并行处理多个空间位置。', '',
        '缓存优化的下一项重点是命中请求的持续受理与返回，使输入交付、MAC、重新量化和写回并行进行。'
        '若将相邻输出合并至 64 B，18,432 B 输出的事务数量下限为 288；该计算只给出可实现的传输形状，'
        '性能收益仍需结合 MAC 生产速度和输出队列进行实测。命中率统计对应 cache 查询；DMA 字节数与事务数反映外部存储器负担。', '',
        '## 7. 复现与原始结果', '',
        '比较生成器逐项检查输入和输出哈希、NPU 完整内存检查结果、Gemmini 实际输出文件、构建参数、'
        '内存服务参数、DMA 最大事务、数据 RAM 总量和实际 Im2Col/DW 活动。运行：', '', '```bash',
        shlex.join(report['reproduction_command'][:2]) + ' \\',
        ' \\\n'.join('  ' + shlex.join(report['reproduction_command'][index:index + 2])
                      for index in range(2, len(report['reproduction_command']), 2)), '```', '',
        '运行所需原始目录包括共同张量、NPU 两组结果与构建文件、Gemmini 三组结果、GEMM 命令文件和固定硬件构建。'
        '用 `--data-root` 指定这些目录的父目录；各输入路径也可单独通过命令行参数指定。'
        '详细逐项统计保存于同名 JSON。', '',
        '| 原始结果 | SHA-256 |', '|---|---|']
    for name, source in report['sources'].items():
        lines.append(f"| `{name}` | `{source['sha256']}` |")
    lines.append('')
    for name, source in report['sources'].items():
        lines.append(f"[^{name}]: `{source['path']}`，SHA-256 `{source['sha256']}`。")
    lines += ['', '报告由 `test/gemmini_comparison/compare_fair_operators.py` 从上述原始结果生成。', '']
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=ROOT.parent)
    defaults = {
        'npu-gemm': 'comparison_dma64_ram64k_gemm/summary.json',
        'npu-conv': 'comparison_dma64_ram64k_conv/summary.json',
        'gemmini-gemm': 'gemmini_dwconv_spdelay1_gemm_results/results.json',
        'gemmini-native': 'gemmini_dwconv_spdelay1_conv_results/results.json',
        'gemmini-im2col': 'gemmini_dwconv_im2col_conv_results/results.json',
        'gemmini-build': 'gemmini_dwconv_build/generated_sp32_acc32_spdelay1/build_manifest.json',
        'gemmini-gemm-traces': 'gemmini_dwconv_gemm_traces',
        'conv-workloads': 'comparison_conv_workloads_five',
    }
    for key, default in defaults.items():
        parser.add_argument('--' + key, type=Path, default=Path(default))
    parser.add_argument('--json', type=Path, default=ROOT / 'docs/fair_dma64_operators.json')
    parser.add_argument('--markdown', type=Path, default=ROOT / 'docs/fair_dma64_operators.md')
    args = parser.parse_args()
    args.data_root = args.data_root.resolve()
    for key in defaults:
        attribute = key.replace('-', '_')
        value = getattr(args, attribute)
        setattr(args, attribute, value.resolve() if value.is_absolute() else (args.data_root / value).resolve())
    report = make_report(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    args.markdown.write_text(render_markdown(report))
    print(json.dumps({'passed': report['passed'], 'gemm_cases': len(report['gemm']),
                      'convolution_cases': len(report['convolution']),
                      'json': str(args.json.resolve()), 'markdown': str(args.markdown.resolve()),
                      'statistics': {key: {name: value for name, value in stats.items()
                                           if name in ('case_count', 'npu_faster_count',
                                                       'aggregate_cycle_speedup', 'geometric_mean_speedup')}
                                     for key, stats in report['statistics'].items()}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
