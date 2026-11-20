#!/usr/bin/env python3
"""检查向量偏移和归约加法的完整数值与位宽行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def fragments(source):
    declarations=re.search(r'  logic \[32:0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;',source,re.S)[0]
    offset=re.search(r'  assign q_offset_low\s*=.*?(?=  assign ready)',source,re.S)[0]
    offset+=re.search(r'  assign q_clamped_data\s*=.*?;',source,re.S)[0]
    first=source.index('  logic [31:0] reduce_sum;') if '  logic [31:0] reduce_sum;' in source else source.index('  always_comb begin\n    reduce_next=')
    last=source.index('  localparam int POOL_SUM_WIDTH',first)
    reduction=source[first:last]
    return declarations,offset,reduction


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='2f06471c')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    ref=read_rtl_source(args.reference_rev+':'+SOURCE, cwd=ROOT, text=True)
    cand=(ROOT/SOURCE).read_text()
    a,b=fragments(ref),fragments(cand)
    packages=[ROOT/'rtl/npu/conv/conv_im2col_pkg.sv',ROOT/'rtl/npu/conv/vector_engine_pkg.sv']
    report={'reference_rev':args.reference_rev,'source_sha256':hashlib.sha256(cand.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(ref.encode()).hexdigest(),'inputs_constrained':False,
            'proof_scope':'Complete quantized offset/clamp and reduction outputs extracted from vector_engine RTL','runs':[]}
    for part in ['offset','reduction']:
        folder=out/part;folder.mkdir(exist_ok=True);commands=[]
        for label,parts in [('reference',a),('candidate',b)]:
            if part=='offset':
                body=parts[0]+parts[1]
                header='''module arithmetic (
                  input logic signed [63:0] q_rounded,
                  input vector_engine_pkg::vector_engine_cfg_t c,
                  output logic signed [31:0] o_result
                );
                '''
                tail='assign o_result=q_clamped_data;'
            else:
                body=parts[2]
                header='''module arithmetic (
                  input logic signed [31:0] reduce_acc,serial_acc_read_data,
                  input vector_engine_pkg::vector_engine_cfg_t c,
                  output logic signed [31:0] reduce_next
                );
                import vector_engine_pkg::*;
                '''
                tail=''
            path=folder/(label+'.sv');path.write_text(header+body+tail+'\nendmodule\n')
            commands+=['read_slang --top arithmetic '+' '.join(shlex.quote(str(p)) for p in packages+[path]),
                       'prep -top arithmetic -flatten','opt -full','rename arithmetic '+label,'design -stash '+label]
        commands+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
                   'equiv_make reference candidate comparison','hierarchy -top comparison','equiv_simple','equiv_status -assert']
        script=folder/'run.ys';script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            r=subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        text=log.read_text();row={'part':part,'passed':r.returncode==0 and 'Equivalence successfully proven' in text,
                                'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        report['runs'].append(row);print(json.dumps(row),flush=True)
        if not row['passed']:raise RuntimeError(text[-8000:])
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
