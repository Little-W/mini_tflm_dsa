#!/usr/bin/env python3
"""Verify DiP weight rotation, shadow preloading, and complete matrix products."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/dip_validation/weights')
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=1)
    args=parser.parse_args()
    if args.jobs < 1: parser.error('--jobs must be positive')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'test/dip_weights/tb.sv',ROOT/'test/dip_weights/main.cpp',
             ROOT/'rtl/npu/loaders/kernel_loader_buffer.sv',ROOT/'rtl/npu/compute/ws_systolic_cell.sv',
             ROOT/'rtl/npu/compute/ws_systolic_array.sv']
    recorded_sources=[Path(__file__).resolve(),*sources]
    hashes={str(path.relative_to(ROOT)):digest(path) for path in recorded_sources}
    results=[]
    for size,width in ((3,8),(4,16),(16,8),(16,16)):
        directory=out/f'n{size}_s{width}';directory.mkdir(exist_ok=True)
        flags=f'-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_SIZE={size} -DTEST_WEIGHT_WIDTH={width}'
        command=[args.verilator,'--cc','--exe','--build','-j',str(args.jobs),'--assert','-Wno-fatal',
                 '--top-module','dip_weight_tb','--Mdir',str(directory/'obj'),
                 f'-GSIZE={size}',f'-GWEIGHT_WIDTH={width}','-CFLAGS',flags,
                 '-LDFLAGS','-fsanitize=undefined','-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
                 *map(str,sources)]
        with (directory/'build.log').open('w') as log:
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode: raise RuntimeError(f'Build failed: {directory}/build.log')
        binary=directory/'obj/Vdip_weight_tb'
        result=subprocess.run([str(binary)],cwd=ROOT,text=True,capture_output=True,timeout=60)
        (directory/'run.log').write_text(result.stdout+result.stderr)
        if result.returncode: raise RuntimeError(result.stderr or result.stdout)
        record=json.loads(result.stdout.strip().splitlines()[-1]);assert record['passed']
        record['binary_sha256']=digest(binary);record['compile_command']=command
        results.append(record);print(result.stdout,end='',flush=True)
    assert hashes=={str(path.relative_to(ROOT)):digest(path) for path in recorded_sources}
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,results=results),indent=2)+'\n')


if __name__=='__main__':
    main()
