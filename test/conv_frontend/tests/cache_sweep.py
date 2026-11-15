#!/usr/bin/env python3
"""Byte-traffic sweep of executable specifications, not measured RTL cycles."""
import csv,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT.parents[1]/'build/conv_frontend'
sys.path.insert(0,str(ROOT/'model'))
from conv_model import *
CASES=[
 ('3x3_rgb',Config(16,16,3,3,3,16,16,pt=1,pl=1,base=0x1003)),
 ('3x3_c16',Config(16,16,16,3,3,16,16,pt=1,pl=1)),
 ('3x3_wide_c32',Config(8,64,32,3,3,8,64,pt=1,pl=1)),
 ('3x3_stride2',Config(17,19,7,3,3,9,10,sh=2,sw=2,pt=1,pl=1)),
 ('3x3_dilation2',Config(12,17,5,3,3,12,17,dh=2,dw=2,pt=2,pl=2)),
 ('5x5_c8',Config(13,17,8,5,5,13,17,pt=2,pl=2)),
 ('1x1_sparse_stride4',Config(32,33,1,1,1,8,9,sh=4,sw=4)),
 ('3x3_row_alias',Config(5,16,256,3,3,5,16,pt=1,pl=1)),
]
CANDIDATES=[('no_cache_word_hold',0,1,4,False),('1KiB_2way_16B',1024,2,16,False),
 ('2KiB_2way_16B',2048,2,16,False),('4KiB_1way_16B',4096,1,16,False),
 ('4KiB_2way_16B',4096,2,16,False),('4KiB_2way_32B',4096,2,32,False),
 ('4KiB_1way_16B_XOR',4096,1,16,True),('4KiB_2way_16B_XOR',4096,2,16,True),
 ('8KiB_2way_16B',8192,2,16,False)]

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    records=[]
    for name,cfg in CASES:
        baseline=None
        for label,cap,ways,line,hashed in CANDIDATES:
            mem=Memory(cfg,[0]*(cfg.h*cfg.w*cfg.cin))
            cache=NoCache(mem) if cap==0 else ReadCache(mem,cap,ways,line,hashed)
            # Defined, reproducible synthetic schedule; no output-channel replay.
            for _ in counted_tiles(cfg,cache,tile_plan(cfg,size=16,reuse_rows=2),16): pass
            if baseline is None: baseline=mem.read_bytes
            rec=dict(case=name,candidate=label,input_bytes=cfg.nbytes,
              data_capacity=cap,ways=ways,line_bytes=line,hash_index=hashed,read_bytes=mem.read_bytes,
              axi_bursts=len(mem.bursts),cache_hits=cache.hits,cache_misses=cache.misses,
              byte_reduction_pct=round(100*(1-mem.read_bytes/baseline),3))
            records.append(rec)
        print(name,[(r['candidate'],r['read_bytes']) for r in records if r['case']==name])
    with (OUTPUT/'cache_sweep.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    (OUTPUT/'cache_sweep.json').write_text(json.dumps({'level':'model_byte_traffic_only',
       'schedule':'SIZE=16, row reuse group=2, reduction-major, no channel-group replay',
       'records':records},indent=2))
if __name__=='__main__':main()
