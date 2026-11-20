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
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from scripts.capacity.config import axi_data_width, selected_config
sys.path.insert(0,str(ROOT/'veri/top_regression'))
from host_tiling import plan
from gen_mem import cmsis_nn_requantize, nmsis_nn_requantize_s64, signed32

WORDS=131072
SENTINEL=bytes.fromhex('c33ca55a')

def payload_bound(size, r, w, stream_rows=None):
    rows = size*r if stream_rows is None else min(size*r, stream_rows)
    return size*4*rows*w

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

def accumulator_mem(path, values):
    path.write_text(''.join(f'{int(value)&0xffffffff:08x}\n' for value in values))

def gemm_accumulators(cfg, image):
    def value(address, width):
        return int.from_bytes(image[address:address+width], 'little', signed=True)
    width=2 if cfg[12] else 1
    accumulators=[]
    for row in range(cfg[3]):
        for col in range(cfg[5]):
            total=value(cfg[16]+4*col,4) if cfg[16] else 0
            for red in range(cfg[4]):
                lhs=value(cfg[14]+row*cfg[18]+red*width,width)+signed32(cfg[21])
                rhs=value(cfg[15]+col*cfg[19]+red,1)+signed32(cfg[22])
                total+=lhs*rhs
            accumulators.append(signed32(total))
    return accumulators

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
         expect_once=False,dataflow=0,requested_r=2,requested_w=2,inject_capacity=False,
         allow_capacity_failure=False,invalidate_geometry=False):
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
    accumulator_mem(d/'acc.mem', acc)
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
            52:error,53:int(inject),56:int(mutate),58:int(expect_once),59:int(inject_capacity),
            60:int(allow_capacity_failure)}
    if invalidate_geometry:values[43]=0
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
              dataflow='IS' if dataflow else 'WS',requested_r=requested_r,requested_w=requested_w,
              allow_capacity_failure=allow_capacity_failure)
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
    cfg=([int(v,16) for v in (d/'config.mem').read_text().split()]+[0]*64)[:64]
    (d/'config.mem').write_text(''.join(f'{v:08x}\n' for v in cfg))
    (d/'required.mem').write_text('@00000000\n0\n')
    accumulator_mem(d/'acc.mem',gemm_accumulators(cfg,load_sparse(d/'init.mem')))
    return d

def precision_task(out, size, *, name, dataflow=0, lhs_s16=True, output_s16=False,
                   rows=None,reduction=None,columns=None,requested_r=2,requested_w=2,
                   expected_error=0,inject_capacity=False,memory_bases=None):
    """Use full input ranges and compare every result before requantization."""
    d=out/name; d.mkdir(exist_ok=True)
    rows=size+1 if rows is None else rows
    red=2*size+3 if reduction is None else reduction
    cols=size+2 if columns is None else columns
    tiling=plan(rows,cols,size,4,16,requested_r,requested_w,bool(dataflow),not output_s16)
    rng=random.Random(8101+int(output_s16))
    lhs=[rng.randint(-32768,32767) if lhs_s16 else rng.randint(-128,127)
         for _ in range(rows*red)]
    lhs[:4]=[-32768,32767,-1,0] if lhs_s16 else [-128,127,-1,0]
    rhs=[rng.randint(-128,127) for _ in range(cols*red)]
    rhs[:4]=[-128,127,-1,0]
    bias=[rng.randint(-65536,65535) for _ in range(cols)]
    width=2 if lhs_s16 else 1
    lhs_base,rhs_base,bias_base,dst_base=0x1003,0x9003,0x11000,0x14003
    qmult_base,qshift_base=0x12000,0x13000
    if memory_bases is not None:
        lhs_base,rhs_base,bias_base,dst_base,qmult_base,qshift_base=memory_bases
        spans=sorted((start,start+length) for start,length in (
            (lhs_base,rows*red*width),(rhs_base,cols*red),(bias_base,cols*4),
            (dst_base,rows*cols*(2 if output_s16 else 1)),
            (qmult_base,cols*4),(qshift_base,cols*4)))
        if spans[0][0] <= 0 or spans[-1][1] > WORDS*4 or any(
                left[1] > right[0] for left,right in zip(spans,spans[1:])):
            raise ValueError('Operand and result memory spans must fit without overlap')
    mult=0x40000000
    shift=-12 if output_s16 else (-21 if lhs_s16 else (-14 if red>64 else -10))
    multipliers=[mult if output_s16 else mult+0x00100000*(col%13) for col in range(cols)]
    shifts=[shift if output_s16 else shift-(col%3) for col in range(cols)]
    output_offset=0 if output_s16 else -3
    act_min,act_max=(-32768,32767) if output_s16 else (-128,127)
    cfg=[0]*64
    settings={0:0x4e505531,1:size,2:4,3:rows,4:red,5:cols,
        6:tiling['ia_reuse'],7:tiling['w_reuse'],8:dataflow,9:16,10:WORDS,11:WORDS,
        12:int(lhs_s16),13:int(not output_s16),14:lhs_base,15:rhs_base,16:bias_base,17:dst_base,
        18:red*width,19:red,20:cols*(2 if output_s16 else 1),21:0,22:0,23:output_offset,
        24:mult if output_s16 else qmult_base,25:shift if output_s16 else qshift_base,
        26:act_min,27:act_max,28:int(output_s16),
        30:tiling['row_groups']|(tiling['col_groups']<<16),
        31:tiling['row_tail_tiles']|(tiling['col_tail_tiles']<<16),52:expected_error,
        59:int(inject_capacity)}
    for key,value in settings.items():cfg[key]=value&0xffffffff
    image=bytearray(SENTINEL*WORDS)
    for index,value in enumerate(lhs):
        image[lhs_base+width*index:lhs_base+width*(index+1)]=value.to_bytes(width,'little',signed=True)
    image[rhs_base:rhs_base+len(rhs)]=bytes(value&255 for value in rhs)
    for base,values in ((bias_base,bias),(qmult_base,multipliers),(qshift_base,shifts)):
        for index,value in enumerate(values):
            image[base+4*index:base+4*index+4]=(value&0xffffffff).to_bytes(4,'little')
    accumulators=gemm_accumulators(cfg,image)
    golden=bytearray(image)
    for index,value in enumerate(accumulators):
        col=index%cols
        scaled=(nmsis_nn_requantize_s64(value,mult,shift) if output_s16
                else cmsis_nn_requantize(value,multipliers[col],shifts[col]))
        result=max(act_min,min(act_max,scaled+output_offset))
        out_width=2 if output_s16 else 1
        if expected_error==0:
            golden[dst_base+out_width*index:dst_base+out_width*(index+1)]=result.to_bytes(out_width,'little',signed=True)
    sparse_mem(d/'init.mem',image);sparse_mem(d/'golden.mem',golden)
    accumulator_mem(d/'acc.mem',accumulators)
    (d/'config.mem').write_text(''.join(f'{value:08x}\n' for value in cfg))
    (d/'required.mem').write_text('@00000000\n0\n')
    (d/'case.json').write_text(json.dumps(dict(name=name,size=size,rows=rows,reduction=red,columns=cols,
        lhs_dtype='int16' if lhs_s16 else 'int8',rhs_dtype='int8',output_dtype='int16' if output_s16 else 'int8',
        dataflow='IS' if dataflow else 'WS',seed=8101+int(output_s16),tiling=tiling,
        expected_error=expected_error,requested_r=requested_r,requested_w=requested_w,
        inject_capacity=int(inject_capacity),
        acc_min=min(accumulators),acc_max=max(accumulators)),indent=2)+'\n')
    return d

def dense_cases(out,size,pool_bytes,force_raw):
    cases=[]
    for red,cols,mode,r,w,suffix in [(800,32,0,1,2,'ws'),
                                    (800,32,1,1,1,'is_r1'),
                                    (800,32,1,2,1,'is_r2'),
                                    (32,10,0,1,1,'ws'),(32,10,1,1,1,'is')]:
        tiling=plan(1,cols,size,4,16,r,w,bool(mode),True)
        sr,sc=(cols,1) if mode else (1,cols)
        frames=min((sc+size-1)//size,tiling['w_reuse'])
        bound=payload_bound(size,tiling['ia_reuse'],frames,sr)
        expected_error=int(force_raw and size==16 and red>size and bound>pool_bytes)
        cases.append(precision_task(out,size,name=f'dense_{red}_{cols}_{suffix}',
            rows=1,reduction=red,columns=cols,dataflow=mode,lhs_s16=False,
            requested_r=r,requested_w=w,expected_error=expected_error))
    cases.append(precision_task(out,size,name='late_axi_error',
        rows=2*size,reduction=size,columns=4*size,lhs_s16=False,
        requested_r=2,requested_w=4,expected_error=3,inject_capacity=3))
    cases.append(precision_task(out,size,name='single_k_no_ps',
        rows=2*size,reduction=size,columns=4*size,lhs_s16=False,
        requested_r=2,requested_w=4))
    return cases

def conv_window_cases(out,size,ref,pool_bytes,force_raw):
    profiles=([(0,1,1),(0,1,2),(1,1,1),(1,2,1)] if pool_bytes<=4096
              else [(0,2,2),(1,2,4),(1,2,8)])
    cases=[]
    for mode,r,w in profiles:
        sr,sc=(32,121) if mode else (121,32)
        bound=payload_bound(size,r,min((sc+size-1)//size,w),sr)
        expected_error=int(force_raw and bound>pool_bytes)
        cases.append(task(out,size,ref,name=f'conv2_{"is" if mode else "ws"}_r{r}_w{w}',
            h=13,w=13,c=16,kh=3,kw=3,ph=0,pw=0,co=32,dataflow=mode,
            requested_r=r,requested_w=w,seed=9231,error=expected_error,
            allow_capacity_failure=not force_raw and bound>pool_bytes))
    return cases

def source_files():
    filelist=ROOT/'veri/flist/dut_axil.f'
    sources=[]
    includes=[]
    for line in filelist.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('//'):continue
        if line.startswith('+incdir+'):
            includes.append((filelist.parent/line.removeprefix('+incdir+')).resolve())
        else:sources.append((filelist.parent/line).resolve())
    sources += [ROOT/'test/ps_compression/ps_stream_capture.sv',
                HERE/'axi_memory.sv',HERE/'tb_conv_npu.sv']
    import runpy
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    tracked=list(dict.fromkeys(sources+[filelist,Path(__file__).resolve(),HERE/'simulator.vlt',
        ROOT/'veri/top_regression/host_tiling.py',ROOT/'veri/top_regression/gen_mem.py']))
    tracked += [p for directory in includes for p in sorted(directory.glob('*.svh'))]
    return sources,includes,list(dict.fromkeys(tracked))

def build(out,size,verilator,jobs,cache_sets=None,cache_policy=3,
          ps_compress=False,pool_bytes=16384,force_raw=False,lint_only=False,
          bus_width=None,shared_bank_bytes=2048,shared_bank_count=0,ps_frame_count=16,
          build_timeout=7200):
    bus_width=axi_data_width(bus_width)
    if cache_sets is None:
        cache_sets=selected_config()['IM2COL_CACHE_BYTES']//32
    if cache_sets<2 or cache_sets&(cache_sets-1):
        raise ValueError('Cache sets must be a power of two >=2')
    if shared_bank_bytes not in (2048,4096,8192) or shared_bank_count not in (0,6,7,8,9):
        raise ValueError('Shared RAM requires 2/4/8 KiB banks and 6..9 physical banks')
    out=Path(out).resolve()
    sources,includes,tracked=source_files()
    out.mkdir(parents=True,exist_ok=True)
    rules=out/'compile_rules.mk'
    rules.write_text(
        '%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
        '$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n'
        '$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n'
        '$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n')
    defines=['-DNPU_SIM_ASSERT','-DCONV_ASSERT',f'-DTB_SIZE={size}',f'-DTB_CONV_CACHE_SETS={cache_sets}',f'-DTB_CONV_CACHE_POLICY={cache_policy}',
             f'-DTB_BUS_WIDTH={bus_width}',f'-DTB_SHARED_BANK_BYTES={shared_bank_bytes}',
             f'-DTB_SHARED_BANK_COUNT={shared_bank_count}',f'-DTB_PS_FRAME_COUNT={ps_frame_count}']
    if ps_compress:defines+=['-DGEMPACT_PS_COMPRESS=1',f'-DGEMMORA_PS_POOL_BYTES={pool_bytes}']
    if force_raw:defines+=['-DGEMMORA_PS_FORCE_RAW=1']
    cmd=[verilator,'--lint-only' if lint_only else '--binary','--timing','--assert','-sv',
         '--top-module','tb_conv_npu','-Wno-fatal','--output-groups','0',
         '--output-split','10000','--output-split-cfuncs','1000',
         *[f'-I{path}' for path in includes],*defines,'--Mdir',out/'obj','-j',jobs,
         '-CFLAGS','-std=c++20 -O1 --param ggc-min-expand=10 --param ggc-min-heapsize=32768',
         '-MAKEFLAGS',f'OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}',HERE/'simulator.vlt',*sources]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    rc=command(cmd,out/'compile.log',timeout=build_timeout)
    text=(out/'compile.log').read_text()
    warnings={w:text.count('%Warning-'+w+':') for w in sorted(set(re.findall(r'%Warning-([^:]+):',text)))}
    after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    result={'returncode':rc,'warnings':warnings,'command':[str(v) for v in cmd],
            'size':size,'bus_width':bus_width,'shared_bank_bytes':shared_bank_bytes,
            'shared_bank_count':shared_bank_count,'cache_sets':cache_sets,'cache_ways':2,'cache_line_bytes':16,'cache_data_bytes':cache_sets*32,'cache_policy':cache_policy,
            'ps_compress':ps_compress,'pool_bytes':pool_bytes,'force_raw':force_raw,'lint_only':lint_only,
            'ps_frame_count':ps_frame_count,
            'source_sha256':before,'sources_unchanged_during_build':before==after,
            'build_timeout_seconds':build_timeout}
    if rc==0 and not lint_only:
        result['binary_sha256']=hashlib.sha256((out/'obj/Vtb_conv_npu').read_bytes()).hexdigest()
    (out/'build.json').write_text(json.dumps(result,indent=2)+'\n')
    if rc:raise RuntimeError(text[-6000:])
    if before!=after:raise RuntimeError('RTL sources changed during compilation; rebuild after edits complete')
    return out/'obj/Vtb_conv_npu'

def run_suite(binary,out,name,tasks,no_random=False,force_codec=False,timeout=300):
    suite=out/(name+'.suite')
    suite.write_text(''.join(f'{d}/config.mem {d}/init.mem {d}/golden.mem {d}/required.mem {d}/acc.mem\n' for d in tasks))
    cmd=[binary,f'+SUITE={suite}']+(['+NO_RANDOM_WAIT'] if no_random else [])
    if force_codec:cmd.append('+FORCE_PS_CODEC')
    binary_hash=hashlib.sha256(binary.read_bytes()).hexdigest()
    rc=command(cmd,out/(name+'.log'),timeout=timeout)
    text=(out/(name+'.log')).read_text()
    measurements=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in text.splitlines() if line.startswith('CONV_TASK_PASS')]
    ok=rc==0 and f'CONV_NPU_PASS tasks={len(tasks)}' in text and len(measurements)==len(tasks)
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=binary_hash:raise RuntimeError('Simulator changed during execution')
    result=dict(name=name,passed=ok,returncode=rc,tasks=[str(t) for t in tasks],measurements=measurements,
                command=[str(v) for v in cmd],binary_sha256=binary_hash,force_codec=force_codec,
                log_sha256=hashlib.sha256((out/(name+'.log')).read_bytes()).hexdigest())
    print(name,'PASS' if ok else 'FAIL',measurements,flush=True)
    if not ok:print(text[-6000:],flush=True)
    return result

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--sizes',type=int,nargs='+',default=[4,8,16]);a.add_argument('--out',type=Path,default=ROOT/'build/conv_npu');a.add_argument('--verilator',default='verilator');a.add_argument('--jobs',type=int,default=1);a.add_argument('--cache-policy',type=int,choices=[0,1,2,3],default=3);a.add_argument('--cache-sets',type=int);a.add_argument('--smoke',action='store_true');a.add_argument('--skip-build',action='store_true');a.add_argument('--reuse-audit',action='store_true',help='Focused byte-level AXI reuse audit, including output-channel group replay')
    a.add_argument('--cache-bytes',type=int,help='Input cache capacity in bytes; defaults to IM2COL_CACHE_BYTES')
    a.add_argument('--ps-compress',action='store_true')
    a.add_argument('--pool-bytes',type=int,default=16384)
    a.add_argument('--force-raw',action='store_true',help='Use RAW records in the shared compressed-store datapath')
    a.add_argument('--force-codec',action='store_true',help='Testbench override: exercise adaptive records for every frame')
    a.add_argument('--dense-only',action='store_true',help='Run Dense configurations, AXI recovery, and a single-K capacity check')
    a.add_argument('--window-only',action='store_true',help='Compare Conv2 and Dense reuse configurations')
    a.add_argument('--lint-only',action='store_true')
    a.add_argument('--keep-objects',action='store_true')
    a.add_argument('--build-timeout',type=int,default=7200)
    a.add_argument('--bus-width',type=int,choices=(32,64))
    a.add_argument('--shared-bank-bytes',type=int,choices=(2048,4096,8192))
    a.add_argument('--shared-bank-count',type=int,choices=(6,7,8,9))
    x=a.parse_args()
    if x.build_timeout<=0:a.error('--build-timeout must be positive')
    selected=selected_config()
    if x.cache_sets is not None and x.cache_bytes is not None:
        a.error('--cache-sets and --cache-bytes are mutually exclusive')
    if x.cache_bytes is not None and (x.cache_bytes<512 or x.cache_bytes>65536 or x.cache_bytes&(x.cache_bytes-1)):
        a.error('--cache-bytes must be a power of two in 512..65536')
    if x.cache_sets is None:
        x.cache_sets=(selected['IM2COL_CACHE_BYTES'] if x.cache_bytes is None else x.cache_bytes)//32
    x.bus_width=axi_data_width(x.bus_width)
    x.shared_bank_bytes=selected['SHARED_BANK_BYTES'] if x.shared_bank_bytes is None else x.shared_bank_bytes
    x.shared_bank_count=selected['SHARED_BANK_COUNT'] if x.shared_bank_count is None else x.shared_bank_count
    if x.cache_sets<2 or x.cache_sets&(x.cache_sets-1):a.error('--cache-sets must be a power of two >=2')
    if x.pool_bytes<64 or x.pool_bytes%64:a.error('--pool-bytes must be a positive multiple of 64')
    if x.force_raw and not x.ps_compress:a.error('--force-raw requires --ps-compress')
    if x.force_codec and (not x.ps_compress or x.force_raw):a.error('--force-codec requires --ps-compress without --force-raw')
    if x.window_only and x.sizes!=[16]:a.error('--window-only requires --sizes 16')
    out=x.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if x.lint_only:
        for size in x.sizes:
            build(out/f's{size}',size,x.verilator,x.jobs,x.cache_sets,x.cache_policy,
                  x.ps_compress,x.pool_bytes,x.force_raw,True,bus_width=x.bus_width,
                  shared_bank_bytes=x.shared_bank_bytes,shared_bank_count=x.shared_bank_count,
                  build_timeout=x.build_timeout)
        print('CONV_LINT_PASS',flush=True)
        return 0
    ref=make_reference(out)
    reference_sources=[HERE/'reference_conv.c',HERE/'host_compat.h',ROOT/'drivers/tflm/NMSIS/NN/Include/riscv_nnsupportfunctions.h']
    summary={'verilator':subprocess.check_output([x.verilator,'--version'],text=True).strip(),
             'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],
             'reference_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in reference_sources},
             'cycle_definition':'calc_start accepted through done_valid; excludes deliberate 3-cycle completion backpressure',
             'scope':'conv_dense_reuse_comparison' if x.window_only else ('dense_dataflow_comparison' if x.dense_only else ('input_byte_reuse_audit' if x.reuse_audit else 'full_functional_regression')),
             'force_codec':x.force_codec,
             'cases':[]}
    for size in x.sizes:
        sd=out/f's{size}';sd.mkdir(exist_ok=True)
        if x.skip_build:
            manifest=json.loads((sd/'build.json').read_text())
            requested={'size':size,'bus_width':x.bus_width,'shared_bank_bytes':x.shared_bank_bytes,
                       'shared_bank_count':x.shared_bank_count,'cache_sets':x.cache_sets,'cache_ways':2,'cache_line_bytes':16,
                       'cache_policy':x.cache_policy,'ps_compress':x.ps_compress,'pool_bytes':x.pool_bytes,
                       'force_raw':x.force_raw,'lint_only':False}
            if any(manifest.get(key)!=value for key,value in requested.items()):
                raise RuntimeError('stale executable parameters: size/cache sets/ways/line/policy differ; omit --skip-build')
            for name,digest in manifest['source_sha256'].items():
                if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
                    raise RuntimeError(f'stale executable: {name} changed; omit --skip-build')
            binary=sd/'obj/Vtb_conv_npu'
            if hashlib.sha256(binary.read_bytes()).hexdigest()!=manifest['binary_sha256']:
                raise RuntimeError('Simulator digest differs from its build manifest')
        else:
            binary=build(sd,size,x.verilator,x.jobs,cache_sets=x.cache_sets,cache_policy=x.cache_policy,
                         ps_compress=x.ps_compress,pool_bytes=x.pool_bytes,force_raw=x.force_raw,
                         bus_width=x.bus_width,shared_bank_bytes=x.shared_bank_bytes,
                         shared_bank_count=x.shared_bank_count,build_timeout=x.build_timeout)
        if x.window_only:
            summary['cases'].append(run_suite(binary,sd,'conv2_windows',
                conv_window_cases(sd,size,ref,x.pool_bytes,x.force_raw),True,x.force_codec))
        if x.dense_only or x.window_only:
            summary['cases'].append(run_suite(binary,sd,'dense_dataflows',
                dense_cases(sd,size,x.pool_bytes,x.force_raw),True,x.force_codec))
            (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            continue
        if x.reuse_audit:
            cache=task(sd,size,ref,name='conv3x3_cache',co=size+1,expect_once=True)
            bypass=task(sd,size,ref,name='conv3x3_bypass',co=size+1,bypass=True)
            replay_cache=task(sd,size,ref,name='channel_replay_cache',co=33,expect_once=True)
            replay_bypass=task(sd,size,ref,name='channel_replay_bypass',co=33,bypass=True)
            sparse=task(sd,size,ref,name='sparse_stride_dilation',h=9,w=10,c=5,kh=2,kw=3,sh=2,sw=1,dh=2,dw=2,ph=1,pw=2,co=size+3,offset=127,input_base=0x10ffd,rhs_base=0x20ffd)
            grouped=task(sd,size,ref,name='sparse_group',h=6,w=7,c=8,gc=3,go=4,kh=3,kw=2,ph=1,pw=0,co=5,dst_stride=11,dst_offset=4,offset=-127)
            for name,tasks in [('cache_fixed',[cache]),('bypass_fixed',[bypass]),('channel_replay_cache',[replay_cache]),('channel_replay_bypass',[replay_bypass]),('sparse_input_usage',[sparse,grouped])]:
                summary['cases'].append(run_suite(binary,sd,name,tasks,True,x.force_codec))
                (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            continue
        smoke=task(sd,size,ref,name='conv3x3_cache',co=size+1,expect_once=True)
        summary['cases'].append(run_suite(binary,sd,'smoke',[smoke],force_codec=x.force_codec))
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not summary['cases'][-1]['passed']:break
        if x.smoke:continue
        bypass=task(sd,size,ref,name='conv3x3_bypass',co=size+1,bypass=True)
        rect=task(sd,size,ref,name='rect_stride_dilation',h=9,w=10,c=5,kh=2,kw=3,sh=2,sw=1,dh=2,dw=2,ph=1,pw=2,co=size+3,offset=127,input_base=0x10ffd,rhs_base=0x20ffd)
        group=task(sd,size,ref,name='group_channel_offset',h=6,w=7,c=8,gc=3,go=4,kh=3,kw=2,ph=1,pw=0,co=5,dst_stride=11,dst_offset=4,offset=-127)
        pos=task(sd,size,ref,name='signed_rounding_positive_shift',h=3,w=5,c=2,kh=1,kw=1,ph=0,pw=0,co=7,offset=0,positive_shift=True)
        mutate=task(sd,size,ref,name='latched_config',co=size+1,mutate=True,seed=321)
        failed=task(sd,size,ref,name='injected_rresp',co=size+1,error=3,inject=True)
        invalid=task(sd,size,ref,name='invalid_geometry',co=size+1,error=1,invalidate_geometry=True)
        recovery=task(sd,size,ref,name='recovery_changed_input',co=size+1,seed=456)
        gemm=gemm_task(sd,size)
        capacity=task(sd,size,ref,name='capacity_error',co=size+1,error=2,inject_capacity=True)
        collision=task(sd,size,ref,name='bus_capacity_priority',co=size+1,error=3,inject=True,inject_capacity=2)
        conv_is=task(sd,size,ref,name='conv3x3_is',co=size+3,dataflow=1)
        gemm_s16_ws=precision_task(sd,size,name='gemm_s16_full_ws')
        gemm_s16_is=precision_task(sd,size,name='gemm_s16_full_is',dataflow=1)
        gemm_s8_ws=precision_task(sd,size,name='gemm_s8_full_ws',lhs_s16=False)
        gemm_s8_is=precision_task(sd,size,name='gemm_s8_full_is',dataflow=1,lhs_s16=False)
        gemm_s16_out=precision_task(sd,size,name='gemm_s16_output',output_s16=True)
        dense_tasks=dense_cases(sd,size,x.pool_bytes,x.force_raw)
        grouped=grouped_batches(sd,size,ref)
        for name,tasks,fixed in [('cache_fixed',[smoke],True),('bypass_fixed',[bypass],True),
            ('geometry',[rect,group,pos,mutate,conv_is],False),
            ('error_recovery',[failed,recovery,invalid,recovery,capacity,recovery,collision,recovery],False),
            ('mixed_conv_gemm',[smoke,gemm,recovery],False),('batch_group_commands',grouped,False),
            ('input_precision',[gemm_s8_ws,gemm_s8_is,gemm_s16_ws,gemm_s16_is,
                                gemm_s16_out,gemm_s16_ws,gemm_s16_is,gemm_s8_ws],False),
            ('dense_dataflows',dense_tasks,True)]:
            summary['cases'].append(run_suite(binary,sd,name,tasks,fixed,x.force_codec))
            (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    summary['passed']=all(c['passed'] for c in summary['cases'])
    summary['task_count']=sum(len(c['measurements']) for c in summary['cases'])
    summary['int32_checks']=sum(m['int32_checks'] for case in summary['cases'] for m in case['measurements'])
    summary['ps_compress']=x.ps_compress
    summary['pool_bytes']=x.pool_bytes
    summary['force_raw']=x.force_raw
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if summary['passed'] and not x.keep_objects:
        for size in x.sizes:
            for path in (out/f's{size}/obj').iterdir():
                if path.name=='Vtb_conv_npu':continue
                if path.is_dir():shutil.rmtree(path)
                else:path.unlink()
    print('CONV_SYSTEM_RESULT',summary['passed'],flush=True)
    return 0 if summary['passed'] else 1

if __name__=='__main__':sys.exit(main())
