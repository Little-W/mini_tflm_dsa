#!/usr/bin/env python3
"""Run an actual external simulator or fail explicitly; never substitute a model."""
import argparse,hashlib,json,shutil,subprocess,sys
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
    ap.add_argument('--lanes',type=int,default=2)
    ap.add_argument('--cache-policy',type=int,default=3)
    ap.add_argument('--prefetch',action='store_true')
    ap.add_argument('--windowed',action='store_true')
    ap.add_argument('--cache-sets',type=int,default=128)
    ap.add_argument('--cache-ways',type=int,default=2)
    ap.add_argument('--line-bytes',type=int,default=16)
    ap.add_argument('--tile-path',action='store_true')
    ap.add_argument('--native-sched-r',type=lambda value:int(value,0),default=0)
    ap.add_argument('--native-sched-groups',type=lambda value:int(value,0),default=0)
    ap.add_argument('--expect-geometry-predictions',type=int,default=-1)
    ap.add_argument('--max-cycles',type=int,default=100000000)
    ap.add_argument('--vectors',type=Path,help='Use an existing vector file')
    ap.add_argument('--out',type=Path,help='Directory for logs, status and compiled RTL')
    a=ap.parse_args()
    if not 0<=a.native_sched_r<2**32 or not 0<=a.native_sched_groups<2**32:
        ap.error('Native scheduler parameters must be unsigned 32-bit integers')
    if a.expect_geometry_predictions < -1 or not 1<=a.max_cycles<2**32:
        ap.error('Invalid expected prediction count or cycle limit')
    if a.tile_path and (a.native_sched_r or a.native_sched_groups or a.expect_geometry_predictions>=0):
        ap.error('Native scheduler checks require the direct frontend interface')
    output=(a.out or OUTPUT).resolve()
    name=f'rtl_s{a.size}_sets{a.cache_sets}_ways{a.cache_ways}_line{a.line_bytes}'
    if a.tile_path: name+='_path'
    name+=f'_lanes{a.lanes}_policy{a.cache_policy}_pf{int(a.prefetch)}_win{int(a.windowed)}'
    if a.native_sched_r or a.native_sched_groups or a.expect_geometry_predictions>=0:
        name+=f'_native_r{a.native_sched_r}_groups{a.native_sched_groups}'
    output.mkdir(parents=True, exist_ok=True)
    status={'scope':'frontend and optional standalone tile adapter RTL; original npu_top not integrated',
            'size':a.size,'cache_sets':a.cache_sets,'cache_ways':a.cache_ways,
            'line_bytes':a.line_bytes,'tile_path':a.tile_path,
            'lanes':a.lanes,'policy':a.cache_policy,'prefetch':a.prefetch,'windowed':a.windowed,
            'native_sched_r':a.native_sched_r,'native_sched_groups':a.native_sched_groups,
            'expected_geometry_predictions':a.expect_geometry_predictions,'max_cycles':a.max_cycles}
    verilator=shutil.which('verilator');vcs=shutil.which('vcs')
    if not(verilator or vcs):
        status.update(status='NOT_RUN',reason='Neither Verilator nor VCS is installed')
        (output/'rtl_status.json').write_text(json.dumps(status,indent=2))
        print(json.dumps(status,indent=2));return 2
    vector_path=a.vectors.resolve() if a.vectors else output/f'{name}_vectors.txt'
    if a.vectors:
        if not vector_path.is_file(): ap.error('Vector file does not exist: '+str(vector_path))
    else:
        subprocess.run([sys.executable,'tests/gen_rtl_vectors.py','--size',str(a.size),'--out',str(vector_path)],cwd=ROOT,check=True)
    status.update(vector_file=str(vector_path),vector_sha256=hashlib.sha256(vector_path.read_bytes()).hexdigest())
    build=output/'objects'/name;build.mkdir(parents=True,exist_ok=True)
    log=output/f'{name}.log'
    try:
        with log.open('w') as f:
            if verilator:
                cmd=[verilator,'--binary','--timing','--assert','-Wall','-Wno-fatal',
                     '-DCONV_ASSERT','--top-module','tb_conv_im2col_frontend',f'-GSIZE={a.size}',f'-GCACHE_SETS={a.cache_sets}',
                     f'-GCACHE_WAYS={a.cache_ways}',f'-GLINE_BYTES={a.line_bytes}',
                     f'-GUSE_TILE_PATH={int(a.tile_path)}',f'-GLANES={a.lanes}',
                     f'-GCACHE_POLICY={a.cache_policy}',f'-GPREFETCH={int(a.prefetch)}',f'-GWINDOWED={int(a.windowed)}',
                     f'-GNATIVE_SCHED_R={a.native_sched_r}',f'-GNATIVE_SCHED_GROUPS={a.native_sched_groups}',
                     f'-GEXPECT_GEOMETRY_PREDICTIONS={a.expect_geometry_predictions}',f'-GMAX_CYCLES={a.max_cycles}',
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
                     f'-pvalue+tb_conv_im2col_frontend.LANES={a.lanes}',
                     f'-pvalue+tb_conv_im2col_frontend.CACHE_POLICY={a.cache_policy}',
                     f'-pvalue+tb_conv_im2col_frontend.PREFETCH={int(a.prefetch)}',
                     f'-pvalue+tb_conv_im2col_frontend.WINDOWED={int(a.windowed)}',
                     f'-pvalue+tb_conv_im2col_frontend.NATIVE_SCHED_R={a.native_sched_r}',
                     f'-pvalue+tb_conv_im2col_frontend.NATIVE_SCHED_GROUPS={a.native_sched_groups}',
                     f'-pvalue+tb_conv_im2col_frontend.EXPECT_GEOMETRY_PREDICTIONS={a.expect_geometry_predictions}',
                     f'-pvalue+tb_conv_im2col_frontend.MAX_CYCLES={a.max_cycles}',
                     '-o',str(binary)]+FILES
                subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
            subprocess.run([str(binary),f'+VECTORS={vector_path}'],
                           cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        text=log.read_text()
        if 'RTL_FRONTEND_PASS' not in text:raise RuntimeError('PASS marker absent')
        if a.expect_geometry_predictions>=0 and f'RTL_NATIVE_GEOMETRY_PASS predictions={a.expect_geometry_predictions}' not in text:
            raise RuntimeError('Native geometry prediction check absent')
        warnings=[line for line in text.splitlines() if line.startswith('%Warning')]
        # Keep every diagnostic in the log. Only reviewed structural/bench style
        # warnings are allowed; width, multi-driver, latch and loop warnings fail.
        reviewed={'UNUSEDSIGNAL','UNUSEDPARAM','BLKSEQ','PROCASSINIT','SYNCASYNCNET'}
        # The 00_ prefix intentionally orders this package before its users.
        package_name_warning="Filename '00_conv_im2col_pkg' does not match PACKAGE name: 'conv_im2col_pkg'"
        # The matrix tile adapter consumes tile_done; its streaming last
        # output is unused. Every other missing port remains an error.
        def unused_adapter_last(warning):
            return (warning.startswith('%Warning-PINMISSING:') and
                    str(RTL/'conv_ia_tile_path.sv') in warning and
                    warning.endswith("Instance has missing pin: 'wr_last'"))
        unexpected=[w for w in warnings if w.split(':',1)[0].removeprefix('%Warning-') not in reviewed
                    and not (w.startswith('%Warning-DECLFILENAME:') and package_name_warning in w)
                    and not unused_adapter_last(w)]
        if unexpected: raise RuntimeError('unreviewed lint warnings: '+repr(unexpected))
        status.update(status='PASS',simulator=verilator or vcs,log=str(log),
                      warnings=warnings,command=cmd)
        rc=0
    except Exception as e:
        status.update(status='FAIL',reason=str(e),log=str(log));rc=1
    (output/'rtl_status.json').write_text(json.dumps(status,indent=2))
    (output/f'{name}_status.json').write_text(json.dumps(status,indent=2))
    print(json.dumps(status,indent=2));return rc
if __name__=='__main__':sys.exit(main())
