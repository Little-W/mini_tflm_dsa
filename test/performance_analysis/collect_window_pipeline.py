#!/usr/bin/env python3
"""Validate window request and response measurements from complete model runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def spatial_elements(node):
    batch, ih, iw, channels = node['input_shapes'][0]
    _, oh, ow, _ = node['output_shapes'][0]
    options = node['options']
    kh, kw = options['kernel_h'], options['kernel_w']
    sh, sw = options['stride_h'], options['stride_w']
    dh, dw = options.get('dilation_h_factor', 1), options.get('dilation_w_factor', 1)
    ph = max(0, (oh - 1) * sh + (kh - 1) * dh + 1 - ih) // 2 if options['padding'] == 'SAME' else 0
    pw = max(0, (ow - 1) * sw + (kw - 1) * dw + 1 - iw) // 2 if options['padding'] == 'SAME' else 0
    rows = sum(0 <= y * sh + ky * dh - ph < ih for y in range(oh) for ky in range(kh))
    cols = sum(0 <= x * sw + kx * dw - pw < iw for x in range(ow) for kx in range(kw))
    taps = batch * rows * cols
    return taps * math.ceil(channels / 16), taps * channels


def aggregate(records):
    fields = ('requests', 'completions', 'response_beats', 'consecutive_responses',
              'request_response_overlap', 'requested_elements', 'response_elements',
              'return_span_cycles', 'npu_busy_cycles')
    result = {key: sum(row[key] for row in records) for key in fields}
    active = [row for row in records if row['requests']]
    result['records'] = len(records)
    result['active_records'] = len(active)
    result['minimum_peak_outstanding'] = min((row['peak_outstanding'] for row in active), default=0)
    result['maximum_peak_outstanding'] = max((row['peak_outstanding'] for row in active), default=0)
    result['all_active_jobs_overlap_requests'] = all(row['peak_outstanding'] >= 2 for row in active)
    result['all_active_jobs_overlap_request_response'] = all(
        row['request_response_overlap'] > 0 for row in active)
    eligible = sum(max(0, row['response_beats'] - 1) for row in records)
    result['consecutive_response_fraction'] = result['consecutive_responses'] / eligible if eligible else None
    span = result['return_span_cycles']
    result['mean_response_beats_per_span_cycle'] = result['response_beats'] / span if span else None
    result['mean_response_elements_per_span_cycle'] = result['response_elements'] / span if span else None
    if records and all('previous_npu_busy_cycles' in row for row in records):
        result['previous_npu_busy_cycles'] = sum(row['previous_npu_busy_cycles'] for row in records)
        result['busy_cycle_speedup'] = result['previous_npu_busy_cycles'] / result['npu_busy_cycles']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    base = args.measurements.resolve()
    build = read(base / 'sim/build.json')
    assert build['returncode'] == 0 and build['sources_unchanged_during_build']
    records, sources = [], []
    paths = sorted(base.glob('results/cases/*/*/trace_63/result.json'))
    assert len(paths) == 8
    for path in paths:
        result, case = read(path), read(path.with_name('case.json'))
        assert result['passed'] and all(result['checks'].values())
        assert result['simulator']['simulator_sha256'] == build['binary_sha256']
        manifest_path = Path(case['prepared_dir']) / 'manifest.json'
        assert sha(manifest_path) == case['prepared_sha256']
        nodes = {node['index']: node for node in read(manifest_path)['graph']['nodes']}
        layers = {row['index']: row for row in result['layers']}
        windows = result['simulator']['window_jobs']
        selected = {index for index, node in nodes.items() if node['op'] in (
            'DEPTHWISE_CONV_2D', 'MAX_POOL_2D', 'AVERAGE_POOL_2D')}
        assert {row['layer'] for row in windows} == selected and len(windows) == len(selected)
        previous_layers = {}
        if args.previous:
            previous_path = args.previous.resolve() / path.relative_to(base)
            previous = read(previous_path)
            assert previous['passed'] and previous['model']['sha256'] == result['model']['sha256']
            assert previous['input_sha256'] == result['input_sha256']
            assert previous['output_comparison']['actual_sha256'] == result['output_comparison']['actual_sha256']
            previous_layers = {row['index']: row for row in previous['layers']}
        sources.append({'model': result['model_id'], 'sample_index': result['sample_index'],
                        'path': str(path.relative_to(base)), 'sha256': sha(path)})
        for window in windows:
            index = window['layer']
            node, layer = nodes[index], layers[index]
            assert window['requests'] == window['completions']
            assert window['requested_elements'] == window['response_elements']
            expected_requests, expected_elements = spatial_elements(node)
            if node['op'] == 'DEPTHWISE_CONV_2D' or window['requests']:
                assert window['requests'] == expected_requests
                assert window['response_elements'] == expected_elements
            else:
                assert node['output_shapes'][0][1:3] == [1, 1]
            traces = [row for row in result['trace'] if row['descriptor']['operator_index'] == index]
            assert traces and all(row['passed'] and row['comparison']['passed'] for row in traces)
            row = {'model': result['model_id'], 'sample_index': result['sample_index'],
                   'layer_index': index, 'operator': node['op'],
                   'input_shape': node['input_shapes'][0], 'output_shape': node['output_shapes'][0],
                   **window, 'npu_busy_cycles': layer['npu_busy_cycles'],
                   'window_cache_hits': layer['window_cache_hits'],
                   'window_cache_misses': layer['window_cache_misses'],
                   'window_cache_read_bytes': layer['window_cache_read_bytes'],
                   'trace_output_exact': True}
            if previous_layers:
                row['previous_npu_busy_cycles'] = previous_layers[index]['npu_busy_cycles']
            records.append(row)
    depthwise = [row for row in records if row['operator'] == 'DEPTHWISE_CONV_2D']
    assert len(depthwise) == 34
    groups = []
    for model, index in sorted({(row['model'], row['layer_index']) for row in records}):
        group = [row for row in records if (row['model'], row['layer_index']) == (model, index)]
        assert len(group) == 2 and {row['sample_index'] for row in group} == {0, 1}
        groups.append({'model': model, 'layer_index': index, 'operator': group[0]['operator'],
                       'input_shape': group[0]['input_shape'], 'output_shape': group[0]['output_shape'],
                       **aggregate(group)})
    report = {
        'passed': True, 'simulator_sha256': build['binary_sha256'],
        'definitions': {
            'requests': 'Window descriptors accepted by ready/valid; count includes requests still awaiting a response.',
            'response_elements': 'Sum of valid INT16 lanes on accepted non-error response beats.',
            'return_span_cycles': 'Inclusive interval from the first accepted response beat to the last, per job.',
            'consecutive_response_fraction': 'Accepted response beats immediately following another accepted beat, divided by sum(max(beats-1,0)) across jobs.',
            'peak_outstanding': 'Maximum accepted descriptors without a consumed final response; limited to four.',
            'all_active_jobs_overlap_requests': 'Each active job reaches at least two accepted descriptors awaiting final responses.',
            'all_active_jobs_overlap_request_response': 'Each active job accepts a new request and a response in the same cycle at least once.',
            'expected_elements': 'Independent convolution geometry count excludes padded spatial positions.'},
        'source_results': sources, 'depthwise': aggregate(depthwise),
        'spatial': aggregate(records), 'layers': groups, 'records': records}
    output = base / 'window_pipeline.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    assert read(output) == report
    print(json.dumps({'passed': True, 'records': len(records), 'depthwise_records': len(depthwise),
                      'peak_outstanding': report['depthwise']['maximum_peak_outstanding'],
                      'output': str(output)}))


if __name__ == '__main__':
    main()
