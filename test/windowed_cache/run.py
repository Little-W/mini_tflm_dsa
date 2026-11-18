#!/usr/bin/env python3
"""Run actual shared-cache RTL using DW's channel/position/tap descriptor order."""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache-sets',type=int,default=128)
    p.add_argument('--cache-policy',type=int,default=3);p.add_argument('--no-prefetch',action='store_true')
    a=p.parse_args();pf=not a.no_prefetch
    out=ROOT/f'build/windowed_cache/s{a.cache_sets}_p{a.cache_policy}_pf{int(pf)}';out.mkdir(parents=True,exist_ok=True)
    files=[(ROOT/'rtl/npu/dma'/n if n.startswith('cache/') else ROOT/'rtl/npu/conv'/n) for n in ['conv_im2col_pkg.sv','cache/conv_sdp_ram.sv','cache/conv_next_use_predictor.sv','conv_axi_span_reader.sv','cache/conv_read_cache.sv','conv_im2col_frontend.sv']]
    files += [ROOT/'test/conv_reuse/axi_counted_memory.sv',ROOT/'test/windowed_cache/tb_windowed_cache.sv']
    import runpy
    files = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](files)
    source_sha={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in files+[Path(__file__)]}
    cmd=[shutil.which('verilator') or 'verilator','--binary','--timing','--assert','-DCONV_ASSERT','-DNPU_SIM_ASSERT','-Wall','-Wno-fatal','--top-module','tb_windowed_cache',f'-GCACHE_SETS={a.cache_sets}',f'-GCACHE_POLICY={a.cache_policy}',f'-GPREFETCH={int(pf)}','--Mdir',str(out/'obj'),'-j','2',*map(str,files)]
    with (out/'build.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    warnings=[line for line in (out/'build.log').read_text().splitlines() if line.startswith('%Warning')]
    reviewed={'UNUSEDSIGNAL','UNUSEDPARAM','BLKSEQ','PROCASSINIT','SYNCASYNCNET'}
    bad=[w for w in warnings if w.split(':',1)[0].removeprefix('%Warning-') not in reviewed]
    if bad:raise RuntimeError('lint diagnostics: '+repr(bad))
    with (out/'run.log').open('w') as f:subprocess.run([str(out/'obj/Vtb_windowed_cache')],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
    text=(out/'run.log').read_text();assert 'WINDOW_CACHE_PASS' in text
    rows=[]
    for line in text.splitlines():
        if line.startswith('WINDOW_CACHE_CASE '):
            row=dict(re.findall(r'(\w+)=([^ ]+)',line));rows.append({k:(v if k=='name' else float(v) if '.' in v else int(v)) for k,v in row.items()});print(line)
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest for name,digest in source_sha.items()):
        raise RuntimeError('Sources changed during verification')
    (out/'results.json').write_text(json.dumps({'status':'PASS','bus_bits':32,'cache_data_bytes':a.cache_sets*32,
        'policy':a.cache_policy,'prefetch':pf,'source_sha256':source_sha,
        'binary_sha256':hashlib.sha256((out/'obj/Vtb_windowed_cache').read_bytes()).hexdigest(),'cases':rows},indent=2)+'\n')
    print('WINDOW_CACHE_PASS '+str(out/'results.json'))
if __name__=='__main__':main()
