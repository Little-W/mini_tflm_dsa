#!/usr/bin/env python3
"""Verify native Gemmini Conv/DW/FC with the trained models' real tensors."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from vendor import digest, stage_vendor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NETWORK = ROOT / 'test/model_benchmark'
sys.path.insert(0, str(NETWORK))
sys.path.insert(0, str(HERE.parent / 'gemmini_dw_rtl'))
import memory_service
from model_data import MODELS, validate_model
from verify_integer_graph import load_schema, limits


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def build_generator(out, software, params, compiler, conv_policy):
    vendor = stage_vendor(out / 'vendor', software, params, ('auto','native','im2col').index(conv_policy))
    binary = out / 'trace_backend'
    command = [compiler, '-std=gnu++17', '-O2', '-fwrapv', '-DGEMMINI_HOST_COMMANDS',
        '-I' + str(HERE), '-I' + str(out / 'vendor'),
        str(HERE / 'backend.cc'), str(HERE / 'trace_backend.cc'), '-o', str(binary)]
    result = subprocess.run(command, text=True, capture_output=True)
    (out / 'compile.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    record = dict(vendor=vendor, command=command, binary_sha256=digest(binary),
        source_sha256={str(path.relative_to(ROOT)):digest(path) for path in
            (HERE / 'backend.cc', HERE / 'backend.h', HERE / 'trace_backend.cc',
             HERE / 'mmio.h', HERE / 'im2col.h')})
    write_json(out / 'generator.json', record)
    return binary, record


def generate(model_dir, output, generator, sample_index):
    validate_model(model_dir)
    manifest = json.loads((model_dir / 'manifest.json').read_text())
    sample = next(value for value in manifest['samples'] if value['sample_index'] == sample_index)
    schema = load_schema()
    model = schema.Model.GetRootAsModel((model_dir / 'model.tflite').read_bytes(), 0)
    graph = model.Subgraphs(0)
    metadata = {value['index']:value for value in manifest['graph']['tensors']}
    tensors = {sample['input']['tensor_index']:(model_dir / sample['input']['path']).read_bytes()}
    for value in sample['nodes']:
        tensors[value['tensor_index']] = (model_dir / value['path']).read_bytes()
    for index in metadata:
        buffer = model.Buffers(graph.Tensors(index).Buffer())
        if buffer.DataLength():
            tensors[index] = buffer.DataAsNumpy().tobytes()
    reports = []
    for node, expected in zip(manifest['graph']['nodes'], sample['nodes']):
        if node['op'] not in ('CONV_2D', 'DEPTHWISE_CONV_2D', 'FULLY_CONNECTED'):
            continue
        directory = output / manifest['name'] / f'node_{node["index"]:03d}'
        directory.mkdir(parents=True, exist_ok=True)
        source, weights = node['inputs'][:2]
        target = node['outputs'][0]
        options = node['options']
        oc = metadata[target]['shape'][-1]
        if node['op'] == 'FULLY_CONNECTED':
            kind = 'fc'
            ih = oh = 1
            iw = ow = int(np.prod(metadata[target]['shape']) // oc)
            ic = metadata[weights]['shape'][-1]
            kh = kw = sh = sw = 1
            ph = pw = 0
        else:
            kind = 'dw' if node['op'] == 'DEPTHWISE_CONV_2D' else 'conv'
            _, ih, iw, ic = metadata[source]['shape']
            _, oh, ow, _ = metadata[target]['shape']
            kh, kw = options['kernel_h'], options['kernel_w']
            sh, sw = options['stride_h'], options['stride_w']
            ph = max(0, (oh - 1) * sh + kh - ih) // 2 if options['padding'] == 'SAME' else 0
            pw = max(0, (ow - 1) * sw + kw - iw) // 2 if options['padding'] == 'SAME' else 0
        amin, amax = limits(metadata[target], options.get('fused_activation_function', 'NONE'))
        parameters = expected['integer_parameters']
        multipliers, shifts = parameters['multipliers'], parameters['shifts']
        if len(multipliers) == 1:
            multipliers, shifts = multipliers * oc, shifts * oc
        payloads = dict(input=tensors[source], weights=tensors[weights],
            bias=tensors[node['inputs'][2]] if len(node['inputs']) > 2 and node['inputs'][2] >= 0 else bytes(oc * 4),
            multipliers=np.asarray(multipliers, dtype='<i4').tobytes(),
            shifts=np.asarray(shifts, dtype='<i4').tobytes())
        for name, raw in payloads.items():
            (directory / (name + '.bin')).write_bytes(raw)
        command = [str(generator), str(directory), kind,
            *map(str, (ih, iw, ic, oh, ow, oc, kh, kw, sh, sw, ph, pw)),
            *[str(directory / (name + '.bin')) for name in payloads],
            str(-metadata[source]['zero_points'][0]), str(metadata[target]['zero_points'][0]),
            str(amin), str(amax), '0', '0']
        environment = os.environ.copy()
        process = subprocess.run(command, env=environment, text=True, capture_output=True)
        (directory / 'generate.log').write_text(process.stdout + process.stderr)
        if process.returncode:
            raise RuntimeError(str(directory) + '\n' + process.stderr)
        quantized = (directory / 'expected_int8.bin').read_bytes()
        golden = (model_dir / expected['path']).read_bytes()
        if quantized != golden:
            differences = sum(a != b for a, b in zip(quantized, golden)) + abs(len(quantized) - len(golden))
            raise RuntimeError(f'Q31 output differs from prepared tensor: {directory}, {differences} elements')
        case = json.loads((directory / 'case.json').read_text())
        record = dict(model_id=manifest['name'], sample_index=sample_index, layer_index=node['index'],
            operation=node['op'], input_shapes=node['input_shapes'], output_shapes=node['output_shapes'],
            options=options, model_sha256=manifest['model']['sha256'],
            input_sha256=digest(directory / 'input.bin'), expected_output_sha256=expected['sha256'],
            input_zero_point=metadata[source]['zero_points'][0],
            output_zero_point=metadata[target]['zero_points'][0],
            per_channel_multipliers=multipliers, per_channel_shifts=shifts,
            software_quantization_matches_prepared=True, case=case, directory=str(directory),
            command=command, payload_sha256={name:digest(directory / (name + '.bin')) for name in payloads},
            raw_reference_sha256=digest(directory / 'expected.bin'),
            command_sha256=digest(directory / 'commands.txt'),
            execution='independent hardware im2col' if case['independent_im2col'] else
                'optimized depthwise loop' if kind == 'dw' else
                'weight-stationary GEMM' if kind == 'fc' or (kh == kw == sh == sw == 1) else
                'native convolution loop')
        write_json(directory / 'layer.json', record)
        reports.append(record)
    return reports


def simulate(binary, record, service):
    directory = Path(record['directory'])
    case = record['case']
    command = [str(binary), str(directory / 'memory.bin'), str(case['memory_base']),
        str(directory / 'commands.txt'), str(case['output_base']), str(case['output_bytes']),
        str(directory / 'expected.bin'), str(case['timed_start']), str(directory / 'rtl_result.json'),
        *memory_service.simulator_arguments(service)]
    with (directory / 'rtl.log').open('w') as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    result = json.loads((directory / 'rtl_result.json').read_text()) if (directory / 'rtl_result.json').exists() else {}
    if process.returncode == 0 and result.get('passed', False):
        memory_service.validate_result(result, service)
    value = dict(record, passed=process.returncode == 0 and result.get('passed', False),
        simulator=dict(result, returncode=process.returncode, command=command, binary_sha256=digest(binary)),
        measurement='accelerator command injection, signed INT8 MAC plus INT32 bias and full accumulator output; CPU requantization excluded')
    write_json(directory / 'result.json', value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--software', type=Path, required=True)
    parser.add_argument('--params', type=Path, required=True)
    parser.add_argument('--simulator', type=Path)
    parser.add_argument('--build-manifest', type=Path)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--models', choices=MODELS, nargs='+', default=list(MODELS))
    parser.add_argument('--sample', type=int, default=0)
    parser.add_argument('--jobs', type=int, default=4)
    memory_service.add_arguments(parser)
    parser.add_argument('--conv-policy', choices=['auto','native','im2col'], default='auto')
    args = parser.parse_args()
    hardware = None
    if args.build_manifest:
        hardware = json.loads(args.build_manifest.read_text())
        if digest(args.params) != hardware['params_header_sha256']:
            raise ValueError('Command parameters differ from the generated hardware header')
        if args.simulator and digest(args.simulator) != hardware['simulator_sha256']:
            raise ValueError('Simulator differs from its build manifest')
    selected_memory = memory_service.configuration(hardware['memory_service'] if hardware else {
        'first_read_latency_cycles': 3, 'read_beat_interval_cycles': 2,
        'inter_burst_read_gap_cycles': 3}, args)
    args.out.mkdir(parents=True, exist_ok=True)
    generator, build = build_generator(args.out / 'generator', args.software, args.params, args.compiler, args.conv_policy)
    cases = []
    for model in args.models:
        cases += generate(args.prepared / model, args.out, generator, args.sample)
    reports = []
    if args.simulator:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for future in as_completed([pool.submit(simulate, args.simulator, case, selected_memory) for case in cases]):
                value = future.result()
                reports.append(value)
                print(json.dumps(dict(model_id=value['model_id'], layer=value['layer_index'],
                    operation=value['operation'], passed=value['passed'],
                    cycles=value['simulator'].get('cycles'))), flush=True)
        reports.sort(key=lambda value:(value['model_id'], value['layer_index']))
    summary = dict(passed=bool(cases) and (not args.simulator or all(value['passed'] for value in reports)),
        generator=build, cases=reports or cases, layer_count=len(cases),
        all_quantized_references_match_prepared=True, rtl_executed=bool(args.simulator),
        memory_service=selected_memory, runner_sha256=digest(Path(__file__)),
        memory_service_source_sha256=digest(Path(memory_service.__file__)))
    if args.build_manifest:
        summary['build_manifest'] = str(args.build_manifest.resolve())
        summary['build_manifest_sha256'] = digest(args.build_manifest)
    write_json(args.out / 'summary.json', summary)
    raise SystemExit(0 if summary['passed'] else 1)


if __name__ == '__main__':
    main()
