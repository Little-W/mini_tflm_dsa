#!/usr/bin/env python3
"""读取前端实际写入逻辑，证明任意状态、字节和偏移下全部输出相同。"""
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
SOURCE=Path('rtl/npu/conv/conv_im2col_frontend.sv')
DECL='''  logic [7:0] offset_high_plus_one, offset_high_minus_one;
  logic unused_offset_high_add_carry, unused_offset_high_sub_carry;
  logic [LANES-1:0][7:0] selected_s8_byte, corrected_s8_high;
  logic [LANES-1:0][8:0] corrected_s8_low;
  logic [LANES-1:0][15:0] corrected_s8_value;
'''
PORTS=[('i_state','5'),('addr','32'),('word_buf','32'),('cache_rsp_data','32'),
       ('group_c','16'),('ch_q','16'),('input_offset','16'),('input_s16','1'),
       ('col_remaining','TILE_COUNT_W'),('col_idx','TILE_COUNT_W'),
       ('active_cols_q','TILE_COUNT_W'),('active_remaining','TILE_COUNT_W'),
       ('group_lane_allowed','LANES'),('word_lane_allowed','LANES')]


def digest(data):return hashlib.sha256(data).hexdigest()


def unit(name,body,enum,declaration=''):
    ports=',\n'.join('  input logic ['+width+'-1:0] '+name for name,width in PORTS)
    header='module '+name+''' #(
  parameter int LANES=4,
  parameter int TILE_COUNT_W=5,
  parameter int CHUNK_COUNT_W=$clog2(LANES+1),
  parameter int OBSERVED_W=49+CHUNK_COUNT_W+18*LANES
)(
'''+ports+''',
  output logic [OBSERVED_W-1:0] observed
);
'''+enum+'''
  st_t state;
  typedef struct packed {logic [15:0] group_c;logic signed [15:0] input_offset;logic input_s16;} config_t;
  config_t c;
  logic [31:0] stream_word,selected_word;
  logic [16:0] group_remaining;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  logic [LANES-1:0] chunk_lane_allowed,wr_mask;
  logic signed [15:0] wr_data[LANES];
  logic [LANES*16-1:0] data_flat;
  assign state=st_t'(i_state);
  assign c.group_c=group_c;
  assign c.input_offset=input_offset;
  assign c.input_s16=input_s16;
'''
    return header+declaration+body+'''
  for(genvar lane=0;lane<LANES;lane++)begin:g_flat
    assign data_flat[lane*16+:16]=wr_data[lane];
  end
  assign observed={group_remaining,chunk_count,chunk_lane_allowed,selected_word,wr_mask,data_flat};
endmodule
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',default='3c8cafeb');p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=read_rtl_source(str(args.reference)+':'+str(SOURCE), cwd=ROOT, text=True)
    enum=re.search(r'  typedef enum logic \[4:0\] \{.*?\} st_t;',reference,re.S)[0]
    end='  always_comb begin\n    cfg_pixel_bytes'
    start_ref=reference.index('  assign stream_word =')
    start_cur=current.index('  // 偏移高字节的相邻值共用计算')
    body_ref=reference[start_ref:reference.index(end,start_ref)]
    body_cur=current[start_cur:current.index(end,start_cur)]
    normalized=current.replace(DECL,'',1).replace(body_cur,body_ref,1)
    if normalized!=reference:raise RuntimeError('Additional frontend changes require verification')
    texts={label:unit(label+'_write_data',body,enum,DECL if label=='current' else '')
      for label,body in (('reference',body_ref),('current',body_cur))}
    for label,text in texts.items():(out/(label+'.sv')).write_text(text)
    ports=',\n'.join('  input logic ['+width+'-1:0] '+name for name,width in PORTS)
    proof=out/'comparison.sv'
    proof.write_text(texts['reference']+texts['current']+'''module write_data_proof #(
  parameter int LANES=4,parameter int TILE_COUNT_W=5,
  parameter int OBSERVED_W=49+$clog2(LANES+1)+18*LANES
)(
'''+ports+''',output logic equivalent);
  logic [OBSERVED_W-1:0] expected,actual;
  reference_write_data #(.LANES(LANES),.TILE_COUNT_W(TILE_COUNT_W)) u_reference(.*,.observed(expected));
  current_write_data #(.LANES(LANES),.TILE_COUNT_W(TILE_COUNT_W)) u_current(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
''')
    cases=[]
    for lanes in (1,2,3,4,8):
        script,log=out/f'lanes{lanes}.ys',out/f'lanes{lanes}.log'
        script.write_text('read_slang --top write_data_proof -GLANES='+str(lanes)+' '+shlex.quote(str(proof))+
          '\nprep -top write_data_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
              cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():raise RuntimeError('Incomplete proof')
        cases.append(dict(lanes=lanes,passed=True,input_bits=170+2*lanes,
            observed_bits=49+lanes.bit_length()+18*lanes,script_sha256=digest(script.read_bytes()),log_sha256=digest(log.read_bytes())))
    report=dict(passed=True,reference_ref=args.reference,
      reference_commit=subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip(),
      source_sha256=digest(current.encode()),reference_sha256=digest(reference.encode()),
      unchanged_outside_write_data=True,actual_source_expressions=True,inputs_constrained=False,
      proof_sha256=digest(proof.read_bytes()),cases=cases)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
