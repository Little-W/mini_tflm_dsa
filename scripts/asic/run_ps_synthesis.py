#!/usr/bin/env python3
"""Synthesize matched NPU configurations with SMIC40 SRAM timing libraries."""
import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import time
from prepare_dc_sources import prepare
from partition_synthesis import execute, rtl_sources

PROFILES = {
    'legacy_ps': dict(frequency=50, compile_mode='quick', max_cores=1,
        bank_bytes=2048, bank_count=9, ia_blocks=2, ps_frames=4,
        force_raw=False, area_target=None, setup_paths=100, hold_paths=100),
    'npu_r16_150': dict(frequency=150, compile_mode='standard', max_cores=4,
        bank_bytes=8192, bank_count=7, ia_blocks=4, ps_frames=16,
        force_raw=True, area_target=3500000, setup_paths=5000, hold_paths=5000),
}
MEMORY_DATABASES = ('RAMTP128X16_tt_1p10v_1p10v_25c.db',
                    'RAMTP1024X16_tt_1p10v_1p10v_25c.db')
STANDARD_DATABASE = 'scc40nll_vhsc40_rvt_tt_v1p1_25c_basic.db'


def tcl_string(value):
    """转义 Tcl 双引号字符串，保持路径及环境值的字面内容。"""
    text = str(value)
    for before, after in (('\\', '\\\\'), ('"', '\\"'), ('$', '\\$'),
                          ('[', '\\['), (']', '\\]'), ('\n', '\\n'), ('\r', '\\r')):
        text = text.replace(before, after)
    return '"'+text+'"'


def collect_diagnostics(out):
    """汇总工具诊断和报告目标，保留每条警告的实际上下文。"""
    diagnostics = []
    for path in (out/'synthesis.log', out/'npu_top_check_design.rpt',
                 out/'npu_top_check_design_elab.rpt', out/'npu_top_check_timing.rpt'):
        if not path.is_file():
            continue
        lines = path.read_text(errors='replace').splitlines()
        for index, line in enumerate(lines):
            if re.search(r'\b(?:Warning|Error|Fatal):', line):
                code = re.search(r'\(([A-Z]+-\d+)\)', line)
                context = [line]
                for following in lines[index+1:index+9]:
                    if re.search(r'\b(?:Warning|Error|Fatal):', following) or not following.strip():
                        break
                    context.append(following)
                diagnostics.append(dict(file=path.name, line=index+1,
                    code=code.group(1) if code else None, text='\n'.join(context)))
    (out/'warnings.json').write_text(json.dumps(diagnostics, indent=2)+'\n')
    return diagnostics


def report_targets(out, area_target, setup_paths, extended, hold_paths=None):
    area_file = out/'npu_top_area.rpt'
    summary_file = out/'npu_top_summary.rpt'
    area = None
    if area_file.is_file():
        match = re.search(r'Total cell area:\s*([\d.]+)', area_file.read_text())
        if match:
            area = float(match.group(1))
    summary = {}
    if summary_file.is_file():
        for line in summary_file.read_text().splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                summary[key.strip()] = value.strip()
    coverage = None
    coverage_file = out/'npu_top_path_coverage.tsv'
    if coverage_file.is_file():
        coverage = {}
        for line in coverage_file.read_text().splitlines()[1:]:
            kind, requested, exported, examined, exhausted = line.split('\t')
            coverage[kind] = dict(requested=int(requested), exported=int(exported),
                                  examined=int(examined), exhausted=bool(int(exhausted)))
    result = dict(area=area, area_target=area_target,
        area_met=None if area_target is None or area is None else area<=area_target,
        setup_met=None if 'setup_result' not in summary else summary['setup_result']=='PASS',
        hold_met=None if 'hold_result' not in summary else summary['hold_result']=='PASS',
        path_coverage=coverage)
    result['setup_coverage_met'] = (None if not extended or coverage is None else
        coverage.get('max', {}).get('exported', 0) >= setup_paths)
    result['hold_coverage_met'] = (None if not extended or coverage is None else
        coverage.get('min', {}).get('exported', 0) >= (setup_paths if hold_paths is None else hold_paths))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--profile',choices=tuple(PROFILES),default='legacy_ps')
    parser.add_argument('--prepare-only',action='store_true',help='Write reproducible inputs without invoking DC or requiring installed libraries')
    parser.add_argument('--common-root',type=Path,help='Use the same requantization implementation in each comparison')
    parser.add_argument('--libs',type=Path,help='Directory containing both SMIC40 SRAM .db files')
    parser.add_argument('--std-db',type=Path,default=os.environ.get('PS_STD_DB'),
                        help='Standard-cell TT .db file; alternatively set PS_STD_DB')
    parser.add_argument('--operating-condition',default='tt_v1p1_25c')
    parser.add_argument('--frequency',type=float)
    parser.add_argument('--max-cores',type=int)
    parser.add_argument('--shared-bank-count',type=int,choices=range(6,10))
    parser.add_argument('--area-target',type=float)
    parser.add_argument('--setup-paths',type=int)
    parser.add_argument('--hold-paths',type=int)
    parser.add_argument('--timeout',type=float,default=1200,help='DC process time budget in seconds')
    parser.add_argument('--max-memory-gib',type=float,default=10,help='Resident plus swapped memory budget')
    parser.add_argument('--compile-mode',choices=('quick','standard','ultra','drc','hold'))
    parser.add_argument('--checkpoint',type=Path,help='Reuse an elaborated or mapped DDC')
    parser.add_argument('--incremental',action='store_true',help='Incrementally optimize a mapped checkpoint')
    parser.add_argument('--force-raw',action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument('--elaborate-only',action='store_true')
    parser.add_argument('--report-only',action='store_true',help='Measure a mapped checkpoint without recompiling')
    args=parser.parse_args()
    profile=PROFILES[args.profile]
    for option in ('frequency','max_cores','compile_mode','force_raw','area_target','setup_paths','hold_paths'):
        if getattr(args,option) is None:setattr(args,option,profile[option])
    if args.shared_bank_count is None:args.shared_bank_count=profile['bank_count']
    if args.report_only and args.checkpoint is None:parser.error('--report-only requires --checkpoint')
    if args.incremental and args.checkpoint is None:parser.error('--incremental requires --checkpoint')
    if args.checkpoint is not None and not args.checkpoint.is_file():parser.error('Checkpoint does not exist')
    root=args.source_root.resolve();out=args.out.resolve()
    previous_results=[path for pattern in ('synthesis.log','npu_top*.rpt','npu_top*.ddc',
        'npu_top*.vg','npu_top*_paths.csv','npu_top_path_coverage.tsv') for path in out.glob(pattern)]
    if previous_results:
        parser.error('Output directory contains DC results; select a new --out directory')
    if args.std_db is None and not args.prepare_only:parser.error('--std-db or PS_STD_DB is required')
    if args.libs is None and not args.prepare_only:parser.error('--libs is required')
    std_db=(args.std_db or out/'libraries'/STANDARD_DATABASE).resolve()
    libs=(args.libs or out/'libraries').resolve()
    required_libraries=[std_db,*[libs/name for name in MEMORY_DATABASES]]
    missing_libraries=[str(path) for path in required_libraries if not path.is_file()]
    if missing_libraries and not args.prepare_only:parser.error('Libraries do not exist: '+', '.join(missing_libraries))
    if not args.prepare_only and not shutil.which('dc_shell'):parser.error('dc_shell is unavailable; use --prepare-only to generate inputs')
    if args.frequency<=0 or args.max_cores<1 or args.timeout<=0 or args.max_memory_gib<=0:
        parser.error('Frequency, core count and resource budgets must be positive')
    if args.setup_paths<1 or args.hold_paths<1 or (args.area_target is not None and args.area_target<=0):
        parser.error('Path counts and area target must be positive')
    if args.profile=='npu_r16_150' and args.setup_paths<5000:
        parser.error('npu_r16_150 requires at least 5000 setup endpoints')
    for checkpoint in (args.checkpoint,):
        if checkpoint and checkpoint.resolve().parent==out:
            parser.error('Use a separate output directory when reusing a checkpoint')
    out.mkdir(parents=True,exist_ok=True)
    filelist=prepare(root,root/'asic/synthesis/filelists/npu_top.f',out/'sources')
    shutil.copytree(root/'include',out/'sources/include',dirs_exist_ok=True)
    shutil.copytree(root/'asic/rtl',out/'sources/asic/rtl',dirs_exist_ok=True)
    shutil.copytree(root/'asic/synthesis/scripts',out/'flow/scripts',dirs_exist_ok=True)
    shutil.copytree(root/'asic/synthesis/constraints',out/'flow/constraints',dirs_exist_ok=True)
    prepared_lines=[]
    for line in filelist.read_text().splitlines():
        if line.startswith('+incdir+'):
            include=Path(line[8:])
            if include.is_relative_to(root):line='+incdir+'+str(out/'sources'/include.relative_to(root))
        prepared_lines.append(line)
    filelist.write_text('\n'.join(prepared_lines)+'\n')
    common_sources={}
    if args.common_root:
        name='rtl/npu/writeback/vec_requant.sv'
        common=args.common_root.resolve()/name
        shutil.copy2(common,out/'sources'/name)
        common_sources[str(common)]=hashlib.sha256(common.read_bytes()).hexdigest()
    parameters=dict(WEIGHT_WIDTH=16,DATA_WIDTH=16,SIZE=16,BUS_WIDTH=64,REG_WIDTH=32,ADDR_WIDTH=19,
        SHARED_BANK_BYTES=profile['bank_bytes'],SHARED_BANK_COUNT=args.shared_bank_count,
        IA_CACHE_BLOCKS=profile['ia_blocks'],IM2COL_CACHE_BYTES=4096,
        PS_FRAME_COUNT=profile['ps_frames'],AXI_READ_OUTSTANDING=4,AXI_WRITE_OUTSTANDING=4,ENABLE_IS_MODE=1,ENABLE_PER_CHANNEL=1)
    if args.profile=='npu_r16_150':
        parameters.update(DW_PE_COUNT=16,VECTOR_PE_COUNT=16,WINDOW_LANES=16)
    pool_bytes=(args.shared_bank_count-1)*profile['bank_bytes']
    defines='+define+GEMPACT_PS_COMPRESS+GEMMORA_PS_POOL_BYTES='+str(pool_bytes)
    if args.force_raw:defines+='+GEMMORA_PS_FORCE_RAW'
    settings=dict(PROJ_PATH=str(out/'flow'),PROJ_ROOT=str(out/'sources'),PROJ_TEMP=str(out),
        RTL_ROOT=str(out/'sources/rtl'),INC_ROOT=str(out/'sources/include'),DESIGN='npu_top',DESIGN_TOP='npu_top',
        DESIGN_FILELIST=str(filelist),DESIGN_SYN_SDC=str(out/'flow/constraints/npu_top.sdc'),
        DESIGN_TARGET_FREQ_MHZ=str(args.frequency),DESIGN_MAX_CORES=str(args.max_cores),DESIGN_COMPILE_MODE=args.compile_mode,
        DESIGN_ELAB_ONLY=str(int(args.elaborate_only)),DESIGN_RTL_DEFINES=defines,
        DESIGN_REPORT_ONLY=str(int(args.report_only)),
        DESIGN_CHECKPOINT=str(args.checkpoint.resolve()) if args.checkpoint else '',
        DESIGN_INCREMENTAL=str(int(args.incremental)),
        DESIGN_PARAMETERS=','.join(k+'='+str(v) for k,v in parameters.items()),
        STD_DB_PATH=str(std_db.parent),STD_DB_LIST=std_db.name,MEM_DB_PATH=str(libs),
        MEM_DB_LIST=' '.join(MEMORY_DATABASES),
        SYN_STD_LIB_NAME=std_db.stem,SYN_OPER_CONDITION=args.operating_condition)
    settings.update(DESIGN_PARTITION_TIMEOUT=str(args.timeout),DESIGN_PARTITION_MEMORY_GIB=str(args.max_memory_gib),
        DESIGN_EXTENDED_REPORTS='1' if args.profile=='npu_r16_150' else '0',
        DESIGN_SETUP_PATH_COUNT=str(args.setup_paths),DESIGN_HOLD_PATH_COUNT=str(args.hold_paths),
        DESIGN_AREA_TARGET='' if args.area_target is None else str(args.area_target))
    env=os.environ.copy();env.update(settings)
    inputs=rtl_sources(root)+list((root/'asic/synthesis').rglob('*.tcl'))
    inputs += list((root/'include').rglob('*.vh'))
    inputs += [root/'asic/synthesis/constraints/npu_top.sdc',root/'asic/synthesis/filelists/npu_top.f']
    inputs = sorted(set(inputs))
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    libraries=[path for path in required_libraries if path.is_file()]
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
    script='\n'.join('set ::env('+name+') '+tcl_string(value) for name,value in sorted(settings.items()))
    script+='\ncd '+tcl_string(out)+'\nsource -e -v '+tcl_string(out/'flow/scripts/dc.tcl')+'\n'
    (out/'run.tcl').write_text(script)
    (out/'environment.json').write_text(json.dumps(settings,indent=2)+'\n')
    prepared_files=sorted(path for folder in ('sources','flow') for path in (out/folder).rglob('*') if path.is_file())
    snapshot_hashes={str(path.relative_to(out)):hashlib.sha256(path.read_bytes()).hexdigest() for path in prepared_files}
    start=time.monotonic();log=out/'synthesis.log'
    manifest=dict(profile=args.profile,passed=None,dc_executed=False,execution_status='NOT_RUN',
        parameters=parameters,frequency_mhz=args.frequency,area_target=args.area_target,
        ps_pool_bytes=pool_bytes,setup_path_count=args.setup_paths,hold_path_count=args.hold_paths,
        force_raw=args.force_raw,compile_mode=args.compile_mode,max_cores=args.max_cores,report_only=args.report_only,
        timeout_seconds=args.timeout,max_memory_gib=args.max_memory_gib,
        library_sha256=library_hashes,missing_libraries=missing_libraries,
        checkpoint=str(args.checkpoint.resolve()) if args.checkpoint else None,incremental=args.incremental,
        checkpoint_sha256=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() if args.checkpoint else None,
        common_source_sha256=common_sources,source_sha256=hashes,snapshot_sha256=snapshot_hashes,
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip())
    if args.prepare_only:
        (out/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(json.dumps(dict(execution_status='NOT_RUN',dc_executed=False,profile=args.profile,
                             parameters=parameters,frequency_mhz=args.frequency,output=str(out))))
        return 0
    returncode=0
    try:
        execute(script,out,env)
    except RuntimeError:
        returncode=1
    text=log.read_text();summary=out/('npu_top_elab_references.rpt' if args.elaborate_only else 'npu_top_summary.rpt')
    unchanged=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==v for p,v in hashes.items())
    libraries_unchanged=all(hashlib.sha256(path.read_bytes()).hexdigest()==library_hashes[path.name]
                            for path in libraries)
    snapshot_unchanged=all(hashlib.sha256((out/name).read_bytes()).hexdigest()==value for name,value in snapshot_hashes.items())
    completed=returncode==0 and summary.is_file() and not re.search(r'^(Error:|Fatal:)',text,re.M) and unchanged and libraries_unchanged and snapshot_unchanged
    diagnostics=collect_diagnostics(out)
    targets=report_targets(out,args.area_target,args.setup_paths,args.profile=='npu_r16_150',args.hold_paths)
    targets_met=all(targets[name] is True for name in ('area_met','setup_met','hold_met',
        'setup_coverage_met','hold_coverage_met')) if args.profile=='npu_r16_150' and not args.elaborate_only else None
    passed=bool(completed and targets_met is not False)
    manifest.update(passed=passed,dc_executed=True,execution_status='COMPLETED' if completed else 'FAILED',
        returncode=returncode,run_completed=bool(completed),targets_met=targets_met,targets=targets,
        diagnostic_count=len(diagnostics),libraries_unchanged=libraries_unchanged,sources_unchanged=unchanged,
        snapshot_unchanged=snapshot_unchanged,elapsed_seconds=time.monotonic()-start,tool_log=str(log))
    (out/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('source_sha256','snapshot_sha256')}))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
