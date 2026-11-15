#!/usr/bin/env python3
"""Run an actual external simulator or fail explicitly; never substitute a model."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
FILES=['rtl/conv_im2col_pkg.sv','rtl/conv_udiv32.sv','rtl/conv_sdp_ram.sv','rtl/conv_next_use_predictor.sv',
       'rtl/conv_axi_span_reader.sv','rtl/conv_read_cache.sv','rtl/conv_im2col_frontend.sv',
       'rtl/conv_ia_write_adapter.sv','rtl/conv_ia_tile_path.sv','tests/tb_conv_im2col_frontend.sv']

RTL=ROOT.parents[1]/'rtl/npu/conv'
FILES=[str(RTL/('00_conv_im2col_pkg.sv' if Path(name).name=='conv_im2col_pkg.sv' else Path(name).name)) if name.startswith('rtl/') else name for name in FILES]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--size',type=int,default=16)
    ap.add_argument('--cache-sets',type=int,default=128)
    ap.add_argument('--cache-ways',type=int,default=2)
    ap.add_argument('--line-bytes',type=int,default=16)
    ap.add_argument('--tile-path',action='store_true')
    a=ap.parse_args()
    name=f'rtl_s{a.size}_sets{a.cache_sets}_ways{a.cache_ways}_line{a.line_bytes}'
    if a.tile_path: name+='_path'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    status={'scope':'frontend and optional standalone tile adapter RTL; original npu_top not integrated',
            'size':a.size,'cache_sets':a.cache_sets,'cache_ways':a.cache_ways,
            'line_bytes':a.line_bytes,'tile_path':a.tile_path}
    verilator=shutil.which('verilator');vcs=shutil.which('vcs')
    if not(verilator or vcs):
        status.update(status='NOT_RUN',reason='Neither Verilator nor VCS is installed')
        (OUTPUT/'rtl_status.json').write_text(json.dumps(status,indent=2))
        print(json.dumps(status,indent=2));return 2
    vector_path=OUTPUT/f'{name}_vectors.txt'
    subprocess.run([sys.executable,'tests/gen_rtl_vectors.py','--size',str(a.size),'--out',str(vector_path)],cwd=ROOT,check=True)
    build=OUTPUT/'objects'/name;build.mkdir(parents=True,exist_ok=True)
    log=OUTPUT/f'{name}.log'
    try:
        with log.open('w') as f:
            if verilator:
                cmd=[verilator,'--binary','--timing','--assert','-Wall','-Wno-fatal',
                     '-DCONV_ASSERT','--top-module','tb_conv_im2col_frontend',f'-GSIZE={a.size}',f'-GCACHE_SETS={a.cache_sets}',
                     f'-GCACHE_WAYS={a.cache_ways}',f'-GLINE_BYTES={a.line_bytes}',
                     f'-GUSE_TILE_PATH={int(a.tile_path)}',
                     '--Mdir',str(build),'-j','2']+FILES
                subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
                binary=build/'Vtb_conv_im2col_frontend'
            else:
                binary=build/'simv'
                cmd=[vcs,'-full64','-sverilog','-timescale=1ns/1ps','+define+CONV_ASSERT',
                     '-top','tb_conv_im2col_frontend',
                     f'-pvalue+tb_conv_im2col_frontend.SIZE={a.size}',
                     f'-pvalue+tb_conv_im2col_frontend.CACHE_SETS={a.cache_sets}',
                     f'-pvalue+tb_conv_im2col_frontend.CACHE_WAYS={a.cache_ways}',
                     f'-pvalue+tb_conv_im2col_frontend.LINE_BYTES={a.line_bytes}',
                     f'-pvalue+tb_conv_im2col_frontend.USE_TILE_PATH={int(a.tile_path)}',
                     '-o',str(binary)]+FILES
                subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
            subprocess.run([str(binary),f'+VECTORS={vector_path}'],
                           cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        text=log.read_text()
        if 'RTL_FRONTEND_PASS' not in text:raise RuntimeError('PASS marker absent')
        warnings=[line for line in text.splitlines() if line.startswith('%Warning')]
        # Keep every diagnostic in the log. Only reviewed structural/bench style
        # warnings are allowed; width, multi-driver, latch and loop warnings fail.
        reviewed={'UNUSEDSIGNAL','UNUSEDPARAM','BLKSEQ','PROCASSINIT','SYNCASYNCNET'}
        # The 00_ prefix intentionally orders this package before its users.
        package_name_warning="Filename '00_conv_im2col_pkg' does not match PACKAGE name: 'conv_im2col_pkg'"
        unexpected=[w for w in warnings if w.split(':',1)[0].removeprefix('%Warning-') not in reviewed
                    and not (w.startswith('%Warning-DECLFILENAME:') and package_name_warning in w)]
        if unexpected: raise RuntimeError('unreviewed lint warnings: '+repr(unexpected))
        status.update(status='PASS',simulator=verilator or vcs,log=str(log),
                      warnings=warnings,command=cmd)
        rc=0
    except Exception as e:
        status.update(status='FAIL',reason=str(e),log=str(log));rc=1
    (OUTPUT/'rtl_status.json').write_text(json.dumps(status,indent=2))
    (OUTPUT/f'{name}_status.json').write_text(json.dumps(status,indent=2))
    print(json.dumps(status,indent=2));return rc
if __name__=='__main__':sys.exit(main())
