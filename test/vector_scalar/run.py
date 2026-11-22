#!/usr/bin/env python3
"""验证标量乘法器的完整乘积、流水周期和连续输入。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--reference-rev',default='ef0dc75')
    parser.add_argument('--simulate',action='store_true')
    parser.add_argument('--simulator',choices=['verilator','iverilog'],default='verilator')
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    parser.add_argument('--synthesis',action='store_true')
    parser.add_argument('--synth-script',type=Path,default=ROOT/'scripts/fpga/open_fpga_synth.py')
    parser.add_argument('--lock-file',type=Path)
    parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)));return
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'rtl/npu/conv/vector_scalar_multiplier.sv'
    old=read_rtl_source(args.reference_rev+':rtl/npu/conv/vector_scalar_multiplier.sv', cwd=ROOT, text=True)
    reference=out/'reference.sv'
    reference.write_text(re.sub(r'\bvector_scalar_multiplier\b','vector_scalar_multiplier_reference',
                                re.sub(r'\bregistered_multiplier_s32\b','registered_multiplier_s32_reference',old)))
    multiplier=ROOT/'rtl/npu/conv/registered_multiplier_s32.sv'
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    multiplier_hash=hashlib.sha256(multiplier.read_bytes()).hexdigest()
    common=ROOT/'rtl/common/parallel_prefix_add.sv'
    common_hash=hashlib.sha256(common.read_bytes()).hexdigest()
    summary={'source_sha256':source_hash,'reference_rev':args.reference_rev,
        'parallel_prefix_add_sha256':common_hash,
        'reference_sha256':hashlib.sha256(old.encode()).hexdigest(),
        'registered_multiplier_s32_sha256':multiplier_hash,
        'latency_edges':2,'initiation_interval':1,'formal':[]}
    commands=[]
    for label,top,path in (('reference','vector_scalar_multiplier_reference',reference),
                           ('candidate','vector_scalar_multiplier',source)):
        commands += ['read_slang -D ASIC_SYNTHESIS=1 --top '+top+' '+
            ' '.join(shlex.quote(str(p)) for p in
                     ([path, common] if label=='reference' else [path, multiplier, common]))]
        commands += ['prep -top '+top+' -flatten','wreduce','opt -full']
        commands += ['rename -top '+label,'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
        'design -copy-from candidate -as candidate candidate','equiv_make reference candidate equivalent',
        'hierarchy -top equivalent','equiv_struct -fwd -icells','equiv_simple -seq 2','equiv_induct -seq 2','equiv_status -assert']
    script=out/'formal.ys';script.write_text('\n'.join(commands)+'\n')
    log_path=out/'formal.log'
    with log_path.open('w') as stream:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT)
    log=log_path.read_text();proved=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log)
    record={'passed':result.returncode==0 and 'Equivalence successfully proven' in log,
        'equivalent_bits':int(proved[1]) if proved else None}
    summary['formal'].append(record);print(json.dumps(record),flush=True)
    if not record['passed']:raise RuntimeError(log[-10000:])
    if args.simulate:
        dependencies=[source,multiplier,reference,common,HERE/'tb_vector_scalar.sv']
        if args.simulator=='verilator':
            cmd=[args.verilator,'--binary','--timing','--assert','-Wno-fatal','--top-module','tb_vector_scalar',
                 '-DASIC_SYNTHESIS=1','-j','1','--Mdir',str(out/'obj'),*map(str,dependencies)]
            execute=[str(out/'obj/Vtb_vector_scalar')]
        else:
            binary=out/'simulation.vvp'
            cmd=[args.iverilog,'-g2012','-DASIC_SYNTHESIS=1','-s','tb_vector_scalar',
                 '-o',str(binary),*map(str,dependencies)]
            execute=[args.vvp,str(binary)]
        with (out/'compile.log').open('w') as stream:
            subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run(execute,capture_output=True,text=True,check=True,timeout=600)
        (out/'simulation.log').write_text(result.stdout+result.stderr)
        line=next(line for line in result.stdout.splitlines() if line.startswith('VECTOR_SCALAR_PASS'))
        summary['simulation']={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}
        summary['simulation'].update(simulator=args.simulator,command=cmd,
            log_sha256=hashlib.sha256((out/'simulation.log').read_bytes()).hexdigest())
        print(line,flush=True)
    if args.synthesis:
        cases={label:{'top':top,'options':['-D','ASIC_SYNTHESIS=1'],'sources':list(map(str, [path,common] if label=='scalar_reference' else [path,multiplier,common])),
               'configuration':'Signed INT32 multiplication, two register edges, one input per cycle'}
               for label,top,path in (('scalar_reference','vector_scalar_multiplier_reference',reference),
                                      ('scalar_current','vector_scalar_multiplier',source))}
        config=out/'cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
        command=[sys.executable,str(args.synth_script.resolve()),'--source-root',str(ROOT),
            '--case-config',str(config),'--cases',*cases,'--out',str(out/'synthesis')]
        if args.lock_file:command+=['--lock-file',str(args.lock_file.resolve())]
        subprocess.run(command,check=True)
    summary['passed']=(hashlib.sha256(source.read_bytes()).hexdigest()==source_hash and
                       hashlib.sha256(common.read_bytes()).hexdigest()==common_hash and
                       hashlib.sha256(multiplier.read_bytes()).hexdigest()==multiplier_hash)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not summary['passed']:raise RuntimeError('Scalar RTL changed during verification')


if __name__=='__main__':main()
