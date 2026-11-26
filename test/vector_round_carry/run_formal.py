#!/usr/bin/env python3
"""比较有符号舍入的分段递增与完整六十四位递增。"""
import argparse
import hashlib
import json
import runpy
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT=Path(__file__).resolve().parents[2]
SOURCE='rtl/npu/conv/vector_round_shift.sv'
DEPENDENCIES = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='1c081bc')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=read_rtl_source(args.reference_ref+':'+SOURCE, cwd=ROOT, text=True)
    reference=out/'reference.sv';reference.write_text(original)
    current=ROOT/SOURCE
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    primitive=re.search(r'^module LUT6\b.*?^endmodule',library.read_text(),re.M|re.S).group()
    model=out/'lut6_model.sv'
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b','',primitive,flags=re.S)+'\n')
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,)}
    summary={'passed':False,'reference_ref':args.reference_ref,'source_sha256':hashes,
             'inputs_constrained':False,
             'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
             'original_reference_sha256':hashlib.sha256(original.encode()).hexdigest(),'runs':[]}
    for middle in (0,1):
        folder=out/f'middle{middle}';folder.mkdir(exist_ok=True)
        options=f'-GREGISTER_MIDDLE={middle}'
        commands=[]
        for name,source in (('reference',reference),('current',current)):
            source_arguments = shlex.join(map(str, DEPENDENCIES([source, model], ROOT)))
            commands.extend([f'read_slang --top vector_round_shift {options} {source_arguments}',
                             'prep -top vector_round_shift -flatten','memory_map','async2sync','opt_clean',
                             f'rename vector_round_shift {name}',f'design -stash {name}'])
        commands.extend(['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                         'equiv_make reference current equivalent','hierarchy -top equivalent','equiv_simple -seq 1',
                         'opt_clean','equiv_induct -seq 2','equiv_status -assert'])
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                  stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
        text=log.read_text();match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',text)
        report={'REGISTER_MIDDLE':middle,
                'passed':result.returncode==0 and 'Equivalence successfully proven' in text,
                'equivalent_bits':int(match[1]) if match else None,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        summary['runs'].append(report);print(json.dumps(report),flush=True)
        if not report['passed']:raise RuntimeError(text[-9000:])
    if hashes!={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (current,)}:
        raise RuntimeError('Source changed during verification')
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
