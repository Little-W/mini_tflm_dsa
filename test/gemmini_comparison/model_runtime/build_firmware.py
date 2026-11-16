#!/usr/bin/env python3
"""Build the Gemmini backend with the shared complete-model TFLM firmware."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from vendor import digest, stage_vendor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NETWORK = ROOT / 'test/model_benchmark'


def load_network_builder():
    spec = importlib.util.spec_from_file_location('gemmini_shared_network_builder', NETWORK / 'build_firmware.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_firmware(out, gcc, software, params, *, trace=False, runtime_root=None,
                   jobs=1, object_cache=None, arena_bytes=512 * 1024, conv_policy='auto'):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    vendor_dir = out / 'vendor'
    vendor = stage_vendor(vendor_dir, software, params, ('auto','native','im2col').index(conv_policy))
    before = {str(path.relative_to(ROOT)): digest(path) for path in
              (Path(__file__), HERE / 'vendor.py')}
    shared = load_network_builder()
    original_sources = shared.sources()
    replacements = {str(shared.TFLM / 'tensorflow/lite/micro/kernels/nmsis_nn' / name): HERE / name
                    for name in ('conv.cc', 'depthwise_conv.cc', 'fully_connected.cc')}
    shared.sources = lambda: [replacements.get(str(path), path) for path in original_sources] + [HERE / 'backend.cc']
    # CPATH supplies the staged scheduler only to this build. The cache is
    # partitioned by all vendor headers, and dependency hashes verify reuse.
    cache_identity = hashlib.sha256(json.dumps(vendor, sort_keys=True).encode()).hexdigest()[:16]
    cache = Path(object_cache or out.parent / 'firmware_objects') / cache_identity
    previous_cpath = os.environ.get('CPATH')
    os.environ['CPATH'] = str(vendor_dir) + os.pathsep + str(HERE)
    if previous_cpath:
        os.environ['CPATH'] += os.pathsep + previous_cpath
    build_cpath = os.environ['CPATH']
    try:
        manifest = shared.build_firmware(out, gcc, hardware=False, trace=trace,
            runtime_root=runtime_root, jobs=jobs, object_cache=cache, arena_bytes=arena_bytes)
    finally:
        if previous_cpath is None:
            os.environ.pop('CPATH', None)
        else:
            os.environ['CPATH'] = previous_cpath
    stable = all(digest(ROOT / path) == value for path, value in before.items())
    manifest['passed'] &= stable
    manifest['sources_unchanged_during_build'] &= stable
    manifest['source_sha256'].update(before)
    revision = subprocess.check_output(['git', '-C', str(software), 'rev-parse', 'HEAD'], text=True).strip()
    manifest.update(profile='gemmini_dwconv', hardware=True,
        supported_modes=[0, shared.abi_constant('MODE_CONV_FC'), shared.abi_constant('MODE_HARDWARE')],
        prepared_dispatch=True, direct_pointwise=True, softmax_s8=False,
        backend='fixed third-party DWConv Gemmini; full INT32 readback and Pico Q31 nearest-even requantization',
        gemmini_vendor=vendor, gemmini_software_revision=revision,
        convolution_policy=conv_policy,
        gemmini_host_transport={'base':0x50000000, 'command_width_bits':64,
            'submit_offset':0x14, 'fence_offset':0x18, 'reset_offset':0x28},
        environment={'CPATH':build_cpath},
        accelerated_operators=['CONV_2D', 'DEPTHWISE_CONV_2D', 'FULLY_CONNECTED'],
        software_operators=['MAX_POOL_2D', 'AVERAGE_POOL_2D', 'ADD', 'SOFTMAX', 'RESHAPE'],
        dispatch='TFLM registration wrappers retain NMSIS Prepare and software fallback; accelerator mask controls Gemmini execution',
        numerical_semantics='Raw signed INT8 MAC plus INT32 bias; valid-tap input zero point correction, per-channel Q31 RNE, output zero point and activation clamp on Pico')
    shared.write_json(out / 'firmware.json', manifest)
    if not manifest['passed']:
        raise RuntimeError('A backend source changed during the firmware build')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gcc', default='riscv64-unknown-elf-gcc')
    parser.add_argument('--software', type=Path, required=True)
    parser.add_argument('--params', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--object-cache', type=Path)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--arena-bytes', type=int, default=512 * 1024)
    parser.add_argument('--trace', action='store_true')
    parser.add_argument('--conv-policy', choices=['auto','native','im2col'], default='auto')
    args = parser.parse_args()
    result = build_firmware(args.out, args.gcc, args.software, args.params,
        trace=args.trace, runtime_root=args.runtime_root, jobs=args.jobs,
        object_cache=args.object_cache, arena_bytes=args.arena_bytes, conv_policy=args.conv_policy)
    print(json.dumps({'passed':result['passed'], 'elf':result['elf'],
                      'profile':result['profile'], 'trace':result['trace_enabled']}))


if __name__ == '__main__':
    main()
