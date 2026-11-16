#!/usr/bin/env python3
"""Verify adjacent exact-range AXI spans with response-edge descriptor handoff."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--out',type=Path,default=ROOT/'build/conv_span_handoff')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/conv/conv_axi_span_reader.sv',HERE/'main.cpp',
             ROOT/'rtl/npu/conv/conv_axi_read_mux.sv',HERE/'read_mux.cpp',Path(__file__)]
    before={str(path.relative_to(ROOT)):digest(path) for path in sources}
    build=[args.verilator,'--cc','--exe','--build','--assert','-DCONV_ASSERT','-Wno-fatal',
           '--top-module','conv_axi_span_reader','--Mdir',out/'obj','-j',args.jobs,
           '-CFLAGS','-std=c++17',*sources[:2]]
    with (out/'build.log').open('w') as log:
        subprocess.run(list(map(str,build)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=out/'obj/Vconv_axi_span_reader'
    with (out/'run.log').open('w') as log:
        subprocess.run([str(binary)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    text=(out/'run.log').read_text();print(text)
    match=re.search(r'SPAN_HANDOFF_PASS cases=(\d+) spans=(\d+) handoffs=(\d+) bytes=(\d+) errors=(\d+)',text)
    if not match or match.groups()[:3]!=('4','452','448'):
        raise RuntimeError('Incomplete span handoff result')
    mux_build=[args.verilator,'--cc','--exe','--build','--assert','-Wno-fatal',
               '--top-module','conv_axi_read_mux','--Mdir',out/'mux_obj','-j',args.jobs,
               '-CFLAGS','-std=c++17',*sources[2:4]]
    with (out/'mux_build.log').open('w') as log:
        subprocess.run(list(map(str,mux_build)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    mux_binary=out/'mux_obj/Vconv_axi_read_mux'
    with (out/'mux_run.log').open('w') as log:
        subprocess.run([str(mux_binary)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
    mux_text=(out/'mux_run.log').read_text();print(mux_text)
    mux_match=re.search(r'READ_MUX_PASS cases=(\d+) bursts=(\d+) handoffs=(\d+) owner_changes=(\d+) stalled_retirements=(\d+) errors=(\d+)',mux_text)
    if not mux_match or mux_match.groups()[:2]!=('6','768'):
        raise RuntimeError('Incomplete read mux result')
    if before!={str(path.relative_to(ROOT)):digest(path) for path in sources}:
        raise RuntimeError('Sources changed during verification')
    (out/'summary.json').write_text(json.dumps({'passed':True,'source_sha256':before,
        'cases':10,'span':{'cases':4,'spans':452,'handoffs':448,'bytes':int(match[4]),'errors':int(match[5]),
                          'binary_sha256':digest(binary),'build_command':list(map(str,build)),
                          'run_log_sha256':digest(out/'run.log'),'result':text.strip()},
        'read_mux':{'cases':6,'bursts':768,'handoffs':int(mux_match[3]),
                    'owner_changes':int(mux_match[4]),'stalled_retirements':int(mux_match[5]),
                    'errors':int(mux_match[6]),'binary_sha256':digest(mux_binary),
                    'build_command':list(map(str,mux_build)),
                    'run_log_sha256':digest(out/'mux_run.log'),'result':mux_text.strip()}},indent=2)+'\n')


if __name__=='__main__':
    main()
