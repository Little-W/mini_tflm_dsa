#!/usr/bin/env python3
"""核对返回标签选择的源码、形式检查、实际 DMA 测试和映射结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_dual_block_dma.sv'
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();build=args.build.resolve()
    formal=json.loads((build/'formal/summary.json').read_text())
    numeric=json.loads((build/'numeric/summary.json').read_text())
    local_source=json.loads((build/'local/source.json').read_text())
    source_sha=digest(ROOT/SOURCE)
    assert formal['passed'] and formal['source_sha256']==source_sha
    assert len(formal['cases'])==16 and not formal['inputs_constrained']
    assert formal['outside_response_tag_selection_unchanged']
    assert local_source['cases']['current']['source_sha256']==source_sha
    assert local_source['cases']['reference']['source_sha256']==formal['reference_sha256']
    for case in formal['cases']:
        name=f"width{case['rd_tag_width']}_{case['implementation']}"
        log=build/'formal'/(name+'.log');script=build/'formal'/(name+'.ys')
        assert case['passed'] and case['log_sha256']==digest(log)
        assert case['script_sha256']==digest(script)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
    assert numeric['passed'] and len(numeric['runs'])==2
    for run in numeric['runs']:
        assert run['passed'] and run['source_sha256'][SOURCE]==source_sha
        for name,value in run['source_sha256'].items():
            assert digest(ROOT/name)==value,name
        directory=build/'numeric'/('bus'+str(run['bus_width']))
        assert digest(directory/'obj/Varbiter_read_tb')==run['binary_sha256']
        assert digest(directory/'summary.json')==run['summary_sha256']
        assert run['undefined_behavior_sanitizer']
    assert {run['bus_width'] for run in numeric['runs']}=={32,64}
    mapping={}
    output_files={}
    for mode,base in [('native',build/'local/results'),('physical_cost',build/'cost')]:
        mapping[mode]={}
        for label in ('reference','current'):
            folder=base/label
            metrics=json.loads((folder/'metrics.json').read_text())
            assert metrics['paths']['graph_complete']
            module=json.loads((folder/'mapped.json').read_text())['modules']['response_tag_connection']
            pre_lut=build/'local/results'/label/'pre_lut.il'
            for name,value in register_origins(pre_lut).items():
                if name in module['cells']:
                    module['cells'][name].setdefault('attributes',{})['fpga_register_origin']=value
            paths=connected_paths(module,limit=10,group_limit=10,
                root_filter=lambda n,c,p:origin(c).startswith('response_queue_error'),
                sink_filter=lambda n,c,p:origin(c)=='o_vector_raw_valid' and p=='D')
            assert paths['graph_complete'] and paths['longest_register_path_cells']>0
            item={'source_sha256':local_source['cases'][label]['source_sha256'],
                  'resources':metrics['resources'],
                  'longest_register_path_cells':metrics['paths']['longest_register_path_cells'],
                  'response_error_to_vector_raw_valid':paths,
                  'mapped_sha256':digest(folder/'mapped.json'),'pre_lut_sha256':digest(pre_lut),
                  'manifest_sha256':digest(folder/'manifest.json')}
            if mode=='physical_cost':
                summary=json.loads((folder/'summary.json').read_text())
                assert summary['functional_verification']['passed']
                assert 'Networks are equivalent.' in (folder/'03_map_lut.log').read_text()
                item['mapping_profile']=summary['lut_mapping']
                item['functional_verification']=summary['functional_verification']
            mapping[mode][label]=item
            for filename in ('mapped.json','manifest.json','metrics.json','03_map_lut.log'):
                path=folder/filename
                output_files[str(path.relative_to(build))]=digest(path)
    for name,value in local_source['support_sha256'].items():
        assert digest(ROOT/name)==value,name
    changed=subprocess.check_output(['git','diff','--name-only',formal['reference_commit'],'--','rtl','config'],
                                    cwd=ROOT,text=True).splitlines()
    assert changed==[SOURCE],changed
    for name in ('formal/summary.json','numeric/summary.json','local/source.json','local/cases.json'):
        output_files[name]=digest(build/name)
    report={'passed':True,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'reference_commit':formal['reference_commit'],'source_sha256':source_sha,
            'other_rtl_configuration_unchanged':True,'added_register_bits':0,'added_interface_cycles':0,
            'formal':formal,'numeric':numeric,'numeric_sources_unchanged_after_simulation':True,
            'mapping_scope':'缓存错误数组、前端写入有效、返回标签和仲裁器向量有效译码的实际源码表达式；输入和输出均寄存。',
            'mapping':mapping,'support_sha256':local_source['support_sha256'],
            'output_sha256':output_files,
            'script_sha256':{name:digest(ROOT/name) for name in (
                'test/dma_response_tag/run_formal.py','test/dma_response_tag/prepare_measurement.py',
                'test/dma_response_tag/collect_report.py','test/dma_read_permission/run_numeric.py',
                'test/dma_abort/run_read_arbiter.py','scripts/fpga/open_fpga_synth.py',
                'scripts/fpga/remap_fpga_luts.py','scripts/fpga/netlist_metrics.py')}}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'source_sha256':source_sha,'formal_cases':16,
                     'numeric_cases':sum(run['cases'] for run in numeric['runs']),
                     'numeric_checks':sum(run['checks'] for run in numeric['runs']),
                     'report_sha256':digest(args.out)},indent=2))


if __name__=='__main__':main()
