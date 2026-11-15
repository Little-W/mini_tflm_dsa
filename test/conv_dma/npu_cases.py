#!/usr/bin/env python3
"""Bounded full-NPU checks for DMA-owned im2col, using raw input tensors."""
import argparse
import ctypes as ct
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('conv_npu_runner', ROOT/'test/conv_npu/run.py')
npu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(npu)
TILING_KEYS = ('ia_reuse', 'w_reuse', 'row_groups', 'row_tail_tiles', 'col_groups', 'col_tail_tiles')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def planner(out):
    libpath = out/'tiling_oracle.so'
    cmd = ['gcc', '-std=c11', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
           '-I', ROOT/'drivers', HERE/'tiling_oracle.c', '-o', libpath]
    if npu.command(cmd, out/'tiling_oracle_build.log'):
        raise RuntimeError((out/'tiling_oracle_build.log').read_text())
    library = ct.CDLL(str(libpath))
    library.conv_dma_plan.argtypes = [ct.c_uint32]*5+[ct.c_int]*2+[ct.POINTER(ct.c_uint32)]
    library.conv_dma_plan.restype = ct.c_int
    return library


def check_planner(case, lib):
    cfg = [int(v, 16) for v in (case/'config.mem').read_text().split()]
    meta = json.loads((case/'case.json').read_text())
    result = (ct.c_uint32*6)()
    accepted = lib.conv_dma_plan(cfg[3], cfg[5], cfg[1], meta['requested_r'],
                                meta['requested_w'], cfg[8], cfg[13], result)
    if not accepted:
        raise RuntimeError(f'production planner rejected {case}')
    actual = dict(zip(TILING_KEYS, result))
    if actual != meta['tiling']:
        raise RuntimeError(f'Python/C planner disagreement: {actual} != {meta["tiling"]}')
    meta['production_c_tiling'] = actual
    meta['production_planner_sha256'] = sha(ROOT/'drivers/gempact_tiling.h')
    meta['numerical_files_sha256'] = {name: sha(case/name)
                                    for name in ('init.mem', 'golden.mem', 'required.mem')}
    (case/'case.json').write_text(json.dumps(meta, indent=2)+'\n')


def prepare(out, size, ref, lib, smoke=False):
    """Every command runs in one simulation, with no intervening hardware reset."""
    common = dict(h=5, w=5, c=3, kh=3, kw=3, ph=1, pw=1, co=size+1,
                  requested_r=0, requested_w=0)
    def conv(name, **kwargs):
        case = npu.task(out, size, ref, name=name, **common, **kwargs)
        check_planner(case, lib)
        return case
    is_case = conv('is_raw_3x3_both_tails', dataflow=1, seed=1201, expect_once=True)
    if smoke:
        return [is_case]
    ws_case = conv('ws_raw_3x3_both_tails', dataflow=0, seed=1201, expect_once=True)
    # The mode changes scheduling only: both cases use the exact same tensors,
    # quantization, and independent C result, not merely equivalent random seeds.
    for name in ('init.mem', 'golden.mem', 'required.mem'):
        if sha(ws_case/name) != sha(is_case/name):
            raise RuntimeError(f'WS/IS numerical input changed: {name}')
    gemm = npu.gemm_task(out, size, name='interposed_gemm_is', dataflow=1)
    changed = conv('is_same_address_changed_input', dataflow=1, seed=1202,
                   mutate=True, expect_once=True)
    failed = conv('is_input_rresp_failure', dataflow=1, seed=1203, error=3, inject=True)
    recovered = conv('is_recovery_after_rresp', dataflow=1, seed=1204, expect_once=True)
    invalid = conv('is_invalid_geometry', dataflow=1, seed=1205, error=1)
    final_ws = conv('ws_recovery_after_is', dataflow=0, seed=1206, expect_once=True)
    return [ws_case, is_case, gemm, changed, failed, recovered, invalid, final_ws]


def current_binary(out, size, args):
    expected = {'size': size, 'cache_sets': args.cache_sets, 'cache_ways': 2,
                'cache_line_bytes': 16, 'cache_policy': args.cache_policy}
    if not args.skip_build:
        return npu.build(out, size, args.verilator, args.jobs,
                         cache_sets=args.cache_sets, cache_policy=args.cache_policy)
    existing = args.reuse_builds_root.resolve()/out.name if args.reuse_builds_root else out
    manifest = json.loads((existing/'build.json').read_text())
    if manifest.get('returncode') or not manifest.get('sources_unchanged_during_build'):
        raise RuntimeError(f'unsuccessful or unstable cached build: {existing}')
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError(f'executable parameters differ: {out}')
    for name, digest in manifest['source_sha256'].items():
        if sha(ROOT/name) != digest:
            raise RuntimeError(f'executable source differs: {name}')
    binary = existing/'obj/Vtb_conv_npu'
    if not binary.is_file(): raise RuntimeError(f'cached executable missing: {binary}')
    if existing != out:
        shutil.copy2(existing/'build.json',out/'build.json')
        (out/'binary_reuse.json').write_text(json.dumps({'source':str(existing), 'binary_sha256':sha(binary), 'compiled_source_hashes_match':True},indent=2)+'\n')
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/conv_dma/npu')
    parser.add_argument('--sizes', type=int, nargs='+', default=[4, 16])
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--cache-sets', type=int, default=32)
    parser.add_argument('--cache-policy', type=int, choices=(0, 1, 2), default=2)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='Only the first genuine IS Conv command')
    parser.add_argument('--reuse-builds-root', type=Path,
                        help='Optional compiled profiles; source hashes and elaboration parameters must match')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ref = npu.make_reference(out)
    lib = planner(out)
    summary = {'stage': 'dma_owned_im2col', 'scope': 'complete_npu_numeric_and_bus_contract',
               'sizes': args.sizes, 'prepared_only': args.prepare_only,
               'reference': 'direct scalar C convolution and original NMSIS requantization; raw NHWC and OHWI in memory',
               'tiling_oracle': 'unmodified drivers/gempact_tiling.h called through C',
               'suite_reset': 'one reset at process start; no reset between commands',
               'harness_sha256': {str(p.relative_to(ROOT)): sha(p) for p in
                   [Path(__file__), HERE/'tiling_oracle.c', ROOT/'drivers/gempact_tiling.h',
                    npu.HERE/'run.py', npu.HERE/'reference_conv.c', npu.HERE/'host_compat.h',
                    ROOT/'drivers/tflm/NMSIS/NN/Include/riscv_nnsupportfunctions.h']},
               'cases': []}
    for size in args.sizes:
        sd = out/f's{size}'
        sd.mkdir(exist_ok=True)
        cases = prepare(sd, size, ref, lib, args.smoke)
        if args.prepare_only:
            summary['cases'].append({'size': size, 'tasks': [str(p) for p in cases]})
        else:
            binary = current_binary(sd, size, args)
            result = npu.run_suite(binary, sd, 'dma_npu_modes', cases)
            result['size'] = size
            result['build_manifest_sha256'] = sha(sd/'build.json')
            summary['cases'].append(result)
            if not result['passed']:
                break
        (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    if not args.prepare_only:
        summary['passed'] = all(c['passed'] for c in summary['cases']) and len(summary['cases']) == len(args.sizes)
        summary['task_count'] = sum(len(c['measurements']) for c in summary['cases'])
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('DMA_NPU_PREPARED' if args.prepare_only else 'DMA_NPU_RESULT',
          summary.get('passed', True), flush=True)
    return 0 if summary.get('passed', True) else 1


if __name__ == '__main__':
    sys.exit(main())
