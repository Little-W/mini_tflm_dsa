#!/usr/bin/env python3
"""执行完整生产 NPU 回归，并验证每个帧地址及十二周期准备间隔。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def packed_cases(out: Path, manifest: dict) -> list[Path]:
    sys.path.insert(0, str(ROOT / 'test/ps_compression'))
    from run_shared_npu import configure, input_bank_count, npu
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for mode in (0, 1):
        for wide in (False, True):
            for layout in (1, 2, 3):
                name = f'packed_{layout}_mode{mode}_s16{int(wide)}'
                directory = npu.precision_task(out, 16, name=name, rows=33, reduction=35, columns=51,
                    dataflow=mode, lhs_s16=wide,
                    memory_bases=(0x1003,0x20003,0x40000,0x58000,0x48000,0x50000))
                banks = input_bank_count(manifest, mode=mode, lhs_s16=wide,
                                         requested_banks=2 if wide else 1)
                configure(directory, banks=banks, r=2, w=3, control=2,
                          bank_bytes=8192, bank_count=7)
                cfg = [int(value,16) for value in (directory/'config.mem').read_text().split()]
                image = npu.load_sparse(directory/'init.mem')
                golden = npu.load_sparse(directory/'golden.mem')
                for bit,base,rows,width,stride in ((1,cfg[14],cfg[3],2 if wide else 1,cfg[18]),
                                                  (2,cfg[15],cfg[5],1,cfg[19])):
                    if not layout & bit:
                        continue
                    depth = cfg[4]
                    tiles = (depth+15)//16
                    packed = bytearray(((rows+15)//16)*tiles*256*width)
                    for row in range(rows):
                        for col in range(depth):
                            target = (((row//16)*tiles + col//16)*256 + (row%16)*16 + col%16)*width
                            origin = base + row*stride + col*width
                            packed[target:target+width] = image[origin:origin+width]
                    image[base:base+len(packed)] = packed
                    golden[base:base+len(packed)] = packed
                cfg[29] = layout
                (directory/'config.mem').write_text(''.join(f'{value:08x}\n' for value in cfg))
                npu.sparse_mem(directory/'init.mem',image)
                npu.sparse_mem(directory/'golden.mem',golden)
                metadata = json.loads((directory/'case.json').read_text())
                metadata['tile_layout'] = {'lhs_packed': bool(layout&1), 'rhs_packed': bool(layout&2), 'tile': 16}
                (directory/'case.json').write_text(json.dumps(metadata,indent=2)+'\n')
                cases.append(directory)
    return cases


def main() -> None:
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--build-timeout', type=int, default=7200)
    parser.add_argument('--sim', type=Path)
    args = parser.parse_args()
    ROOT = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError('Cannot locate Verilator: ' + args.verilator)
    observer = ROOT/'test/frame_address/npu_observer.sv'
    tracked = [ROOT/'rtl/npu/top/frame_address_prepare.sv',ROOT/'rtl/npu/top/npu_top.sv',observer]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    wrapper = out/'verilator_frame_address'
    wrapper.write_text('#!'+sys.executable+'\nimport os, subprocess, sys\n' +
        'arguments=sys.argv[1:]\ncommand='+repr([verilator,str(observer)])+'+arguments\n'+
        'if "--binary" in arguments:\n    subprocess.run(["--lint-only" if item=="--binary" else item for item in command],check=True)\n'+
        'os.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    results = {}
    if args.sim is None:
        command = [sys.executable,str(ROOT/'test/fpga_integration/run.py'),'--out',str(out/'fpga'),
                   '--verilator',str(wrapper),'--jobs',str(args.jobs),'--build-timeout',str(args.build_timeout)]
        with (out/'integration.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        results['functional'] = json.loads((out/'fpga/summary.json').read_text())
        sim = out/'fpga/npu/s16'
    else:
        sim = args.sim.resolve()
    for name, script in [('capacity','test/ps_capacity_limits/run_npu.py'),
                         ('output','test/writeback_cyclic/run_npu.py')]:
        command = [sys.executable,str(ROOT/script),'--out',str(out/name),'--sim',str(sim)]
        if name == 'capacity':
            command += ['--verilator',str(wrapper)]
        with (out/(name+'.log')).open('w') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        results[name] = json.loads((out/name/'summary.json').read_text())
    sys.path.insert(0,str(ROOT/'test/ps_compression'))
    from run_shared_npu import npu
    manifest = json.loads((sim/'build.json').read_text())
    cases = packed_cases(out/'packed', manifest)
    results['packed'] = npu.run_suite(sim/'obj/Vtb_conv_npu',out,'packed',cases,no_random=False,timeout=900)
    if not results['packed']['passed']:
        raise RuntimeError('Packed frame address validation failed')
    coverage = []
    for path in sorted(out.rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith('FRAME_ADDRESS_NPU_PASS '):
                coverage.append({'log':str(path.relative_to(out)),
                                 **{key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}})
    if not any(row['ws_frames'] and row['is_frames'] and row['packed_frames'] and row['wide_frames'] for row in coverage):
        raise RuntimeError('Frame mode and layout coverage incomplete')
    if not coverage or any(row.get('cache_slot_checks', 0) != row['started'] for row in coverage):
        raise RuntimeError('Frame cache slot checks do not cover every executed frame')
    if hashes != {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}:
        raise RuntimeError('Sources changed during production validation')
    summary = {'passed':True,'source_sha256':hashes,'simulator_manifest':str(sim/'build.json'),
               'frame_start_delay_cycles':12,'coverage':coverage,'runs':results}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({'passed':True,'frame_start_delay_cycles':12,'coverage':coverage},indent=2))


if __name__ == '__main__':
    main()
