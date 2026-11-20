#!/usr/bin/env python3
"""核对受测源码、形式、数值与实际连接映射摘要，保存当前设计报告。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from extract import ROOT, TOP, CTRL, ARB, ADD, REFERENCE, digest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def validate_sources(values):
    for name,expected in values.items():
        path=Path(name)
        if not path.is_absolute():path=ROOT/path
        if digest(path)!=expected:raise RuntimeError('Verified source differs: '+str(path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=Path('build/npu_admission_r22'))
    parser.add_argument('--out',type=Path,default=Path('test/npu_admission_r22/measurement.json'))
    args=parser.parse_args();base=args.build.resolve()
    inputs={
        'formal':base/'formal_complete/summary.json',
        'controller_numeric':base/'controller_numeric/summary.json',
        'dma_numeric':base/'dma_numeric/summary.json',
        'mapping_inputs':base/'mapping_inputs/manifest.json',
        'mapping':base/'path_summary.json',
    }
    data={name:json.loads(path.read_text()) for name,path in inputs.items()}
    for name in ('formal','controller_numeric','dma_numeric'):
        if data[name]['passed'] is not True:raise RuntimeError('Verification is incomplete: '+name)
        validate_sources(data[name]['source_sha256'])
    validate_sources(data['formal']['arbiter']['source_sha256'])
    for run in data['dma_numeric']['runs']:validate_sources(run['source_sha256'])
    for label,values in data['mapping_inputs']['source_sha256'].items():
        if label=='current':validate_sources(values)
        else:
            for name,expected in values.items():
                source=read_rtl_source(f'{REFERENCE}:{name}', cwd=ROOT)
                if hashlib.sha256(source).hexdigest()!=expected:
                    raise RuntimeError('Reference source differs: '+name)
    for label,values in data['mapping_inputs']['extracted_sha256'].items():
        for name,expected in values.items():
            if digest(base/'mapping_inputs'/label/name)!=expected:
                raise RuntimeError('Measured source excerpt differs: '+name)
    for name,row in data['mapping'].items():
        if not row['all_paths']['graph_complete'] or not row['functional_verification']['passed']:
            raise RuntimeError('Mapping or complete graph verification failed: '+name)
        if row['mapped_sha256']!=digest(base/'cost'/name/'mapped.json'):
            raise RuntimeError('Mapped graph differs: '+name)
        if row['pre_lut_sha256']!=digest(base/'pre'/name/'pre_lut.il'):
            raise RuntimeError('Register source graph differs: '+name)
    if any(row['unique_state_bits']!=24 for row in data['formal']['controller']):
        raise RuntimeError('The complete controller state must contain 24 observed bits')
    report={'passed':True,'reference_commit':REFERENCE,
        'source_sha256':{str(p):digest(ROOT/p) for p in (TOP,CTRL,ARB,ADD)},
        'additional_register_bits':0,'additional_interface_cycles':0,
        'controller_address_observation':'Only zero/nonzero is consumed; compare min(REG_WIDTH,32) low bits after the original 32-bit result and controller-port conversion.',
        'formal':data['formal'],'controller_numeric':data['controller_numeric'],
        'dma_numeric':data['dma_numeric'],'mapping_inputs':data['mapping_inputs'],
        'mapping':data['mapping'],
        'report_inputs_sha256':{name:digest(path) for name,path in inputs.items()},
        'verification_source_sha256':{str(path.relative_to(ROOT)):digest(path)
            for path in sorted((ROOT/'test/npu_admission_r22').glob('*.py'))},
        'imported_verification_source_sha256':{str(path):digest(ROOT/path) for path in (
            Path('test/npu_admission/run_formal.py'),Path('test/npu_fault_fanin/extract_fault.py'),
            Path('test/dma_return_admission/run_arbiter_formal.py'),Path('test/dma_read_permission/run_numeric.py'),
            Path('test/dma_abort/run_read_arbiter.py'))},
        'scope':'Independent actual-controller and actual-return-control connection measurements; complete SoC area and depth require the fixed integrated design.',
        'physical_lut_positions':None,'timing_150mhz_confirmed':None}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':True,'output':str(args.out),'sha256':digest(args.out)},ensure_ascii=False))


if __name__=='__main__':main()
