#!/usr/bin/env python3
"""Compute complete-model cycle budgets and depthwise utilization from measured runs."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean


OPERATORS = {
    'CONV_2D': 'Conv',
    'DEPTHWISE_CONV_2D': 'DW',
    'FULLY_CONNECTED': 'FC',
    'MAX_POOL_2D': 'Pool',
    'AVERAGE_POOL_2D': 'Pool',
    'ADD': 'Add',
    'SOFTMAX': 'Softmax',
    'RESHAPE': 'Framework',
}
CATEGORIES = ('Conv', 'DW', 'FC', 'Pool', 'Add', 'Softmax', 'Framework')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path, base):
    path = Path(path).resolve()
    return {'path': os.path.relpath(path, base), 'sha256': sha(path)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def depthwise_geometry(node, pes, tile):
    batch, ih, iw, channels = node['input_shapes'][0]
    output_batch, oh, ow, output_channels = node['output_shapes'][0]
    require(batch == output_batch and output_channels % channels == 0,
            'Invalid depthwise tensor geometry')
    options = node['options']
    kh, kw = options['kernel_h'], options['kernel_w']
    sh, sw = options['stride_h'], options['stride_w']
    dh = options.get('dilation_h_factor', 1)
    dw = options.get('dilation_w_factor', 1)
    if options['padding'] == 'SAME':
        ph = max(0, (oh - 1) * sh + (kh - 1) * dh + 1 - ih) // 2
        pw = max(0, (ow - 1) * sw + (kw - 1) * dw + 1 - iw) // 2
    else:
        require(options['padding'] == 'VALID', 'Unsupported depthwise padding')
        ph = pw = 0
    valid_rows = sum(0 <= y * sh + ky * dh - ph < ih
                     for y in range(oh) for ky in range(kh))
    valid_columns = sum(0 <= x * sw + kx * dw - pw < iw
                        for x in range(ow) for kx in range(kw))
    spatial_taps = batch * valid_rows * valid_columns
    return {
        'input_shape': node['input_shapes'][0],
        'output_shape': node['output_shapes'][0],
        'kernel_shape': [kh, kw],
        'depth_multiplier': output_channels // channels,
        'nominal_macs_including_padding': batch * oh * ow * output_channels * kh * kw,
        'useful_macs': spatial_taps * output_channels,
        'expected_compute_cycles': spatial_taps * math.ceil(output_channels / pes),
        'expected_window_requests': spatial_taps * math.ceil(channels / tile),
        'expected_window_elements': spatial_taps * channels,
        'input_tensor_bytes': batch * ih * iw * channels,
    }


def aggregate_depthwise(rows, pes, window_width):
    summed = (
        'nominal_macs_including_padding', 'useful_macs', 'expected_compute_cycles',
        'input_tensor_bytes', 'npu_busy_cycles', 'layer_cycles',
        'vector_compute_cycles', 'vector_dma_wait_cycles',
        'requests', 'response_beats', 'consecutive_responses',
        'request_response_overlap', 'response_elements', 'return_span_cycles',
        'cache_demand_hits', 'cache_demand_misses', 'cache_input_read_bytes',
        'npu_read_bytes', 'npu_write_bytes',
    )
    result = {key: sum(row[key] for row in rows) for key in summed}
    result['records'] = len(rows)
    result['unique_layers'] = len({(row['model'], row['layer']) for row in rows})
    result['pes'] = pes
    result['window_elements_per_beat'] = window_width
    result['cache_demand_requests'] = result['cache_demand_hits'] + result['cache_demand_misses']
    divisions = {
        'pe_effective_mac_utilization_percent':
            (100 * result['useful_macs'], pes * result['npu_busy_cycles']),
        'compute_lane_utilization_percent':
            (100 * result['useful_macs'], pes * result['vector_compute_cycles']),
        'window_elements_per_return_span_cycle':
            (result['response_elements'], result['return_span_cycles']),
        'window_elements_per_npu_busy_cycle':
            (result['response_elements'], result['npu_busy_cycles']),
        'window_beats_per_return_span_cycle':
            (result['response_beats'], result['return_span_cycles']),
        'window_lane_utilization_percent':
            (100 * result['response_elements'], window_width * result['return_span_cycles']),
        'demand_hit_rate_percent':
            (100 * result['cache_demand_hits'], result['cache_demand_requests']),
        'input_read_amplification':
            (result['cache_input_read_bytes'], result['input_tensor_bytes']),
        'consecutive_response_fraction':
            (result['consecutive_responses'], sum(max(row['response_beats'] - 1, 0) for row in rows)),
    }
    result.update({key: a / b if b else None for key, (a, b) in divisions.items()})
    result['minimum_peak_outstanding'] = min((row['peak_outstanding'] for row in rows), default=0)
    result['maximum_peak_outstanding'] = max((row['peak_outstanding'] for row in rows), default=0)
    result['minimum_layer_demand_hit_rate_percent'] = min(
        (100 * row['cache_demand_hits'] /
         (row['cache_demand_hits'] + row['cache_demand_misses']) for row in rows), default=None)
    result['all_layers_reach_multiple_outstanding_requests'] = bool(rows) and all(
        row['peak_outstanding'] >= 2 for row in rows)
    result['all_layers_overlap_requests_and_responses'] = bool(rows) and all(
        row['request_response_overlap'] > 0 for row in rows)
    result['mac_and_window_width_lower_bound_cycles'] = sum(
        max(row['expected_compute_cycles'], math.ceil(row['response_elements'] / window_width))
        for row in rows)
    return result


def analyze(base, target):
    build_path = base / 'sim/build.json'
    build = read(build_path)
    profile = build['profile']
    require(build['returncode'] == 0 and build['sources_unchanged_during_build'],
            'Simulator build is not complete')
    summary_path = base / 'summary/summary.json'
    summary = read(summary_path)
    require(summary['complete'] and summary['functional_passed'] and
            summary['completed_runs'] == summary['expected_runs'] == 32,
            'Analysis requires all 32 complete-model runs')
    paths = sorted(base.glob('results/cases/*/*/*/result.json'))
    require(len(paths) == 32, 'Expected 32 model result files')
    indexed, sources, manifests = {}, [], {}
    for path in paths:
        result = read(path)
        require(result['passed'] and all(result['checks'].values()),
                'Model run failed: ' + str(path))
        require(result['simulator']['simulator_sha256'] == build['binary_sha256'],
                'Model run uses a different simulator')
        case_path = path.with_name('case.json')
        case = read(case_path)
        manifest_path = Path(case['prepared_dir']) / 'manifest.json'
        require(sha(manifest_path) == case['prepared_sha256'], 'Prepared graph digest differs')
        manifest = read(manifest_path)
        require(result['model']['sha256'] == manifest['model']['sha256'], 'Model digest differs')
        require(result['input_sha256'] == case['sample']['input']['sha256'], 'Input digest differs')
        key = result['model_id'], result['sample_index'], result['kind'], result['mode']
        require(key not in indexed, 'Duplicate model run')
        indexed[key] = result
        manifests[result['model_id']] = manifest
        sources.append({'model': result['model_id'], 'sample': result['sample_index'],
                        'kind': result['kind'], 'mode': result['mode_name'],
                        'result': reference(path, base), 'case': reference(case_path, base),
                        'input_sha256': result['input_sha256'],
                        'model_sha256': result['model']['sha256'],
                        'firmware_elf_sha256': result['firmware_elf_sha256']})
    require(len(manifests) == 4, 'Expected four distinct models')
    ram_latencies = {result['ram_fixed_lat'] for result in indexed.values()}
    require(len(ram_latencies) == 1, 'All models must use identical RAM timing')
    pes, tile = profile['pe_count'], profile['size']
    window_width = profile['im2col_corrected_elements_per_cycle']
    models, categories, depthwise = [], [], []
    for model, manifest in sorted(manifests.items()):
        samples = sorted({key[1] for key in indexed if key[0] == model})
        require(len(samples) == 2, 'Expected two inputs per model')
        nodes = {node['index']: node for node in manifest['graph']['nodes']}
        perf_samples, trace_samples = [], []
        operator_samples = defaultdict(list)
        for sample in samples:
            sw, hw = (indexed[model, sample, 'perf', mode] for mode in (0, 63))
            sw_trace, hw_trace = (indexed[model, sample, 'trace', mode] for mode in (0, 63))
            runs = sw, hw, sw_trace, hw_trace
            require(len({run['input_sha256'] for run in runs}) == 1 and
                    len({run['ram_fixed_lat'] for run in runs}) == 1 and
                    len({run['output_comparison']['actual_sha256'] for run in runs}) == 1,
                    'Paired runs differ in input, RAM timing, or output')
            sw_cycles, hw_cycles = sw['result']['invoke_cycles'], hw['result']['invoke_cycles']
            busy = hw['network']['npu_busy_cycles']
            budget = sw_cycles / target
            perf_samples.append({
                'sample': sample, 'sw_invoke_cycles': sw_cycles,
                'hw_invoke_cycles': hw_cycles, 'speedup': sw_cycles / hw_cycles,
                'allowed_hw_invoke_cycles': budget,
                'actual_minus_budget_cycles': hw_cycles - budget,
                'required_reduction_cycles': max(0, hw_cycles - budget),
                'sw_initialization_cycles': sw['result']['init_cycles'],
                'hw_initialization_cycles': hw['result']['init_cycles'],
                'hw_npu_busy_cycles': busy,
                'hw_elapsed_outside_npu_busy_cycles': hw_cycles - busy,
            })
            trace_samples.append({'sample': sample,
                                  'sw_invoke_cycles': sw_trace['result']['invoke_cycles'],
                                  'hw_invoke_cycles': hw_trace['result']['invoke_cycles']})
            layer_sets = [{row['index']: row for row in run['layers']}
                          for run in (sw_trace, hw_trace)]
            require(all(set(rows) == set(nodes) for rows in layer_sets), 'Trace layer set differs')
            totals = {category: {'sw_cycles': 0, 'hw_cycles': 0, 'hw_npu_busy_cycles': 0,
                                 'nodes': 0, 'reshape_cycles': 0, 'framework_and_profiling_cycles': 0}
                      for category in CATEGORIES}
            for index, node in nodes.items():
                category = OPERATORS[node['op']]
                left, right = (rows[index] for rows in layer_sets)
                totals[category]['sw_cycles'] += left['cycles']
                totals[category]['hw_cycles'] += right['cycles']
                totals[category]['hw_npu_busy_cycles'] += right['npu_busy_cycles']
                totals[category]['nodes'] += 1
                if node['op'] == 'RESHAPE':
                    totals[category]['reshape_cycles'] += right['cycles']
            for mode_name, run, rows in zip(('sw', 'hw'), (sw_trace, hw_trace), layer_sets):
                residual = run['result']['invoke_cycles'] - sum(row['cycles'] for row in rows.values())
                require(residual >= 0, 'Layer intervals exceed Invoke')
                totals['Framework'][mode_name + '_cycles'] += residual
                if mode_name == 'hw':
                    totals['Framework']['framework_and_profiling_cycles'] = residual
            require(sum(value['hw_cycles'] for value in totals.values()) ==
                    hw_trace['result']['invoke_cycles'], 'Category sum differs from trace Invoke')
            for category, values in totals.items():
                operator_samples[category].append(values)
            windows = {row['layer']: row for row in hw_trace['simulator']['window_jobs']}
            for index, node in nodes.items():
                if node['op'] != 'DEPTHWISE_CONV_2D':
                    continue
                layer, window = layer_sets[1][index], windows[index]
                geometry = depthwise_geometry(node, pes, tile)
                require(layer['vector_compute_cycles'] == geometry['expected_compute_cycles'],
                        'Depthwise MAC issue count differs from geometry')
                require(window['requests'] == window['completions'] == geometry['expected_window_requests'] and
                        window['requested_elements'] == window['response_elements'] == geometry['expected_window_elements'],
                        'Depthwise window counts differ from geometry')
                require(window['response_elements'] <= window_width * window['response_beats'],
                        'Response elements exceed window bus width')
                record = {
                    'model': model, 'sample': sample, 'layer': index, **geometry,
                    'npu_busy_cycles': layer['npu_busy_cycles'], 'layer_cycles': layer['cycles'],
                    'vector_compute_cycles': layer['vector_compute_cycles'],
                    'vector_dma_wait_cycles': layer['vector_dma_wait_cycles'],
                    **{key: window[key] for key in ('requests', 'response_beats', 'consecutive_responses',
                       'request_response_overlap', 'response_elements', 'return_span_cycles', 'peak_outstanding')},
                    'cache_demand_hits': layer['window_cache_hits'],
                    'cache_demand_misses': layer['window_cache_misses'],
                    'cache_input_read_bytes': layer['window_cache_read_bytes'],
                    'npu_read_bytes': layer['npu_read_bytes'], 'npu_write_bytes': layer['npu_write_bytes'],
                    'output_exact': True,
                }
                record['metrics'] = aggregate_depthwise([record], pes, window_width)
                depthwise.append(record)
        value = {'model': model, 'samples': len(samples),
                 'model_sha256': manifest['model']['sha256'], 'per_sample': perf_samples,
                 'target_speedup': target}
        for key in perf_samples[0]:
            if key not in ('sample', 'speedup'):
                value[key + '_mean'] = mean(row[key] for row in perf_samples)
        sw_cycles, hw_cycles = value['sw_invoke_cycles_mean'], value['hw_invoke_cycles_mean']
        value['speedup'] = sw_cycles / hw_cycles
        value['target_met_all_samples'] = all(row['speedup'] >= target for row in perf_samples)
        value['required_reduction_percent'] = 100 * max(0, value['actual_minus_budget_cycles_mean']) / hw_cycles
        value['hw_trace_invoke_cycles_mean'] = mean(row['hw_invoke_cycles'] for row in trace_samples)
        value['sw_trace_invoke_cycles_mean'] = mean(row['sw_invoke_cycles'] for row in trace_samples)
        value['trace_minus_perf_hw_cycles_mean'] = value['hw_trace_invoke_cycles_mean'] - hw_cycles
        value['allowed_npu_busy_cycles_at_current_outside_busy_time'] = (
            value['allowed_hw_invoke_cycles_mean'] - value['hw_elapsed_outside_npu_busy_cycles_mean'])
        models.append(value)
        for category, rows in operator_samples.items():
            row = {'model': model, 'operator': category, 'samples': len(rows)}
            row.update({key + '_mean': mean(item[key] for item in rows) for key in rows[0]})
            row['hw_share_of_trace_invoke_percent'] = 100 * row['hw_cycles_mean'] / value['hw_trace_invoke_cycles_mean']
            row['sw_share_of_trace_invoke_percent'] = 100 * row['sw_cycles_mean'] / value['sw_trace_invoke_cycles_mean']
            row['hw_elapsed_outside_npu_busy_cycles_mean'] = row['hw_cycles_mean'] - row['hw_npu_busy_cycles_mean']
            row['speedup'] = row['sw_cycles_mean'] / row['hw_cycles_mean'] if row['hw_cycles_mean'] else None
            categories.append(row)
    require(len(depthwise) == 34, 'Expected 34 depthwise layer/input records')
    aggregate = {
        'workload': 'One inference from each model, using the mean of its two inputs',
        'sw_invoke_cycles': sum(row['sw_invoke_cycles_mean'] for row in models),
        'hw_invoke_cycles': sum(row['hw_invoke_cycles_mean'] for row in models),
        'hw_npu_busy_cycles': sum(row['hw_npu_busy_cycles_mean'] for row in models),
        'hw_elapsed_outside_npu_busy_cycles': sum(row['hw_elapsed_outside_npu_busy_cycles_mean'] for row in models),
        'sw_initialization_cycles': sum(row['sw_initialization_cycles_mean'] for row in models),
        'hw_initialization_cycles': sum(row['hw_initialization_cycles_mean'] for row in models),
        'hw_trace_invoke_cycles': sum(row['hw_trace_invoke_cycles_mean'] for row in models),
    }
    aggregate['speedup'] = aggregate['sw_invoke_cycles'] / aggregate['hw_invoke_cycles']
    aggregate['allowed_hw_invoke_cycles'] = aggregate['sw_invoke_cycles'] / target
    aggregate['actual_minus_budget_cycles'] = aggregate['hw_invoke_cycles'] - aggregate['allowed_hw_invoke_cycles']
    aggregate['required_reduction_cycles'] = max(0, aggregate['actual_minus_budget_cycles'])
    aggregate['required_reduction_percent'] = 100 * aggregate['required_reduction_cycles'] / aggregate['hw_invoke_cycles']
    aggregate['target_met'] = aggregate['speedup'] >= target
    aggregate['all_models_meet_target'] = all(row['target_met_all_samples'] for row in models)
    aggregate['sum_reductions_to_meet_each_model_mean_budget'] = sum(
        max(0, row['actual_minus_budget_cycles_mean']) for row in models)
    aggregate['trace_minus_perf_hw_cycles'] = aggregate['hw_trace_invoke_cycles'] - aggregate['hw_invoke_cycles']
    category_totals = []
    for category in CATEGORIES:
        selected = [row for row in categories if row['operator'] == category]
        cycles = sum(row['hw_cycles_mean'] for row in selected)
        category_totals.append({'operator': category,
            'sw_cycles': sum(row['sw_cycles_mean'] for row in selected),
            'hw_cycles': cycles,
            'hw_npu_busy_cycles': sum(row['hw_npu_busy_cycles_mean'] for row in selected),
            'hw_share_of_trace_invoke_percent': 100 * cycles / aggregate['hw_trace_invoke_cycles']})
    groups = []
    for model in sorted({row['model'] for row in depthwise}):
        selected = [row for row in depthwise if row['model'] == model]
        groups.append({'model': model, **aggregate_depthwise(selected, pes, window_width)})
    return {
        'schema_version': 1, 'passed': True,
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'measurement_directory': str(base),
        'analysis_script': {'repository_path': 'test/performance_analysis/analyze_model_budget.py',
                            'sha256': sha(__file__)},
        'target_speedup': target, 'source_build': reference(build_path, base),
        'source_summary': reference(summary_path, base), 'source_results': sources,
        'simulator_sha256': build['binary_sha256'], 'soc_profile': profile,
        'ram_fixed_lat': next(iter(ram_latencies)),
        'definitions': {
            'performance_budget': 'Software perf Invoke cycles divided by target_speedup; initialization is recorded separately.',
            'operator_cycles': 'Measured in separate trace firmware. Categories sum to trace Invoke and are not substituted for perf Invoke.',
            'Framework': 'RESHAPE node intervals plus trace Invoke time outside the sum of all node intervals.',
            'outside_npu_busy': 'Elapsed Invoke or node cycles outside NPU busy; not a count of retired CPU instructions.',
            'useful_macs': 'Depthwise output-channel MAC operations at valid input positions; padded positions skipped by hardware are excluded.',
            'pe_effective_mac_utilization_percent': '100 * useful_macs / (PE count * NPU busy cycles).',
            'compute_lane_utilization_percent': '100 * useful_macs / (PE count * vector_compute_cycles).',
            'return_span_cycles': 'Sum of inclusive intervals from first to last accepted response beat for each depthwise job.',
            'window_elements_per_return_span_cycle': 'Valid INT16 response elements divided by the summed response intervals.',
            'demand_hit_rate_percent': '100 * demand hits / (demand hits + demand misses), counted when each demand is accepted, including cold demands.',
            'cache_input_read_bytes': 'All input-window bytes read from external RAM, including demand fills and prefetch fills.',
            'vector_dma_wait_cycles': 'Cycles satisfying the vector engine DMA activity/wait condition; they may overlap computation and are not additive stall time.',
            'mac_and_window_width_lower_bound_cycles': 'Sum of max(expected MAC issue cycles, ceil(window elements / window width)); excludes parameter loads, output writes, and control work.',
        },
        'prefetch_statistics': {
            'prefetch_requests_in_demand_hit_rate_denominator': False,
            'cache_input_read_bytes_include_prefetch_fills': True,
            'separate_prefetch_used_wasted_late_counts_recorded': False,
        },
        'models': models, 'aggregate': aggregate,
        'operator_categories': categories, 'aggregate_operator_categories': category_totals,
        'depthwise': {'overall': aggregate_depthwise(depthwise, pes, window_width),
                      'models': groups, 'records': depthwise},
    }


def compare_capacity(current, base, previous_base):
    previous_path = previous_base / 'model_budget.json'
    previous = read(previous_path)
    require(previous['passed'] and previous['analysis_script'] == current['analysis_script'],
            'Capacity comparison requires matching analysis versions')
    require(sha(previous_base / previous['source_summary']['path']) == previous['source_summary']['sha256'],
            'Reference summary differs from its analysis')
    current_build = read(base / 'sim/build.json')
    previous_build = read(previous_base / 'sim/build.json')
    require(current_build['source_sha256'] == previous_build['source_sha256'],
            'Capacity comparison requires identical simulator sources')
    changed = {key for key in current['soc_profile'] if
               current['soc_profile'][key] != previous['soc_profile'].get(key)}
    require(changed <= {'ps_storage_rows'} and current['ram_fixed_lat'] == previous['ram_fixed_lat'],
            'Capacity comparison may change only PS storage rows')
    def identities(report):
        return {(row['model'], row['sample'], row['kind'], row['mode']):
                (row['model_sha256'], row['input_sha256'], row['firmware_elf_sha256'])
                for row in report['source_results']}
    require(identities(current) == identities(previous),
            'Capacity comparison requires identical models, inputs, and firmware')
    previous_models = {row['model']: row for row in previous['models']}
    rows = []
    for row in current['models']:
        old = previous_models[row['model']]
        require(row['sw_invoke_cycles_mean'] == old['sw_invoke_cycles_mean'],
                'Software cycles differ between NPU capacity configurations')
        old_cycles, new_cycles = old['hw_invoke_cycles_mean'], row['hw_invoke_cycles_mean']
        rows.append({'model': row['model'], 'previous_hw_cycles': old_cycles,
                     'current_hw_cycles': new_cycles, 'cycle_change': new_cycles - old_cycles,
                     'cycle_change_percent': 100 * (new_cycles - old_cycles) / old_cycles,
                     'sw_cycles_identical': True})
    previous_summary = read(previous_base / 'summary/summary.json')
    current_summary = read(base / 'summary/summary.json')
    old_layers = {(row['model'], row['sample'], row['layer']): row
                  for row in previous_summary['layers']}
    changed_layers = []
    for row in current_summary['layers']:
        old = old_layers[row['model'], row['sample'], row['layer']]
        require(all(row[key] == old[key] for key in ('op', 'input_shapes', 'output_shapes', 'sw_cycles')),
                'Trace geometry or software layer cycles differ across capacities')
        fields = ('hw_cycles', 'hw_busy_cycles', 'hw_read_bytes', 'hw_write_bytes')
        delta = {key: row[key] - old[key] for key in fields}
        if any(delta.values()):
            changed_layers.append({'model': row['model'], 'sample': row['sample'],
                'layer': row['layer'], 'op': row['op'],
                'previous': {key: old[key] for key in fields},
                'current': {key: row[key] for key in fields}, 'change': delta})
    old_total, new_total = previous['aggregate']['hw_invoke_cycles'], current['aggregate']['hw_invoke_cycles']
    return {'previous_analysis': reference(previous_path, base),
            'previous_ps_storage_rows': previous['soc_profile']['ps_storage_rows'],
            'current_ps_storage_rows': current['soc_profile']['ps_storage_rows'],
            'identical_simulator_sources': True, 'identical_models_inputs_and_firmware': True,
            'models': rows, 'changed_trace_layers': changed_layers, 'aggregate': {
                'previous_hw_cycles': old_total, 'current_hw_cycles': new_total,
                'cycle_change': new_total - old_total,
                'cycle_change_percent': 100 * (new_total - old_total) / old_total}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements', type=Path, required=True)
    parser.add_argument('--target-speedup', type=float, default=1000)
    parser.add_argument('--reference-measurements', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.target_speedup <= 0:
        parser.error('Target speedup must be positive')
    base = args.measurements.resolve()
    result = analyze(base, args.target_speedup)
    if args.reference_measurements:
        result['capacity_comparison'] = compare_capacity(
            result, base, args.reference_measurements.resolve())
    destination = args.out.resolve() if args.out else base / 'model_budget.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    require(read(destination) == result, 'Serialized analysis differs')
    print(json.dumps({'passed': True, 'output': str(destination), 'sha256': sha(destination),
                      'aggregate': result['aggregate'],
                      'depthwise': result['depthwise']['overall']}, indent=2))


if __name__ == '__main__':
    main()
