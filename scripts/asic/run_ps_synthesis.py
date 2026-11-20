#!/usr/bin/env python3
"""Synthesize matched NPU configurations with SMIC40 SRAM timing libraries."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import time
from prepare_dc_sources import prepare
from partition_synthesis import execute, rtl_sources


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--common-root',type=Path,help='Use the same requantization implementation in each comparison')
    parser.add_argument('--libs',type=Path,required=True)
    parser.add_argument('--std-db',type=Path,default=os.environ.get('PS_STD_DB'),
                        help='Standard-cell TT .db file; alternatively set PS_STD_DB')
    parser.add_argument('--operating-condition',default='tt_v1p1_25c')
    parser.add_argument('--frequency',type=float,default=50)
    parser.add_argument('--max-cores',type=int,default=1)
    parser.add_argument('--shared-bank-count',type=int,choices=range(6,10),default=9)
    parser.add_argument('--timeout',type=float,default=1200,help='DC process time budget in seconds')
    parser.add_argument('--max-memory-gib',type=float,default=10,help='Resident plus swapped memory budget')
    parser.add_argument('--compile-mode',choices=('quick','standard','ultra','drc','hold'),default='quick')
    parser.add_argument('--checkpoint',type=Path,help='Reuse an elaborated or mapped DDC')
    parser.add_argument('--incremental',action='store_true',help='Incrementally optimize a mapped checkpoint')
    parser.add_argument('--force-raw',action='store_true')
    parser.add_argument('--elaborate-only',action='store_true')
    parser.add_argument('--report-only',action='store_true',help='Measure a mapped checkpoint without recompiling')
    args=parser.parse_args()
    if args.report_only and args.checkpoint is None:parser.error('--report-only requires --checkpoint')
    if args.incremental and args.checkpoint is None:parser.error('--incremental requires --checkpoint')
    if args.checkpoint is not None and not args.checkpoint.is_file():parser.error('Checkpoint does not exist')
    if args.std_db is None:parser.error('--std-db or PS_STD_DB is required')
    std_db=args.std_db.resolve()
    if not std_db.is_file():parser.error('Standard-cell library does not exist')
    root=args.source_root.resolve();out=args.out.resolve()
    if args.frequency<=0 or args.max_cores<1 or args.timeout<=0 or args.max_memory_gib<=0:
        parser.error('Frequency, core count and resource budgets must be positive')
    for checkpoint in (args.checkpoint,):
        if checkpoint and checkpoint.resolve().parent==out:
            parser.error('Use a separate output directory when reusing a checkpoint')
    out.mkdir(parents=True,exist_ok=True)
    filelist=prepare(root,root/'asic/synthesis/filelists/npu_top.f',out/'sources')
    common_sources={}
    if args.common_root:
        name='rtl/npu/writeback/vec_requant.sv'
        common=args.common_root.resolve()/name
        shutil.copy2(common,out/'sources'/name)
        common_sources[str(common)]=hashlib.sha256(common.read_bytes()).hexdigest()
    parameters=dict(WEIGHT_WIDTH=16,DATA_WIDTH=16,SIZE=16,BUS_WIDTH=64,REG_WIDTH=32,ADDR_WIDTH=19,
        SHARED_BANK_BYTES=2048,SHARED_BANK_COUNT=args.shared_bank_count,IA_CACHE_BLOCKS=2,IM2COL_CACHE_BYTES=4096,
        PS_FRAME_COUNT=4,AXI_READ_OUTSTANDING=4,AXI_WRITE_OUTSTANDING=4,ENABLE_IS_MODE=1,ENABLE_PER_CHANNEL=1)
    defines='+define+GEMPACT_PS_COMPRESS+GEMMORA_PS_POOL_BYTES='+str((args.shared_bank_count-1)*2048)
    if args.force_raw:defines+='+GEMMORA_PS_FORCE_RAW'
    env=os.environ.copy();env.update(PROJ_PATH=str(root/'asic/synthesis'),PROJ_ROOT=str(root),PROJ_TEMP=str(out),
        RTL_ROOT=str(root/'rtl'),INC_ROOT=str(root/'include'),DESIGN='npu_top',DESIGN_TOP='npu_top',
        DESIGN_FILELIST=str(filelist),DESIGN_SYN_SDC=str(root/'asic/synthesis/constraints/npu_top.sdc'),
        DESIGN_TARGET_FREQ_MHZ=str(args.frequency),DESIGN_MAX_CORES=str(args.max_cores),DESIGN_COMPILE_MODE=args.compile_mode,
        DESIGN_ELAB_ONLY=str(int(args.elaborate_only)),DESIGN_RTL_DEFINES=defines,
        DESIGN_REPORT_ONLY=str(int(args.report_only)),
        DESIGN_CHECKPOINT=str(args.checkpoint.resolve()) if args.checkpoint else '',
        DESIGN_INCREMENTAL=str(int(args.incremental)),
        DESIGN_PARAMETERS=','.join(k+'='+str(v) for k,v in parameters.items()),
        STD_DB_PATH=str(std_db.parent),STD_DB_LIST=std_db.name,MEM_DB_PATH=str(args.libs.resolve()),
        MEM_DB_LIST='RAMTP128X16_tt_1p10v_1p10v_25c.db RAMTP1024X16_tt_1p10v_1p10v_25c.db',
        SYN_STD_LIB_NAME=std_db.stem,SYN_OPER_CONDITION=args.operating_condition)
    env.update(DESIGN_PARTITION_TIMEOUT=str(args.timeout),DESIGN_PARTITION_MEMORY_GIB=str(args.max_memory_gib))
    inputs=rtl_sources(root)+list((root/'asic/synthesis').rglob('*.tcl'))
    inputs += list((root/'include').rglob('*.vh'))
    inputs += [root/'asic/synthesis/constraints/npu_top.sdc',root/'asic/synthesis/filelists/npu_top.f']
    inputs = sorted(set(inputs))
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    libraries=[std_db,*sorted(args.libs.resolve().glob('*.db'))]
    library_hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in libraries}
    if args.checkpoint:
        prior_file=args.checkpoint.parent/'run.json'
        if prior_file.is_file():
            prior=json.loads(prior_file.read_text())
            if prior['parameters']!=parameters or prior['force_raw']!=args.force_raw:
                parser.error('Checkpoint parameters differ from the requested hardware')
            for name,digest in prior['source_sha256'].items():
                if name.startswith(('rtl/','include/','asic/rtl/')) and hashes.get(name)!=digest:
                    parser.error('Checkpoint RTL differs from the current sources: '+name)
    start=time.monotonic();log=out/'synthesis.log'
    returncode=0
    try:
        execute('source -e -v {'+str(root/'asic/synthesis/scripts/dc.tcl')+'}\n',out,env)
    except RuntimeError:
        returncode=1
    text=log.read_text();summary=out/('npu_top_elab_references.rpt' if args.elaborate_only else 'npu_top_summary.rpt')
    unchanged=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==v for p,v in hashes.items())
    libraries_unchanged=all(hashlib.sha256(path.read_bytes()).hexdigest()==library_hashes[path.name]
                            for path in libraries)
    passed=returncode==0 and summary.is_file() and not any(line.startswith('Error:') for line in text.splitlines()) and unchanged and libraries_unchanged
    manifest=dict(passed=passed,returncode=returncode,parameters=parameters,frequency_mhz=args.frequency,
        force_raw=args.force_raw,compile_mode=args.compile_mode,max_cores=args.max_cores,report_only=args.report_only,
        timeout_seconds=args.timeout,max_memory_gib=args.max_memory_gib,
        library_sha256=library_hashes,libraries_unchanged=libraries_unchanged,
        checkpoint=str(args.checkpoint.resolve()) if args.checkpoint else None,incremental=args.incremental,
        checkpoint_sha256=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() if args.checkpoint else None,
        common_source_sha256=common_sources,source_sha256=hashes,sources_unchanged=unchanged,elapsed_seconds=time.monotonic()-start,
        tool_log=str(log),source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())
    (out/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='source_sha256'}))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
