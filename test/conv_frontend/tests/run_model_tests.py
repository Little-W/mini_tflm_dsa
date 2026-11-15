#!/usr/bin/env python3
"""Executed verification level: Python protocol/functional model + compiled C.
No RTL simulator is invoked here; never label these tests RTL PASS.
"""
from pathlib import Path
import ctypes as ct
import json, random, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
sys.path.insert(0,str(ROOT/'model'))
from conv_model import *


def build_oracle():
    output=OUTPUT/'libdirect_conv.so'
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                    str(ROOT/'tests/direct_conv.c'),'-o',str(output)],check=True)
    lib=ct.CDLL(str(output))
    lib.direct_conv.argtypes=[ct.POINTER(ct.c_int32),ct.POINTER(ct.c_int16),
      ct.POINTER(ct.c_int8),ct.POINTER(ct.c_int32),ct.c_int32,ct.POINTER(ct.c_int32)]
    lib.direct_conv.restype=ct.c_int
    lib.quant_contract.argtypes=[ct.c_int32,ct.c_int32,ct.c_int,ct.c_int,ct.c_int,ct.c_int,
                                 ct.POINTER(ct.c_int32)]
    lib.quant_contract.restype=ct.c_int
    return lib


def cases(rng):
    yield 'overlap_s8',Config(9,11,3,3,3,9,11,pt=1,pl=1,offset=17,base=0x1003),7,16
    yield 'rect_stride_dilation',Config(8,11,5,2,3,5,5,sh=2,sw=2,dh=2,dw=2,pt=2,pl=1,offset=-127),9,8
    yield 's16',Config(7,8,5,3,3,7,8,pt=1,pl=1,s16=True,base=0x1ffe),5,16
    yield 'pointwise',Config(3,7,17,1,1,3,7,offset=128,base=0x0ffd),19,16
    yield 'group_offset',Config(7,6,12,3,2,7,6,gc=4,go=8,pt=1,pl=1,offset=-53),5,4
    yield 'all_padding',Config(1,1,1,3,3,5,5,pt=10,pl=10,offset=91,base=0x3fff),1,4
    yield 'one_pixel_tail',Config(1,1,3,1,1,1,1,offset=128,base=0x2fff),3,16
    yield 'wide_row',Config(5,43,17,3,3,5,43,pt=1,pl=1,offset=-19),17,16
    yield 'large_kernel',Config(9,10,5,5,7,9,10,pt=2,pl=3,offset=13),4,16
    yield 'channel_one',Config(5,7,1,3,3,3,4,sh=2,sw=2,pt=1,pl=1,offset=-127),3,4
    for i in range(140):
        h=rng.randint(1,10); w=rng.randint(1,12); cin=rng.choice([1,2,3,4,5,7,8,12,17])
        kh=rng.choice([1,2,3,5]); kw=rng.choice([1,2,3,5]); sh=rng.choice([1,2,3]); sw=rng.choice([1,2])
        dh=rng.choice([1,1,2,3]); dw=rng.choice([1,1,2]); pt=rng.randrange(4); pl=rng.randrange(4)
        pb=rng.randrange(4); pr=rng.randrange(4)
        oh=(h+pt+pb-(kh-1)*dh-1)//sh+1
        ow=(w+pl+pr-(kw-1)*dw-1)//sw+1
        oh=max(1,oh); ow=max(1,ow)
        gc=rng.randint(1,cin); go=rng.randint(0,cin-gc)
        s16=i%9==0
        base=0x0ff0+rng.randrange(16)
        if s16: base&=~1
        yield f'random_{i:03}',Config(h,w,cin,kh,kw,oh,ow,sh,sw,dh,dw,pt,pl,gc,go,
              0 if s16 else rng.randint(-127,128),s16,base),rng.randint(1,19),rng.choice([4,8,16])


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    start=time.monotonic(); rng=random.Random(0xC0110C); lib=build_oracle()
    report={'verification_level':'Python executable specification + GCC-compiled independent C oracle',
            'rtl_simulation':'NOT_RUN_BY_THIS_SCRIPT','upstream_npu_integration':'NOT_TESTED_BY_THIS_SCRIPT',
            'seed':0xC0110C,'tests':{},'conv_cases':[]}
    for _ in range(10000):
        a=rng.randrange(2**32); b=rng.randint(1,2**32-1)
        assert udiv32(a,b)==divmod(a,b)
    report['tests']['restoring_divider_model']=10000
    proto=Counter()
    for _ in range(2000):
        base=rng.randrange(0x10000); n=rng.randint(1,2048)
        proto.update(handshake_span(base,n,rng))
    report['tests']['axi_span_protocol_model']=2000
    report['protocol_model_counters']=dict(proto)
    total_values=0; total_outputs=0; tile_count=0
    for name,cfg,cout,size in cases(rng):
        cfg.validate()
        limit=3000 if cfg.s16 else 128
        values=[rng.randrange(-limit,limit) for _ in range(cfg.h*cfg.w*cfg.cin)]
        weights=[rng.randrange(-8,8) for _ in range(cout*cfg.red)]
        bias=[rng.randrange(-400,400) for _ in range(cout)]
        mem=Memory(cfg,values); cache=ReadCache(mem)
        plan=tile_plan(cfg,size,reuse_rows=rng.choice([1,2,3]),replays=1)
        results=list(counted_tiles(cfg,cache,plan,size))
        for t,actual,_ in results:
            assert actual==direct_im2col(cfg,values,t,size), (name,t)
            total_values+=len(actual)*size; tile_count+=1
        matrix=reconstruct_matrix(cfg,results,size)
        actual=matmul_conv(matrix,weights,bias,cout)
        p=[cfg.h,cfg.w,cfg.cin,cfg.kh,cfg.kw,cfg.oh,cfg.ow,cfg.sh,cfg.sw,
           cfg.dh,cfg.dw,cfg.pt,cfg.pl,cfg.group_c,cfg.go,cfg.offset]
        out=(ct.c_int32*(cfg.positions*cout))()
        rc=lib.direct_conv((ct.c_int32*len(p))(*p),(ct.c_int16*len(values))(*values),
          (ct.c_int8*len(weights))(*weights),(ct.c_int32*len(bias))(*bias),cout,out)
        assert rc==0 and actual==list(out),name
        total_outputs+=len(actual)
        # Repeat/reorder descriptors; correctness must not depend on raster order.
        if len(plan)>1:
            shuffled=plan[:]; rng.shuffle(shuffled)
            for t,actual,_ in counted_tiles(cfg,cache,shuffled,size):
                assert actual==direct_im2col(cfg,values,t,size),(name,'reorder')
        report['conv_cases'].append({'name':name,'cfg':asdict(cfg),'cout':cout,'size':size,
          'tile_count':len(plan),'int32_outputs':len(out),'cache_hits':cache.hits,
          'cache_misses':cache.misses,'memory_bytes':mem.read_bytes})
    report['tests']['conv_configurations']=len(report['conv_cases'])
    report['tests']['initial_order_tiles']=tile_count
    report['tests']['initial_order_ia_elements_including_tail']=total_values
    report['tests']['int32_conv_outputs']=total_outputs
    # Numerical contract test only; no claim of linked upstream quantizer verification.
    for _ in range(10000):
        v=rng.randint(-1000000,1000000); mult=rng.randint(1,2**31-1); shift=rng.randint(-15,5)
        offset=rng.randint(-128,127); amin=rng.randint(-128,0); amax=rng.randint(0,127)
        expected=requantize_two_round(v,mult,shift,offset,amin,amax)
        out=ct.c_int32()
        assert lib.quant_contract(v,mult,shift,offset,amin,amax,ct.byref(out))==0
        assert out.value==expected,(v,mult,shift,out.value,expected)
    report['tests']['quantization_numerical_contract']=10000
    # Invalidation at same physical base: stale cache data must never survive a job.
    cfg=Config(3,3,3,1,1,3,3,base=0x1003)
    m1=Memory(cfg,[1]*27); ca=ReadCache(m1,capacity=128)
    assert ca.read_word(cfg.base)[3]==1
    m2=Memory(cfg,[7]*27); ca.configure(m2)
    assert ca.read_word(cfg.base)[3]==7
    # Failed fill must not set tag valid, and following retry must perform a fill.
    ca.configure(m2); m2.fail_next=True
    try: ca.read_word(cfg.base)
    except BusFault: pass
    else: raise AssertionError('read error not propagated')
    assert not any(l.valid for row in ca.lines for l in row)
    assert ca.read_word(cfg.base)[3]==7 and ca.misses==2
    report['tests']['cache_invalidate_and_failed_fill']=2
    # Exclusive end is legal below 2^32; line-end arithmetic itself needs 33 bits.
    high=Config(1,1,5,1,1,1,1,base=0xfffffff8)
    hm=Memory(high,[-2,-1,0,1,2]); hc=ReadCache(hm,capacity=128)
    for t,actual,_ in counted_tiles(high,hc,tile_plan(high,4),4):
        assert actual==direct_im2col(high,[-2,-1,0,1,2],t,4)
    assert all(b.addr+b.nbytes <= high.base+high.nbytes for b in hm.bursts)
    report['tests']['high_address_clipped_fill']=1
    # Compare byte-demand bypass against the cached path, including padded outputs.
    for bcfg in [Config(9,11,3,3,3,9,11,pt=1,pl=1,offset=17,base=0x1003),
                 Config(5,7,5,3,3,3,4,sh=2,sw=2,pt=1,pl=1,s16=True,base=0x1002)]:
        vals=[(i%31)-15 for i in range(bcfg.h*bcfg.w*bcfg.cin)]
        nc=NoCache(Memory(bcfg,vals))
        for t,actual,_ in counted_tiles(bcfg,nc,tile_plan(bcfg,8),8):
            assert actual==direct_im2col(bcfg,vals,t,8)
    report['tests']['bypass_model']=2
    invalid=[Config(0,1,1,1,1,1,1),Config(1,1,1,1,1,1,1,sh=0),
      Config(1,1,2,1,1,1,1,gc=2,go=1),Config(1,1,1,1,1,1,1,s16=True,base=3),
      Config(1,1,1,1,1,1,1,s16=True,offset=1),Config(1,1,1,1,1,1,1,offset=-128),
      Config(1,1,1,1,1,1,1,base=2**32-1),Config(1,1,1,1,1,1,1,dh=0),
      Config(1,1,1,1,1,1,1,pt=-1)]
    for bad in invalid:
        try: bad.validate()
        except ValueError: pass
        else: raise AssertionError('bad cfg accepted')
    report['tests']['invalid_config_rejection']=len(invalid)
    report['status']='PASS_FOR_MODEL_AND_C_ONLY'
    report['elapsed_seconds']=round(time.monotonic()-start,3)
    (OUTPUT/'model_test_results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='conv_cases'},indent=2))

if __name__=='__main__': main()
