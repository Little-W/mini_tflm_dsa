#!/usr/bin/env python3
"""汇总实际源码、SAT、四态、完整协议与局部映射结果。"""
import argparse
import hashlib
import json
from pathlib import Path
from common import ROOT,SOURCES
from prepare_measurement import PARAMETERS


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):return json.loads(path.read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal',type=Path,required=True)
    parser.add_argument('--four-state',type=Path,required=True)
    parser.add_argument('--protocol-production',type=Path,required=True)
    parser.add_argument('--protocol-model',type=Path,required=True)
    parser.add_argument('--mapped-reference',type=Path,required=True)
    parser.add_argument('--mapped-current',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    formal=read(args.formal/'summary.json');four=read(args.four_state/'summary.json')
    assert formal['passed'] and len(formal['profiles'])==24
    assert four['passed'] and len(four['profiles'])==24
    assert formal['inputs']==four['inputs']
    production,model=formal['inputs']['sources']
    for row in [production,model]:assert digest(ROOT/row['source'])==row['current_sha256']
    protocols=[]
    expected={(dw,dp,outstanding,latency,random) for dw in [32,64]
              for dp,outstanding in [(1031,4),(1024,1),(1031,3)]
              for latency in ([1,2,3,8,17] if (dp,outstanding)==(1031,4) else [8])
              for random in [False,True]}
    for label,path,source in [('production',args.protocol_production,production),
                              ('model',args.protocol_model,model)]:
        status=read(path/'modified_status.json')
        assert status['source_sha256']==source['current_sha256']
        assert all(row['status']=='PASS' for row in status['runs'])
        keys={(r['data_bits'],r['dp'],r['outstanding'],r['first_read_latency'],r['random']) for r in status['runs']}
        assert len(status['runs'])==28 and keys==expected
        protocols.append({'implementation':label,'passed':True,'runs':len(status['runs']),
            'source_sha256':status['source_sha256'],'testbench_sha256':status['testbench_sha256'],
            'simulator':status['simulator'],'compile_jobs':status['compile_jobs'],
            'report_sha256':digest(path/'modified_status.json'),
            'profiles':[{k:v for k,v in row.items() if k not in ['warnings','log']}
                         for row in status['runs']]})
    mapped=[]
    for label,path in [('reference',args.mapped_reference),('current',args.mapped_current)]:
        summary=read(path/'summary.json');manifest=read(path/'manifest.json')
        assert production[label+'_sha256'] in manifest['sources_sha256'].values()
        for name,value in manifest['sources_sha256'].items():
            if name.startswith('rtl/common/'):assert digest(ROOT/name)==value
        assert summary['functional_verification']['passed']
        resources=summary['resources']
        mapped.append({'version':label,
            **{key:resources[key] for key in ['logic_lut_cells','flip_flops','carry4','dsp48e1',
                    'ramb36e1','ramb18e1','distributed_ram_lut_sites_nominal','shift_register_lut_sites_nominal']},
            'longest_register_path_cells':summary['longest_register_path_cells'],
            'graph_complete':summary['register_path_requirement']['graph_complete'],
            'mapping_verification':summary['functional_verification'],
            'manifest_sha256':digest(path/'manifest.json'),'summary_sha256':digest(path/'summary.json'),
            'metrics_sha256':digest(path/'metrics.json'),
            'peak_process_tree_rss_bytes':summary['mapping_stage']['peak_process_tree_rss_bytes']})
    report={'inputs':formal['inputs'],'parameters':PARAMETERS,'formal':formal,'four_state':four,
        'protocol':protocols,'mapping':mapped,
        'mapping_options':{'mode':'physical-cost','small_lut_area_cost':1.0,'max_lut_inputs':6,
                           'wire_delay_ps':500,'delay_target_ps':6667},
        'physical_lut_positions':None,'timing_150mhz_confirmed':None,
        'scripts_sha256':{str(p.relative_to(ROOT)):digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
        'protocol_runner_sha256':digest(ROOT/'test/conv_soc_ram/run.py')}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'protocol_runs':56,'formal_profiles':24,'mapping':mapped},ensure_ascii=False))


if __name__=='__main__':main()
