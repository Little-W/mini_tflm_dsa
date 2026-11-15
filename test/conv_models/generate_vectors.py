#!/usr/bin/env python3
"""Generate deterministic real-model Conv vectors from source TFLite files.

The public API returns model/tiling metadata and newly generated case paths.
No historical catalogue, tensor binary, memory image or test result is an input.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_SEED = 20261115


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


npu = _module("conv_vector_npu_backend", ROOT / "test/conv_npu/run.py")
extractor = _module("conv_vector_model_extractor", HERE / "extract_shapes.py")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")

def make_tiling_oracle(out):
    source = npu.ROOT / 'test/conv_models/driver_tiling_oracle.c'
    header = npu.ROOT / 'drivers/gempact_tiling.h'
    binary = out / 'driver_tiling_oracle'
    command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-I', npu.ROOT / 'drivers', source, '-o', binary]
    if npu.command(command, out / 'tiling_oracle_build.log'):
        raise RuntimeError((out / 'tiling_oracle_build.log').read_text())
    provenance = {'source': str(source.relative_to(npu.ROOT)),
                  'source_sha256': sha256(source),
                  'header': str(header.relative_to(npu.ROOT)),
                  'header_sha256': sha256(header), 'binary_sha256': sha256(binary),
                  'size': 16, 'ia_cache_blocks': 4, 'ps_frame_count': 16,
                  'is_mode': 0, 'per_channel': 1, 'pool_bytes': 0}
    return binary, provenance


def plan_with_driver(oracle, rows, columns, policy):
    requested = 0 if policy == 'driver-auto' else 2
    process = subprocess.run([str(oracle)],
                             input=f'{rows} {columns} {requested} {requested}\n',
                             text=True, capture_output=True, check=True)
    values = [int(word) for word in process.stdout.split()]
    keys = ['ia_reuse', 'w_reuse', 'row_groups', 'row_tail_tiles',
            'col_groups', 'col_tail_tiles']
    if len(values) != len(keys):
        raise ValueError(f'unexpected C tiling oracle output: {process.stdout!r}')
    return dict(zip(keys, values))


def layer_id(layer):
    return layer.get('layer_id', layer.get('id'))


def layer_slug(layer):
    identity = layer_id(layer)
    if not identity:
        raise ValueError('missing layer ID')
    slug = identity.replace(':', '_')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in slug):
        raise ValueError(f'layer ID cannot form a safe filename: {identity!r}')
    return slug


def validate_layer(layer):
    """All four spatial paddings and the recorded output shape must agree."""
    if layer.get('operator') != 'CONV_2D' or not layer.get('regular_int8'):
        raise ValueError('only verified regular INT8 CONV_2D layers are selected')
    batch, height, width, channels = layer['input_shape']
    out_channels, kernel_h, kernel_w, filter_channels = layer['filter_shape']
    out_batch, output_h, output_w, output_channels = layer['output_shape']
    stride_h, stride_w = layer['stride_hw']
    dilation_h, dilation_w = layer['dilation_hw']
    pad = layer['padding']
    if batch != 1 or out_batch != 1:
        raise ValueError('this selected profile requires the original model batch=1')
    if channels != filter_channels or out_channels != output_channels:
        raise ValueError('selected layer must be regular ungrouped OHWI Conv2D')
    if min(height, width, channels, kernel_h, kernel_w, output_h, output_w,
           out_channels, stride_h, stride_w, dilation_h, dilation_w) <= 0:
        raise ValueError('non-positive geometry')
    expected_h = (height + pad['top'] + pad['bottom'] -
                  dilation_h * (kernel_h - 1) - 1) // stride_h + 1
    expected_w = (width + pad['left'] + pad['right'] -
                  dilation_w * (kernel_w - 1) - 1) // stride_w + 1
    if (output_h, output_w) != (expected_h, expected_w):
        raise ValueError('recorded TFLite output shape disagrees with exact padding')
    input_bytes = height * width * channels
    filter_bytes = out_channels * kernel_h * kernel_w * channels
    output_bytes = output_h * output_w * out_channels
    # The unchanged monitor indexes input bytes in this fixed 64 KiB arena.
    # Filter and parameter arenas are disjoint. Output has the rest of 512 KiB.
    if input_bytes > 0x10000 or filter_bytes > 0x10000:
        raise ValueError('input/filter exceeds an unchanged 64 KiB test arena')
    if out_channels * 4 > 0x1000 or output_bytes > npu.WORDS * 4 - 0x40003:
        raise ValueError('parameters/output exceed their unchanged test arenas')
    model = npu.ROOT / layer['model_path']
    if sha256(model) != layer['model_sha256']:
        raise ValueError(f'model source changed: {model}')
    return dict(h=height, w=width, c=channels, kh=kernel_h, kw=kernel_w,
                oh=output_h, ow=output_w, co=out_channels,
                sh=stride_h, sw=stride_w, dh=dilation_h, dw=dilation_w,
                ph=pad['top'], pw=pad['left'])


def prepare_case(out, ref, layer, seed, oracle, policy):
    geometry = validate_layer(layer)
    identity = layer_id(layer)
    slug = layer_slug(layer)
    task = npu.task(out, 16, ref, name=slug, seed=seed,
                    input_base=0x10000, rhs_base=0x20000, **geometry)
    cfg = [int(word, 16) for word in (task / 'config.mem').read_text().split()]
    old_cfg = cfg.copy()
    tiling = plan_with_driver(oracle, cfg[3], cfg[5], policy)
    cfg[6] = tiling['ia_reuse']
    cfg[7] = tiling['w_reuse']
    cfg[30] = tiling['row_groups'] | (tiling['col_groups'] << 16)
    cfg[31] = tiling['row_tail_tiles'] | (tiling['col_tail_tiles'] << 16)
    changed = [index for index, (old, new) in enumerate(zip(old_cfg, cfg)) if old != new]
    if not set(changed).issubset({6, 7, 30, 31}):
        raise AssertionError('tiling change modified unrelated descriptor fields')
    (task / 'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
    image = npu.load_sparse(task / 'init.mem')
    golden = npu.load_sparse(task / 'golden.mem')
    tensor_lengths = {'input': geometry['h'] * geometry['w'] * geometry['c'],
                      'filter': geometry['co'] * geometry['kh'] * geometry['kw'] * geometry['c'],
                      'bias': 4 * geometry['co'], 'multiplier': 4 * geometry['co'],
                      'shift': 4 * geometry['co'], 'output': cfg[3] * cfg[5]}
    bases = {'input': cfg[33], 'filter': cfg[15], 'bias': cfg[16],
             'multiplier': cfg[24], 'shift': cfg[25], 'output': cfg[17]}
    tensors = {}
    for name, length in tensor_lengths.items():
        base = bases[name]
        value = bytes((golden if name == 'output' else image)[base:base + length])
        path = task / f'{name}.bin'
        path.write_bytes(value)
        tensors[name] = {'address': base, 'end_exclusive': base + length,
                         'bytes': length, 'sha256': sha256(path)}
    ranges = sorted((v['address'], v['end_exclusive'], k) for k, v in tensors.items())
    for first, second in zip(ranges, ranges[1:]):
        if first[1] > second[0]:
            raise ValueError(f'tensor ranges overlap: {first[2]} and {second[2]}')
    metadata = json.loads((task / 'case.json').read_text())
    metadata.update(layer_id=identity, layer_slug=slug, model_layer=layer, tensors=tensors,
                    tiling=tiling, tiling_policy=policy,
                    requested_r=0 if policy == 'driver-auto' else 2,
                    requested_w=0 if policy == 'driver-auto' else 2,
                    descriptor_words_changed_from_stress_w2=changed,
                    geometry_source='original local TFLite, no dimension reduction',
                    numerical_source='deterministic synthetic values; not trained model weights or original quantization',
                    output_check='every output byte and all memory checked by unchanged RTL testbench against direct C + NMSIS reference')
    write_json(task / 'case.json', metadata)
    # Both modes share the exact memory/golden/required files. Only the cache
    # bypass field changes; the source geometry and data remain identical.
    bypass = out / (slug + '_bypass')
    bypass.mkdir(exist_ok=True)
    for name in ['init.mem', 'golden.mem', 'required.mem']:
        target = bypass / name
        if target.exists():
            target.unlink()
        target.symlink_to(task / name)
    bypass_cfg = cfg.copy()
    bypass_cfg[50] = 1
    (bypass / 'config.mem').write_text(''.join(f'{v:08x}\n' for v in bypass_cfg))
    write_json(bypass / 'case.json', {**metadata, 'bypass': True})
    return task, bypass, metadata


def metadata_only_layer(layer, seed, oracle, policy):
    """Scheduling/geometry only; a missing output hash is never a numeric pass."""
    g = validate_layer(layer)
    h, w, c, co = g['h'], g['w'], g['c'], g['co']
    kh, kw, oh, ow = g['kh'], g['kw'], g['oh'], g['ow']
    parameters = [h, w, c, c, 0, kh, kw, oh, ow, co, g['sh'], g['sw'],
                  g['dh'], g['dw'], g['ph'], g['pw'], -7, -3, -117, 109]
    pixels = set()
    logical = padding = 0
    for y in range(oh):
        for x in range(ow):
            for ky in range(kh):
                for kx in range(kw):
                    iy, ix = y * g['sh'] + ky * g['dh'] - g['ph'], x * g['sw'] + kx * g['dw'] - g['pw']
                    if 0 <= iy < h and 0 <= ix < w:
                        pixels.add(iy * w + ix)
                        logical += c
                    else:
                        padding += c
    lengths = {'input': h*w*c, 'filter': co*kh*kw*c, 'bias': 4*co,
               'multiplier': 4*co, 'shift': 4*co, 'output': oh*ow*co}
    bases = {'input': 0x10000, 'filter': 0x20000, 'bias': 0x30000,
             'multiplier': 0x31000, 'shift': 0x32000, 'output': 0x40003}
    return {'name': layer_slug(layer), 'layer_id': layer_id(layer), 'layer_slug': layer_slug(layer),
            'size': 16, 'parameters': parameters, 'seed': seed, 'model_layer': layer,
            'tiling': plan_with_driver(oracle, oh*ow, co, policy), 'tiling_policy': policy,
            'tensors': {name: {'address': bases[name], 'end_exclusive': bases[name]+length,
                               'bytes': length, 'sha256': None} for name, length in lengths.items()},
            'per_channel': True, 'bypass': False, 'expected_error': 0, 'outputs': oh*ow*co,
            'input_base': 0x10000, 'input_bytes': h*w*c, 'weight_bytes': co*kh*kw*c,
            'dst_stride': co, 'required_unique_input_bytes': len(pixels)*c,
            'logical_input_uses_per_output_channel': logical, 'padding_zeros_per_output_channel': padding,
            'dataflow': 'WS', 'requested_r': 0 if policy == 'driver-auto' else 2,
            'requested_w': 0 if policy == 'driver-auto' else 2,
            'numeric_vectors_generated': False, 'case_dir': None,
            'verification_level': 'geometry and real C tiling only; no output reference or RTL execution'}


def generate_layers(out, selected=None, *, seed=DEFAULT_SEED,
                    tiling_policy='driver-auto', metadata_only=False, ref=None):
    """Return layers, cached/bypass case Paths and a freshly extracted catalogue.

    selected accepts exact layer IDs or safe slugs. Every layer uses the same
    historical seed, independent of selection order/subset. out may be external.
    """
    if tiling_policy not in ('driver-auto', 'stress-w2'):
        raise ValueError('unknown tiling policy')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    catalogue = extractor.extract_catalogue()
    catalogue_path = out / 'models.json'
    write_json(catalogue_path, catalogue)
    aliases = {}
    for layer in catalogue['layers']:
        for name in (layer_id(layer), layer_slug(layer)):
            if name in aliases:
                raise ValueError('model layer identifier collision')
            aliases[name] = layer
    names = list(selected) if selected is not None else catalogue['recommended_layer_ids']
    layers = [aliases[name] for name in names]
    if len({layer_id(layer) for layer in layers}) != len(layers):
        raise ValueError('duplicate selected layer')
    for layer in layers:
        validate_layer(layer)
    oracle, oracle_provenance = make_tiling_oracle(out)
    if not metadata_only and ref is None:
        ref = npu.make_reference(out)
    result = {'layers': [], 'cases': {}, 'bypass_cases': {}, 'catalogue_path': catalogue_path,
              'tiling_oracle': oracle_provenance, 'seed': seed,
              'metadata_only': metadata_only, 'tiling_policy': tiling_policy}
    for layer in layers:
        slug = layer_slug(layer)
        if metadata_only:
            metadata = metadata_only_layer(layer, seed, oracle, tiling_policy)
        else:
            case, bypass, metadata = prepare_case(out / 'cases', ref, layer, seed, oracle, tiling_policy)
            metadata.update(case_dir=str(case), bypass_case_dir=str(bypass), numeric_vectors_generated=True)
            write_json(case / 'case.json', metadata)
            write_json(bypass / 'case.json', {**metadata, 'bypass': True})
            result['cases'][slug], result['bypass_cases'][slug] = case, bypass
        result['layers'].append(metadata)
    sources = [Path(__file__).resolve(), HERE/'extract_shapes.py', HERE/'driver_tiling_oracle.c',
               npu.HERE/'run.py', npu.HERE/'reference_conv.c', npu.HERE/'host_compat.h',
               ROOT/'drivers/gempact_tiling.h',
               ROOT/'drivers/tflm/NMSIS/NN/Include/riscv_nnsupportfunctions.h']
    manifest = {**result, 'cases': {k: str(v) for k,v in result['cases'].items()},
                'bypass_cases': {k: str(v) for k,v in result['bypass_cases'].items()},
                'catalogue_path': str(catalogue_path),
                'generation_source_sha256': {str(p.relative_to(ROOT)): sha256(p) for p in sources},
                'data_policy': 'Real original model dimensions; deterministic synthetic inputs, filters, bias and quantization; direct C plus repository NMSIS requantization golden.'}
    write_json(out/'manifest.json', manifest)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'build/conv_models/vectors')
    ap.add_argument('--layers', nargs='+')
    ap.add_argument('--seed', type=int, default=DEFAULT_SEED)
    ap.add_argument('--tiling-policy', choices=['driver-auto','stress-w2'], default='driver-auto')
    ap.add_argument('--metadata-only', action='store_true')
    args = ap.parse_args()
    result = generate_layers(args.out, args.layers, seed=args.seed,
                             tiling_policy=args.tiling_policy, metadata_only=args.metadata_only)
    print(json.dumps({'layers': len(result['layers']), 'numeric_cases': len(result['cases']),
                      'out': str(args.out.resolve()), 'seed': args.seed}))


if __name__ == '__main__':
    main()


