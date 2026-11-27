#!/usr/bin/env python3
"""比较算子运行的完整前端记录、缓存请求元数据和处理延迟统计。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json

FIELDS = ('addr','index','index_valid','epoch','retire','progress')
PREFIXES = ('FRONTEND_TRANSACTION ','CACHE_THROUGHPUT_PROFILE ',
            'CACHE_THROUGHPUT_BIN ','CONV_DESCRIPTOR_REQUEST_PROFILE ','CONV_FRONTEND_PROFILE ')


def load(path):
    actual = path if path.exists() else path.with_suffix(path.suffix+'.gz')
    raw = gzip.open(actual,'rb').read() if actual.suffix=='.gz' else actual.read_bytes()
    lines = raw.decode().splitlines()
    trace = [dict(token.split('=',1) for token in line.split()[1:]) for line in lines
             if line.startswith('FRONTEND_TRANSACTION ')]
    if not trace:
        raise ValueError('运行记录必须启用 FRONTEND_TRANSACTION_TRACE')
    return trace,[line for line in lines if line.startswith(PREFIXES)],hashlib.sha256(raw).hexdigest()


def difference(reference,current,fields):
    for index,(old,new) in enumerate(zip(reference,current)):
        changed = {key:[old[key],new[key]] for key in fields if old[key]!=new[key]}
        if changed:
            return dict(index=index,cycle=[old['cycle'],new['cycle']],differences=changed,
                        reference=old,current=new)
    if len(reference)!=len(current):
        return dict(index=min(len(reference),len(current)),counts=[len(reference),len(current)])
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--expect-equal',action='store_true')
    parser.add_argument('--cases',nargs='+',default=['dw3x3_s1_48_c8','conv3x3_32_c16_o16'])
    args=parser.parse_args();results={}
    for name in args.cases:
        old,old_lines,old_hash=load(args.reference/'conv/cases'/name/'run.log')
        new,new_lines,new_hash=load(args.current/'conv/cases'/name/'run.log')
        old_requests=[row for row in old if row['request']=='11']
        new_requests=[row for row in new if row['request']=='11']
        old_tiles=[row for row in old if row['tile']=='11']
        new_tiles=[row for row in new if row['tile']=='11']
        payload_difference=difference(old_requests,new_requests,FIELDS)
        item=dict(cycles=[len(old),len(new)],requests=[len(old_requests),len(new_requests)],
            cancellations=[sum(row['cancel']=='1' for row in old),sum(row['cancel']=='1' for row in new)],
            request_payload_equal=payload_difference is None,request_payload_first_difference=payload_difference,
            all_recorded_cycles_equal=old_lines==new_lines,
            first_cycle_difference=difference(old,new,old[0].keys()),
            first_request_cycle_difference=difference(old_requests,new_requests,('cycle',*FIELDS)),
            first_descriptor_difference=difference(old_tiles,new_tiles,('cycle','p','q','rows','cols','slot')),
            log_sha256=[old_hash,new_hash])
        results[name]=item
        if args.expect_equal and not item['all_recorded_cycles_equal']:
            raise AssertionError((name,item['first_cycle_difference']))
        print(json.dumps(dict(case=name,cycles=item['cycles'],requests=item['requests'],
            request_payload_equal=item['request_payload_equal'],all_recorded_cycles_equal=item['all_recorded_cycles_equal'])))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(dict(reference=str(args.reference),current=str(args.current),
        required_every_cycle_equal=args.expect_equal,results=results),indent=2)+'\n')


if __name__=='__main__':
    main()
