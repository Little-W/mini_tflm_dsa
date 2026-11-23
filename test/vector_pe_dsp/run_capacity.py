#!/usr/bin/env python3
"""核对各 PE 配置的生产矩阵、向量单元、存储容量和寄存状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.capacity import config, elaboration


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--pes',type=int,nargs='+',default=[8,16])
    parser.add_argument('--ia-compact-enable',type=int,choices=(0,1))
    parser.add_argument('--verilator',default='verilator')
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    values=config.selected_config(ROOT/'config/npu_fpga.mk')
    if args.ia_compact_enable is not None:
        values['IA_COMPACT_ENABLE']=args.ia_compact_enable
    hashes=elaboration.sources_sha256()
    runs=[]
    for pes in args.pes:
        if pes<1 or pes>values['SIZE'] or pes&(pes-1):
            parser.error('--pes must be a supported power of two within SIZE')
        profile=dict(values,VECTOR_PE_COUNT=pes)
        measured=elaboration.measure(profile,verilator=args.verilator,output_dir=out/f'pe{pes}')
        if not measured['passed']:
            raise RuntimeError(f'PE{pes} 容量或计算结构检查未通过')
        state=measured['elaborated_state']
        counts=state['module_instances']
        if counts.get('vector_pe')!=pes or counts.get('ws_systolic_cell')!=values['SIZE']**2:
            raise RuntimeError('计算单元并行数量不一致')
        runs.append({'pe_count':pes,'passed':True,
                     'total_state_bits':state['total_bits'],
                     'buffer_arrays_bits':state['buffer_arrays_bits'],
                     'register_arrays_bits':state['register_arrays_bits'],
                     'vector_pe_instances':counts['vector_pe'],
                     'systolic_cell_instances':counts['ws_systolic_cell'],
                     'hardware_configuration':measured['hardware_configuration']})
    if hashes!=elaboration.sources_sha256():
        raise RuntimeError('结构检查期间源码发生变化')
    report={'passed':True,'configuration':values,'source_sha256':hashes,
            'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'runs':runs}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'pe_counts':args.pes}),flush=True)


if __name__=='__main__':
    main()
