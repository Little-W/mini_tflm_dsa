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
    parser.add_argument('--source-root',type=Path,default=ROOT,help='包含候选 RTL 的独立源码目录')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--pes',type=int,choices=(8,16),default=8)
    parser.add_argument('--bus-width',type=int,choices=(32,64),default=32)
    parser.add_argument('--window-lanes',type=int,choices=(4,8,16),default=4)
    parser.add_argument('--shared-quant',action='store_true')
    parser.add_argument('--cache-sets',type=int,default=128)
    parser.add_argument('--cache-line-bytes',type=int,choices=(16,32,64,128),default=16)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--rtl-assertions',action='store_true',help='启用 RTL 内部时序与状态检查')
    args=parser.parse_args()
    if args.jobs<1 or args.jobs>2:
        parser.error('--jobs must be 1 or 2')
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=True)
    source_root=args.source_root.resolve()
    conv=source_root/'rtl/npu/conv'
    sources=[conv/'conv_im2col_pkg.sv',conv/'vector_engine_pkg.sv']
    sources += [path for path in sorted(conv.rglob('*.sv')) if path not in sources]
    sources += sorted((source_root/'rtl/npu/dma').rglob('*.sv'))
    sources += [source_root/'rtl/npu/writeback'/name for name in
                ('vec_requant.sv','requant_compute_lane.sv','requant_group_buffer.sv')]
    sources += [HERE/'shared_quant_model.sv']
    sources += [source_root/'rtl/common/pseudo_dual_port_ram.v',HERE/'window_error_top.sv']
    import runpy
    observer_root=source_root/'test/monitors'
    if not observer_root.is_dir():observer_root=ROOT/'test/monitors'
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](
        sources, source_root=source_root, observer_root=observer_root)
    dependencies=sources+[HERE/'window_error.cpp',Path(__file__)]
    source_sha={str(path):digest(path) for path in dependencies}
    parameters={'pe_count':args.pes,'bus_width':args.bus_width,'window_lanes':args.window_lanes,'shared_quant':args.shared_quant,
                'cache_sets':args.cache_sets,'cache_line_bytes':args.cache_line_bytes,
                'cache_bytes':2*args.cache_sets*args.cache_line_bytes,'rtl_assertions':args.rtl_assertions}
    binary=out/'obj/Vwindow_error_top'; manifest_path=out/'build.json'
    build_command=[args.verilator,'--cc','--exe','--assert','--top-module','window_error_top',
                   '-Wno-fatal','-Wno-PINMISSING',f'-GPE_COUNT={args.pes}',
                   f'-GBUS_WIDTH={args.bus_width}',f'-GWINDOW_LANES={args.window_lanes}',f'-GSHARED_QUANT_ENABLE={int(args.shared_quant)}',
                   f'-GCACHE_SETS={args.cache_sets}',f'-GCACHE_LINE_BYTES={args.cache_line_bytes}',
                   '--Mdir',out/'obj',
                   '--output-groups','0','--output-split','12000','--output-split-cfuncs','200',
                   '-CFLAGS',f'-std=c++{20 if args.rtl_assertions else 17} --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096 -DTEST_BUS_WIDTH={args.bus_width}',
                   ROOT/'test/conv_npu/simulator.vlt',*sources,
                   *(['-DNPU_SIM_ASSERT=1','--timing'] if args.rtl_assertions else []),HERE/'window_error.cpp']
    make_command=['make','-C',out/'obj','-f','Vwindow_error_top.mk','-j',args.jobs,
                  'OPT_FAST=-O1','OPT_SLOW=-O0','OPT_GLOBAL=-O1','VK_PCH_I_FAST=',
                  'VK_PCH_I_SLOW=','CFG_CXXFLAGS_PCH=-E']
    if args.skip_build:
        previous=json.loads(manifest_path.read_text())
        if (previous['source_sha256']!=source_sha or digest(binary)!=previous['binary_sha256'] or
                previous.get('parameters')!=parameters):
            raise RuntimeError('Sources or executable differ from the saved build')
    else:
        command(build_command,out/'verilate.log')
        command(make_command,out/'compile.log')
        if any(digest(ROOT/name)!=value for name,value in source_sha.items()):
            raise RuntimeError('Sources changed during build')
        manifest_path.write_text(json.dumps({'passed':True,'source_sha256':source_sha,'parameters':parameters,
            'sources_unchanged_during_build':True,'binary_sha256':digest(binary),
            'build_command':list(map(str,build_command)),'make_command':list(map(str,make_command))},indent=2)+'\n')
    command([binary],out/'run.log')
    text=(out/'run.log').read_text()
    match=re.search(r'WINDOW_ERROR_PASS cases=(\d+) injected_errors=(\d+) recovery_tasks=(\d+)',text)
    task_count=(8 if args.shared_quant else 4)*(args.bus_width//8)
    if not match or tuple(map(int,match.groups()))!=(task_count,task_count//2,task_count//2):
        raise RuntimeError('Incomplete directed test result')
    if any(digest(ROOT/name)!=value for name,value in source_sha.items()):
        raise RuntimeError('Sources changed during execution')
    result={'passed':True,'cases':task_count,'injected_errors':task_count//2,'recovery_tasks':task_count//2,'parameters':parameters,
            'verification':f'Terminal window error with queued output and shared quantization in flight; fixed and random AXI waits; byte offsets 0..{args.bus_width//8-1} across a page; complete memory comparison; no transactions after DONE; next task numerical comparison.',
            'source_sha256':source_sha,'binary_sha256':digest(binary),
            'build_manifest':str(manifest_path),'build_manifest_sha256':digest(manifest_path),
            'run_log':str(out/'run.log'),'run_log_sha256':digest(out/'run.log'),
            'result':text.strip()}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(text,flush=True)


if __name__=='__main__':
    main()
