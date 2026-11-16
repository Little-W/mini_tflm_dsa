#!/usr/bin/env python3
"""Verify terminal window errors while an output write receives its grant."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(arguments,path):
    arguments=list(map(str,arguments))
    with path.open('w') as stream:
        stream.write('COMMAND: '+shlex.join(arguments)+'\n')
        stream.flush()
        result=subprocess.run(arguments,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(path.read_text()[-10000:])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--out',type=Path,default=ROOT/'build/vector_window_error')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--skip-build',action='store_true')
    args=parser.parse_args()
    if args.jobs<1 or args.jobs>2:
        parser.error('--jobs must be 1 or 2')
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    conv=ROOT/'rtl/npu/conv'
    sources=[conv/'00_conv_im2col_pkg.sv',conv/'01_vector_engine_pkg.sv']
    sources += [path for path in sorted(conv.glob('*.sv')) if path not in sources]
    sources += sorted((ROOT/'rtl/npu/dma').glob('*.sv'))
    sources += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'window_error_top.sv']
    dependencies=sources+[HERE/'window_error.cpp',Path(__file__)]
    source_sha={str(path.relative_to(ROOT)):digest(path) for path in dependencies}
    binary=out/'obj/Vwindow_error_top'; manifest_path=out/'build.json'
    build_command=[args.verilator,'--cc','--exe','--assert','--top-module','window_error_top',
                   '-Wno-fatal','-Wno-PINMISSING','--Mdir',out/'obj',
                   '--output-groups','0','--output-split','12000','--output-split-cfuncs','200',
                   '-CFLAGS','-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
                   *sources,HERE/'window_error.cpp']
    make_command=['make','-C',out/'obj','-f','Vwindow_error_top.mk','-j',args.jobs,
                  'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
                  'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E']
    if args.skip_build:
        previous=json.loads(manifest_path.read_text())
        if previous['source_sha256']!=source_sha or digest(binary)!=previous['binary_sha256']:
            raise RuntimeError('Sources or executable differ from the saved build')
    else:
        command(build_command,out/'verilate.log')
        command(make_command,out/'compile.log')
        if any(digest(ROOT/name)!=value for name,value in source_sha.items()):
            raise RuntimeError('Sources changed during build')
        manifest_path.write_text(json.dumps({'passed':True,'source_sha256':source_sha,
            'sources_unchanged_during_build':True,'binary_sha256':digest(binary),
            'build_command':list(map(str,build_command)),'make_command':list(map(str,make_command))},indent=2)+'\n')
    command([binary],out/'run.log')
    text=(out/'run.log').read_text()
    match=re.search(r'WINDOW_ERROR_PASS cases=(\d+) injected_errors=(\d+) recovery_tasks=(\d+)',text)
    if not match or tuple(map(int,match.groups()))!=(16,8,8):
        raise RuntimeError('Incomplete directed test result')
    if any(digest(ROOT/name)!=value for name,value in source_sha.items()):
        raise RuntimeError('Sources changed during execution')
    result={'passed':True,'cases':16,'injected_errors':8,'recovery_tasks':8,
            'verification':'Terminal window error before WB_REQ grant; fixed and random AXI waits; byte offsets 0..3 across a page; complete memory comparison; no transactions after DONE; next task numerical comparison.',
            'source_sha256':source_sha,'binary_sha256':digest(binary),
            'build_manifest':str(manifest_path),'build_manifest_sha256':digest(manifest_path),
            'run_log':str(out/'run.log'),'run_log_sha256':digest(out/'run.log'),
            'result':text.strip()}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(text,flush=True)


if __name__=='__main__':
    main()
