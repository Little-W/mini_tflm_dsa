#!/usr/bin/env python3
"""复用生产 NPU 仿真程序，覆盖合并输出、方向切换及错误恢复。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test/ps_compression'))
from run_shared_npu import configure,input_bank_count,npu


def generate(folder, manifest):
    folder.mkdir(parents=True,exist_ok=True)
    cases=[]
    bases=(0x1003,0x20003,0x40000,0x58000,0x48000,0x50000)
    specifications=[
        ('ws_short',0,5,16,32,1,2,0,0,0,False),
        ('is_short',1,5,16,32,2,1,0,0,0,False),
        ('ws_group_tail',0,33,35,64,2,4,0,0,0,False),
        ('is_group_tail',1,19,35,64,4,2,0,0,0,False),
        ('ws_write_abort',0,33,16,64,2,4,0,3,2,False),
        ('is_recovery',1,19,16,64,4,2,0,0,0,False),
        ('ws_frame',0,33,35,64,2,2,2,0,0,False),
        ('is_frame',1,19,35,64,4,2,2,0,0,False),
        ('ws_s16_output',0,19,35,32,2,2,0,0,0,True),
        ('ws_refresh',0,5,16,32,1,2,0,0,0,False),
        ('is_read_abort',1,5,16,32,2,1,0,3,1,False),
        ('ws_after_read_abort',0,33,16,64,2,4,0,0,0,False),
        ('is_invalid_reuse',1,5,16,32,3,1,0,2,0,False),
        ('ws_after_invalid',0,5,16,32,1,2,0,0,0,False),
        ('is_after_invalid',1,5,16,32,2,1,0,0,0,False),
    ]
    for name,mode,rows,red,cols,r,w,control,error,inject,out16 in specifications:
        # 写响应错误可发生于部分输出已经写回之后，预先填入正确输出以检查任意完成前缀。
        make_error=0 if inject==2 else error
        directory=npu.precision_task(folder,16,name=name,dataflow=mode,rows=rows,reduction=red,
            columns=cols,lhs_s16=out16,output_s16=out16,expected_error=make_error,memory_bases=bases)
        banks=input_bank_count(manifest,mode=mode,lhs_s16=out16,requested_banks=2 if out16 else 1)
        configure(directory,banks=banks,r=r,w=w,control=control,bank_bytes=8192,bank_count=7)
        config=directory/'config.mem'
        words=[int(value,16) for value in read_rtl_text(config).split()]
        words[52],words[53]=error,inject
        config.write_text(''.join(f'{value:08x}\n' for value in words))
        if inject==2:
            (directory/'init.mem').write_bytes((directory/'golden.mem').read_bytes())
        metadata=json.loads(read_rtl_text(directory/'case.json'))
        metadata.update(expected_error=error,inject_axi_response=inject,
            preinitialized_output=inject==2,expected_frame_commands=control==2)
        (directory/'case.json').write_text(json.dumps(metadata,indent=2)+'\n')
        cases.append(directory)
    return cases


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    sims=p.add_mutually_exclusive_group(required=True)
    sims.add_argument('--sim',type=Path,help='生产仿真目录，包含 build.json 和 obj/Vtb_conv_npu')
    sims.add_argument('--reference-sim',type=Path,help='仅检查案例期望值，不要求新增观察器')
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sim=(args.sim or args.reference_sim).resolve()
    manifest=json.loads(read_rtl_text(sim/'build.json'))
    expected={'returncode':0,'size':16,'bus_width':64,'shared_bank_bytes':8192,
        'shared_bank_count':7,'ps_compress':True,'force_raw':True,'pool_bytes':49152}
    for key,value in expected.items():
        if manifest.get(key)!=value:raise RuntimeError(f'Simulator {key} differs from {value}')
    binary=sim/'obj/Vtb_conv_npu'
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=manifest['binary_sha256']:
        raise RuntimeError('Simulator binary differs from its manifest')
    if args.sim:
        source_root=Path(manifest.get('source_root',ROOT)).resolve()
        for name in ('rtl/npu/writeback/vec_s8_to_fifo.sv',
                     'test/monitors/npu_top_observer.sv',
                     'test/monitors/npu_output_pipeline_observer.sv'):
            source=source_root/name if name.startswith('rtl/') else ROOT/name
            if manifest['source_sha256'].get(name)!=hashlib.sha256(source.read_bytes()).hexdigest():
                raise RuntimeError('Simulator source differs: '+name)
    cases=generate(out/'cases',manifest)
    result=npu.run_suite(binary,out,'fifo_modes',cases,no_random=False)
    text=read_rtl_text(out/'fifo_modes.log')
    matches=re.findall(r'^NPU_FIFO_COMPARE_PASS (.*)$',text,re.M)
    coverage={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',matches[-1])} if matches else {}
    coverage_passed=all(coverage.get(key,0)>0 for key in ('coalesce_cycles','frame_cycles',
        'ws_coalesce_cycles','is_coalesce_cycles','ws_to_is','is_to_ws','recovery_resets'))
    measurements=result['measurements']
    command_modes_passed=len(measurements)==len(cases) and all(
        (item['frame_commands']>0)==(index in (6,7)) for index,item in enumerate(measurements))
    summary={'passed':result['passed'] and command_modes_passed and (coverage_passed or args.reference_sim is not None),
        'validation_scope':'case_expectations' if args.reference_sim else 'production_fifo',
        'cases':len(cases),'completed_cases':len(measurements),'coverage':coverage,
        'coverage_passed':coverage_passed,'command_modes_passed':command_modes_passed,
        'int32_checks':sum(item['int32_checks'] for item in measurements),
        'ia_compact_enable':manifest['ia_compact_enable'],
        'simulator_manifest':str(sim/'build.json'),'suite':result}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='suite'},indent=2))
    if not summary['passed']:raise SystemExit(1)


if __name__=='__main__':main()
