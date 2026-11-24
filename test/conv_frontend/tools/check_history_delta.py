#!/usr/bin/env python3
"""证明完整位置差、行范围和模行尾比较的保存关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module


def extract(text,start,stop):
    first=text.index(start);return text[first:text.index(stop,first)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    path=args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv';text=path.read_text();sha=hashlib.sha256(path.read_bytes()).hexdigest()
    geometry_path,geometry=read_module(args.source_root,'geometry')
    geometry_sha=hashlib.sha256(geometry_path.read_bytes()).hexdigest()
    delta_instance=re.search(r'^  parallel_prefix_add\s*#\([^;]+\)\s*u_history_delta\s*\(',geometry,re.M)
    if delta_instance is None:raise ValueError('Missing history difference arithmetic')
    update=geometry[delta_instance.start():geometry.index('  always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) p_wrap_target_q',delta_instance.start())]
    compares=extract(geometry,'  assign p_sum_wrap_i_a =','  always_comb begin\n    history_result.valid =')
    assert re.findall(r'\blast_p\s*<=\s*([^;]+);',text)==['0','p0','p0']
    assert re.findall(r'\bp0\s*<=\s*([^;]+);',text)==['0','committing_tile.position']
    overflow_assignments=re.findall(r'\blast_p_overflow_q\s*<=\s*([^;]+);',text)
    assert overflow_assignments==['0','(&p0[31:16]) && history_limit_carry','(&p0[31:16]) && history_limit_carry']
    sv=args.out/'history.sv';ys=args.out/'history.ys';log=args.out/'history.log'
    sv.write_text('''module proof(input logic clk,rst_n,input logic[1:0]event_choice,
 input logic[31:0]position,input logic invalid,input logic[15:0]output_width,last_x,p_wrap_target_q,last_output_col_q,
 output logic equivalent);
 typedef struct packed {logic[15:0]output_w;}cfg_t;cfg_t c;
 typedef struct packed {logic invalid;logic[31:0]position;}tile_t;tile_t committing_tile;
 logic[31:0]p0,last_p,last_p_limit;
 logic last_p_valid,last_p_overflow_q;
 logic[32:0]p_history_delta_q,history_delta_full,reference_limit_sum,reference_delta;
 logic history_limit_carry,unused_history_carry_equal,unused_history_delta_carry;
 logic[15:0]history_carry_i_a,history_carry_i_b;
 logic history_range_valid;
 logic[16:0]history_limit_i_a,history_limit_i_b;
 logic history_limit_o_less,unused_history_limit_equal;
 wire tile_commit=event_choice==2;
 wire p_cache_write_enable=rst_n&&event_choice==3;
 assign committing_tile={invalid,position};
 logic[15:0]p_sum_wrap_i_a,p_sum_wrap_i_b,p_sum_wrap_i_target,p_sum_wrap_carry;
 logic p_sum_wrap_i_carry_in,p_sum_wrap_o_equal,unused_p_sum_wrap_carry;
 logic[15:0]p_sum_last_i_a,p_sum_last_i_b,p_sum_last_i_target;
 logic p_sum_last_i_carry_in,p_sum_last_o_equal;
 logic[15:0]reference_sum;
 assign reference_sum=last_x+p0[15:0]-last_p[15:0];
 assign reference_delta={1'b0,p0}-{1'b0,last_p};
 assign reference_limit_sum={1'b0,last_p}+{17'd0,c.output_w};
 always_ff @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin p0<=0;last_p<=0;last_p_limit<=0;last_p_overflow_q<=0;last_p_valid<=0;c<='0;end
  else begin
   case(event_choice)
    1:begin c.output_w<=output_width;last_p_valid<=0;end
    2:if(!invalid)p0<=position;
    3:begin
     last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_p_valid<=1;
     last_p_overflow_q<=(&p0[31:16])&&history_limit_carry;
    end
    default:;
   endcase
  end
 end
'''+update+compares+'''
 assign equivalent=p_history_delta_q==reference_delta&&
   (!last_p_valid||(last_p_limit==reference_limit_sum[31:0]&&last_p_overflow_q==reference_limit_sum[32]))&&
   (history_range_valid==(last_p_valid&&p0>=last_p&&p0<=last_p_limit))&&
   (p_sum_wrap_o_equal==(reference_sum==p_wrap_target_q))&&
   (p_sum_last_o_equal==(reference_sum==last_output_col_q));
endmodule
'''+('(* keep_hierarchy = "yes" *)\n'+re.search(r'\bmodule\s+conv_history_wrap_select\b.*?\bendmodule',geometry,re.S)[0]
       if 'module conv_history_wrap_select' in geometry else ''))
    dependencies=[args.source_root/'rtl/common'/name for name in
                  ('add_equal.sv','unsigned_compare.sv','parallel_unsigned_compare.sv','parallel_prefix_add.sv')]
    dependency_sha256={str(item):hashlib.sha256(item.read_bytes()).hexdigest() for item in dependencies}
    ys.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 '+shlex.join(map(str,[sv,*dependencies]))+
                  '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                  'prep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n'
                  'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify\n'
                  'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
    with log.open('w')as stream:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],
                              stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode or 'Induction step proven: SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
    assert sha==hashlib.sha256(path.read_bytes()).hexdigest()
    assert geometry_sha==hashlib.sha256(geometry_path.read_bytes()).hexdigest()
    assert dependency_sha256=={str(item):hashlib.sha256(item.read_bytes()).hexdigest() for item in dependencies}
    report={'passed':True,'source_sha256':sha,'geometry_sha256':geometry_sha,'reset_steps':2,'unbounded_induction_steps':1,
            'dependency_sha256':dependency_sha256,
            'position_and_width_constraints':[],'formal_domain':'all binary input and state values',
            'event_scope':'Configuration, valid or invalid descriptor commit, and history storage are mutually exclusive.',
            'event_relationship_proof':'check_frontend_event_domains.py','position_update_sites':2,'history_update_sites':3,
            'synthesis_configuration':['SYNTHESIS=1','XILINX_FPGA=1'],
            'properties':['33-bit position difference','32-bit modulo upper bound and overflow','forward history range','two 16-bit modulo row-end equalities'],
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (args.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print('HISTORY_DELTA_PASS',report)


if __name__=='__main__':main()
