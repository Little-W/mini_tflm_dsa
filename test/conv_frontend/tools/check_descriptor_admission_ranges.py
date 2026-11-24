#!/usr/bin/env python3
"""验证描述符行范围和归约范围的完整输入关系与四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
DESCRIPTOR = Path('rtl/npu/conv/conv_im2col_descriptor.sv')
CHECKS = 4096
WIDTHS = (1, 2, 4, 5, 8, 16, 31, 32)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def range_block(source):
    first = source.index('  // 描述符范围比较独立完成') if '  // 描述符范围比较独立完成' in source else \
        source.index('  // 描述符的四段范围比较并行进行')
    return source[first:source.index('  // 直连描述符在接收周期完成数据字匹配', first)]


def range_module(source, name, width):
    return f'''module {name}(
 input logic [31:0] i_tile_p0,i_position_count,i_tile_q0,i_reduction_len,
 input logic [{width-1}:0] i_tile_rows,
 input logic [{max(1,32-min(width,31))-1}:0] i_position_high_minus_one_q,
 output logic [1:0] result);
 localparam int p_rw={width},p_row_low_w=p_rw<32?p_rw:31,p_row_high_w=32-p_row_low_w;
 logic [3:0] tile_q_byte_before,tile_q_byte_equal;
 logic o_tile_rows_in_range,o_tile_q_before_end;
{range_block(source)}
 assign result={{o_tile_rows_in_range,o_tile_q_before_end}};
endmodule
'''


def bench(inputs):
    bits=sum(inputs.values()); padded=(bits+31)//32*32
    declarations='\n'.join('logic '+(f'[{w-1}:0] ' if w>1 else '')+name+';' for name,w in inputs.items())
    names=','.join(inputs)
    low_width=min(inputs['i_tile_rows'],31)
    return f'''module tb;
{declarations}
logic equivalent,boundary_equivalent;
logic [1:0] actual_value,expected_value;
logic [{padded-1}:0] pattern;
logic [{bits-1}:0] applied,seen_x='0,seen_z='0;
integer positive=0,negative=0;
proof dut(.*);
initial begin
 for(integer sample=0;sample<{CHECKS};sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
  {{{names}}}=pattern;
  if(sample%4==0)begin
   i_position_count=i_tile_p0+32'(i_tile_rows);
   i_reduction_len=i_tile_q0+32'd1;
  end
  if(sample%4==1)i_position_count=i_tile_p0;
  if(sample%4==2)i_reduction_len=i_tile_q0;
  if(sample%2==0)i_position_high_minus_one_q=i_position_count[31:{low_width}]-1;
  applied={{{names}}};
  if(sample%3==0)applied[(sample/3)%{bits}]=1'bx;
  if(sample%5==0)applied[(sample/5)%{bits}]=1'bz;
  {{{names}}}=applied;
  for(integer b=0;b<{bits};b++)begin
   if(applied[b]===1'bx)seen_x[b]=1'b1;
   if(applied[b]===1'bz)seen_z[b]=1'b1;
  end
  #1;
  if(equivalent!==1'b1)$fatal(1,"Range mismatch sample=%0d actual=%b expected=%b inputs=%h",sample,actual_value,expected_value,applied);
  if(actual_value===2'b11)positive++;
  if(actual_value===2'b00)negative++;
 end
 if(seen_x!=='1||seen_z!=='1)$fatal(1,"Incomplete X/Z coverage");
 if(positive<10||negative<10)$fatal(1,"Incomplete range outcomes");
 $display("DESCRIPTOR_RANGES_FOUR_STATE_PASS checks={CHECKS} positive=%0d negative=%0d",positive,negative);
 $finish;
end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-ref',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iverilog',default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp',default=shutil.which('vvp') or 'vvp')
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    utilities_path=Path(__file__).with_name('check_frontend_range_comparisons.py')
    utilities=runpy.run_path(str(utilities_path))
    current=(root/DESCRIPTOR).read_text()
    reference=read_reference_file(root, args.reference_ref, str(DESCRIPTOR), text=True)
    inputs_files=[root/DESCRIPTOR,root/'rtl/common/parallel_unsigned_compare.sv',Path(__file__).resolve(),utilities_path]
    hashes={str(p):digest(p) for p in inputs_files}
    helper=out/'descriptor_range_helpers.sv'
    helper.write_text(utilities['module'](current,'conv_descriptor_match')+'\n'+
                      utilities['module'](current,'conv_descriptor_row_range_result'))
    support=[root/'rtl/common/parallel_unsigned_compare.sv',helper]
    results=[];mapping={}
    for width in WIDTHS:
        inputs={'i_tile_p0':32,'i_position_count':32,'i_tile_q0':32,'i_reduction_len':32,
                'i_tile_rows':width,'i_position_high_minus_one_q':32-min(width,31)}
        porttext=',\n'.join('input logic '+(f'[{w-1}:0] ' if w>1 else '')+name for name,w in inputs.items())
        connections=','.join('.'+name+'('+name+')' for name in inputs)
        proof=f'''module proof({porttext},
 output logic equivalent,boundary_equivalent,
 output logic [1:0] actual_value,expected_value);
 range_current actual({connections},.result(actual_value));
 range_reference expected({connections},.result(expected_value));
 wire prepared_high=i_position_high_minus_one_q==i_position_count[31:{min(width,31)}]-{32-min(width,31)}'(1);
 wire [32:0] row_end={{1'b0,i_tile_p0}}+33'(i_tile_rows);
 assign equivalent=actual_value===expected_value;
 assign boundary_equivalent=(!prepared_high)||
     (actual_value=={{row_end<={{1'b0,i_position_count}},i_tile_q0<i_reduction_len}});
endmodule
'''
        model=out/f'width{width}_model.sv'
        model.write_text((range_module(current,'range_current',width)+
                          range_module(reference,'range_reference',width)+proof).replace('always_comb','always @*'))
        ys,log,tb,binary,build,simulation=[out/f'width{width}{suffix}' for suffix in
            ('.ys','.formal.log','.tb.sv','.vvp','.build.log','.four_state.log')]
        ys.write_text('read_slang -DSYNTHESIS --top proof '+shlex.join(map(str,support+[model]))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n'
            'sat -verify -prove boundary_equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as f:
            subprocess.run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                           stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        if log.read_text().count('SAT proof finished - no model found: SUCCESS!')!=2:
            raise RuntimeError(str(log))
        tb.write_text(bench(inputs))
        with build.open('w') as f:
            subprocess.run([args.iverilog,'-g2012','-s','tb','-o',str(binary),*map(str,support+[model,tb])],
                           stdout=f,stderr=subprocess.STDOUT,check=True)
        with simulation.open('w') as f:
            subprocess.run([args.vvp,str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
        if 'DESCRIPTOR_RANGES_FOUR_STATE_PASS' not in simulation.read_text():raise RuntimeError(str(simulation))
        binary.unlink()
        results.append(dict(width=width,formal_properties=2,formal_passed=True,four_state_checks=CHECKS,
            all_input_bits_x_z=True,input_bits=sum(inputs.values()),model_sha256=digest(model),
            formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)))
        if width==5:
            for kind in ('actual','expected'):
                wrapper=out/f'row_range_{kind}_mapping.sv'
                wrapper.write_text(utilities['mapping_wrapper'](inputs,2,kind).replace(
                    'logic unused_equivalent;','logic unused_equivalent,unused_boundary;').replace(
                    '.equivalent(unused_equivalent)', '.equivalent(unused_equivalent),.boundary_equivalent(unused_boundary)'))
                mapping['row_range_'+kind]=dict(top='comparison_mapping',options=['-D','SYNTHESIS=1'],
                    sources=list(map(str,support+[model,wrapper])),configuration='Registered descriptor range checks')
        print('DESCRIPTOR_RANGES_PASS',f'width={width}',flush=True)
    assert hashes=={path:digest(path) for path in hashes}
    (out/'mapping_cases.json').write_text(json.dumps(mapping,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,sources_unchanged=True,
        reference_ref=args.reference_ref,reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        inputs_constrained=False,formal_properties=2*len(results),four_state_checks=CHECKS*len(results),
        cases=results),indent=2)+'\n')


if __name__=='__main__':
    main()
