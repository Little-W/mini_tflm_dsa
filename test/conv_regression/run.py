#!/usr/bin/env python3
"""Verify the unified NPU with generated tensors and a complete memory comparison."""
import argparse, hashlib, json, os, re, subprocess, sys, tarfile, time
from pathlib import Path

a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--out',type=Path);a.add_argument('--verilator',required=True);a.add_argument('--sizes',nargs='+',type=int,default=[4,8,16]);a.add_argument('--pcr',action='store_true');a.add_argument('--skip-build',action='store_true');a.add_argument('--pcr-only',action='store_true');a.add_argument('--compare',type=Path);a.add_argument('--baseline-ref',help='Generate and run a baseline from this local Git commit before comparing current results');a.add_argument('--jobs',type=int,default=2);x=a.parse_args()
r=x.root.resolve();out=(x.out or r/'build/conv_regression').resolve();out.mkdir(parents=True,exist_ok=True)
if x.compare and x.baseline_ref:
    a.error('--compare and --baseline-ref are mutually exclusive')
if x.baseline_ref:
    commit=subprocess.check_output(['git','rev-parse',x.baseline_ref+'^{commit}'],cwd=r,text=True).strip()
    baseline_root=out/'baseline_source'
    baseline_root.mkdir(exist_ok=True)
    previous=baseline_root/'baseline_source.json'
    if previous.exists() and json.loads(previous.read_text())['commit']!=commit:
        raise RuntimeError('baseline output directory belongs to another commit; choose a fresh --out')
    # Extract sources at runtime; no source snapshot or generated vector is
    # shipped as an input. Limit extraction to dependencies of the real benches.
    selected=['rtl/npu','rtl/common','test/dep_modules',
              'veri/top_regression','drivers/gempact_tiling.h']
    proc=subprocess.Popen(['git','archive',commit,'--',*selected],cwd=r,stdout=subprocess.PIPE)
    extracted={}
    with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
        for member in archive:
            name=Path(member.name)
            if not member.isfile() or name.suffix not in ('.sv','.v','.svh','.py','.h'):
                continue
            if name.is_absolute() or '..' in name.parts:
                raise RuntimeError('unsafe Git archive path')
            data=archive.extractfile(member).read()
            target=baseline_root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            extracted[str(name)]=hashlib.sha256(data).hexdigest()
    if proc.wait():raise RuntimeError('git archive baseline failed')
    previous.write_text(json.dumps({'commit':commit,'source_sha256':extracted},indent=2)+'\n')
    baseline_out=out/'baseline'
    child=[sys.executable,Path(__file__).resolve(),'--root',baseline_root,'--out',baseline_out,
           '--verilator',x.verilator,'--jobs',str(x.jobs),'--sizes',*map(str,x.sizes)]
    if x.pcr:child.append('--pcr')
    if x.pcr_only:child.append('--pcr-only')
    if x.skip_build:child.append('--skip-build')
    print('GENERATED_BASELINE',commit,flush=True)
    with (out/'baseline_run.log').open('w') as log:
        log.write('COMMAND: '+repr(list(map(str,child)))+'\n');log.flush()
        result=subprocess.run(list(map(str,child)),cwd=r,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        print((out/'baseline_run.log').read_text()[-8000:],flush=True)
        raise SystemExit(result.returncode)
    x.compare=baseline_out/'summary.json'
metrics=out/'npu_metrics.sv'
metrics.write_text('''`timescale 1ns/1ps
module npu_metrics;
  longint unsigned cycle=0,start_cycle=0,end_cycle=0,ar_requests=0,ar_bytes=0,r_beats=0,w_bytes=0;
  bit started=0,completed=0;
  always @(posedge tb_npu_top.clk) if(tb_npu_top.rst_n)begin
    cycle=cycle+1;
    if(tb_npu_top.calc_start && !started)begin started=1;start_cycle=cycle;end
    if(started && !completed && tb_npu_top.done_valid)begin end_cycle=cycle;completed=1;end
    if(tb_npu_top.m_axi_arvalid && tb_npu_top.m_axi_arready)begin
      ar_requests=ar_requests+1;ar_bytes=ar_bytes+((64'(tb_npu_top.m_axi_arlen)+1)<<tb_npu_top.m_axi_arsize);
    end
    if(tb_npu_top.m_axi_rvalid && tb_npu_top.m_axi_rready)r_beats=r_beats+1;
    if(tb_npu_top.m_axi_wvalid && tb_npu_top.m_axi_wready)w_bytes=w_bytes+64'($countones(tb_npu_top.m_axi_wstrb));
  end
  final $display("[NPU_METRICS] completed=%0d cycles=%0d ar_requests=%0d ar_bytes=%0d r_beats=%0d w_bytes=%0d",completed,end_cycle-start_cycle,ar_requests,ar_bytes,r_beats,w_bytes);
endmodule
bind tb_npu_top npu_metrics u_npu_metrics();
''')
summary={'repository':str(r),'commit':json.loads((r/'baseline_source.json').read_text())['commit'] if (r/'baseline_source.json').exists() else subprocess.check_output(['git','rev-parse','HEAD'],cwd=r,text=True).strip(),'verilator':str(x.verilator),'version':subprocess.check_output([x.verilator,'--version'],text=True).strip(),'builds':{},'cases':[],'vectors_generated_each_run':True,'baseline_ref':x.baseline_ref}
def save(): (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
def run(cmd,log,timeout=600):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as f:
        f.write('COMMAND: '+repr(list(map(str,cmd)))+'\n');f.flush()
        try: q=subprocess.run(list(map(str,cmd)),cwd=r,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.TimeoutExpired: f.write('\nTIMEOUT\n');return 124
    return q.returncode

def build(size,pcr=False):
    tag='pcr16' if pcr else f's{size}'
    d=out/tag;d.mkdir(exist_ok=True);src=sorted((r/'rtl/npu').rglob('*.sv'))+sorted((r/'rtl/npu').rglob('*.v'))+[r/'rtl/common/pseudo_dual_port_ram.v']
    src += [r/'test/dep_modules/ddr_axi_mem_model.sv',Path(__file__).resolve().parent/'tb_npu_top.sv']
    src += [metrics]
    flags=['--binary','--timing','--assert','-sv','--top-module','tb_npu_top','-Wno-fatal','--output-groups','0','--output-split','10000',f'-I{r/"rtl/npu/gempact"}',f'-DTB_SIZE={size}','-DTB_IA_CACHE_BLOCKS=4','-DTB_PS_FRAME_COUNT=16','-DTB_AXI_READ_OUTSTANDING=4','-DTB_DATA_WIDTH=16','-DTB_WEIGHT_WIDTH=16','-DTB_MEM_WORDS=131072','--Mdir',str(d/'obj'),'-j',str(x.jobs),'-CFLAGS','-std=c++20 -O1','-MAKEFLAGS','CFG_CXXFLAGS_PCH_I=-include OPT_FAST=-O1 OPT_SLOW=-O0']
    if pcr: flags += ['-DGEMPACT_PS_COMPRESS=1','-DGEMMORA_PS_POOL_BYTES=12288']
    cmd=[x.verilator,*flags,*src]
    dependencies=src+sorted((r/'rtl/npu').rglob('*.svh'))
    source_before={str(p.relative_to(r)) if p.is_relative_to(r) else '@test/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    manifest_path=d/'build.json'
    expected={'size':size,'pcr':pcr,'flags':[str(flag).replace(str(r),'@ROOT').replace(str(out),'@OUT') for flag in flags]}
    print('BUILD',tag,flush=True)
    if x.skip_build:
        manifest=json.loads(manifest_path.read_text())
        if manifest['sources']!=source_before or manifest['parameters']!=expected or manifest['returncode']:
            raise RuntimeError('cached GEMM executable source/parameters differ; remove --skip-build')
        if not (d/'obj/Vtb_npu_top').is_file():raise RuntimeError('cached executable missing')
        if manifest.get('binary_sha256')!=hashlib.sha256((d/'obj/Vtb_npu_top').read_bytes()).hexdigest():
            raise RuntimeError('cached executable hash differs or was not recorded; remove --skip-build')
        code=0
    else:
        code=run(cmd,d/'compile.log',1800)
    txt=(d/'compile.log').read_text() if (d/'compile.log').exists() else ''
    warnings={w:len(re.findall(r'%Warning-'+re.escape(w)+':',txt)) for w in sorted(set(re.findall(r'%Warning-([^:]+):',txt)))}
    source_after={str(p.relative_to(r)) if p.is_relative_to(r) else '@test/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    if source_before!=source_after:code=125
    summary['builds'][tag]={'returncode':code,'warnings':warnings,'command':list(map(str,cmd)),'parameters':expected,'sources':source_before,'sources_unchanged_during_build':source_before==source_after}
    if x.skip_build:
        summary['builds'][tag]={**manifest,'reused_binary':True,'source_and_flags_revalidated':True}
    else:
        if code==0:
            summary['builds'][tag]['binary_sha256']=hashlib.sha256((d/'obj/Vtb_npu_top').read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(summary['builds'][tag],indent=2)+'\n')
    save()
    if code: print('BUILD FAILED',tag,txt[-3000:],flush=True);return
    specs=[('ws_s8_tail',0,1,False,True),('is_s8_tail',1,1,False,True),('ws_s16_tail',0,2,False,True),('is_s16_per_channel',1,2,True,True),('ws_s16_output',0,2,False,True),('ws_s8_per_channel',0,1,True,True)]
    if pcr: specs=[('pcr_ws',0,1,False,True),('pcr_is',1,1,False,True)]
    for idx,(name,mode,dtype,pc,rand) in enumerate(specs):
        cd=d/name;cd.mkdir(exist_ok=True);case=cd/'case'
        dims=([129,53,35] if mode else [35,53,129]) if pcr else [size+3,2*size+5,size+5]
        cmd=[sys.executable,r/'veri/top_regression/gen_mem.py','--out_dir',case,'--size',size,'--ia_cache_blocks',4,'--ps_frame_count',16,'--mem_words',131072,'--K',dims[0],'--N',dims[1],'--M',dims[2],'--lhs_dtype',dtype,'--dataflow_mode',mode,'--ia_reuse_num',2,'--w_reuse_num',8 if pcr else 2,'--random','--random_quant','--seed',1000+size*10+idx,'--lhs_zp',0 if pcr or name=='ws_s16_output' else 3,'--rhs_zp',0]
        if pc:cmd += ['--per_channel']
        if name=='ws_s16_output':cmd += ['--int16_output']
        cmd += ['--tight_strides']
        gen=run(cmd,cd/'generate.log')
        sim=[d/'obj/Vtb_npu_top',f'+INIT_MEM={case}/init.mem',f'+GOLDEN_MEM={case}/golden.mem',f'+CASE_MEM={case}/config.mem','+DDR_RAND_LAT=1','+DDR_CMD_MAX_LAT=3','+DDR_W_MAX_LAT=2','+DDR_RSP_MAX_LAT=5','+DDR_SEED=55','+TB_TIMEOUT_CYCLES=2000000','+FULL_MEM_CHECK']
        rc=run(sim,cd/'run.log',300) if gen==0 else -1
        txt=(cd/'run.log').read_text() if (cd/'run.log').exists() else ''
        ok=rc==0 and '[TB] PASS' in txt and '[TB] FAIL' not in txt and '[TB] FATAL' not in txt
        line=next((l for l in txt.splitlines() if '[NPU_METRICS]' in l),'')
        measurement={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)}
        if pcr:
            storage=next((l for l in txt.splitlines() if '[PS_STORAGE_METRICS]' in l),'')
            measurement.update({'ps_'+k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',storage)})
        summary['cases'].append({'tag':tag,'name':name,'returncode':rc,'passed':ok,'metrics':measurement,'generate_command':list(map(str,cmd)),'run_command':list(map(str,sim)),'log':str(cd/'run.log')});save()
        print(tag,name,'PASS' if ok else 'FAIL',measurement,flush=True)
        if not ok:print(txt[-1800:],flush=True)
if not x.pcr_only:
    for s in x.sizes:build(s)
if x.pcr:build(16,True)
summary['passed']=all(v['returncode']==0 for v in summary['builds'].values()) and all(v['passed'] for v in summary['cases']) and bool(summary['cases']);save()
if x.compare:
    baseline=json.loads(x.compare.read_text())
    before={(c['tag'],c['name']):c for c in baseline['cases']}
    comparisons=[]
    for c in summary['cases']:
        b=before.get((c['tag'],c['name']))
        same=b is not None and b['passed'] and c['passed'] and b['metrics']==c['metrics']
        comparisons.append({'tag':c['tag'],'name':c['name'],'identical':same,
                            'before':None if b is None else b['metrics'],'after':c['metrics']})
    comparison_ok=len(comparisons)==len(before) and all(c['identical'] for c in comparisons)
    summary['baseline_comparison']={'reference':str(x.compare),'identical':comparison_ok,'cases':comparisons}
    summary['passed']=summary['passed'] and comparison_ok;save()
print('BASELINE_RESULT',summary['passed'],len(summary['cases']),flush=True)
sys.exit(0 if summary['passed'] else 1)
