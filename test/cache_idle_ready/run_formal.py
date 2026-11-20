#!/usr/bin/env python3
"""证明缓存配置空闲判断在通用及官方LUT模型下完全等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('rtl/npu/dma/cache/conv_read_cache.sv')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',default='9f750ed5')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=subprocess.check_output(['git','show',args.reference+':'+str(SOURCE)],cwd=ROOT,text=True)
    original=re.search(r'  assign cfg_ready=fill_state==F_IDLE.*?;',reference,re.S).group(0)
    start=current.index('  localparam int p_cfg_idle_width =')
    end=current.index('`endif',start)+len('`endif')
    changed=current[start:end]
    assert current[:start]+original+current[end:]==reference
    assert 'typedef enum logic [1:0] {FG_IDLE, FG_MISS, FG_RESP}' in current
    assert 'typedef enum logic [1:0] {F_IDLE, F_REQ, F_DATA}' in current
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=out/'lut6_2.sv';model.write_text(re.search(r'^module LUT6_2\b.*?^endmodule',library.read_text(),re.M|re.S).group(0)+'\n')
    proof=out/'proof.sv'
    proof.write_text('''module idle_proof #(parameter int DQ_CW=3, PF_CW=4) (
  input logic [1:0] fill_state,fg_state,
  input logic clearing,pf_active_valid,offer_valid,select_stage_valid,
  input logic [PF_CW-1:0] pf_count,
  input logic [DQ_CW-1:0] outstanding_count,request_count,response_count,
  output logic equivalent
);
  localparam logic [1:0] F_IDLE=2'd0,FG_IDLE=2'd0;
  logic reference_ready,current_ready;
'''+original.replace('cfg_ready','reference_ready')+'\n'+re.sub(r'\bcfg_ready\b','current_ready',changed)+'''
  assign equivalent=reference_ready==current_ready;
endmodule
''')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();cases=[]
    for fpga in (False,True):
        for width in (1,3,4,5,7):
            name=f'dq{width}_fpga{int(fpga)}';script=out/(name+'.ys');log=out/(name+'.log')
            script.write_text(f'read_slang --top idle_proof -GDQ_CW={width} '+
                ('-D XILINX_FPGA=1 ' if fpga else '')+shlex.quote(str(proof))+' '+shlex.quote(str(model))+
                '\nprep -top idle_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            cases.append(dict(fpga=fpga,demand_count_width=width,passed=True,script_sha256=digest(script),log_sha256=digest(log)))
    result=dict(passed=True,reference=args.reference,source_sha256=digest(ROOT/SOURCE),reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        unchanged_outside_cfg_ready=True,actual_source_expressions=True,inputs_constrained=False,
        official_primitive_library_sha256=digest(library),proof_sha256=digest(proof),cases=cases)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
