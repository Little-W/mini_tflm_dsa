#!/usr/bin/env python3
"""Raw NHWC -> real NPU -> NHWC, checked against direct C + NMSIS math."""
import argparse
import ctypes as ct
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'veri/top_regression'))
from host_tiling import plan

WORDS=131072
SENTINEL=bytes.fromhex('c33ca55a')

def command(cmd,log,cwd=ROOT,timeout=900):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as f:
        f.write('COMMAND: '+repr([str(x) for x in cmd])+'\n');f.flush()
        try:r=subprocess.run([str(x) for x in cmd],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
        except subprocess.TimeoutExpired:f.write('\nTIMEOUT\n');return 124
    return r.returncode

def sparse_mem(path,image):
    previous=-2
    with path.open('w') as f:
        for i in range(len(image)//4):
            word=image[4*i:4*i+4]
            if word!=SENTINEL:
                if i!=previous+1:f.write(f'@{i:08x}\n')
                f.write(f'{int.from_bytes(word,"little"):08x}\n');previous=i

def make_reference(out):
    lib=out/'reference.so'
    cmd=['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-include',HERE/'host_compat.h',
         '-I',ROOT/'drivers/tflm/NMSIS/NN/Include',HERE/'reference_conv.c','-o',lib]
    if command(cmd,out/'reference_build.log'):
        raise RuntimeError((out/'reference_build.log').read_text())
    ref=ct.CDLL(str(lib));ref.reference_conv.restype=ct.c_int
    return ref

def task(out,size,ref,*,name='conv3x3',h=5,w=5,c=3,gc=None,go=0,kh=3,kw=3,
         oh=None,ow=None,sh=1,sw=1,dh=1,dw=1,ph=1,pw=1,co=5,offset=-7,
         bypass=False,per_channel=True,seed=123,error=0,inject=False,mutate=False,
         input_base=0x10003,dst_stride=None,dst_offset=0,positive_shift=False,
         rhs_base=0x20001,bias_base=0x30000,qmult_base=0x31000,qshift_base=0x32000,
         expect_once=False,dataflow=0,requested_r=2,requested_w=2):
    if dataflow not in (0,1):raise ValueError('dataflow must be 0 (WS) or 1 (IS)')
    gc=c if gc is None else gc
    oh=(h+2*ph-dh*(kh-1)-1)//sh+1 if oh is None else oh
    ow=(w+2*pw-dw*(kw-1)-1)//sw+1 if ow is None else ow
    dst_stride=co if dst_stride is None else dst_stride
    d=out/name;d.mkdir(parents=True,exist_ok=True)
    rng=random.Random(seed)
    data=[rng.randint(-15,15) for _ in range(h*w*c)]
    if len(data)>=3:data[0:3]=[-128,127,-1]
    weight=[rng.randint(-8,7) for _ in range(co*kh*kw*gc)]
    bias=[rng.randint(-300,300) for _ in range(co)]
    mult=[rng.randint(0x40000000,0x7fffffff) for _ in range(co)]
    shift=[(-7-(i%4)) for i in range(co)]
    if positive_shift:
        data=[(i%3)-1 for i in range(len(data))];weight=[(i%3)-1 for i in range(len(weight))]
        bias=[i-2 for i in range(co)];shift=[[-1,0,1,2][i%4] for i in range(co)]
    if not per_channel:mult=[mult[0]]*co;shift=[shift[0]]*co
    output_offset=-3;amin=-117;amax=109
    p=[h,w,c,gc,go,kh,kw,oh,ow,co,sh,sw,dh,dw,ph,pw,offset,output_offset,amin,amax]
    a=(ct.c_int8*len(data))(*data);b=(ct.c_int8*len(weight))(*weight)
    bias_c=(ct.c_int32*co)(*bias);mult_c=(ct.c_int32*co)(*mult);shift_c=(ct.c_int32*co)(*shift)
    output=(ct.c_int8*(oh*ow*co))();acc=(ct.c_int32*(oh*ow*co))()
    rc=ref.reference_conv(a,b,bias_c,mult_c,shift_c,(ct.c_int32*len(p))(*p),output,acc)
    if rc:raise RuntimeError('reference accumulator exceeded supported INT32')
    image=bytearray(SENTINEL*WORDS)
    rhs=rhs_base;bb=bias_base;qb=qmult_base;qs=qshift_base;dst=0x40003+dst_offset
    image[input_base:input_base+len(data)]=bytes(x&255 for x in data)
    image[rhs:rhs+len(weight)]=bytes(x&255 for x in weight)
    for base,values in [(bb,bias),(qb,mult),(qs,shift)]:
        for i,v in enumerate(values):image[base+4*i:base+4*i+4]=(v&0xffffffff).to_bytes(4,'little')
    golden=bytearray(image)
    if error==0:
        for row in range(oh*ow):
            golden[dst+row*dst_stride:dst+row*dst_stride+co]=bytes(output[row*co+i]&255 for i in range(co))
    sparse_mem(d/'init.mem',image);sparse_mem(d/'golden.mem',golden)
    k=oh*ow;n=kh*kw*gc
    tiling=plan(k,co,size,4,16,requested_r,requested_w,bool(dataflow),per_channel)
    cfg=[0]*64
    values={0:0x4e505531,1:size,2:4,3:k,4:n,5:co,6:tiling['ia_reuse'],7:tiling['w_reuse'],
            8:dataflow,9:16,10:WORDS,11:WORDS,12:1,13:int(per_channel),14:input_base,15:rhs,
            16:bb,17:dst,18:math.ceil(n/size)*size*2,19:n,20:dst_stride,21:0,22:0,
            23:output_offset,24:qb if per_channel else mult[0],25:qs if per_channel else shift[0],
            26:amin,27:amax,28:0,30:tiling['row_groups']|(tiling['col_groups']<<16),
            31:tiling['row_tail_tiles']|(tiling['col_tail_tiles']<<16),32:1,
            33:input_base,34:h,35:w,36:c,37:gc,38:go,39:kh,40:kw,41:oh,42:ow,
            43:sh,44:sw,45:dh,46:dw,47:ph,48:pw,49:offset,50:int(bypass),51:0,
            52:error,53:int(inject),56:int(mutate),58:int(expect_once)}
    if error==1:values[43]=0
    for i,v in values.items():cfg[i]=v&0xffffffff
    (d/'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
    required=set();logical_uses=0;padding_zeros=0
    for y in range(oh):
        for x in range(ow):
            for ky in range(kh):
                for kx in range(kw):
                    iy=y*sh+ky*dh-ph;ix=x*sw+kx*dw-pw
                    if 0<=iy<h and 0<=ix<w:
                        for channel in range(gc):
                            required.add(input_base-0x10000+(iy*w+ix)*c+go+channel)
                        logical_uses+=gc
                    else:padding_zeros+=gc
    with (d/'required.mem').open('w') as f:
        f.write('@00000000\n0\n')
        for address in sorted(required):f.write(f'@{address:08x}\n1\n')
    meta=dict(name=name,size=size,parameters=p,per_channel=per_channel,bypass=bypass,
              expected_error=error,seed=seed,outputs=oh*ow*co,reference='direct C convolution + unmodified repository riscv_nn_requantize',
              input_base=input_base,input_bytes=len(data),weight_bytes=len(weight),dst_stride=dst_stride,
              required_unique_input_bytes=len(required),logical_input_uses_per_output_channel=logical_uses,
              padding_zeros_per_output_channel=padding_zeros,expect_each_input_byte_once=expect_once,
              output_min=min(output),output_max=max(output),acc_min=min(acc),acc_max=max(acc),tiling=tiling,
              dataflow='IS' if dataflow else 'WS',requested_r=requested_r,requested_w=requested_w)
    (d/'case.json').write_text(json.dumps(meta,indent=2)+'\n')
    return d

def load_sparse(path):
    image=bytearray(SENTINEL*WORDS);cursor=0
    for word in path.read_text().split():
        if word.startswith('@'):cursor=int(word[1:],16)
        else:
            image[4*cursor:4*cursor+4]=int(word,16).to_bytes(4,'little');cursor+=1
    return image

def grouped_batches(out,size,ref):
    """Four commands share immutable input/weight arrays and one NHWC output."""
    tasks=[];initials=[];expected=[]
    h=4;w=5;c=6;gc=3;co=3;total_co=6
    for batch in range(2):
        for group in range(2):
            d=task(out,size,ref,name=f'batch{batch}_group{group}',h=h,w=w,c=c,gc=gc,go=group*gc,
                   kh=3,kw=3,ph=1,pw=1,co=co,dst_stride=total_co,
                   dst_offset=batch*h*w*total_co+group*co,input_base=0x10003+batch*h*w*c,
                   rhs_base=0x20001+group*co*3*3*gc,bias_base=0x30000+group*co*4,
                   qmult_base=0x31000+group*co*4,qshift_base=0x32000+group*co*4)
            tasks.append(d);initials.append(load_sparse(d/'init.mem'));expected.append(load_sparse(d/'golden.mem'))
    image=bytearray(SENTINEL*WORDS)
    for initial in initials:
        for i in range(WORDS):
            if initial[i*4:i*4+4]!=SENTINEL:
                # Disjoint allocations may share a 32-bit storage word. Merge bytes.
                for lane in range(4):
                    off=i*4+lane
                    if initial[off]!=SENTINEL[lane]:image[off]=initial[off]
    for d,gold in zip(tasks,expected):
        cfg=[int(v,16) for v in (d/'config.mem').read_text().split()]
        sparse_mem(d/'init.mem',image)
        for row in range(cfg[3]):
            base=cfg[17]+row*cfg[20]
            image[base:base+cfg[5]]=gold[base:base+cfg[5]]
        sparse_mem(d/'golden.mem',image)
    return tasks

def gemm_task(out,size,*,name='mixed_gemm_is',dataflow=1):
    d=out/name;d.mkdir(exist_ok=True)
    cmd=[sys.executable,ROOT/'veri/top_regression/gen_mem.py','--out_dir',d,'--size',size,
         '--ia_cache_blocks',4,'--ps_frame_count',16,'--mem_words',WORDS,'--K',size+1,
         '--N',size+3,'--M',size+2,'--lhs_dtype',2,'--dataflow_mode',dataflow,'--per_channel',
         '--random','--random_quant','--tight_strides','--seed',789]
    if command(cmd,d/'generate.log'):raise RuntimeError((d/'generate.log').read_text())
    cfg=[int(v,16) for v in (d/'config.mem').read_text().split()]+[0]*32
    (d/'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
    (d/'required.mem').write_text('@00000000\n0\n')
    return d

def build(out,size,verilator,jobs,cache_sets=32,cache_policy=2):
    npu=ROOT/'rtl/npu';pkg=npu/'conv/00_conv_im2col_pkg.sv'
    sources=[pkg]+[p for p in sorted(npu.rglob('*.sv')) if p!=pkg]+sorted(npu.rglob('*.v'))
    sources += [ROOT/'rtl/common/pseudo_dual_port_ram.v',HERE/'axi_memory.sv',HERE/'tb_conv_npu.sv']
    cmd=[verilator,'--binary','--timing','--assert','-sv','--top-module','tb_conv_npu','-Wno-fatal',
         f'-I{npu/"gempact"}',f'-DTB_SIZE={size}',f'-DTB_CONV_CACHE_SETS={cache_sets}',f'-DTB_CONV_CACHE_POLICY={cache_policy}','--Mdir',out/'obj','-j',jobs,
         '-CFLAGS','-std=c++20 -O1','-MAKEFLAGS','OPT_FAST=-O1 OPT_SLOW=-O0',*sources]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    rc=command(cmd,out/'compile.log',timeout=1200)
    text=(out/'compile.log').read_text()
    warnings={w:text.count('%Warning-'+w+':') for w in sorted(set(re.findall(r'%Warning-([^:]+):',text)))}
    after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    result={'returncode':rc,'warnings':warnings,'command':[str(v) for v in cmd],
            'size':size,'cache_sets':cache_sets,'cache_ways':2,'cache_line_bytes':16,'cache_policy':cache_policy,
            'source_sha256':before,'sources_unchanged_during_build':before==after}
    (out/'build.json').write_text(json.dumps(result,indent=2)+'\n')
    if rc:raise RuntimeError(text[-6000:])
    if before!=after:raise RuntimeError('RTL sources changed during compilation; rebuild after edits complete')
    return out/'obj/Vtb_conv_npu'

def run_suite(binary,out,name,tasks,no_random=False):
    suite=out/(name+'.suite')
    suite.write_text(''.join(f'{d}/config.mem {d}/init.mem {d}/golden.mem {d}/required.mem\n' for d in tasks))
    cmd=[binary,f'+SUITE={suite}']+(['+NO_RANDOM_WAIT'] if no_random else [])
    rc=command(cmd,out/(name+'.log'),timeout=300)
    text=(out/(name+'.log')).read_text()
    measurements=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in text.splitlines() if line.startswith('CONV_TASK_PASS')]
    ok=rc==0 and f'CONV_NPU_PASS tasks={len(tasks)}' in text
    result=dict(name=name,passed=ok,returncode=rc,tasks=[str(t) for t in tasks],measurements=measurements,command=[str(v) for v in cmd])
    print(name,'PASS' if ok else 'FAIL',measurements,flush=True)
    if not ok:print(text[-6000:],flush=True)
    return result

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--sizes',type=int,nargs='+',default=[4,8,16]);a.add_argument('--out',type=Path,default=ROOT/'build/conv_npu');a.add_argument('--verilator',default='verilator');a.add_argument('--jobs',type=int,default=2);a.add_argument('--cache-policy',type=int,choices=[0,1,2],default=2);a.add_argument('--cache-sets',type=int,default=32);a.add_argument('--smoke',action='store_true');a.add_argument('--skip-build',action='store_true');a.add_argument('--reuse-audit',action='store_true',help='Focused byte-level AXI reuse audit, including output-channel group replay');x=a.parse_args()
    if x.cache_sets<2 or x.cache_sets&(x.cache_sets-1):a.error('--cache-sets must be a power of two >=2')
    out=x.out.resolve();out.mkdir(parents=True,exist_ok=True);ref=make_reference(out)
    reference_sources=[HERE/'reference_conv.c',HERE/'host_compat.h',ROOT/'drivers/tflm/NMSIS/NN/Include/riscv_nnsupportfunctions.h']
    summary={'verilator':subprocess.check_output([x.verilator,'--version'],text=True).strip(),
             'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
             'reference_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in reference_sources},
             'cycle_definition':'calc_start accepted through done_valid; excludes deliberate 3-cycle completion backpressure',
             'scope':'input_byte_reuse_audit' if x.reuse_audit else 'full_functional_regression',
             'cases':[]}
    for size in x.sizes:
        sd=out/f's{size}';sd.mkdir(exist_ok=True)
        if x.skip_build:
            manifest=json.loads((sd/'build.json').read_text())
            requested={'size':size,'cache_sets':x.cache_sets,'cache_ways':2,'cache_line_bytes':16,'cache_policy':x.cache_policy}
            if any(manifest.get(key)!=value for key,value in requested.items()):
                raise RuntimeError('stale executable parameters: size/cache sets/ways/line/policy differ; omit --skip-build')
            for name,digest in manifest['source_sha256'].items():
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError(f'stale executable: {name} changed; omit --skip-build')
            binary=sd/'obj/Vtb_conv_npu'
        else:
            binary=build(sd,size,x.verilator,x.jobs,cache_sets=x.cache_sets,cache_policy=x.cache_policy)
        if x.reuse_audit:
            cache=task(sd,size,ref,name='conv3x3_cache',co=size+1,expect_once=True)
            bypass=task(sd,size,ref,name='conv3x3_bypass',co=size+1,bypass=True)
            replay_cache=task(sd,size,ref,name='channel_replay_cache',co=33,expect_once=True)
            replay_bypass=task(sd,size,ref,name='channel_replay_bypass',co=33,bypass=True)
            sparse=task(sd,size,ref,name='sparse_stride_dilation',h=9,w=10,c=5,kh=2,kw=3,sh=2,sw=1,dh=2,dw=2,ph=1,pw=2,co=size+3,offset=127,input_base=0x10ffd,rhs_base=0x20ffd)
            grouped=task(sd,size,ref,name='sparse_group',h=6,w=7,c=8,gc=3,go=4,kh=3,kw=2,ph=1,pw=0,co=5,dst_stride=11,dst_offset=4,offset=-127)
            for name,tasks in [('cache_fixed',[cache]),('bypass_fixed',[bypass]),('channel_replay_cache',[replay_cache]),('channel_replay_bypass',[replay_bypass]),('sparse_input_usage',[sparse,grouped])]:
                summary['cases'].append(run_suite(binary,sd,name,tasks,True))
                (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            continue
        smoke=task(sd,size,ref,name='conv3x3_cache',co=size+1,expect_once=True)
        summary['cases'].append(run_suite(binary,sd,'smoke',[smoke]))
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not summary['cases'][-1]['passed']:break
        if x.smoke:continue
        bypass=task(sd,size,ref,name='conv3x3_bypass',co=size+1,bypass=True)
        rect=task(sd,size,ref,name='rect_stride_dilation',h=9,w=10,c=5,kh=2,kw=3,sh=2,sw=1,dh=2,dw=2,ph=1,pw=2,co=size+3,offset=127,input_base=0x10ffd,rhs_base=0x20ffd)
        group=task(sd,size,ref,name='group_channel_offset',h=6,w=7,c=8,gc=3,go=4,kh=3,kw=2,ph=1,pw=0,co=5,dst_stride=11,dst_offset=4,offset=-127)
        pos=task(sd,size,ref,name='signed_rounding_positive_shift',h=3,w=5,c=2,kh=1,kw=1,ph=0,pw=0,co=7,offset=0,positive_shift=True)
        mutate=task(sd,size,ref,name='latched_config',co=size+1,mutate=True,seed=321)
        failed=task(sd,size,ref,name='injected_rresp',co=size+1,error=3,inject=True)
        invalid=task(sd,size,ref,name='invalid_geometry',co=size+1,error=1)
        recovery=task(sd,size,ref,name='recovery_changed_input',co=size+1,seed=456)
        gemm=gemm_task(sd,size)
        grouped=grouped_batches(sd,size,ref)
        for name,tasks,fixed in [('cache_fixed',[smoke],True),('bypass_fixed',[bypass],True),('geometry',[rect,group,pos,mutate],False),('error_recovery',[failed,recovery,invalid,recovery],False),('mixed_conv_gemm',[smoke,gemm,recovery],False),('batch_group_commands',grouped,False)]:
            summary['cases'].append(run_suite(binary,sd,name,tasks,fixed))
            (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    summary['passed']=all(c['passed'] for c in summary['cases'])
    summary['task_count']=sum(len(c['measurements']) for c in summary['cases'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('CONV_SYSTEM_RESULT',summary['passed'],flush=True)
    return 0 if summary['passed'] else 1

if __name__=='__main__':sys.exit(main())
