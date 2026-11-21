#!/usr/bin/env python3
"""Generate expected IA tile writes from direct_im2col, NOT from the cache model."""
import argparse,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
sys.path[:0]=[str(ROOT/'model'),str(ROOT/'tests')]
from conv_model import *
from run_model_tests import cases


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--size',type=int,default=16);ap.add_argument('--out',type=Path)
    args=ap.parse_args();size=args.size
    if size<2 or size&(size-1): raise SystemExit('SIZE must be a power of two >=2')
    path=args.out or OUTPUT/f'rtl_vectors_s{size}.txt'
    rng=random.Random(762943); selected=list(cases(rng))[:30]
    jobs=[]
    for i,(name,cfg,_,_) in enumerate(selected):
        values=[rng.randint(-3000,3000) if cfg.s16 else rng.randint(-128,127)
                for _ in range(cfg.h*cfg.w*cfg.cin)]
        plan=tile_plan(cfg,size,2,1)
        if i%3==1: rng.shuffle(plan)
        # Same cfg/input with completely non-aligned logical starting coordinates.
        if cfg.positions>3 and cfg.red>5:
            plan.append(Tile(3,5,min(size,cfg.positions-3),3))
        jobs.append((cfg,values,plan,i%4==0,False))
    cfg=Config(3,4,3,3,3,3,4,pt=1,pl=1,base=0x1003)
    jobs.append((cfg,[3]*(cfg.h*cfg.w*cfg.cin),[Tile(0,cfg.group_c*(cfg.kw+1),min(size,cfg.positions),0)],False,True))
    # Explicit error recovery, same-address invalidation, extreme values, and
    # high-address clipping. The bench maps this allocation to a small local RAM.
    jobs.append((cfg,[-7]*(cfg.h*cfg.w*cfg.cin),tile_plan(cfg,size),False,False))
    jobs.append((cfg,[91]*(cfg.h*cfg.w*cfg.cin),tile_plan(cfg,size),False,False))
    for bypass in (False, True):
        high=Config(1,1,5,1,1,1,1,offset=128,base=0xfffffff8)
        jobs.append((high,[-128,-1,0,126,127],tile_plan(high,size),bypass,False))
        high16=Config(1,1,3,1,1,1,1,s16=True,base=0xfffffff8)
        jobs.append((high16,[-32768,0,32767],tile_plan(high16,size),bypass,False))
    # 通道分组逐个遍历空间位置，检查非零通道起点、跨输出行和步长变化。
    for channels,stride,base,s16 in ((32,1,0x28000,False),(64,1,0x2c000,True),
                                    (48,2,0x30001,False)):
        grouped=Config(5,7,channels,3,3,5 if stride==1 else 3,7 if stride==1 else 4,
                       sh=stride,sw=stride,pt=1,pl=1,offset=0 if s16 else -17,base=base,s16=s16)
        values=[rng.randint(-3000,3000) if s16 else rng.randint(-128,127)
                for _ in range(grouped.h*grouped.w*grouped.cin)]
        plan=[Tile(position,tap*channels+channel,1,(position+tap)%8)
              for channel in range(0,channels,size)
              for position in range(grouped.positions)
              for tap in range(grouped.kh*grouped.kw)
              if 0<=(position//grouped.ow)*grouped.sh+(tap//grouped.kw)*grouped.dh-grouped.pt<grouped.h
              and 0<=(position%grouped.ow)*grouped.sw+(tap%grouped.kw)*grouped.dw-grouped.pl<grouped.w]
        jobs.append((grouped,values,plan,False,False))
    # 矩形卷积同时覆盖非等长核、空洞、跨页输入和接近字节上界的偏移。
    geometry=Config(9,10,5,2,3,5,10,sh=2,sw=1,dh=2,dw=2,pt=1,pl=2,
                    offset=127,base=0x10ffd)
    geometry_rng=random.Random(123)
    values=[geometry_rng.randint(-15,15) for _ in range(geometry.h*geometry.w*geometry.cin)]
    values[:3]=[-128,127,-1]
    jobs.append((geometry,values,tile_plan(geometry,size,2,1),False,False))
    plan=[Tile(position,reduction,1,index%8)
          for index,(reduction,position) in enumerate(
              (reduction,position) for reduction in range(0,geometry.red,size)
              for position in range(geometry.positions))]
    jobs.append((geometry,values,plan,False,False))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        f.write(f'{len(jobs)}\n')
        for cfg,values,plan,bypass,fail in jobs:
            fields=[cfg.base,cfg.h,cfg.w,cfg.cin,cfg.group_c,cfg.go,cfg.kh,cfg.kw,cfg.oh,cfg.ow,
                    cfg.sh,cfg.sw,cfg.dh,cfg.dw,cfg.pt,cfg.pl,cfg.offset,int(cfg.s16),int(bypass),
                    int(fail),len(plan),cfg.nbytes]
            f.write(' '.join(map(str,fields))+'\n')
            mem=Memory(cfg,values)
            f.write(' '.join(f'{b:02x}' for b in mem.data)+'\n')
            for t in plan:
                f.write(f'{t.p0} {t.q0} {t.rows} {t.slot}\n')
                expected=direct_im2col(cfg,values,t,size)
                for row in expected: f.write(' '.join(map(str,row))+'\n')
    print(f'generated {path}: {len(jobs)} jobs, SIZE={size}; expected data from direct equations')
if __name__=='__main__':main()
