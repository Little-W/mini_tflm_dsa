#!/usr/bin/env python3
"""Run the unified matrix-DMA contract and the unchanged legacy DMA benches."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_command(command, log, timeout=1200):
    with log.open('w') as stream:
        stream.write('COMMAND: '+repr([str(p) for p in command])+'\n');stream.flush()
        result=subprocess.run([str(p) for p in command],cwd=ROOT,stdout=stream,
                              stderr=subprocess.STDOUT,timeout=timeout)
    return result.returncode


def sources(tb, memory=False, source_root=ROOT):
    package=ROOT/'rtl/npu/conv/conv_im2col_pkg.sv'
    packages=[package,ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    result=packages+[p for p in sorted((ROOT/'rtl/npu/conv').rglob('*.sv')) if p not in packages]
    result+=sorted((ROOT/'rtl/npu/dma').rglob('*.sv'))
    if memory:result.append(ROOT/'test/conv_npu/axi_memory.sv')
    result.append(tb)
    import runpy
    result = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](result)
    result = [source_root / path.relative_to(ROOT)
              if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] == 'rtl'
              else path for path in result]
    return result


def build(out,top,src,size,args):
    out.mkdir(parents=True,exist_ok=True)
    manifest_path=out/'build.json'
    parameters={'size':size,'top':top,'cache_sets':32,'cache_ways':2,'cache_line_bytes':16,'cache_policy':2}
    import runpy
    dependency_tools=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    source_root=args.source_root.resolve()
    tracked=dependency_tools['input_files'](src,source_root,include_dirs=(source_root/'include',))
    source_hashes={str(p):sha(p) for p in tracked}
    if args.skip_build:
        existing=args.reuse_builds_root.resolve()/out.name if args.reuse_builds_root else out
        manifest=json.loads((existing/'build.json').read_text())
        if manifest['parameters']!=parameters or manifest['source_sha256']!=source_hashes:
            raise RuntimeError(f'stale binary parameters or sources: {out}')
        if manifest.get('returncode') or not manifest.get('sources_unchanged_during_build'):
            raise RuntimeError(f'cached build was unsuccessful or unstable: {existing}')
        binary=existing/'obj'/('V'+top)
        if not binary.is_file():raise RuntimeError(f'missing executable: {binary}')
        if existing!=out:
            manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
            (out/'binary_reuse.json').write_text(json.dumps({'source':str(existing),'binary_sha256':sha(binary),'compiled_sources_match':True},indent=2)+'\n')
        return binary
    cmd=[args.verilator,'--binary','--timing','--assert','-sv','--top-module',top,
         '-Wno-fatal',f'-DTB_SIZE={size}','-I'+str(source_root/'include'),
         '--Mdir',out/'obj','-j',args.jobs,
         '-CFLAGS','-std=c++20 -O1','-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',*src]
    rc=run_command(cmd,out/'compile.log')
    after={str(p):sha(p) for p in tracked}
    text=(out/'compile.log').read_text()
    warnings={kind:text.count('%Warning-'+kind+':')
              for kind in sorted(set(re.findall(r'%Warning-([^:]+):',text)))}
    manifest={'command':[str(p) for p in cmd],'returncode':rc,'warnings':warnings,
              'parameters':parameters,'source_sha256':source_hashes,
              'source_sha256_after':after,'sources_unchanged_during_build':source_hashes==after}
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    if rc or source_hashes!=after:
        raise RuntimeError(text[-6000:] if rc else 'Sources changed during build; preserve this run and rebuild')
    return out/'obj'/('V'+top)


def cleanup_objects(binary):
    for path in binary.parent.iterdir():
        if path!=binary and path.is_file() and path.suffix in ('.h','.cpp','.o','.a','.d','.mk','.gch'):
            path.unlink()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/conv_dma/matrix')
    parser.add_argument('--sizes',type=int,nargs='+',default=[4,16])
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--jobs',type=int,default=2)
    parser.add_argument('--source-root',type=Path,default=ROOT,
                        help='包含待验证 RTL 的独立源码目录')
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--reuse-builds-root',type=Path,help='Optional compiled profiles, checked against all current RTL sources')
    parser.add_argument('--legacy-only',action='store_true')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    summary={'stage':'dma_owned_im2col','scope':'matrix_element_and_owner_contract',
             'verilator':subprocess.check_output([args.verilator,'--version'],text=True).strip(),
             'runner_sha256':sha(Path(__file__)),'runs':[]}
    cases=[]
    if args.legacy_only:
        for unit,marker in [('axi_dual_block_dma','[AXI_DUAL_DMA] ALL PASS'),
                            ('axi_block_dma_arbiter','[AXI_ARB] ALL PASS')]:
            cases.append((unit,'tb_'+unit,ROOT/'test'/unit/('tb_'+unit+'.sv'),8,False,marker))
    else:
        cases=[(f's{size}','tb_conv_dma',HERE/'tb_conv_dma.sv',size,True,'CONV_DMA_PASS') for size in args.sizes]
    for name,top,tb,size,memory,marker in cases:
        case_out=out/name;case_out.mkdir(exist_ok=True)
        binary=build(case_out,top,sources(tb,memory,args.source_root.resolve()),size,args)
        cmd=[binary]
        if memory:cmd.append('+MATRIX_TRACE='+str(case_out/'matrix_returns.csv'))
        rc=run_command(cmd,case_out/'run.log',timeout=180)
        log=(case_out/'run.log').read_text()
        record={'name':name,'size':size,'passed':rc==0 and marker in log,'returncode':rc,
                'command':[str(p) for p in cmd],'build_sha256':sha(case_out/'build.json'),
                'binary_sha256':sha(binary),'log_sha256':sha(case_out/'run.log')}
        if memory:
            record['descriptors']=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
                                   for line in log.splitlines() if line.startswith('DMA_MATRIX_PASS')]
            record['summary']=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
                              for line in log.splitlines() if line.startswith('CONV_DMA_PASS')]
            record['matrix_trace_sha256']=sha(case_out/'matrix_returns.csv')
        summary['runs'].append(record)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(name,'PASS' if record['passed'] else 'FAIL',record.get('summary',[]),flush=True)
        if not record['passed']:
            print(log[-6000:],flush=True);break
        if not args.skip_build:cleanup_objects(binary)
    summary['passed']=len(summary['runs'])==len(cases) and all(r['passed'] for r in summary['runs'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return 0 if summary['passed'] else 1


if __name__=='__main__':sys.exit(main())
