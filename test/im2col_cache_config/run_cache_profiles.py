#!/usr/bin/env python3
"""Check input-cache capacity and data using the production im2col frontend."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from scripts.capacity.config import selected_config

CAPACITIES=(512,1024,2048,4096,8192,16384,32768,65536)
RTL_NAMES=('conv_im2col_pkg.sv','conv_sdp_ram.sv',
           'conv_next_use_predictor.sv','conv_axi_span_reader.sv',
           'conv_read_cache.sv','conv_im2col_frontend.sv',
           'conv_ia_write_adapter.sv','conv_ia_tile_path.sv')


def rtl_path(name):
    directory='dma/cache' if name in {'conv_sdp_ram.sv','conv_next_use_predictor.sv','conv_read_cache.sv'} else 'conv'
    return ROOT/'rtl/npu'/directory/name


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command,log,*,timeout=600):
    with log.open('w') as output:
        output.write('COMMAND: '+repr([str(x) for x in command])+'\n')
        output.flush()
        subprocess.run([str(x) for x in command],cwd=ROOT,stdout=output,
                       stderr=subprocess.STDOUT,timeout=timeout,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/im2col_cache_config/cache_profiles')
    parser.add_argument('--capacities',type=int,nargs='+',default=list(CAPACITIES))
    parser.add_argument('--traffic-capacities',type=int,nargs='*',default=[512,4096,65536])
    parser.add_argument('--verilator',default=shutil.which('verilator') or 'verilator')
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    if any(x not in CAPACITIES for x in args.capacities+args.traffic_capacities):
        parser.error('Capacities must be powers of two in 512..65536')
    if len(set(args.capacities))!=len(args.capacities):parser.error('Repeated capacity')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    vector=out/'vectors.txt'
    execute([sys.executable,ROOT/'test/conv_frontend/tests/gen_rtl_vectors.py',
             '--size','16','--out',vector],out/'vectors.log')
    files=[rtl_path(n) for n in RTL_NAMES]
    files += [ROOT/'test/conv_frontend/tests/tb_conv_im2col_frontend.sv',HERE/'tb_frontend_profile.sv']
    tracked=files+[Path(__file__),ROOT/'test/conv_frontend/tests/gen_rtl_vectors.py',
                   ROOT/'test/conv_frontend/tests/run_model_tests.py',
                   ROOT/'test/conv_frontend/model/conv_model.py']
    hashes={str(p.relative_to(ROOT)):digest(p) for p in tracked}
    summary={'passed':False,'complete':False,'selected_config_bytes':selected_config()['IM2COL_CACHE_BYTES'],
             'vector_sha256':digest(vector),'vector_file':str(vector),'source_sha256':hashes,
             'verilator':subprocess.check_output([args.verilator,'--version'],text=True).strip(),
             'capacities':args.capacities,'bus_bits':32,
             'traffic_scope':'Production frontend with channel-position-tap window traversal',
             'profiles':[],'traffic_profiles':[]}
    for capacity in args.capacities:
        folder=out/str(capacity);folder.mkdir(exist_ok=True)
        command=[args.verilator,'--binary','--timing','--assert','-Wall','-Wno-fatal',
                 '-DCONV_ASSERT','--top-module','tb_frontend_profile',f'-GCACHE_BYTES={capacity}',
                 '--Mdir',folder/'obj','-j',args.jobs,*files]
        execute(command,folder/'build.log')
        binary=folder/'obj/Vtb_frontend_profile'
        execute([binary,f'+VECTORS={vector}'],folder/'run.log',timeout=300)
        text=(folder/'run.log').read_text()
        if f'IM2COL_RAM_CAPACITY_PASS bytes={capacity} sets={capacity//32}' not in text:
            raise RuntimeError('Physical RAM check is absent')
        if 'RTL_FRONTEND_PASS' not in text:raise RuntimeError('Frontend result is absent')
        rows=[]
        for line in text.splitlines():
            if line.startswith('RTL_FRONTEND_JOB_PASS '):
                rows.append({k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)})
        expected_jobs=int(vector.read_text().splitlines()[0])
        if len(rows)!=expected_jobs or [r['job'] for r in rows]!=list(range(expected_jobs)):
            raise RuntimeError('Incomplete frontend case set')
        profile={'passed':True,'bytes':capacity,'sets':capacity//32,'ways':2,'line_bytes':16,
                 'jobs':len(rows),'tiles':sum(x['tiles'] for x in rows),
                 'cases':rows,'binary_sha256':digest(binary),'log_sha256':digest(folder/'run.log'),
                 'build_log_sha256':digest(folder/'build.log'),'command':[str(x) for x in command]}
        (folder/'summary.json').write_text(json.dumps(profile,indent=2)+'\n')
        summary['profiles'].append(profile)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({'bytes':capacity,'jobs':len(rows),'passed':True}),flush=True)
    traffic_files=[rtl_path(n) for n in RTL_NAMES[:7]]
    traffic_files += [ROOT/'test/conv_reuse/axi_counted_memory.sv',ROOT/'test/windowed_cache/tb_windowed_cache.sv']
    traffic_hashes={str(p.relative_to(ROOT)):digest(p) for p in traffic_files}
    for capacity in args.traffic_capacities:
        folder=out/('traffic_'+str(capacity));folder.mkdir(exist_ok=True)
        command=[args.verilator,'--binary','--timing','--assert','-DCONV_ASSERT','-Wall','-Wno-fatal',
                 '--top-module','tb_windowed_cache',f'-GCACHE_SETS={capacity//32}',
                 '-GCACHE_POLICY=3','-GPREFETCH=1','--Mdir',folder/'obj','-j',args.jobs,*traffic_files]
        execute(command,folder/'build.log')
        binary=folder/'obj/Vtb_windowed_cache'
        execute([binary],folder/'run.log',timeout=300)
        text=(folder/'run.log').read_text()
        if 'WINDOW_CACHE_PASS' not in text:raise RuntimeError('Window cache result is absent')
        cases=[]
        for line in text.splitlines():
            if line.startswith('WINDOW_CACHE_CASE '):
                row=dict(re.findall(r'(\w+)=([^ ]+)',line))
                cases.append({k:(v if k=='name' else float(v) if '.' in v else int(v)) for k,v in row.items()})
        if len(cases)!=9 or any(x['cache_bytes']!=capacity for x in cases):
            raise RuntimeError('Window cache case set or capacity differs')
        profile={'passed':True,'bytes':capacity,'cases':cases,'source_sha256':traffic_hashes,
                 'binary_sha256':digest(binary),'log_sha256':digest(folder/'run.log'),
                 'build_log_sha256':digest(folder/'build.log'),'command':[str(x) for x in command]}
        (folder/'summary.json').write_text(json.dumps(profile,indent=2)+'\n')
        summary['traffic_profiles'].append(profile)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({'traffic_bytes':capacity,'cases':len(cases),'passed':True}),flush=True)
    for name,value in {**hashes,**traffic_hashes}.items():
        if digest(ROOT/name)!=value:raise RuntimeError('Verification source changed: '+name)
    summary['source_sha256'].update(traffic_hashes)
    summary.update(passed=True,complete=True,sources_unchanged=True,
                   frontend_jobs=sum(p['jobs'] for p in summary['profiles']),
                   frontend_tiles=sum(p['tiles'] for p in summary['profiles']),
                   traffic_cases=sum(len(p['cases']) for p in summary['traffic_profiles']))
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('passed','complete','frontend_jobs','frontend_tiles','traffic_cases')}))


if __name__=='__main__':main()
