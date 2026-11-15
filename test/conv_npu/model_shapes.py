#!/usr/bin/env python3
"""Run unscaled, extracted CNN Conv2D shapes on existing capacity RTL binaries.

Model geometry is real; inputs, filters, bias and quantization are deterministic
synthetic values. This is an operator-shape experiment, not whole-model accuracy.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "test/conv_models"))
from generate_vectors import (npu, generate_layers, layer_id, layer_slug, validate_layer,
                              make_tiling_oracle, plan_with_driver, prepare_case)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def verify_binary(build_root, capacity, destination, cache_policy=2):
    if capacity < 64 or capacity % 32 or (capacity // 32) & (capacity // 32 - 1):
        raise ValueError('capacity must be 32 times a power of two, with >=2 sets')
    profile = build_root / f'cache_{capacity}B'
    manifest_path = profile / 'build.json'
    manifest = json.loads(manifest_path.read_text())
    expected = {'size': 16, 'cache_sets': capacity // 32,
                'cache_ways': 2, 'cache_line_bytes': 16, 'cache_policy':cache_policy}
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f'{manifest_path}: {key} differs from {value}')
    if manifest.get('returncode') != 0 or not manifest.get('sources_unchanged_during_build'):
        raise RuntimeError(f'{manifest_path}: build did not complete with stable sources')
    command = manifest.get('command', [])
    for flag in ['-DTB_SIZE=16', f'-DTB_CONV_CACHE_SETS={capacity // 32}', f'-DTB_CONV_CACHE_POLICY={cache_policy}']:
        if flag not in command:
            raise RuntimeError(f'{manifest_path}: missing compilation flag {flag}')
    for name, digest in manifest['source_sha256'].items():
        if sha256(npu.ROOT / name) != digest:
            raise RuntimeError(f'stale binary source: {name}; rebuild the capacity profile')
    binary = profile / 'obj/Vtb_conv_npu'
    if not binary.is_file():
        raise RuntimeError(f'missing binary {binary}')
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, destination / 'build.json')
    record = {**expected, 'data_bytes': capacity, 'binary': str(binary),
              'binary_sha256': sha256(binary),
              'original_build_manifest': str(manifest_path),
              'original_build_manifest_sha256': sha256(manifest_path),
              'all_current_sources_match_build': True}
    write_json(destination / 'reuse.json', record)
    return binary, record


def check_histogram(path, metrics, input_base, input_bytes):
    total = unique = maximum = required = prefetched = covered = 0
    rows = 0
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            address = int(row['byte_address'], 16)
            if address != input_base + rows or int(row['allocation_offset']) != rows:
                raise AssertionError(f'input histogram omits/reorders a byte: {path}')
            count = int(row['axi_read_count'])
            need = int(row['required_by_window'])
            total += count
            unique += count > 0
            maximum = max(maximum, count)
            required += need
            covered += bool(need and count)
            prefetched += bool(not need and count)
            rows += 1
    expected = {'input_bytes': total, 'input_unique': unique,
                'input_duplicate': total - unique, 'input_max_reads': maximum,
                'input_required': required, 'input_prefetched_unused': prefetched}
    if rows != input_bytes or covered != required:
        raise AssertionError(f'incomplete spatial/channel coverage: {path}')
    for key, value in expected.items():
        if metrics[key] != value:
            raise AssertionError(f'{path}: independent histogram {key} differs')
    if metrics['padding_reads'] != 0:
        raise AssertionError('padding caused an external read')
    return {'histogram_sha256': sha256(path), 'allocated_bytes_enumerated': rows,
            'all_required_bytes_read': covered == required}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layers', nargs='+', help='exact layer IDs from the extracted catalogue')
    parser.add_argument('--binaries-root', type=Path, default=npu.ROOT / 'build/conv_capacity')
    parser.add_argument('--out', type=Path, default=npu.ROOT / 'build/conv_real_cnn')
    parser.add_argument('--capacities', type=int, nargs='+', default=[256, 512, 1024, 2048, 4096])
    parser.add_argument('--bypass', action='store_true', help='also execute every layer with raw-input cache bypass')
    parser.add_argument('--seed', type=int, default=20261115)
    parser.add_argument('--cache-policy', type=int, choices=[0, 1, 2], default=2)
    parser.add_argument('--tiling-policy', choices=['driver-auto', 'stress-w2'], default='driver-auto',
                        help='driver-auto calls the actual C planner with requested R/W=0/0')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    generated = generate_layers(out / 'vectors', args.layers, seed=args.seed,
                                tiling_policy=args.tiling_policy)
    catalogue_bytes = generated['catalogue_path'].read_bytes()
    layers = [metadata['model_layer'] for metadata in generated['layers']]
    selected_ids = [layer_id(layer) for layer in layers]
    capacities = sorted(set(args.capacities))
    if args.bypass and 4096 not in capacities:
        parser.error('--bypass uses the 4 KiB binary; include 4096 in --capacities')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'models_snapshot.json').write_bytes(catalogue_bytes)
    binaries = {}
    provenance = {}
    for capacity in capacities:
        binaries[capacity], provenance[str(capacity)] = verify_binary(
            args.binaries_root.resolve(), capacity, out / 'builds' / f'cache_{capacity}B', args.cache_policy)
    oracle_provenance = generated['tiling_oracle']
    reference_sources = [npu.HERE / 'reference_conv.c', npu.HERE / 'host_compat.h',
                         npu.ROOT / 'drivers/tflm/NMSIS/NN/Include/riscv_nnsupportfunctions.h']
    summary = {'scope': 'unscaled real CNN Conv2D layer geometry with synthetic numerical tensors',
               'not_run': ['whole model inference', 'trained-weight accuracy', 'depthwise convolution', 'IA-only alternative RTL'],
               'models_catalogue': str(generated['catalogue_path']),
               'models_catalogue_sha256': hashlib.sha256(catalogue_bytes).hexdigest(),
               'models_catalogue_snapshot': str(out / 'models_snapshot.json'),
               'selected_layer_ids': selected_ids, 'seed': args.seed,
               'tiling_policy': args.tiling_policy, 'tiling_oracle': oracle_provenance,
               'size': 16, 'cache_ways': 2, 'cache_line_bytes': 16, 'cache_policy':args.cache_policy,
               'input_base': 0x10000, 'filter_base': 0x20000,
               'bus': '32-bit AXI, same fixed response timing for every configuration',
               'binary_reuse': provenance,
               'reference_source_sha256': {str(p.relative_to(npu.ROOT)): sha256(p) for p in reference_sources},
               'runner_sha256': sha256(Path(__file__)), 'task_generator_sha256': sha256(npu.HERE / 'run.py'),
               'layers': [], 'rows': [], 'passed': False}
    write_json(out / 'selected_layers.json', layers)
    cases = []
    for metadata in generated['layers']:
        layer = metadata['model_layer']
        slug = metadata['layer_slug']
        task, bypass = generated['cases'][slug], generated['bypass_cases'][slug]
        summary['layers'].append(metadata)
        cases.append((layer, task, bypass, metadata))
    write_json(out / 'summary.json', summary)
    modes = [(capacity, False) for capacity in capacities]
    if args.bypass:
        modes.append((4096, True))
    for capacity, bypass_enabled in modes:
        mode = 'bypass' if bypass_enabled else f'cache_{capacity}B'
        profile = out / mode
        profile.mkdir(exist_ok=True)
        for layer, cached_case, bypass_case, metadata in cases:
            identity = layer_id(layer)
            slug = layer_slug(layer)
            record = npu.run_suite(binaries[capacity], profile, slug,
                                   [bypass_case if bypass_enabled else cached_case], no_random=True)
            if not record['passed'] or len(record['measurements']) != 1:
                summary['failure'] = {'mode': mode, 'layer_id': identity, **record}
                write_json(out / 'summary.json', summary)
                return 1
            metrics = record['measurements'][0]
            if metrics['error'] or metrics['write_bytes'] != metadata['tensors']['output']['bytes']:
                raise AssertionError('unexpected error or incomplete output write')
            histogram = profile / f'{slug}.suite.task0.input_reads.csv'
            verified = check_histogram(histogram, metrics, 0x10000, metadata['input_bytes'])
            summary['rows'].append({'layer_id': identity, 'model_id': layer['model_id'],
                                    'mode': mode, 'capacity_bytes': 0 if bypass_enabled else capacity,
                                    'physical_cache_bytes': capacity, 'passed': True,
                                    **metrics, **verified,
                                    'output_bytes': metadata['tensors']['output']['bytes'],
                                    'output_sha256': metadata['tensors']['output']['sha256'],
                                    'output_hash_kind': 'reference output, every byte matched by RTL memory comparison',
                                    'log': str(profile / f'{slug}.log'),
                                    'histogram': str(histogram)})
            write_json(out / 'summary.json', summary)
    # A single reference output per layer is shared by every executed profile.
    for identity in selected_ids:
        digests = {row['output_sha256'] for row in summary['rows'] if row['layer_id'] == identity}
        if len(digests) != 1:
            raise AssertionError('capacity comparison changed the layer output')
    summary['passed'] = True
    summary['rtl_commands'] = len(summary['rows'])
    write_json(out / 'summary.json', summary)
    fields = ['layer_id', 'model_id', 'mode', 'capacity_bytes', 'output_bytes',
              'input_required', 'input_bytes', 'input_unique', 'input_duplicate', 'input_max_reads',
              'input_prefetched_unused', 'padding_reads', 'misses', 'hits', 'cycles',
              'ar_bytes', 'ar_requests', 'write_bytes', 'output_sha256']
    with (out / 'real_cnn.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(summary['rows'])
    print('REAL_CNN_SHAPES_RTL_PASS', len(layers), 'layers', summary['rtl_commands'], 'commands', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
