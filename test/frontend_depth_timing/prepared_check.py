#!/usr/bin/env python3
"""证明描述符准备寄存器两侧的完整坐标及候选选择保持等价。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
FRONTEND='rtl/npu/conv/conv_im2col_frontend.sv'


def coordinate_unit(source):
    spec=importlib.util.spec_from_file_location('window_proof',ROOT/'test/frontend_window_timing/check.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    inputs=dict(module.INPUTS)
    names=('next_row_ix','next_row_iy','incoming_step_ix','incoming_wrap_ix','incoming_wrap_iy')
    for name in names: del inputs[name]
    inputs.update(row_wrap='logic',row_wrap_dx='logic signed [32:0]')
    ports=',\n'.join('input '+typ+' '+name for name,typ in inputs.items())
    declarations='\n'.join('logic '+('signed ' if key in ('incoming_ix','incoming_iy') else '')+
        ('['+str(bits-1)+':0] ' if bits>1 else '')+key+';' for key,bits in module.OUTPUTS.items())
    derived='''
logic signed[34:0] next_row_ix,next_row_iy,incoming_step_ix,incoming_wrap_ix,incoming_wrap_iy;
assign next_row_ix=row_base_ix+(row_wrap ? 35'(row_wrap_dx) : 35'(c.stride_w));
assign next_row_iy=row_base_iy+(row_wrap ? 35'(c.stride_h) : 35'd0);
assign incoming_step_ix=row_base_ix+35'(c.dilation_w);
assign incoming_wrap_ix=row_base_ix+35'(tap_wrap_dx);
assign incoming_wrap_iy=row_base_iy+35'(c.dilation_h);
logic signed[34:0] prepared_coordinate_x,prepared_coordinate_y,prepared_coordinate_dx,prepared_coordinate_dy;
logic[1:0] prepared_coordinate_carry;
logic[34:0] prepared_sum_x,prepared_sum_y;
'''
    start=source.index('  // 坐标基址与步长在准备阶段保存')
    end=source.index('  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_coordinate',start)
    return 'module prepared_coordinate_comparison #('+module.PARAMETERS+')(\n'+ports+',output logic equivalent);\n'+\
        module.HELPERS+declarations+derived+module.extract(source)+source[start:end]+'''
assign prepared_sum_x=prepared_coordinate_x+prepared_coordinate_dx+35'(prepared_coordinate_carry[0]);
assign prepared_sum_y=prepared_coordinate_y+prepared_coordinate_dy+35'(prepared_coordinate_carry[1]);
assign equivalent=prepared_sum_x==incoming_ix && prepared_sum_y==incoming_iy;
endmodule
'''


def selection_unit(source):
    start=source.index('  // 填充和字命中的候选值、选择条件分别保存')
    end=source.index('  always_comb begin\n    preparing_tile =',start)
    old_start=source.index('    assign incoming_window_word_match[target]')
    old_end=source.index('\n  end',old_start)
    flags=('incoming_next_position_fast','incoming_next_tile_fast','incoming_skip_tap','incoming_q_equal',
           'incoming_tap_wrap','incoming_position_same_tap','incoming_position_previous_row',
           'incoming_position_forward_tap','incoming_position_backward_tap','finishing_tile','waiting','word_valid')
    pads=('window_previous_padding','window_backward_padding','window_forward_padding','window_next_padding',
          'next_row_padding','incoming_skip_padding','incoming_wrap_padding','incoming_step_padding','incoming_base_padding')
    ports=',\n'.join('input logic '+name for name in flags+pads)
    return '''module prepared_selection_comparison #(parameter int p_word_shift=2)(
''' + ports + ''',input logic[15:0] kx0_q,
input logic[31:0] row_base_addr,window_next_addr,addr,word_addr,
input logic[6:0][1:0] incoming_candidate_word_match,input logic[1:0] next_row_word_match,
output logic equivalent);
logic[8:0] prepared_padding_select,prepared_padding_value;
logic[9:0] prepared_word_select,prepared_word_value;
logic[9:0][1:0] prepared_word_match;
logic[1:0] incoming_window_word_match,incoming_skip_word_match,incoming_advanced_word_match,base_word_match;
logic expected_padding,expected_word_hit;
localparam logic[21:0] WAIT_WORD=22'h080000;
logic[21:0] state;
assign state=waiting ? WAIT_WORD : 22'h000001;
''' + source[start:end] + '''
for(genvar target=0;target<2;target++) begin : g_reference
 logic[31-p_word_shift:0] high_i_target;
 assign high_i_target=target==0 ? word_addr[31:p_word_shift] : addr[31:p_word_shift];
''' + source[old_start:old_end] + '''
 assign base_word_match[target]=incoming_q_equal ? row_base_addr[31:p_word_shift]==high_i_target :
  incoming_tap_wrap ? incoming_candidate_word_match[1][target] : incoming_candidate_word_match[0][target];
end
assign expected_word_hit=(incoming_next_position_fast || incoming_next_tile_fast || incoming_skip_tap) ?
 (finishing_tile && waiting ? incoming_advanced_word_match[1] :
  word_valid && word_addr[p_word_shift-1:0]=='0 && incoming_advanced_word_match[0]) :
 (finishing_tile && waiting ? base_word_match[1] :
  word_valid && word_addr[p_word_shift-1:0]=='0 && base_word_match[0]);
assign expected_padding=incoming_next_position_fast ?
 (incoming_position_same_tap ? window_next_padding : incoming_position_previous_row ? window_previous_padding :
  incoming_position_forward_tap ? window_forward_padding : window_backward_padding) :
 incoming_next_tile_fast ? next_row_padding : incoming_skip_tap ? incoming_skip_padding :
 !incoming_q_equal ? (incoming_tap_wrap ? incoming_wrap_padding : incoming_step_padding) : incoming_base_padding;
assign equivalent=(|(prepared_padding_select & prepared_padding_value))==expected_padding &&
 (|(prepared_word_select & prepared_word_value))==expected_word_hit;
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();source_root=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    frontend=source_root/FRONTEND;source=frontend.read_text()
    cases=[(f'coordinate_s{size}_p{policy}','prepared_coordinate_comparison',coordinate_unit(source),
            [f'-GSIZE={size}',f'-GCACHE_POLICY={policy}']) for size in (4,16,64) for policy in (0,3)]
    cases.extend((f'selection_b{bits}','prepared_selection_comparison',selection_unit(source),
                 [f'-Gp_word_shift={bits}']) for bits in (2,3,4))
    results=[]
    for name,top,body,options in cases:
        target=out/(name+'.sv');target.write_text(body)
        paths=[source_root/'rtl/npu/conv/conv_im2col_pkg.sv',source_root/'rtl/common/add_equal.sv',
               source_root/'rtl/common/parallel_prefix_add.sv',target]
        script=out/(name+'.ys');log=out/(name+'.log')
        script.write_text('read_slang --top '+top+' '+' '.join(options)+' '+
            ' '.join(shlex.quote(str(p)) for p in paths)+'\nprep -top '+top+
            ' -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        results.append({'case':name,'passed':True,'log':str(log)})
        print('PREPARED_DESCRIPTOR_EQUIVALENCE_PASS',name,flush=True)
    (out/'summary.json').write_text(json.dumps({'passed':True,'cases':results,
        'source_sha256':hashlib.sha256(frontend.read_bytes()).hexdigest()},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
