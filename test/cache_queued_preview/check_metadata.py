#!/usr/bin/env python3
"""验证多项队列的预读有效位并行读取、同拍转发及四态结果。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
MODULE='rtl/npu/dma/cache/conv_cache_metadata_way.sv'
PORTS='''input logic clk,rst_n,i_cfg_accept,i_lookup_preview_selected,
input logic [1:0] i_lookup_candidate_select,
input logic [1:0][SI-1:0] i_lookup_input_set,
input logic [2:0][SI-1:0] other_set,
input logic [SI-1:0] read_set,valid_i_wr_addr,
input logic valid_i_wr_en,
input logic [0:0] valid_i_wr_data,
input logic i_lookup_unknown,
input logic [SETS-1:0] valid_memory'''
NAMES=('clk','rst_n','i_cfg_accept','i_lookup_preview_selected','i_lookup_candidate_select',
       'i_lookup_input_set','other_set','read_set','valid_i_wr_addr','valid_i_wr_en',
       'valid_i_wr_data','i_lookup_unknown','valid_memory')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name,text):
    marker='    end else begin : g_current_lookup_valid'
    start=text.index(marker);end=text.index('    assign o_lookup_valid_raw',start)
    block=text[start:end].replace(marker,'    if (1) begin : g_current_lookup_valid',1)
    selected='lookup_selected_valid' if 'logic lookup_selected_valid' in block else 'lookup_candidate_valid[i_lookup_candidate_select]'
    return f'''// 元数据实际读取过程的独立检查模型。
module {name} #(parameter integer SETS=16,SI=$clog2(SETS))(
{PORTS},output logic selected_value,stored_value);
  localparam bit p_preview_request=1'b1;
  localparam integer p_valid_read_ports=12;
  logic [p_valid_read_ports-1:0][SI-1:0] valid_i_rd_addr;
  logic [p_valid_read_ports-1:0][0:0] valid_o_rd_data;
  logic [3:0][SI-1:0] i_lookup_candidate_set;
  logic [5:0][SI-1:0] i_read_set;
  logic [3:0] o_lookup_source_valid;
  logic [5:0] valid_read_value;
  assign i_lookup_candidate_set={{other_set[2],
      (i_lookup_preview_selected ? i_lookup_input_set[1] : i_lookup_input_set[0]),
      other_set[1],other_set[0]}};
  assign i_read_set={{{{5*SI{{1'b0}}}},read_set}};
  for(genvar p=0;p<p_valid_read_ports;p++) begin:g_read
    assign valid_o_rd_data[p][0]=valid_memory[valid_i_rd_addr[p]];
  end
{block}
  assign selected_value=g_current_lookup_valid.{selected};
  assign stored_value=valid_read_value[0];
endmodule
'''


def bench(sets):
    declarations=PORTS.replace('input logic','logic').replace(',\n',';\n')+';\n'
    width=8+7*(sets.bit_length()-1)+sets
    fields=','.join(n for n in NAMES if n!='clk')
    connect=','.join('.'+n+'('+n+')' for n in NAMES)
    return f'''`timescale 1ns/1ps
// 枚举控制四态并逐位注入地址与存储数据的未知值。
module tb;
  localparam integer SETS={sets},SI=$clog2(SETS),W={width};
  {declarations}
  logic ref_selected,ref_stored,cur_selected,cur_stored;
  logic [W-1:0] stimulus,saved;
  integer checks=0;
  int unsigned random_state=32'h6f12c39a;
  reference #(.SETS(SETS)) u_ref({connect},.selected_value(ref_selected),.stored_value(ref_stored));
  current #(.SETS(SETS)) u_cur({connect},.selected_value(cur_selected),.stored_value(cur_stored));
  assign {{{fields}}}=stimulus;
  function automatic logic value4(input integer code);
    case(code) 0:value4=0;1:value4=1;2:value4=1'bx;default:value4=1'bz;endcase
  endfunction
  function automatic int unsigned next_random();
    random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
    return random_state;
  endfunction
  task automatic initialize;
    for(integer b=0;b<W;b++)stimulus[b]=1'(next_random());
  endtask
  task automatic check;
    #1;
    if(cur_selected!==ref_selected)$fatal(1,"selected valid case=%0d",checks);
    clk=1;#1;
    if(cur_stored!==ref_stored)$fatal(1,"stored valid case=%0d",checks);
    clk=0;checks++;
  endtask
  initial begin
    clk=0;
    for(integer scenario=0;scenario<65536;scenario++)begin
      initialize();
      for(integer b=0;b<5;b++)stimulus[W-1-b]=value4((scenario>>(2*b))&3);
      stimulus[SETS+2]=value4((scenario>>10)&3);
      stimulus[SETS+1]=value4((scenario>>12)&3);
      stimulus[SETS]=value4((scenario>>14)&3);
      check();
    end
    for(integer scenario=0;scenario<64;scenario++)begin
      initialize();saved=stimulus;
      for(integer b=0;b<W;b++)begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus=saved;stimulus[b]=1'bz;check();
      end
    end
    for(integer scenario=0;scenario<20000;scenario++)begin
      initialize();
      for(integer b=0;b<W;b++)if((next_random()&15)==0)stimulus[b]=value4(2+(next_random()&1));
      check();
    end
    $display("CACHE_QUEUED_METADATA_PASS checks=%0d",checks);$finish;
  end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='3f4bc2a97dfecf0ec38ad49d704c2ee4ee7f8365')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=subprocess.check_output(['git','show',args.reference+':'+MODULE],cwd=ROOT,text=True)
    current=(ROOT/MODULE).read_text();source_hash=digest(ROOT/MODULE)
    models=out/'models.sv';models.write_text(model('reference',reference)+model('current',current))
    results=[]
    for sets in (2,16,256):
        test=out/f'tb_{sets}.sv';test.write_text(bench(sets))
        connect=','.join('.'+n+'('+n+')' for n in NAMES)
        proof=out/f'proof_{sets}.sv'
        proof.write_text(f'''// 两种元数据读取实现共享任意输入和任意有效位存储。
module proof #(parameter integer SETS={sets},SI=$clog2(SETS))(
{PORTS},output logic match_result);
logic ref_selected,cur_selected,ref_stored,cur_stored;
reference #(.SETS(SETS)) u_ref({connect},.selected_value(ref_selected),.stored_value(ref_stored));
current #(.SETS(SETS)) u_cur({connect},.selected_value(cur_selected),.stored_value(cur_stored));
assign match_result=ref_selected==cur_selected;
endmodule
''')
        for mode,flags in (('generic',['-USYNTHESIS','-UXILINX_FPGA']),('fpga',['-DSYNTHESIS=1','-DXILINX_FPGA=1'])):
            name=f'{mode}_{sets}';script=out/(name+'.ys');log=out/(name+'.log')
            script.write_text('read_slang --top proof '+shlex.join(flags+[str(models),str(proof)])+
                '\nprep -top proof -flatten\nopt -full\nsat -prove match_result 1 -verify\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    check=True,stdout=stream,stderr=subprocess.STDOUT)
            binary=out/(name+'.vvp')
            compiler_flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
            subprocess.run(['iverilog','-g2012','-s','tb','-o',binary]+compiler_flags+[str(models),str(test)],check=True,capture_output=True)
            simulation=subprocess.run(['vvp',binary],check=True,capture_output=True,text=True)
            simlog=out/(name+'_four_state.log');simlog.write_text(simulation.stdout)
            count=int(re.search(r'PASS checks=(\d+)',simulation.stdout).group(1))
            result=dict(mode=mode,sets=sets,formal_passed=True,four_state_checks=count,
                log_sha256=digest(log),four_state_log_sha256=digest(simlog))
            results.append(result);print(json.dumps(result),flush=True)
    assert digest(ROOT/MODULE)==source_hash
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=source_hash,
        reference_commit=args.reference,cases=results,input_constraints=[]),indent=2)+'\n')


if __name__=='__main__':main()
