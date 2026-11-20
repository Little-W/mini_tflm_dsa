#!/usr/bin/env python3
"""Prove the actual tensor extent stages at every configuration consumption phase."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'test'))
from rtl_reference import read_rtl_source

FIELDS = {
    'rhs_product_diagonal':64, 'rhs_product_cross':33,
    'conv_input_low':32, 'conv_input_high':32, 'conv_kernel_low':32,
    'conv_kernel_high':32, 'conv_output_area':32,
    'rhs_base':32, 'bias_base':32, 'm':32, 'n':32, 'k':32,
    'q_mult_pt':32, 'q_shift_pt':32, 'run_rhs_tile_packed':1,
    'use_per_channel':1, 'conv_syntax_invalid':1, 'input_base':32,
}
EXTRA = ('rhs_base','bias_base','m','n','k','q_mult_pt','q_shift_pt',
         'run_rhs_tile_packed','use_per_channel','conv_syntax_invalid')
RESULT = ('rhs_allocation_bytes,conv_input_bytes,conv_kernel_elements,'
          'conv_range_end[0],conv_range_end[1],conv_range_end[2],conv_range_end[3],'
          'conv_input_range_invalid,conv_rhs_range_invalid,conv_parameter_range_invalid,'
          'conv_dimension_invalid,conv_validation_invalid')


def build(text, name):
    start = text.index('    logic [63:0] rhs_allocation_bytes;')
    end = text.index('    wire abort_pending =', start)
    declarations = text[start:end]
    start = text.index('        assign cfg_stage2_fire =')
    end = text.index('        always_ff @(posedge clk) begin\n            if (cfg_start_event)', start)
    control = text[start:end]
    start = text.index('                case (cfg_capacity_phase)', end)
    end = text.index('                endcase', start) + len('                endcase')
    phases = text[start:end]
    ports=',\n'.join(f'    input logic [{width-1}:0] i_{field}' for field,width in FIELDS.items())
    extra='\n'.join(f'    logic [{FIELDS[field]-1}:0] {field};' for field in EXTRA)
    capture='\n'.join(f'                {"conv_cfg_q.input_base" if field=="input_base" else field} <= i_{field};'
                      for field in FIELDS)
    return f'''module {name} #(parameter int SIZE=16, REG_WIDTH=32) (
    input logic clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
{ports},
    output logic [296:0] result,
    output logic cfg_stage2_valid,cfg_stage2_fire,
    output logic [2:0] cfg_capacity_phase
);
    localparam int SIZE_SHIFT=$clog2(SIZE);
    struct packed {{logic [31:0] input_base;}} conv_cfg_q;
    logic [32:0] conv_range_end[4];
{extra}
{declarations}
{control}
    always_ff @(posedge clk or negedge core_rst_n) begin
        if (!core_rst_n) cfg_stage2_valid<=0;
        else begin
            if (cfg_stage2_fire) cfg_stage2_valid<=0;
            if (!cfg_stage2_valid && i_load) cfg_stage2_valid<=1;
        end
    end
    always_ff @(posedge clk) begin
        if (!cfg_stage2_valid && i_load) begin
{capture}
        end
        if (cfg_stage2_valid) begin
{phases}
        end
    end
    assign result={{{RESULT}}};
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='2297cb12')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'rtl/npu/top/npu_top.sv'
    texts={'reference':read_rtl_source(args.reference+':rtl/npu/top/npu_top.sv',cwd=ROOT,text=True),
           'candidate':source.read_text()}
    files=[]
    for label,text in texts.items():
        path=out/(label+'.sv');path.write_text(build(text,label));files.append(path)
    inputs=',\n'.join(f'    input logic [{width-1}:0] i_{field}' for field,width in FIELDS.items())
    harness=out/'formal.sv'
    harness.write_text(f'''module extent_formal #(parameter int SIZE=16)(
    input logic clk,core_rst_n,i_load,ctrl_sa_ready,frame_scheduler_ready,
{inputs},
    output logic bad
);
    logic [296:0] reference_result,candidate_result;
    logic reference_valid,reference_fire,candidate_valid,candidate_fire;
    logic [2:0] reference_phase,candidate_phase;
    reference #(.SIZE(SIZE)) r(.*,.result(reference_result),.cfg_stage2_valid(reference_valid),
        .cfg_stage2_fire(reference_fire),.cfg_capacity_phase(reference_phase));
    candidate #(.SIZE(SIZE)) c(.*,.result(candidate_result),.cfg_stage2_valid(candidate_valid),
        .cfg_stage2_fire(candidate_fire),.cfg_capacity_phase(candidate_phase));
    assign bad=core_rst_n && (
        ({{reference_valid,reference_fire,reference_phase}} != {{candidate_valid,candidate_fire,candidate_phase}}) ||
        (candidate_valid && candidate_phase>=3'd5 && reference_result!=candidate_result));
endmodule
''')
    files.append(harness)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    report=dict(passed=False,reference=args.reference,source_sha256=digest(source),
                extracted_sha256={p.name:digest(p) for p in files},
                proof_scope='Actual phase counter and extent assignments; unrestricted partial products and fields captured at stage-2 entry',
                reset='First sampled cycle resets control; later reset, ready, and load inputs arbitrary',runs=[])
    for size in (1,2,3,4,16,32):
        script=out/f'size{size}.ys';log=out/f'size{size}.log'
        script.write_text('read_slang --top extent_formal '+f'-GSIZE={size} '+shlex.join(map(str,files))+'\n'+
            'prep -top extent_formal -flatten\nmemory_map\nasync2sync\nopt -full\n'+
            'sat -seq 2 -tempinduct -maxsteps 12 -set-at 1 core_rst_n 0 -prove bad 0 -verify -timeout 180\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=220)
        if 'Induction step proven: SUCCESS!' not in log.read_text():raise RuntimeError('Extent proof incomplete')
        report['runs'].append(dict(size=size,passed=True,log_sha256=digest(log)))
        print(f'SIZE={size}: PASS',flush=True)
    if source.read_text()!=texts['candidate']:
        raise RuntimeError('Top source changed during verification')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    cases={label:dict(top=label,sources=[str(out/(label+'.sv'))],options=['-D','SYNTHESIS=1'],
                      configuration='Actual eight-phase extent preparation, all tensor products and ranges')
           for label in texts}
    (out/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')


if __name__=='__main__':main()
