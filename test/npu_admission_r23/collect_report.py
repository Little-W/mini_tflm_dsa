#!/usr/bin/env python3
"""核对当前源码、正式证明、数值结果与映射文件，整理局部测量报告。"""
import argparse
import hashlib
import json
from pathlib import Path

from extract import ROOT,REFERENCE,digest,source_at,SOURCES
from prepare_measurement import build


def read(path):
    return json.loads(path.read_text())


def check_sources(data):
    for relative,expected in data.items():
        if digest(ROOT/relative)!=expected:
            raise RuntimeError('Source differs from verified input: '+relative)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();folder=args.build.resolve()
    formal_path=folder/'formal_complete/summary.json'
    paths_path=folder/'paths.json'
    numeric_path=folder/'dma_numeric/summary.json'
    kernel_path=folder/'kernel_numeric/summary.json'
    formal=read(formal_path);paths=read(paths_path)
    numeric=read(numeric_path);kernel=read(kernel_path)
    manifest=read(folder/'inputs/manifest.json')
    assert formal['passed'] and formal['reference_commit']==REFERENCE
    assert numeric['passed'] and kernel['passed']
    check_sources(formal['source_sha256']);check_sources(formal['test_source_sha256'])
    check_sources(formal['arbiter']['source_sha256']);check_sources(formal['kernel']['source_sha256'])
    check_sources(numeric['source_sha256']);check_sources(kernel['source_sha256'])
    for run in numeric['runs']:
        check_sources(run['source_sha256'])
        summary=folder/'dma_numeric'/('bus'+str(run['bus_width']))/'summary.json'
        assert digest(summary)==run['summary_sha256']
    formal_summary=json.loads(json.dumps(formal))
    observations=formal_summary['arbiter']['state_observation']+formal_summary['kernel']['runs']
    for row in observations:
        states=row.pop('observed_state')
        row['observed_state_names_count']=len(states)
        row['state_observation_sha256']=hashlib.sha256(
            json.dumps(states,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    report={'reference_commit':REFERENCE,'source_sha256':formal['source_sha256'],
        'passed':True,'formal':formal_summary,'numeric':{'kernel':kernel,'dma':numeric},
        'artifact_sha256':{str(p.relative_to(ROOT)):digest(p) for p in
            (formal_path,paths_path,numeric_path,kernel_path,folder/'inputs/manifest.json')},
        'measurement_scope':manifest['scope'],'measurements':{}}
    for label in ('reference','current'):
        snapshot={p:source_at(p,REFERENCE if label=='reference' else None) for p in SOURCES}
        extracted=folder/'inputs'/label/'return_control.sv'
        assert extracted.read_text()==build(snapshot)
        if label=='current':check_sources(manifest['source_sha256'][label])
        for name,expected in manifest['extracted_sha256'][label].items():
            assert digest(folder/'inputs'/label/name)==expected
        row=paths[label]
        assert row['all_paths']['graph_complete'] and row['functional_verification']['passed']
        assert digest(folder/'cost'/label/'mapped.json')==row['mapped_sha256']
        assert digest(folder/'pre'/label/'pre_lut.il')==row['pre_lut_sha256']
        report['measurements'][label]={k:row[k] for k in ('mapped_sha256','pre_lut_sha256','resources','functional_verification')}
        report['measurements'][label]['maximum_register_levels']=row['all_paths']['longest_register_path_cells']
        report['measurements'][label]['paths']={s:{t:{k:v[k] for k in ('connected','levels')}
            for t,v in values.items()} for s,values in row['paths'].items()}
        report['measurements'][label]['context_to_ready']=row['paths']['rd_context_count']['o_sa_ready']['path']
        report['measurements'][label]['context_to_vector_start']=row['paths']['rd_context_count']['o_vector_start']['path']
    increases=[]
    for source,targets in paths['reference']['paths'].items():
        for target,old in targets.items():
            new=paths['current']['paths'][source][target]
            if new['levels']>old['levels']:
                increases.append({'source':source,'target':target,'reference':old['levels'],'current':new['levels']})
    assert not increases
    report['source_groups']=len(paths['current']['paths'])
    report['endpoint_groups']=len(paths['current']['paths']['all_sources'])
    report['path_level_increases']=increases
    report['full_soc_evaluation']='在整合后固定源码上重新测量完整 SoC；本文件记录局部连接结果。150 MHz 需完整厂商布线后静态时序分析。'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(args.out,digest(args.out))


if __name__=='__main__':main()
