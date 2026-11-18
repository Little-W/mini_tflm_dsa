#!/usr/bin/env python3
"""Compare direct INT32 and compressed stores with identical full-NPU tests."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import sys


def load_runner(root, name):
    spec = importlib.util.spec_from_file_location(name, root/'test/conv_npu/run.py')
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def configure(npu, source, target, ia, r, w, cap, bank_count=9):
    target.mkdir(parents=True, exist_ok=True)
    cfg = [int(v, 16) for v in (source/'config.mem').read_text().split()]
    rows, cols = (cfg[5], cfg[3]) if cfg[8] else (cfg[3], cfg[5])
    rt, ct = math.ceil(rows/16), math.ceil(cols/16)
    cfg[6], cfg[7], cfg[62] = r, w, ia
    cfg[2],cfg[9]=2,4
    cfg[30] = math.ceil(rt/r) | (math.ceil(ct/w) << 16)
    cfg[31] = ((rt-1) % r+1) | (((ct-1) % w+1) << 16)
    live_rows=min(rows,16*r)
    needs_capacity_control=math.ceil(live_rows*cap/(bank_count-ia))*w>128
    cfg[61] = (16 if cap == 2 else 0) | (12 if (w & (w-1) or needs_capacity_control) else 0)
    (target/'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
    for name in ('init.mem', 'golden.mem', 'acc.mem', 'required.mem'):
        path = target/name
        if path.is_symlink():path.unlink()
        path.symlink_to((source/name).resolve())
    return dict(ia_banks=ia, r=r, w=w, word_cap=cap)


def candidates(rows, columns, cap, wide=False, bank_count=9):
    configurations = []
    for ia in (1, 2, 4):
        if wide and ia == 1:continue
        for r in (1, 2, 4, 8):
            if r > ia*(2 if wide else 4):continue
            for w in (1, 2, 3, 4):
                if w > math.ceil(columns/16):continue
                live_rows = min(rows, 16*r)
                banks = bank_count-ia
                if banks < cap:continue
                if math.ceil(live_rows*cap/banks) > 128:continue
                if live_rows*w > 1024:continue
                configurations.append((ia, r, w))
    return configurations


def make_input(npu, out, kind, flow):
    source = npu.precision_task(out, 16, name=f'{kind}_{flow}', rows=96,
        columns=96, reduction=256, lhs_s16=kind == 'wide', dataflow=flow,
        memory_bases=(0x1000, 0x14000, 0x24000, 0x30000, 0x25000, 0x26000))
    cfg = [int(v, 16) for v in (source/'config.mem').read_text().split()]
    image = npu.load_sparse(source/'init.mem')
    if kind in ('zero', 'small', 'outlier'):
        rng = random.Random(19231)
        for base, count in ((cfg[14], cfg[3]*cfg[4]), (cfg[15], cfg[5]*cfg[4])):
            values = [0 if kind == 'zero' else rng.randint(-2, 2) for _ in range(count)]
            if kind == 'outlier':
                for i in range(0, count, 97):values[i] = -128 if i % 2 else 127
            image[base:base+count] = bytes(v & 255 for v in values)
        image[cfg[16]:cfg[16]+4*cfg[5]] = bytes(4*cfg[5])
    accumulators = npu.gemm_accumulators(cfg, image)
    golden = bytearray(image)
    for i, value in enumerate(accumulators):
        col = i % cfg[5]
        mult = int.from_bytes(image[cfg[24]+4*col:cfg[24]+4*col+4], 'little', signed=True)
        shift = int.from_bytes(image[cfg[25]+4*col:cfg[25]+4*col+4], 'little', signed=True)
        result = max(-128, min(127, npu.cmsis_nn_requantize(value, mult, shift)+npu.signed32(cfg[23])))
        golden[cfg[17]+i] = result & 255
    npu.sparse_mem(source/'init.mem', image)
    npu.sparse_mem(source/'golden.mem', golden)
    npu.accumulator_mem(source/'acc.mem', accumulators)
    return source


def binary(npu, out, raw, jobs, reuse, bank_count=9):
    sim = out/'sim'
    if not reuse or not (sim/'build.json').is_file():
        return npu.build(sim, 16, 'verilator', jobs, ps_compress=True,
            pool_bytes=16384, force_raw=raw, bus_width=64, shared_bank_bytes=2048,
            shared_bank_count=bank_count, ps_frame_count=4)
    manifest = json.loads((sim/'build.json').read_text())
    assert manifest['ps_frame_count'] == 4 and manifest['force_raw'] == raw
    assert manifest['shared_bank_count'] == bank_count
    for name, digest in manifest['source_sha256'].items():
        assert hashlib.sha256((npu.ROOT/name).read_bytes()).hexdigest() == digest, name
    executable = sim/'obj/Vtb_conv_npu'
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == manifest['binary_sha256']
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-root', type=Path, required=True)
    parser.add_argument('--compressed-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--reuse-build', action='store_true')
    parser.add_argument('--raw-banks',type=int,choices=range(6,10),default=9)
    parser.add_argument('--compressed-banks',type=int,choices=range(6,10),default=9)
    parser.add_argument('--kinds', nargs='+', choices=('zero','small','outlier','random','wide'),
                        default=['zero','small','outlier','random','wide'])
    parser.add_argument('--flows', type=int, nargs='+', choices=(0,1), default=[0,1])
    args = parser.parse_args()
    out = args.out.resolve();out.mkdir(parents=True, exist_ok=True)
    adaptive = load_runner(args.compressed_root.resolve(), 'compressed_npu_test')
    raw = load_runner(args.raw_root.resolve(), 'raw_npu_test')
    runners = {'raw':raw, 'compressed':adaptive}
    bank_counts={'raw':args.raw_banks,'compressed':args.compressed_banks}
    executables = {name:binary(runner, out/name, name=='raw', args.jobs, args.reuse_build,bank_counts[name])
                   for name, runner in runners.items()}
    summary = dict(passed=True, shared_data_bytes=2048*args.raw_banks if args.raw_banks==args.compressed_banks else None, array=[16,16], bus_width=64,
                   ps_frame_count=4, directory_in_data_budget=False,
                   shared_data_bytes_by_implementation={name:2048*n for name,n in bank_counts.items()},
                   directory_bytes_by_implementation={'raw':0,'compressed':6144},
                   same_total_sram_capacity=2048*args.raw_banks==2048*args.compressed_banks+6144, datasets=[])
    for kind in args.kinds:
        for flow in args.flows:
            source = make_input(adaptive, out, kind, flow)
            cap = 2 if kind in ('zero','small') else (4 if kind=='wide' else 3)
            item = dict(kind=kind, dataflow=flow, m=96, n=96, k=256,
                        input_sha256=hashlib.sha256((source/'init.mem').read_bytes()).hexdigest(),
                        configurations={})
            for name, runner in runners.items():
                word_cap = 4 if name=='raw' else cap
                directory = out/name/f'{kind}_{flow}';directory.mkdir(parents=True, exist_ok=True)
                tasks, settings = [], []
                for ia, r, w in candidates(96,96,word_cap,kind=='wide' and flow==0,bank_counts[name]):
                    target = directory/f'b{ia}_r{r}_w{w}'
                    settings.append(configure(adaptive,source,target,ia,r,w,word_cap,bank_counts[name]))
                    tasks.append(target)
                result = runner.run_suite(executables[name], directory, 'search', tasks, True)
                summary['passed'] &= result['passed']
                records = [{**s, **m} for s,m in zip(settings,result['measurements'])]
                summary['passed'] &= all(r['ps_committed_rows']==8640 and
                    r['write_bytes']==9216 and r['int32_checks']==9216 for r in records)
                item['configurations'][name] = records
            if summary['passed']:
                for name, records in item['configurations'].items():
                    item[name+'_best'] = min(records,key=lambda x:x['cycles'])
                raw_best = item['raw_best']
                item['compressed_same_workspace'] = next((r for r in item['configurations']['compressed']
                    if all(r[k] == raw_best[k] for k in ('ia_banks','r','w'))),None)
            summary['datasets'].append(item)
            (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            if not summary['passed']:return 1
    print('PS_HARDWARE_COMPARISON_PASS',len(summary['datasets']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
