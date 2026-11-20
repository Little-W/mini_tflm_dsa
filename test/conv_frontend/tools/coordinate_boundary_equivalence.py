#!/usr/bin/env python3
"""证明前端坐标末列与 padding 判断在全部输入编码下保持一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
OUTPUTS = ('row_wrap', 'tap_wrap', 'next_row_ix', 'next_row_iy',
           'next_tap_ix', 'next_tap_iy', 'next_row_padding', 'next_tap_padding',
           'incoming_padding', 'incoming_tap_wrap')


def coordinate_module(source, name):
    equations=[]
    for signal in OUTPUTS:
        assignment=re.search(r'\b'+signal+r'\s*=\s*([^;]+);',source)
        if assignment is None and signal == 'incoming_tap_wrap':
            assignment = re.search(r"if \((kx0\+1==32'\(c\.kernel_w\))\) begin", source)
        if assignment is None:
            raise ValueError(f'coordinate expression missing: {signal}')
        equations.append('assign '+signal+' = '+assignment.group(1).replace('c.','cfg_')+';')
    saved=re.search(r'last_kernel_col_q\s*<=\s*([^;]*cfg\.kernel_w[^;]*);',source)
    capture=saved.group(1).replace('cfg.kernel_w','cfg_kernel_w') if saved else "cfg_kernel_w - 16'd1"
    output_saved=re.search(r'last_output_col_q\s*<=\s*([^;]*cfg\.output_w[^;]*);',source)
    output_capture=output_saved.group(1).replace('cfg.output_w','cfg_output_w')
    width_valid=re.search(r'kernel_width_valid_q\s*<=\s*([^;]*cfg\.kernel_w[^;]*);',source)
    width_capture=width_valid.group(1).replace('cfg.kernel_w','cfg_kernel_w') if width_valid else "cfg_kernel_w != 16'd0"
    return f'''module {name} (
  input logic [15:0] ox_q, kx_q, kx0_q, cfg_output_w, cfg_kernel_w, cfg_input_w, cfg_input_h,
  input logic [15:0] cfg_stride_w, cfg_stride_h, cfg_dilation_w, cfg_dilation_h,
  input logic signed [34:0] row_base_ix, row_base_iy, ix, iy, incoming_ix, incoming_iy,
  input logic signed [32:0] row_wrap_dx, tap_wrap_dx,
  output logic row_wrap, tap_wrap, next_row_padding, next_tap_padding,
  output logic incoming_padding, incoming_tap_wrap,
  output logic signed [34:0] next_row_ix, next_row_iy, next_tap_ix, next_tap_iy
);
localparam int COORD_W=35;
logic [31:0] ox, kx, kx0;
logic [15:0] last_kernel_col_q, last_output_col_q;
logic kernel_width_valid_q;
assign ox = {{16'd0,ox_q}};
assign kx = {{16'd0,kx_q}};
assign kx0 = {{16'd0,kx0_q}};
assign last_kernel_col_q = {capture};
assign kernel_width_valid_q = {width_capture};
assign last_output_col_q = {output_capture};
{chr(10).join(equations)}
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='b8b34d5')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    old=subprocess.check_output(['git','show',f'{args.reference_ref}:{SOURCE}'],cwd=ROOT,text=True)
    current=(ROOT/SOURCE).read_text()
    (out/'reference_frontend.sv').write_text(old)
    (out/'current_frontend.sv').write_text(current)
    old_module=coordinate_module(old,'coordinate_reference')
    current_module=coordinate_module(current,'coordinate_current')
    (out/'coordinate_reference.sv').write_text(old_module)
    (out/'coordinate_current.sv').write_text(current_module)
    miter=out/'coordinate_boundary_miter.sv'
    declarations=[];connections=[]
    for side in ['old','new']:
        declarations.append(f'logic {side}_row_wrap, {side}_tap_wrap, {side}_next_row_padding, {side}_next_tap_padding, {side}_incoming_padding, {side}_incoming_tap_wrap;')
        declarations.append(f'logic signed [34:0] {side}_next_row_ix, {side}_next_row_iy, {side}_next_tap_ix, {side}_next_tap_iy;')
        module='coordinate_reference' if side=='old' else 'coordinate_current'
        ports=', '.join(f'.{signal}({side}_{signal})' for signal in OUTPUTS)
        connections.append(f'{module} u_{side} ({ports}, .*);')
    lhs=','.join('old_'+signal for signal in OUTPUTS)
    rhs=','.join('new_'+signal for signal in OUTPUTS)
    miter.write_text(old_module+current_module+f'''
module coordinate_boundary_miter (
  input logic [15:0] ox_q, kx_q, kx0_q, cfg_output_w, cfg_kernel_w, cfg_input_w, cfg_input_h,
  input logic [15:0] cfg_stride_w, cfg_stride_h, cfg_dilation_w, cfg_dilation_h,
  input logic signed [34:0] row_base_ix, row_base_iy, ix, iy, incoming_ix, incoming_iy,
  input logic signed [32:0] row_wrap_dx, tap_wrap_dx,
  output logic equivalent
);
{chr(10).join(declarations)}
{chr(10).join(connections)}
assign equivalent = {{{lhs}}} == {{{rhs}}};
endmodule
''')
    script=out/'proof.ys'
    script.write_text('read_slang --top coordinate_boundary_miter '+shlex.quote(str(miter))+'\n'+
        'prep -top coordinate_boundary_miter -flatten\n'+
        'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    log=out/'proof.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       stdout=stream,stderr=subprocess.STDOUT,check=True)
    if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
        raise AssertionError('SAT success marker missing')
    result={'passed':True,'reference_ref':args.reference_ref,
            'source_sha256':hashlib.sha256(current.encode()).hexdigest(),
            'reference_sha256':hashlib.sha256(old.encode()).hexdigest(),
            'inputs_constrained':False,'scope':'all 16-bit geometry, 33-bit deltas and 35-bit coordinates',
            'outputs':list(OUTPUTS)}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('FRONTEND_COORDINATE_BOUNDARY_EQUIVALENCE_PASS',out/'summary.json')


if __name__=='__main__':main()
