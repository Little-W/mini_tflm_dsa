#!/usr/bin/env python3
"""从实际量化源提取两个加法阶段，证明连接、符号扩展和配置暂停完全相同。"""
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

ROOT=Path(__file__).resolve().parents[2]
PORTS='''(
    input logic clk,init_cfg,s16_mode,round_increment_s9,
    input logic signed [47:0] product_high_s1,product_low_s1,
    input logic signed [33:0] quotient_s9,
    input logic signed [31:0] dst_offset_r,
    output logic signed [47:0] product_high_s2,
    output logic signed [35:0] rounded_s10
);\n'''
ROUNDING_PORTS='''(
    input logic clk,init_cfg,s16_mode,round_increment_s9,
    input logic signed [33:0] quotient_s9,
    input logic signed [31:0] dst_offset_r,
    output logic signed [35:0] rounded_s10
);\n'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-rev',default='1c081bc')
    parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)));return
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'rtl/npu/writeback/vec_requant.sv').read_text()
    old=read_rtl_source(args.reference_rev+':rtl/npu/writeback/vec_requant.sv', cwd=ROOT, text=True)
    reference_full=old.split('module vec_requant_full #(',1)[1].split('\nendmodule',1)[0]
    includes_product='    logic product_sum_i_en;' in source
    registers=('product_high_s2','rounded_s10') if includes_product else ('rounded_s10',)
    ports=PORTS if includes_product else ROUNDING_PORTS
    updates=[re.search(r'\b'+name+r'\s*<=.*?;',reference_full,re.S).group(0) for name in registers]
    reference=out/'reference.sv'
    reference.write_text('module sum_integration_reference '+ports+'always_ff @(posedge clk) begin\nif(!init_cfg) begin\n'+
                         '\n'.join(updates)+'\nend\nend\nendmodule\n')
    offset=re.search(r'  logic signed \[35:0\] rounding_offset;\s*assign rounding_offset\s*=.*?;',source,re.S).group(0)
    if includes_product:
        first=source.index('    logic product_sum_i_en;')
        last=source.index('    );',source.index('requant_registered_sum #(.p_width(36))',first))+len('    );')
        connections=source[first:last]
    else:
        declarations=re.findall(r'^    logic[^;]*\brounding_sum_\w+[^;]*;',source,re.M)
        assignments=re.findall(r'^    assign (?:rounding_sum_\w+|rounded_s10)\s*=.*?;',source,re.M|re.S)
        instance=re.search(r'    requant_registered_sum #\(\.p_width\(36\)\) u_rounding_sum \(.*?    \);',source,re.S)[0]
        connections='\n'.join(declarations+assignments+[instance])
    helper=re.search(r'^module requant_registered_sum\b.*?^endmodule',source,re.M|re.S).group(0)
    candidate=out/'candidate.sv'
    candidate.write_text('module sum_integration_candidate '+ports+offset+'\n'+connections+'\nendmodule\n'+helper+'\n')
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S).group(0)
    model=re.sub(r'\bspecify\b.*?\bendspecify\b','',model,flags=re.S)
    model_path=out/'dsp48e1.sv';model_path.write_text(model+'\n')
    commands=[]
    for label,path in [('reference',reference),('candidate',candidate)]:
        commands+=['read_verilog -formal -sv -D VERIFIC -D XILINX_FPGA '+str(path)+' '+str(model_path),
                   'prep -top sum_integration_'+label+' -flatten','wreduce','opt -full',
                   'rename -top '+label,'design -stash '+label]
    commands+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
               'equiv_make reference candidate equivalent','hierarchy -top equivalent',
               'equiv_simple -seq 2','equiv_induct -seq 2','equiv_status -assert']
    script=out/'integration.ys';script.write_text('\n'.join(commands)+'\n')
    with (out/'integration.log').open('w') as stream:
        result=subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT)
    log=(out/'integration.log').read_text()
    passed=result.returncode==0 and 'Equivalence successfully proven' in log
    bits=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',log)
    summary={'passed':passed,'reference_rev':args.reference_rev,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
             'registers':list(registers),
             'reference_source_sha256':hashlib.sha256(old.encode()).hexdigest(),
             'equivalent_bits':int(bits[1]) if bits else None,'clock_enable':'arbitrary init_cfg values and stalls',
             'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if not passed:raise RuntimeError(log[-8000:])


if __name__=='__main__':main()
