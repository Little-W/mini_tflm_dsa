#!/usr/bin/env python3
"""验证卷积分组余量的完整范围关系和分段低位比较。"""
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

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
STREAM=Path('rtl/npu/conv/conv_im2col_stream.sv')
CONFIGURATIONS=((1,1),(2,2),(4,3),(8,4),(16,5),(17,5),(31,5),(32,6),(64,7),(32768,16),(8,5),(16,6))
CHECKS=2048


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def block(source):
    first=source.index('  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range')
    return source[first:source.index('  assign o_incoming_tap_wrap',first)]


def circuit(name,source,size,rw):
    return f'''module {name}(
 input logic [15:0] group_c,i_window_next_ch,i_ch0_q,
 input logic [16:0] i_window_group_remaining_q,
 input logic [{rw-1}:0] i_tile_cols,
 output logic [1:0] o_incoming_tile_group_fits);
 localparam int p_size={size},p_rw={rw},p_tile_count_w=$clog2(p_size+1);
 typedef struct packed{{logic [15:0]group_c;}} cfg_t;
 cfg_t i_c;
 wire [16:0] o_initial_group_remaining={{1'b0,group_c}}-{{1'b0,i_ch0_q}};
 assign i_c.group_c=group_c;
{block(source)}
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-ref',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iverilog',default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp',default=shutil.which('vvp') or 'vvp')
    args=parser.parse_args();root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    utility_path=Path(__file__).with_name('check_frontend_range_comparisons.py');utilities=runpy.run_path(str(utility_path))
    current=(root/STREAM).read_text()
    reference=read_reference_file(root, args.reference_ref, str(STREAM), text=True)
    support=[root/'rtl/common/add_equal.sv',root/'rtl/common/increment_equal.sv',root/'rtl/common/parallel_unsigned_compare.sv']
    paths=[root/STREAM,*support,Path(__file__).resolve(),utility_path]
    hashes={str(p):digest(p) for p in paths}
    helper=out/'tile_group_helpers.sv'
    helper.write_text('\n'.join(utilities['module'](current,name) for name in
        ('conv_tile_low_difference','conv_tile_high_compare','conv_tile_low_less_select',
         'conv_tile_low_flag_select','conv_tile_group_low5','conv_tile_group_range_result')))
    support.append(helper);results=[];mapping={}
    for size,rw in CONFIGURATIONS:
        name=f'size{size}_rw{rw}'
        inputs={'group_c':16,'i_window_next_ch':16,'i_ch0_q':16,'i_window_group_remaining_q':17,'i_tile_cols':rw}
        ports=',\n'.join(utilities['declarations'](inputs,'input '));connections=','.join('.'+x+'('+x+')' for x in inputs)
        text=circuit('actual_group',current,size,rw)+circuit('reference_group',reference,size,rw)+f'''
module proof({ports},output logic equivalent,boundary_equivalent,output logic[1:0]actual_value,expected_value);
actual_group actual({connections},.o_incoming_tile_group_fits(actual_value));
reference_group expected({connections},.o_incoming_tile_group_fits(expected_value));
wire [16:0] requested_columns=i_tile_cols==0?17'({size}):17'(i_tile_cols);
wire [16:0] channel_end={{1'b0,i_ch0_q}}+requested_columns;
assign equivalent=actual_value===expected_value;
assign boundary_equivalent=32'(i_tile_cols)>{size}||(actual_value[1]==(channel_end<={{1'b0,group_c}}));
endmodule
'''
        model=out/(name+'_model.sv');model.write_text(text.replace('always_comb','always @*'))
        ys,log,tb,binary,build,simulation=[out/(name+x) for x in ('.ys','.formal.log','.tb.sv','.vvp','.build.log','.four_state.log')]
        ys.write_text('read_slang -DSYNTHESIS --top proof '+shlex.join(map(str,support+[model]))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n'
            'sat -verify -prove boundary_equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as f:subprocess.run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        if log.read_text().count('SAT proof finished - no model found: SUCCESS!')!=2:raise RuntimeError(str(log))
        bits=sum(inputs.values());padded=(bits+31)//32*32;names=','.join(inputs);decl=';\n'.join(utilities['declarations'](inputs))+';'
        tb.write_text(f'''module tb;
{decl}
logic equivalent,boundary_equivalent;
logic [1:0]actual_value,expected_value;
logic [{padded-1}:0]pattern;
logic [{bits-1}:0]applied,seen_x='0,seen_z='0;
integer positive=0,negative=0;
proof dut(.*);
initial begin
for(integer sample=0;sample<{CHECKS};sample++)begin
 for(integer part=0;part<{padded//32};part++)pattern[32*part+:32]=$urandom;
 {{{names}}}=pattern;
 if(sample%4==0)group_c=i_ch0_q+16'(sample%64);
 if(sample%4==1)group_c=i_ch0_q;
 if(sample%7==0)i_tile_cols=0;
 applied={{{names}}};
 if(sample<2*{bits})applied[sample/2]=(sample%2)?1'bz:1'bx;
 {{{names}}}=applied;
 for(integer b=0;b<{bits};b++)begin
  if(applied[b]===1'bx)seen_x[b]=1;
  if(applied[b]===1'bz)seen_z[b]=1;
 end
 #1;
 if(equivalent!==1)$fatal(1,"Group mismatch sample=%0d actual=%b expected=%b input=%h",sample,actual_value,expected_value,applied);
 if(actual_value[1]===1'b1)positive++;
 if(actual_value[1]===1'b0)negative++;
end
if(seen_x!=='1||seen_z!=='1||positive<20||negative<20)$fatal(1,"Incomplete group coverage");
$display("TILE_GROUP_FOUR_STATE_PASS checks={CHECKS} positive=%0d negative=%0d",positive,negative);
$finish;
end
endmodule
''')
        with build.open('w') as f:subprocess.run([args.iverilog,'-g2012','-s','tb','-o',str(binary),*map(str,support+[model,tb])],stdout=f,stderr=subprocess.STDOUT,check=True)
        with simulation.open('w') as f:subprocess.run([args.vvp,str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
        if 'TILE_GROUP_FOUR_STATE_PASS' not in simulation.read_text():raise RuntimeError(str(simulation))
        binary.unlink();results.append(dict(size=size,rw=rw,formal_properties=2,formal_passed=True,four_state_checks=CHECKS,
            input_bits=bits,all_input_bits_x_z=True,model_sha256=digest(model),formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)))
        if (size,rw)==(16,5):
            for kind in ('actual','expected'):
                wrapper=out/(kind+'_mapping.sv');text=utilities['mapping_wrapper'](inputs,2,kind)
                text=text.replace('output logic [1:0] o_value','output logic o_value').replace(f'o_value <= {kind}_value;',f'o_value <= {kind}_value[1];')
                text=text.replace('logic unused_equivalent;','logic unused_equivalent,unused_boundary;').replace('.equivalent(unused_equivalent)', '.equivalent(unused_equivalent),.boundary_equivalent(unused_boundary)')
                wrapper.write_text(text)
                mapping[kind]=dict(top='comparison_mapping',options=['-D','SYNTHESIS=1'],sources=list(map(str,support+[model,wrapper])),configuration='Complete registered current-channel group range')
        print('TILE_GROUP_CANDIDATES_PASS',name,flush=True)
    if hashes!={p:digest(p) for p in hashes}:raise RuntimeError('检查期间源码发生变化')
    (out/'mapping_cases.json').write_text(json.dumps(mapping,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,sources_unchanged=True,reference_ref=args.reference_ref,
        reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),formal_properties=2*len(results),four_state_checks=CHECKS*len(results),
        reference_comparison_inputs_constrained=False,boundary_property='Channel plus requested columns is within group for valid descriptor column counts.',cases=results),indent=2)+'\n')


if __name__=='__main__':main()
