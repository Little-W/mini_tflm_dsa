#!/usr/bin/env python3
"""Compare real RTL cache policies using freshly generated full CNN layers."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('replacement_npu_runner', ROOT / 'test/conv_npu/run.py')
npu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npu)
from focus import FOCUS, line_events, simulate
from geometry_oracle import Geometry
from trace_model import generated_layers, generate_requests, lru


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def existing_binary(profile, policy, capacity):
    manifest = json.loads((profile / 'build.json').read_text())
    expected = {'size': 16, 'cache_sets': capacity // 32,
                'cache_ways': 2, 'cache_line_bytes': 16, 'cache_policy': policy}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RuntimeError('cached executable has different elaboration parameters')
    if not manifest['sources_unchanged_during_build'] or manifest['returncode']:
        raise RuntimeError('cached executable lacks successful stable-source build')
    for name, digest in manifest['source_sha256'].items():
        if sha256(ROOT / name) != digest:
            raise RuntimeError(f'stale executable: {name}; remove --skip-build')
    binary = profile / 'obj/Vtb_conv_npu'
    if not binary.is_file():
        raise RuntimeError(f'cached executable missing: {binary}')
    return binary


def check_byte_histogram(path, expected, layer):
    start = layer['tensors']['input']['address']
    count = layer['tensors']['input']['bytes']
    seen = set()
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            address = int(row['byte_address'], 16)
            if address in seen or not start <= address < start + count:
                raise AssertionError(('duplicate/out-of-allocation histogram byte', address))
            seen.add(address)
            actual = int(row['axi_read_count'])
            if actual != expected[address]:
                raise AssertionError(('RTL/model byte count mismatch', hex(address), actual, expected[address]))
    if len(seen) != count:
        raise AssertionError(('incomplete allocation histogram', len(seen), count))
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/conv_replacement/npu')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--profiles', nargs='+', default=['2:512', '2:1024', '2:2048', '1:1024', '0:1024'],
                        help='POLICY:DATA_BYTES; 0 LRU, 1 next-use low index, 2 next-use XOR')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--reuse-builds-root', type=Path,
                        help='Optional compiled profiles, verified against current sources and parameters')
    parser.add_argument('--layers', nargs='+', default=FOCUS)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if len(set(args.layers)) != len(args.layers):
        parser.error('duplicate layer ID')
    bundle = generated_layers(out / 'generated', args.layers, metadata_only=False)
    tasks = [(layer, Path(bundle['cases'][layer['layer_slug']])) for layer in bundle['layers']]
    summary = {'scope': 'Current RTL; complete CNN geometry, current production C auto tiling, deterministic synthetic tensors and scalar C golden',
               'runner_sha256': sha256(Path(__file__)), 'seed': 20261115,
               'selected_layers': args.layers, 'inputs_generated_on_this_run': True,
               'same_numerical_files_for_every_policy': True,
               'policy_names': {'0': 'legacy LRU low-index', '1': 'geometry next-use low-index',
                                '2': 'geometry next-use XOR-index'},
               'rows': [], 'profiles': [], 'passed': False}
    for specification in args.profiles:
        policy, capacity = map(int, specification.split(':'))
        sets = capacity // 32
        if policy not in [0, 1, 2] or sets < 2 or capacity % 32 or sets & (sets - 1):
            parser.error(f'invalid profile {specification}')
        profile = out / f'policy{policy}_{capacity}B'
        profile.mkdir(exist_ok=True)
        if args.skip_build:
            existing = args.reuse_builds_root.resolve() / profile.name if args.reuse_builds_root else profile
            binary = existing_binary(existing, policy, capacity)
            if existing != profile:
                shutil.copy2(existing / 'build.json', profile / 'build.json')
                if (existing / 'compile.log').exists():
                    shutil.copy2(existing / 'compile.log', profile / 'compile.log')
                write_json(profile / 'binary_reuse.json',
                           {'existing_profile': str(existing), 'binary': str(binary),
                            'binary_sha256': sha256(binary), 'parameters_and_recorded_sources_match': True})
        else:
            binary = npu.build(profile, 16, args.verilator, args.jobs,
                               cache_sets=sets, cache_policy=policy)
        summary['profiles'].append({'policy': policy, 'capacity_bytes': capacity,
                                    'build_manifest': str(profile / 'build.json'),
                                    'binary_sha256': sha256(binary)})
        for layer, task in tasks:
            record = npu.run_suite(binary, profile, layer['layer_slug'], [task], no_random=True)
            if not record['passed'] or len(record['measurements']) != 1:
                summary['failure'] = {'policy': policy, 'capacity_bytes': capacity,
                                      'layer_id': layer['layer_id'], **record}
                write_json(out / 'summary.json', summary)
                return 1
            metrics = record['measurements'][0]
            requests = generate_requests(layer)
            legacy, legacy_hist = lru(requests, layer, capacity)
            if policy == 0 or Geometry.from_layer(layer).unsupported_reasons():
                prediction = {'input_read_bytes': legacy['input_bytes']}
                histogram = legacy_hist
                expected_path = 'legacy LRU' if policy == 0 else 'geometry-ineligible fallback to LRU'
            else:
                prediction, histogram = simulate(line_events(requests), capacity,
                    'next_use_admission', 'xor' if policy == 2 else 'low', 2, return_histogram=True)
                expected_path = 'geometry next-use with current-line transient'
            model_equal = metrics['input_bytes'] == prediction['input_read_bytes']
            histogram_path = profile / (layer['layer_slug'] + '.suite.task0.input_reads.csv')
            checked_bytes = check_byte_histogram(histogram_path, histogram, layer)
            row = {'layer_id': layer['layer_id'], 'policy': policy, 'capacity_bytes': capacity,
                   'output_reference_sha256': layer['tensors']['output']['sha256'],
                   'complete_output_matched': True, **metrics,
                   'offline_line_model_input_bytes': prediction['input_read_bytes'],
                   'offline_line_model_equal': model_equal,
                   'every_input_byte_count_matched': True, 'histogram_bytes_checked': checked_bytes,
                   'expected_path_from_geometry': expected_path,
                   'model_transient_only_lines': prediction.get('transient_only_lines'),
                   'model_main_line_admissions': prediction.get('line_admissions'),
                   'model_lru_input_bytes': legacy['input_bytes'],
                   'log': str(profile / (layer['layer_slug'] + '.log'))}
            summary['rows'].append(row)
            write_json(out / 'summary.json', summary)
            if not model_equal:
                raise AssertionError(('real RTL bytes differ from model', row))
        if not args.skip_build:
            for path in (profile / 'obj').iterdir():
                if path.is_file() and path.name != 'Vtb_conv_npu':
                    path.unlink()
    summary['passed'] = True
    summary['rtl_commands'] = len(summary['rows'])
    write_json(out / 'summary.json', summary)
    with (out / 'rtl_compare.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary['rows'][0]))
        writer.writeheader()
        writer.writerows(summary['rows'])
    print('REPLACEMENT_RTL_PASS', summary['rtl_commands'], flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
