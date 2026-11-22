#!/usr/bin/env python3
"""验证 IA 请求捕获后的标记与槽号一致关系。"""
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
SOURCE = Path('rtl/npu/loaders/ia_loader.sv')


def assignment(text: str, name: str, prefix: str = 'assign ') -> str:
    match = re.search(re.escape(prefix + name) + r'\s*=.*?;', text, re.S)
    if match is None:
        raise RuntimeError('赋值未找到: ' + name)
    return match.group(0)


def capture(text: str, name: str) -> str:
    matches = re.findall(re.escape(name) + r'\s*<=.*?;', text, re.S)
    if len(matches) != 1:
        raise RuntimeError('捕获赋值数量不匹配: ' + name)
    return matches[0]


def unit(source: str, candidate: str, controller: str) -> str:
    start = source.index('    localparam int unsigned ORDERED_TAG_W')
    end = source.index('    logic ctrl_load_req', start)
    tag = source[start:end]
    start = source.index('    assign {unused_demand_p0_carry, demand_p0_nxt}')
    end = re.search(r'^\s*(?:\(\*.*?\*\)\s*)?logic \[CACHE_SLOT_W-1:0\] request_slot_sum;',
                    source[start:], re.M).start() + start
    coordinates = source[start:end]
    start = candidate.index('    logic demand_lookup_match;')
    end = candidate.index('    wire prefetch_cached', start)
    actual = candidate[start:end]
    start = source.index('    wire cache_hit_event')
    end = source.index('    wire prefetch_cached', start)
    expected = source[start:end].replace('cache_hit_event', 'expected_hit')
    row_reset = re.findall(r'tl_rows_to_read_r\s*<=.*?;', controller, re.S)
    start_reset = re.findall(r'tl_start_r\s*<=.*?;', controller, re.S)
    assert len(row_reset) == len(start_reset) == 2
    request_fields = '\n'.join(assignment(source, f'request_descriptor.{field}', '')
                               for field in ('rows', 'p0', 'q0', 'slot'))
    demand_fields = '\n'.join(assignment(source, f'demand_descriptor.{field}', '')
                              for field in ('rows', 'p0', 'q0', 'slot'))
    return f'''module comparison #(
parameter int REG_WIDTH=32, SIZE=16, CACHE_SLOT_W=6, DATA_WIDTH=16,
parameter int LOG2_SIZE=$clog2(SIZE), ORDERED_JOB=1
)(
input logic clk,rst_n,init_cfg,load_issue,
input logic [REG_WIDTH-1:0] request_p0,request_q0,p0_base_q,q0_base_q,
input logic [REG_WIDTH-1:0] cfg_p0_base,cfg_q0_base,cfg_cache_slot_base,load_rows_cur,
input logic [CACHE_SLOT_W-1:0] request_slot,cache_slot_base_q,cache_slot_mask,incoming_slot_mask,
input logic preserve_cache_q,request_lookup_valid,request_tag_match,cache_flush,prefetch_start,
input logic [(1<<CACHE_SLOT_W)-1:0] cache_tags_valid,
output logic actual_hit,reference_hit,actual_start,reference_start,equivalent,relation
);
{tag}
logic [REG_WIDTH-1:0] demand_p0_nxt,demand_q0_nxt,demand_p0_q,demand_q0_q;
logic [REG_WIDTH-1:0] request_p0_absolute,request_q0_absolute,request_rows;
logic [REG_WIDTH-1:0] tl_rows_to_read_r,tl_rows_to_read;
logic tl_start_r,tl_start;
logic unused_demand_p0_carry,unused_demand_q0_carry;
logic [CACHE_SLOT_W-1:0] demand_slot_q,demand_slot_next,demand_slot_mask_next,demand_slot_base_next,request_slot_sum;
logic [CACHE_TAG_W-1:0] request_lookup_q;
logic [CACHE_SLOT_W-1:0] request_lookup_slot_q;
dma_descriptor_t demand_descriptor,request_descriptor;
{coordinates}
{assignment(source, 'request_slot_sum')}
{assignment(source, 'request_p0_absolute')}
{assignment(source, 'request_q0_absolute')}
{assignment(controller, 'request_rows')}
{assignment(controller, 'tl_start')}
{assignment(controller, 'tl_rows_to_read')}
always_comb begin
 demand_descriptor='0;
 request_descriptor='0;
 {request_fields}
 {demand_fields}
end
always_ff @(posedge clk) begin
 {capture(source, 'request_lookup_q')}
 {capture(source, 'request_lookup_slot_q')}
end
always_ff @(posedge clk or negedge rst_n) begin
 if(!rst_n)begin
  {start_reset[0]}
  {row_reset[0]}
 end else begin
  {start_reset[1]}
  {row_reset[1]}
 end
end
{actual}
{expected}
assign actual_hit=cache_hit_event;
assign reference_hit=expected_hit;
assign actual_start=(tl_start&&!cache_hit_event)||prefetch_start;
assign reference_start=(tl_start&&!expected_hit)||prefetch_start;
assign equivalent=(actual_hit==reference_hit)&&(actual_start==reference_start);
assign relation=!tl_start||demand_lookup_match==
  ((request_lookup_slot_q==demand_descriptor.slot)&&
   (request_lookup_q==descriptor_tag(demand_descriptor)));
endmodule
'''


def four_state_bench() -> str:
    header = '''module tb;
logic clk=0,rst_n=0,init_cfg,load_issue;
logic [31:0] request_p0,request_q0,p0_base_q,q0_base_q,cfg_p0_base,cfg_q0_base,cfg_cache_slot_base,load_rows_cur;
logic [6:0] request_slot,cache_slot_base_q,cache_slot_mask,incoming_slot_mask;
logic preserve_cache_q,request_lookup_valid,request_tag_match,cache_flush,prefetch_start;
logic [127:0] cache_tags_valid;
logic [5:0] actual_hit,reference_hit,actual_start,reference_start,equivalent,relation;
integer checks=0;
integer seed=32'h31bb8271;
function automatic logic random_control;
 case($urandom_range(0,7))
  0:random_control=1'bx;
  1:random_control=1'bz;
  default:random_control=1'($urandom);
 endcase
endfunction
function automatic logic [31:0] random_value;
logic [31:0] value;
integer index;
begin
 value=$urandom;
 if($urandom_range(0,7)==0)begin
  index=$urandom_range(0,31);
  value[index]=$urandom_range(0,1)?1'bx:1'bz;
 end
 return value;
end
endfunction
task automatic check_outputs;
begin
 if(actual_hit!==reference_hit||actual_start!==reference_start)
  $fatal(1,"IA lookup capture differs at cycle %0d hit=%b/%b start=%b/%b",checks,actual_hit,reference_hit,actual_start,reference_start);
 checks+=6;
end
endtask
'''
    profiles = [(8, 3, 3), (16, 4, 3), (32, 8, 4), (32, 16, 6), (32, 16, 7), (32, 32, 6)]
    text = [header]
    for index, (width, size, slot) in enumerate(profiles):
        connections = ['.clk', '.rst_n', '.init_cfg', '.load_issue']
        connections += [f'.{name}({name}[{width-1}:0])' for name in (
            'request_p0', 'request_q0', 'p0_base_q', 'q0_base_q',
            'cfg_p0_base', 'cfg_q0_base', 'cfg_cache_slot_base', 'load_rows_cur')]
        connections += [f'.{name}({name}[{slot-1}:0])' for name in (
            'request_slot', 'cache_slot_base_q', 'cache_slot_mask', 'incoming_slot_mask')]
        connections += ['.preserve_cache_q', '.request_lookup_valid', '.request_tag_match', '.cache_flush', '.prefetch_start',
                        f'.cache_tags_valid(cache_tags_valid[{(1<<slot)-1}:0])']
        connections += [f'.{name}({name}[{index}])' for name in (
            'actual_hit', 'reference_hit', 'actual_start', 'reference_start', 'equivalent', 'relation')]
        text.append(f'comparison #(.REG_WIDTH({width}),.SIZE({size}),.CACHE_SLOT_W({slot})) u_{index}(\n'+',\n'.join(connections)+');\n')
    text.append('''initial begin
 seed=$urandom(seed);
 init_cfg=0;load_issue=0;request_p0=0;request_q0=0;p0_base_q=0;q0_base_q=0;
 cfg_p0_base=0;cfg_q0_base=0;cfg_cache_slot_base=0;load_rows_cur=0;
 request_slot=0;cache_slot_base_q=0;cache_slot_mask='1;incoming_slot_mask='1;
 preserve_cache_q=1;request_lookup_valid=1;request_tag_match=1;cache_flush=0;prefetch_start=0;cache_tags_valid='1;
 #1;clk=1;#1;check_outputs();clk=0;rst_n=1;
 for(integer cycle=0;cycle<100000;cycle++)begin
  request_p0=random_value();request_q0=random_value();
  p0_base_q=random_value();q0_base_q=random_value();
  cfg_p0_base=random_value();cfg_q0_base=random_value();
  cfg_cache_slot_base=random_value();load_rows_cur=random_value();
  request_slot=7'(random_value());cache_slot_base_q=7'(random_value());
  cache_slot_mask=7'(random_value());incoming_slot_mask=7'(random_value());
  init_cfg=random_control();load_issue=random_control();
  preserve_cache_q=random_control();request_lookup_valid=random_control();
  request_tag_match=random_control();cache_flush=random_control();prefetch_start=random_control();
  for(integer bit_index=0;bit_index<128;bit_index++)cache_tags_valid[bit_index]=random_control();
  if(cycle%137==0)rst_n=0;
  #1;check_outputs();clk=1;#1;check_outputs();clk=0;
  if(!rst_n)begin rst_n=1;#1;check_outputs();end
 end
 $display("IA_LOOKUP_CAPTURE_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    return '\n'.join(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = (args.reference_root.resolve() / SOURCE).read_text()
    candidate = (args.source_root.resolve() / SOURCE).read_text()
    controller_path = args.source_root.resolve() / 'rtl/npu/loaders/ia_loader_ctrl.sv'
    rtl = out / 'comparison.sv'
    rtl.write_text(unit(reference, candidate, controller_path.read_text()))
    records = []
    for width, size, slot in [(8,3,3),(16,4,3),(32,8,4),(32,16,6),(32,16,7),(32,32,6)]:
        name = f'{width}_{size}_{slot}'
        script, log = out / (name+'.ys'), out / (name+'.log')
        script.write_text(f'read_slang --top comparison -GREG_WIDTH={width} -GSIZE={size} -GCACHE_SLOT_W={slot} {shlex.quote(str(rtl))}\n'
                          'prep -top comparison -flatten\nasync2sync\nopt_clean\n'
                          'sat -verify -seq 3 -set-at 1 rst_n 0 -prove equivalent 1 -show-inputs -show-outputs\n'
                          'sat -verify -tempinduct -seq 2 -set-init-zero -prove relation 1 -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                    stdout=stream,stderr=subprocess.STDOUT,timeout=60)
        passed = result.returncode == 0 and 'Induction step proven: SUCCESS!' in log.read_text()
        if not passed:
            raise RuntimeError(f'SAT 未完成: {name}\n'+log.read_text()[-3000:])
        records.append({'REG_WIDTH':width,'SIZE':size,'CACHE_SLOT_W':slot,'passed':True,
                        'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
        print('IA_LOOKUP_CAPTURE_SAT_PASS',name,flush=True)
    bench = out / 'four_state.sv'
    bench.write_text(four_state_bench())
    executable = out / 'four_state.vvp'
    with (out/'four_state_build.log').open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(executable),str(rtl),str(bench)],
                       stdout=stream,stderr=subprocess.STDOUT,check=True)
    with (out/'four_state.log').open('w') as stream:
        subprocess.run(['vvp',str(executable)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
    four_state=(out/'four_state.log').read_text()
    count=re.search(r'IA_LOOKUP_CAPTURE_FOUR_STATE_PASS checks=(\d+)',four_state)
    if count is None:
        raise RuntimeError('四态比较未完成')
    summary={'passed':True,'scope':'Actual request and demand capture expressions; reset, configuration and arbitrary control inputs',
             'input_constraints':False,'profiles':records,'four_state_comparisons':int(count[1]),
             'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
             'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
             'controller_sha256':hashlib.sha256(controller_path.read_bytes()).hexdigest(),
             'extracted_rtl_sha256':hashlib.sha256(rtl.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
