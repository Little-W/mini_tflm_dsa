#!/usr/bin/env python3
"""Aggregate measured Invoke cycles and per-operator profiling records."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from statistics import mean

from model_data import MODELS
from run import HARDWARE_MODE, write_json


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def pair(sw,hw):
    keys=('model_id','sample_index','input_sha256','ram_fixed_lat')
    if any(sw[k]!=hw[k] for k in keys) or sw['model']['sha256']!=hw['model']['sha256'] or sw['simulator']['simulator_sha256']!=hw['simulator']['simulator_sha256']:
        raise ValueError('Comparison requires identical model, input, simulator and RAM timing')
    if sw['output_comparison']['actual_sha256']!=hw['output_comparison']['actual_sha256']:
        raise ValueError('Software and hardware outputs differ')


def summarize(out,prepared_root):
    out=Path(out); prepared_root=Path(prepared_root)
    destination=out/'summary';destination.mkdir(parents=True,exist_ok=True)
    runs=[json.loads(p.read_text()) for p in sorted((out/'results/cases').glob('*/*/*/result.json'))]
    indexed={(r['model_id'],r['sample_index'],r['kind'],r['mode']):r for r in runs if r['passed']}
    models=[];layers=[];operators=[]
    for name in MODELS:
        manifest=json.loads((prepared_root/name/'manifest.json').read_text())
        samples=[s['sample_index'] for s in manifest['samples']]
        complete_perf=[];complete_trace=[]
        for sample in samples:
            sw=indexed.get((name,sample,'perf',0));hw=indexed.get((name,sample,'perf',HARDWARE_MODE))
            if sw and hw:
                pair(sw,hw);complete_perf.append((sw,hw))
            sw=indexed.get((name,sample,'trace',0));hw=indexed.get((name,sample,'trace',HARDWARE_MODE))
            if not(sw and hw):continue
            pair(sw,hw)
            complete_trace.append((sw,hw))
            a={r['index']:r for r in sw['layers']};b={r['index']:r for r in hw['layers']}
            for node in manifest['graph']['nodes']:
                index=node['index'];left=a[index];right=b[index]
                x=left['cycles'];y=right['cycles']
                tensors=[r for run in (sw,hw) for r in run['trace']
                         if r['descriptor']['operator_index']==index]
                layers.append({'model':name,'sample':sample,'layer':index,'op':node['op'],
                    'input_shapes':json.dumps(node['input_shapes'],separators=(',',':')),
                    'output_shapes':json.dumps(node['output_shapes'],separators=(',',':')),
                    'sw_cycles':x,'hw_cycles':y,'speedup':x/y,
                    'sw_share_percent':100*x/sw['result']['invoke_cycles'],
                    'hw_share_percent':100*y/hw['result']['invoke_cycles'],
                    'hw_jobs':right['jobs'],'hw_busy_cycles':right['npu_busy_cycles'],
                    'hw_done':right['done_jobs'],'hw_conv_jobs':right['conv_jobs'],
                    'hw_dw_jobs':right['dw_jobs'],'hw_pool_jobs':right['pool_jobs'],
                    'hw_add_jobs':right['add_jobs'],'hw_add_done':right['add_done'],
                    'hw_gemm_jobs':right['gemm_jobs'],'hw_vector_jobs':right['vector_jobs'],
                    'execution':'hardware' if right['jobs'] else 'cpu',
                    'hw_read_bytes':right['npu_read_bytes'],'hw_write_bytes':right['npu_write_bytes'],
                    'output_exact':bool(tensors) and all(r['passed'] for r in tensors)})
        if complete_perf:
            a=[s['result']['invoke_cycles'] for s,h in complete_perf]
            b=[h['result']['invoke_cycles'] for s,h in complete_perf]
            target=1000
            models.append({'model':name,'samples':len(a),'sw_cycles_mean':mean(a),
                'hw_cycles_mean':mean(b),'speedup':sum(a)/sum(b),
                'minimum_sample_speedup':min(x/y for x,y in zip(a,b)),
                'target_speedup':target,
                'target_met':all(x/y>=target for x,y in zip(a,b)),
                'hw_jobs_per_inference':mean(h['network']['jobs'] for s,h in complete_perf),
                'model_sha256':manifest['model']['sha256']})
        for op in sorted({r['op'] for r in layers if r['model']==name}):
            selected=[r for r in layers if r['model']==name and r['op']==op]
            count=len({r['sample'] for r in selected})
            x=sum(r['sw_cycles'] for r in selected);y=sum(r['hw_cycles'] for r in selected)
            operators.append({'model':name,'op':op,'samples':count,
                'nodes_per_inference':len(selected)//count,'sw_cycles_mean':x/count,
                'hw_cycles_mean':y/count,'speedup':x/y,
                'minimum_layer_speedup':min(r['speedup'] for r in selected),
                'sw_share_percent':sum(r['sw_share_percent'] for r in selected)/count,
                'hw_share_percent':sum(r['hw_share_percent'] for r in selected)/count,
                'hw_jobs_per_inference':sum(r['hw_jobs'] for r in selected)/count,
                'hw_add_jobs_per_inference':sum(r['hw_add_jobs'] for r in selected)/count,
                'hw_add_done_per_inference':sum(r['hw_add_done'] for r in selected)/count,
                'hardware_nodes_per_inference':sum(r['execution']=='hardware' for r in selected)/count,
                'cpu_nodes_per_inference':sum(r['execution']=='cpu' for r in selected)/count})
        if complete_trace:
            software_residual=[s['result']['invoke_cycles']-sum(r['cycles'] for r in s['layers'])
                               for s,h in complete_trace]
            hardware_residual=[h['result']['invoke_cycles']-sum(r['cycles'] for r in h['layers'])
                               for s,h in complete_trace]
            if min(software_residual+hardware_residual)<0:
                raise ValueError('Operator intervals exceed the profiled Invoke interval')
            operators.append({'model':name,'op':'framework_and_profiling','samples':len(complete_trace),
                'nodes_per_inference':0,'sw_cycles_mean':mean(software_residual),
                'hw_cycles_mean':mean(hardware_residual),
                'speedup':sum(software_residual)/sum(hardware_residual) if sum(hardware_residual) else '',
                'minimum_layer_speedup':'',
                'sw_share_percent':mean(100*x/s['result']['invoke_cycles']
                    for x,(s,h) in zip(software_residual,complete_trace)),
                'hw_share_percent':mean(100*y/h['result']['invoke_cycles']
                    for y,(s,h) in zip(hardware_residual,complete_trace)),
                'hw_jobs_per_inference':0,'hw_add_jobs_per_inference':0,'hw_add_done_per_inference':0,
                'hardware_nodes_per_inference':0,'cpu_nodes_per_inference':0})
    expected=4*sum(len(json.loads((prepared_root/name/'manifest.json').read_text())['samples']) for name in MODELS)
    dw=[r for r in layers if r['op']=='DEPTHWISE_CONV_2D']
    report={'functional_passed':bool(runs) and all(r['passed'] for r in runs),
        'complete':len(runs)==expected,'expected_runs':expected,'completed_runs':len(runs),
        'models':models,'operators':operators,'layers':layers,
        'dw_all_layers_above_20x':bool(dw) and all(r['speedup']>20 for r in dw),
        'dw_layer_input_pairs':len(dw),
        'dw_aggregate_speedup':sum(r['sw_cycles'] for r in dw)/sum(r['hw_cycles'] for r in dw) if dw else None,
        'dw_minimum_layer_speedup':min(r['speedup'] for r in dw) if dw else None,
        'model_targets_met':len(models)==4 and all(r['target_met'] is not False for r in models),
        'rounding_mode':'nearest_even','bus_width':32,'systolic_size':16,'vector_pes':8,
        'ram_bytes':2097152,'measurement':'Full Invoke cycles from performance firmware; operator shares from separate profiling firmware',
        'runs':[{'model':r['model_id'],'sample':r['sample_index'],'kind':r['kind'],
                 'mode':r['mode_name'],'passed':r['passed'],'case_dir':r['case_dir']} for r in runs]}
    write_csv(destination/'models.csv',models);write_csv(destination/'operators.csv',operators)
    write_csv(destination/'layers.csv',layers);write_json(destination/'summary.json',report)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--prepared',type=Path,required=True)
    args=parser.parse_args()
    value=summarize(args.out,args.prepared)
    print(json.dumps({k:v for k,v in value.items() if k not in ('layers','runs')},indent=2))
