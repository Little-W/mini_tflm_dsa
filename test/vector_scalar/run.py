#!/usr/bin/env python3
"""验证正式标量乘法器的完整乘积、DSP 流水周期和综合资源。"""
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
    parser.add_argument('--verilator',default='verilator-modern')
    parser.add_argument('--simulate',action='store_true')
    parser.add_argument('--synthesis',action='store_true')
    parser.add_argument('--synth-script',type=Path,default=ROOT/'scripts/fpga/open_fpga_synth.py')
    parser.add_argument('--lock-file',type=Path)
    parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)));return
    import pyosys
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    models=[re.search(r'^module '+name+r'\b.*?^endmodule',library.read_text(),re.M|re.S).group(0)
            for name in ('DSP48E1','FDRE')]
    model=re.sub(r'\bspecify\b.*?\bendspecify\b','', '\n'.join(models), flags=re.S)
    model_file=out/'xilinx_dsp48e1.sv';model_file.write_text(model+'\n')
    source=ROOT/'rtl/npu/conv/vector_scalar_multiplier.sv'
    old=read_rtl_source('b8b34d5:rtl/npu/conv/vector_scalar_multiplier.sv', cwd=ROOT, text=True)
    reference=out/'reference.sv'
    reference.write_text(old.replace('module vector_scalar_multiplier (','module vector_scalar_multiplier_reference ('))
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    common=ROOT/'rtl/common/parallel_prefix_add.sv'
    common_hash=hashlib.sha256(common.read_bytes()).hexdigest()
    summary={'source_sha256':source_hash,'reference_rev':'b8b34d5',
        'parallel_prefix_add_sha256':common_hash,
        'reference_sha256':hashlib.sha256(old.encode()).hexdigest(),
        'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
        'latency_edges':2,'initiation_interval':1,'formal':[]}
    for use_dsp in (0,1):
        if use_dsp and 'p_cascade_mode' in source.read_text():
            spec=importlib.util.spec_from_file_location('four_dsp',ROOT/'test/requant_four_dsp/run_formal.py')
            proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
            result=proof.run_formal(source,out/'four_dsp')
            summary['formal'].append({'p_use_dsp':1,'passed':result['passed'],'stages':result})
            continue
        commands=[]
        for label,top,path in (('reference','vector_scalar_multiplier_reference',reference),
                               ('candidate','vector_scalar_multiplier',source)):
            commands += ['read_verilog -formal -sv -D VERIFIC -D XILINX_FPGA '+
                ' '.join(shlex.quote(str(p)) for p in
                         (path,model_file,ROOT/'rtl/common/parallel_prefix_add.sv'))]
            if label=='candidate':commands += [f'chparam -set p_use_dsp {use_dsp} {top}']
            commands += ['prep -top '+top+' -flatten','wreduce','opt -full']
            if label == 'candidate' and 'module registered_multiplier_s32' in source.read_text():
                commands += ['cd '+top]
                for name in ('low_product', 'low_high_product', 'high_low_product', 'high_product', 'diagonal'):
                    prefix = 'g_generic.' if 'p_cascade_mode' in source.read_text() else ''
                    commands += [f'rename u_multiplier.{prefix}{name} {name}']
                commands += ['cd ..']
            commands += ['rename -top '+label,'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate','equiv_make reference candidate equivalent',
            'hierarchy -top equivalent','equiv_simple -seq 2','equiv_induct -seq 2','equiv_status -assert']
        script=out/f'formal_dsp{use_dsp}.ys';script.write_text('\n'.join(commands)+'\n')
        log_path=out/f'formal_dsp{use_dsp}.log'
        with log_path.open('w') as stream:
            result=subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT)
        log=log_path.read_text();proved=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log)
        record={'p_use_dsp':use_dsp,'passed':result.returncode==0 and 'Equivalence successfully proven' in log,
            'equivalent_bits':int(proved[1]) if proved else None}
        summary['formal'].append(record);print(json.dumps(record),flush=True)
        if not record['passed']:raise RuntimeError(log[-10000:])
    if args.simulate:
        cmd=[args.verilator,'--binary','--timing','--assert','-Wno-fatal','--top-module','tb_vector_scalar',
            '-j','2','--Mdir',str(out/'obj'),str(source),str(reference),str(model_file),
            str(ROOT/'rtl/common/parallel_prefix_add.sv'),str(HERE/'tb_vector_scalar.sv')]
        with (out/'compile.log').open('w') as stream:subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([str(out/'obj/Vtb_vector_scalar')],capture_output=True,text=True,check=True)
        (out/'simulation.log').write_text(result.stdout+result.stderr)
        line=next(line for line in result.stdout.splitlines() if line.startswith('VECTOR_SCALAR_PASS'))
        summary['simulation']={key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}
        print(line,flush=True)
    if args.synthesis:
        cases={label:{'top':top,'options':[],'sources':[str(path)],
               'configuration':'Signed INT32 multiplication, two register edges, one input per cycle'}
               for label,top,path in (('scalar_reference','vector_scalar_multiplier_reference',reference),
                                      ('scalar_dsp','vector_scalar_multiplier',source))}
        config=out/'cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
        command=[sys.executable,str(args.synth_script.resolve()),'--source-root',str(ROOT),
            '--case-config',str(config),'--cases',*cases,'--out',str(out/'synthesis')]
        if args.lock_file:command+=['--lock-file',str(args.lock_file.resolve())]
        subprocess.run(command,check=True)
    summary['passed']=(hashlib.sha256(source.read_bytes()).hexdigest()==source_hash and
                       hashlib.sha256(common.read_bytes()).hexdigest()==common_hash)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not summary['passed']:raise RuntimeError('Scalar RTL changed during verification')


if __name__=='__main__':main()
