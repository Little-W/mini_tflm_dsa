#!/usr/bin/env python3
"""Summarize the 100 longest mapped data paths and their logic distribution."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re


def region(name):
    if 'u_ps_buffer' in name:
        if 'u_encoder' in name:return 'PS encoder'
        if 'u_decoder' in name:return 'PS decoder'
        if 'u_directory_ram' in name:return 'PS directory'
        return 'PS storage control'
    if 'u_vec_requant_s64' in name:return 'INT64 requantization'
    if 'u_vec_requant' in name:return 'INT32 requantization'
    if 'u_engine' in name:return 'Vector engine'
    if 'u_compute_core' in name:return 'Systolic array'
    if 'u_block_dma' in name:return 'DMA'
    if 'u_scheduler' in name:return 'Capacity scheduler'
    if 'u_ia_loader' in name:return 'Input loader'
    if 'u_kernel_loader' in name:return 'Weight loader'
    parts=name.split('/')
    return re.sub(r'\[\d+\]', '[*]', parts[0]) if parts[0].startswith(('u_', 'g_')) else 'Top-level control'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--top',default='npu_top')
    args=parser.parse_args();run=args.run.resolve()
    with (run/f'{args.top}_top100_delay.csv').open() as source:
        records=list(csv.DictReader(source))
    assert len(records)==100,'The design must provide 100 constrained endpoint paths'
    for record in records:
        for key in ('delay_ns','slack_ns'):record[key]=float(record[key])
        for key in ('rank','logic_depth'):record[key]=int(record[key])
        record['start_region']=region(record['startpoint'])
        record['end_region']=region(record['endpoint'])
    assert all(a['delay_ns']>=b['delay_ns'] for a,b in zip(records,records[1:]))
    points=defaultdict(list);rank=None
    for line in (run/f'{args.top}_top100_delay.rpt').read_text().splitlines():
        match=re.match(r'Path (\d+):',line)
        if match:rank=int(match[1])
        fields=line.split('\t')
        if len(fields)==4 and rank is not None:
            arrival,delay,name,reference=fields
            points[rank].append(dict(arrival_ns=float(arrival),increment_ns=float(delay),
                                     pin=name,cell_reference=reference,region=region(name)))
    regional=defaultdict(lambda:dict(path_count=0,total_increment_ns=0.0,max_path_ns=0.0))
    references=Counter()
    for record in records:
        per_path=defaultdict(float)
        record['points']=points[record['rank']]
        for point in record['points']:
            per_path[point['region']]+=point['increment_ns']
            references[point['cell_reference']]+=point['increment_ns']
        for name,delay in per_path.items():
            regional[name]['path_count']+=1
            regional[name]['total_increment_ns']+=delay
            regional[name]['max_path_ns']=max(regional[name]['max_path_ns'],delay)
    data=dict(method='One maximum-delay path per constrained endpoint; sorted by cell plus net delay',
        path_count=len(records),positive_slack_paths=sum(r['slack_ns']>=0 for r in records),
        maximum_delay_ns=records[0]['delay_ns'],minimum_delay_ns=records[-1]['delay_ns'],
        regions=dict(regional),cell_reference_delay_sum_ns=dict(references.most_common()),paths=records)
    (run/'top_paths.json').write_text(json.dumps(data,indent=2)+'\n')
    report='# Maximum-delay path analysis\n\n'
    report+='The ranking uses cell and net propagation delays and includes paths with positive timing slack. Each endpoint contributes its maximum-delay path.\n\n'
    report+='| Logic region | Paths containing region | Sum of path increments / ns | Maximum contribution / ns |\n|---|---:|---:|---:|\n'
    for name,values in sorted(regional.items(),key=lambda x:x[1]['total_increment_ns'],reverse=True):
        report+=f'| {name} | {values["path_count"]} | {values["total_increment_ns"]:.4f} | {values["max_path_ns"]:.4f} |\n'
    report+='\n| Rank | Delay / ns | Slack / ns | Logic depth | Startpoint | Endpoint |\n|---|---:|---:|---:|---|---|\n'
    for r in records:
        report+=f'| {r["rank"]} | {r["delay_ns"]:.5f} | {r["slack_ns"]:.5f} | {r["logic_depth"]} | `{r["startpoint"]}` | `{r["endpoint"]}` |\n'
    (run/'top_paths.md').write_text(report)
    print(json.dumps({key:data[key] for key in ('path_count','positive_slack_paths','maximum_delay_ns','minimum_delay_ns')}))


if __name__=='__main__':main()
