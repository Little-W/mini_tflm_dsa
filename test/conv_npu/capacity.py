#!/usr/bin/env python3
"""Five real-RTL cache capacities; identical tensors and bus timing per case."""
import argparse
import csv
import json
import math
from pathlib import Path
import subprocess
import sys

import run as npu

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=npu.ROOT/'build/conv_capacity')
    p.add_argument('--verilator',default='verilator')
    p.add_argument('--jobs',type=int,default=2)
    p.add_argument('--sets',type=int,nargs='+',default=[8,16,32,64,128])
    p.add_argument('--cache-policy',type=int,choices=[0,1,2],default=2)
    x=p.parse_args();out=x.out.resolve();out.mkdir(parents=True,exist_ok=True)
    ref=npu.make_reference(out)
    result={'method':'actual NPU RTL simulations, not address-trace model',
            'verilator':subprocess.check_output([x.verilator,'--version'],text=True).strip(),
            'size':16,'ways':2,'line_bytes':16,'cache_policy':x.cache_policy,'ia_cache_slots':4,
            'ia_element_bits':16,'ia_one_tile_bytes':512,'ia_all_tiles_bytes':2048,
            'bus':'32-bit AXI, fixed response timing, no random stalls',
            'rows':[]}
    for sets in x.sets:
        if sets<2 or sets&(sets-1):p.error('sets must be a power of two >=2')
        profile=out/f'cache_{sets*32}B';profile.mkdir(exist_ok=True)
        binary=npu.build(profile,16,x.verilator,x.jobs,cache_sets=sets,cache_policy=x.cache_policy)
        cases=[npu.task(profile,16,ref,name='small_75B',h=5,w=5,c=3,co=17,expect_once=True),
               npu.task(profile,16,ref,name='dense_2304B',h=12,w=12,c=16,kh=3,kw=3,ph=1,pw=1,co=17)]
        for task in cases:
            record=npu.run_suite(binary,profile,task.name,[task],no_random=True)
            if not record['passed']:
                result['passed']=False;result['failure']=record
                (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return 1
            m=record['measurements'][0];tag_bits=32-4-int(math.log2(sets))
            storage=dict(sets=sets,ways=2,line_bytes=16,data_bytes=sets*32,
                         tag_bits_per_line=tag_bits,tag_array_bits=sets*2*tag_bits,
                         valid_array_bits=sets*2,lru_array_bits=sets)
            storage['tag_valid_lru_bits']=storage['tag_array_bits']+storage['valid_array_bits']+storage['lru_array_bits']
            storage['tag_valid_lru_bytes']=storage['tag_valid_lru_bits']//8
            storage['data_and_tag_arrays_bytes']=storage['data_bytes']+storage['tag_valid_lru_bytes']
            result['rows'].append({'case':task.name,'passed':True,**storage,**m,
                                   'log':str(profile/(task.name+'.log')),
                                   'note':'Storage figures count RTL arrays only; exclude fixed control/pipeline registers and physical macro granularity.'})
            (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        # Executables and logs suffice for reproduction; release expendable C++
        # products before the next parameter elaboration in limited workspaces.
        for path in (profile/'obj').iterdir():
            if path.is_file() and path.name!='Vtb_conv_npu':path.unlink()
    result['passed']=True;result['rtl_commands']=len(result['rows'])
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    fields=['case','data_bytes','sets','tag_bits_per_line','tag_valid_lru_bytes','data_and_tag_arrays_bytes',
            'input_required','input_bytes','input_unique','input_duplicate','input_max_reads','misses','hits','cycles']
    with (out/'capacity.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(result['rows'])
    print('CONV_CAPACITY_RTL_PASS',result['rtl_commands'],flush=True)
    return 0

if __name__=='__main__':sys.exit(main())
