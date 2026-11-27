#!/usr/bin/env python3
"""检查连续读取的完整地址步进、三路选择和四态数据保持。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']([
        ROOT/'rtl/npu/conv/conv_im2col_request_payload.sv'],ROOT)
    hashes={str(p):digest(p) for p in sources};results=[]
    for shift in (1,2,3,4,5,6,7):
        instance=f'''
  wire [2:0] source=stimulus[194:192];
  wire [31:0] address=stimulus[191:160],pixel=stimulus[159:128];
  wire [31:0] seed_address=stimulus[127:96],seed_pixel=stimulus[95:64];
  wire [31:0] saved_address=stimulus[63:32],saved_pixel=stimulus[31:0];
  wire [31:{shift}] next_word=saved_address[31:{shift}]+{32-shift}'d1;
  wire [31:0] next_pixel=saved_pixel+32'd1;
  wire [63:0] following={{next_word,{{{shift}{{1'b0}}}},next_pixel}};
  wire [63:0] actual;
  logic [63:0] expected;
  conv_im2col_request_payload #(.p_word_shift({shift})) dut(
    .i_select(source),.i_address(address),.i_pixel(pixel),
    .i_seed_address(seed_address),.i_seed_pixel(seed_pixel),
    .i_saved_address(saved_address),.i_saved_pixel(saved_pixel),
    .o_address(actual[63:32]),.o_pixel(actual[31:0])
  );
  always_comb begin
    expected=({{64{{source[0]}}}} & {{address,pixel}}) |
             ({{64{{source[1]}}}} & {{seed_address,seed_pixel}}) |
             ({{64{{source[2]}}}} & following);
    case(source)
      3'b001:expected={{address,pixel}};
      3'b010:expected={{seed_address,seed_pixel}};
      3'b100:expected=following;
      default:begin end
    endcase
  end
'''
        for mode,defines in [('generic','`undef SYNTHESIS\n`undef XILINX_FPGA\n'),
                             ('fpga','`define SYNTHESIS 1\n`define XILINX_FPGA 1\n')]:
            name=f'{mode}_shift{shift}';prefix=defines+''.join(f'`include "{p}"\n' for p in sources)
            formal=out/(name+'_formal.sv')
            formal.write_text(prefix+'module proof(input logic [194:0] stimulus);\n'+instance+
                '  always_comb assert(actual==expected);\nendmodule\n')
            script=out/(name+'.ys');script.write_text(f'read_slang --top proof {formal}\n'
                'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top proof -flatten\nchformal -lower\nsat -verify -prove-asserts -show-inputs\n')
            formal_log=out/(name+'_formal.log')
            with formal_log.open('w') as output:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
            assert 'SUCCESS' in formal_log.read_text()
            bench=out/(name+'_tb.sv')
            bench.write_text(prefix+'''module tb;
  logic [194:0] stimulus;
  bit [194:0] seen_zero='0,seen_one='0,seen_x='0,seen_z='0;
  int unsigned random_state=32'h572ba913;
'''+instance+'''
  function automatic int unsigned random_word;
    random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
    return random_state;
  endfunction
  initial begin
    if($bits(stimulus)!=195 || $bits(actual)!=64)$fatal(1,"REQUEST_PAYLOAD_WIDTH");
    for(integer sample=0;sample<8192;sample++)begin
      for(integer bit_index=0;bit_index<195;bit_index++)stimulus[bit_index]=1'(random_word());
      case(sample%16)
        0:stimulus='0;
        1:stimulus='1;
        2:stimulus='x;
        3:stimulus='z;
        4:begin stimulus[194:192]=3'b001;stimulus[191:160]='z;end
        5:begin stimulus[194:192]=3'b010;stimulus[127:64]='z;end
        6:begin stimulus[194:192]=3'b100;stimulus[63:0]='z;end
        7,8,9:stimulus[sample%195]=1'bx;
        10,11,12:stimulus[sample%195]=1'bz;
        default:begin end
      endcase
      #1;
      if(actual!==expected)$fatal(1,"REQUEST_PAYLOAD_MISMATCH sample=%0d actual=%h expected=%h",sample,actual,expected);
      for(integer bit_index=0;bit_index<195;bit_index++)
        case(stimulus[bit_index])
          1'b0:seen_zero[bit_index]=1;
          1'b1:seen_one[bit_index]=1;
          1'bx:seen_x[bit_index]=1;
          default:seen_z[bit_index]=1;
        endcase
    end
    if(!(&seen_zero) || !(&seen_one) || !(&seen_x) || !(&seen_z))$fatal(1,"REQUEST_PAYLOAD_COVERAGE");
    $display("REQUEST_PAYLOAD_PASS samples=8192 input_bits=195 output_bits=64");$finish;
  end
endmodule
''')
            binary=out/(name+'.vvp');simulation=out/(name+'_four_state.log')
            with (out/(name+'_build.log')).open('w') as output:
                subprocess.run(['iverilog','-g2012','-s','tb','-o',binary,bench],
                    stdout=output,stderr=subprocess.STDOUT,check=True,timeout=120)
            with simulation.open('w') as output:
                subprocess.run(['vvp',binary],stdout=output,stderr=subprocess.STDOUT,check=True,timeout=180)
            assert 'REQUEST_PAYLOAD_PASS' in simulation.read_text()
            result=dict(mode=mode,word_shift=shift,passed=True,input_bits=195,output_bits=64,
                input_constraints=[],four_state_checks=8192,every_input_bit_all_four_states=True,
                formal_log_sha256=digest(formal_log),four_state_log_sha256=digest(simulation))
            results.append(result);print(json.dumps(result),flush=True)
    assert all(digest(p)==expected for p,expected in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,results=results),indent=2)+'\n')


if __name__=='__main__':
    main()
