#!/usr/bin/env python3
"""证明地址范围选择和带符号配置因子的定宽关系。"""
from pathlib import Path
from source_sections import read_module
import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, default=ROOT)
parser.add_argument('--out', type=Path, default=ROOT/'build/frontend_pipeline/control_formal')
args = parser.parse_args()
SOURCE, rtl = read_module(args.source_root, 'stream')
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
choice=re.search(r'      assign next_available\[byte_index\] = tile_commit \?.*?;',rtl,re.S).group(0)
choice=choice.replace('state[$clog2(ADDRESS_CHANNEL)]','address_channel')
word='''module comparison #(parameter int WORD_SHIFT=3)(
input logic [1:0] mode,
input logic invalid,fast,output_valid,output_ready,chunk_reaches_end,
input logic row_last_q,row_base_valid,geometry_tile,past_active_q,active_after_chunk,
input logic group_end_o_equal,coordinate_address_valid,linear_candidate,
input logic [(1<<WORD_SHIFT)-1:0][4:0] source_available,
output logic equivalent
);
localparam int p_cache_read_bytes=1<<WORD_SHIFT;
logic tile_commit,address_channel,stream_write,column_advance,address_linear_tap;
logic [4:0] select;
logic [p_cache_read_bytes-1:0] next_available,expected;
assign tile_commit=mode==2'd1;
assign address_channel=mode==2'd2;
assign stream_write=mode==2'd3&&output_valid&&output_ready;
assign column_advance=!chunk_reaches_end&&!past_active_q&&active_after_chunk;
assign address_linear_tap=!coordinate_address_valid&&linear_candidate;
assign select[0]=tile_commit&&!invalid&&fast;
assign select[1]=stream_write&&chunk_reaches_end&&!row_last_q&&row_base_valid&&!geometry_tile;
assign select[2]=stream_write&&column_advance&&group_end_o_equal&&coordinate_address_valid;
assign select[3]=stream_write&&column_advance&&(!group_end_o_equal||address_linear_tap);
assign select[4]=address_channel;
for(genvar byte_index=0;byte_index<p_cache_read_bytes;byte_index++)begin:g_byte
CHOICE
assign expected[byte_index]=|(select&source_available[byte_index]);
end
assign equivalent=!(|select)||expected==next_available;
endmodule
'''.replace('CHOICE',choice)
(OUT/'word_choice.sv').write_text(word)
factor='''module comparison(input logic [15:0] dimension,output logic equivalent);
logic signed [16:0] factor;
logic [32:0] old_factor,new_factor;
assign factor=17'sd1-$signed({1'b0,dimension});
assign old_factor=33'd1-{17'd0,dimension};
assign new_factor=33'(factor);
assign equivalent=old_factor==new_factor;
endmodule
'''
(OUT/'factor.sv').write_text(factor)
events='''module comparison #(parameter int WIDTH=9)(
input logic clk,
input logic [2:0] event_kind,
input logic [WIDTH-1:0] loaded_value,advanced_value,
output logic equivalent
);
logic observable;
logic [WIDTH-1:0] reference_range,prepared_range;
always_ff @(posedge clk)begin
case(event_kind)
3'd1,3'd5,3'd7:begin
  reference_range<=loaded_value;prepared_range<=loaded_value;observable<=1'b1;
end
3'd2:if(observable)begin
  reference_range<=advanced_value;prepared_range<=advanced_value;
end
3'd3,3'd6:begin prepared_range<=advanced_value;observable<=1'b0;end
3'd4:if(!observable)prepared_range<=advanced_value;
default:;
endcase
end
assign equivalent=!observable||reference_range==prepared_range;
endmodule
'''
(OUT/'range_events.sv').write_text(events)
cases=[]
def run(name,model,options='',sequential=False):
    script=OUT/(name+'.ys');log=OUT/(name+'.log')
    script.write_text(f'read_slang --top comparison {options} {OUT/model}\n'
                     'prep -top comparison -flatten\n'+
                     ('sat -seq 8 -set-init-zero -tempinduct -verify -prove equivalent 1\n' if sequential else
                      'sat -verify -prove equivalent 1\n'))
    with log.open('w') as output:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                              cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    assert result.returncode==0,log
    cases.append({'name':name,'passed':True,'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                  'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
for shift in (1,2,3,4):run('word_'+str(shift),'word_choice.sv',f'-GWORD_SHIFT={shift}')
run('signed_factor','factor.sv')
for width in (5,9):run('range_events_'+str(width),'range_events.sv',f'-GWIDTH={width}',True)
extractors=runpy.run_path(str(ROOT/'test/frontend_group_feedback/check.py'))
for lanes in (1,2,4,8):
    saved=8 if lanes>4 else 4
    row=extractors['row_unit'](rtl,lanes,min(lanes,4)).replace('module comparison #(', 'module row_predicate #(')
    qualifier=extractors['guard_unit'](rtl,lanes,True,min(lanes,4))
    qualifier=qualifier.replace('module comparison #(', 'module lane_predicate #(')
    qualifier=qualifier.replace('output logic equivalent','output logic equivalent,output logic [LANES-1:0] observed_lanes')
    qualifier=qualifier.replace('endmodule', 'assign observed_lanes=chunk_lane_allowed;\nendmodule')
    wrapper=f'''module comparison(
input logic [{saved}:0] range_a,range_b,
input logic [{lanes-1}:0] word_s8,word_s16,
input logic [{lanes}:0] active_lane_allowed_q,column_lane_allowed_q,
input logic narrow_output,word_output_q,input_s16,
output logic equivalent
);
logic [1:0] row_end;
logic [{lanes-1}:0] observed_a,observed_b;
'''
    for index,label in enumerate(('a','b')):
        wrapper+=f'''row_predicate u_row_{label}(
.group_lane_allowed(range_{label}[{lanes-1}:0]),.word_s8,.word_s16,
.active_lane_allowed_q,.column_lane_allowed_q,.narrow_output,.word_output_q,.past_active_q(1'b1),.input_s16,
.actual_end(row_end[{index}]),.expected_end(),.equivalent());
lane_predicate u_lane_{label}(
.group_range_q(range_{label}),.active_lane_allowed_q,.column_lane_allowed_q,
.word_lane_allowed(input_s16?word_s16:word_s8),.narrow_output,.word_output_q,.past_active_q(1'b1),
.chunk_reaches_end(1'b0),.active_after_chunk(1'b0),.equivalent(),.observed_lanes(observed_{label}));
'''
    wrapper+='assign equivalent=row_end[0]==row_end[1]&&observed_a==observed_b;\nendmodule\n'
    model=f'padding_independence_{lanes}.sv'
    (OUT/model).write_text(row+qualifier+wrapper)
    run('padding_independence_'+str(lanes),model)
# 因子证明覆盖全部十六位尺寸；乘法比较覆盖每个尺寸及正负范围的边界步长。
checks=0
for dimension in range(65536):
    factor_value=1-dimension
    for step in (0,1,2,3,7,127,255,32767,32768,65534,65535):
        expected=(-(((dimension-1)&((1<<64)-1))*step))&((1<<33)-1)
        actual=(factor_value*step)&((1<<33)-1)
        assert actual==expected
        checks+=1
summary={'passed':True,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
         'cases':cases,'configuration_product_comparisons':checks,
         'range_event_scope':'Abstract update-event model; observable data is restored by row, descriptor or decode loads.'}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'passed':True,'cases':len(cases),'configuration_product_comparisons':checks}))
