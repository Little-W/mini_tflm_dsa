#!/usr/bin/env python3
"""Verify shared matrix and DW quantization with the production RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--out',type=Path,default=ROOT/'build/vector_shared_quant')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/name for name in (
        'rtl/npu/writeback/vec_requant.sv','rtl/npu/writeback/requant_compute_lane.sv',
        'rtl/npu/writeback/requant_group_buffer.sv','rtl/npu/conv/vector_scalar_multiplier.sv',
        'rtl/common/regfile.v','rtl/common/add_equal.sv','rtl/common/onehot_check.sv',
        'rtl/common/parallel_prefix_add.sv')]
    sources += [HERE/'shared_quant_top.sv',HERE/'main.cpp']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+[Path(__file__)]}
    command=[args.verilator,'--cc','--exe','--build','-j','2','--assert','-Wno-fatal','-Wno-PINMISSING',
             '--top-module','shared_quant_top','--Mdir',str(out/'obj'),'-CFLAGS','-std=c++17',*map(str,sources)]
    with (out/'build.log').open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    if any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in hashes.items()):
        raise RuntimeError('Sources changed during build')
    binary=out/'obj/Vshared_quant_top'
    result=subprocess.run([str(binary)],text=True,capture_output=True)
    text=result.stdout+result.stderr;(out/'run.log').write_text(text)
    match=re.search(r'VECTOR_SHARED_QUANT_PASS vectors=(\d+) outputs=(\d+) dw_vectors=(\d+) matrix_vectors=(\d+) tasks=(\d+)',text)
    summary={'passed':result.returncode==0 and match is not None,'source_sha256':hashes,
             'executable_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'command':command,'result':text}
    if match:
        summary.update(dict(zip(('vectors','outputs','dw_vectors','matrix_vectors','tasks'),map(int,match.groups()))))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(text,end='')
    if not summary['passed']:raise RuntimeError('Shared quantization verification failed')

if __name__=='__main__':
    main()
