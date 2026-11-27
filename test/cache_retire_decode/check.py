#!/usr/bin/env python3
"""证明完整释放描述的并行解码，并检查移位和来源选择的四态行为。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    sources = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies'](
        [ROOT/'rtl/npu/dma/cache/conv_cache_retire_decode.sv'], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    instances = '''
  logic [31:0] selected;
  wire [31:0] actual;
  logic [31:0] expected;
  always_comb begin
    selected = stimulus[31:0];
    if (stimulus[64]) selected = stimulus[63:32];
    expected = selected[22] ? 32'hffff_ffff : ({14'd0,selected[17:0]} >> selected[21:18]);
  end
  conv_cache_retire_decode dut(.i_use_incoming(stimulus[64]),
      .i_incoming(stimulus[63:32]), .i_saved(stimulus[31:0]), .o_retire(actual));
'''
    records = []
    for mode, definitions in (
        ('generic', '`undef SYNTHESIS\n`undef XILINX_FPGA\n'),
        ('fpga', '`define SYNTHESIS 1\n`define XILINX_FPGA 1\n'),
    ):
        prefix = definitions+''.join(f'`include "{path}"\n' for path in sources)
        formal = out/(mode+'_formal.sv')
        formal.write_text(prefix+'module proof(input logic [64:0] stimulus);\n'+instances+
            '  always_comb assert(actual == expected);\nendmodule\n')
        script = out/(mode+'.ys')
        script.write_text(f'read_slang --top proof {formal}\n'
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top proof -flatten\nchformal -lower\n'
            'sat -verify -prove-asserts -show-inputs\n')
        log = out/(mode+'_formal.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        assert 'SUCCESS' in log.read_text()
        bench = out/(mode+'_tb.sv')
        bench.write_text(prefix+'''
module tb;
  logic [64:0] stimulus;
  integer checks = 0;
  integer known_results = 0;
  integer unknown_results = 0;
  logic [31:0] random_state = 32'h7821b35d;
  integer coverage [65][4];
'''+instances+'''
  function automatic logic value4(input integer code);
    case(code & 3)
      0: value4=1'b0;
      1: value4=1'b1;
      2: value4=1'bx;
      3: value4=1'bz;
    endcase
  endfunction
  task automatic check_result;
    integer state_index;
    #1;
    if (actual !== expected)
      $fatal(1,"RETIRE_DECODE_MISMATCH stimulus=%h actual=%h expected=%h",stimulus,actual,expected);
    checks++;
    if ((^actual) === 1'bx) unknown_results++;
    else known_results++;
    for(integer bit_index=0;bit_index<65;bit_index++) begin
      case(stimulus[bit_index])
        1'b0: state_index=0;
        1'b1: state_index=1;
        1'bx: state_index=2;
        default: state_index=3;
      endcase
      coverage[bit_index][state_index]++;
    end
  endtask
  initial begin
    if ($bits(stimulus)!=65 || $bits(actual)!=32) $fatal(1,"RETIRE_DECODE_WIDTH");
    for(integer bit_index=0;bit_index<65;bit_index++)
      for(integer value=0;value<4;value++) coverage[bit_index][value]=0;
    for(integer pattern=0;pattern<4;pattern++)
      for(integer bit_index=0;bit_index<65;bit_index++)
        for(integer value=0;value<4;value++) begin
          stimulus=pattern[0] ? '1 : '0;
          stimulus[64]=pattern[1];
          stimulus[bit_index]=value4(value);
          check_result();
        end
    for(integer shifts=0;shifts<65536;shifts++)
      for(integer source=0;source<4;source++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus={source[0],random_state,~random_state};
        stimulus[64]=value4(source);
        for(integer bit_index=0;bit_index<4;bit_index++) begin
          stimulus[18+bit_index]=value4(shifts>>(2*bit_index));
          stimulus[50+bit_index]=value4(shifts>>(8+2*bit_index));
        end
        stimulus[22]=value4(shifts>>2);
        stimulus[54]=value4(shifts>>4);
        check_result();
      end
    for(integer shifts=0;shifts<256;shifts++)
      for(integer control=0;control<64;control++) begin
        stimulus={1'b0,32'h0003ffff,32'h00015555};
        stimulus[64]=value4(control);
        stimulus[22]=value4(control>>2);
        stimulus[54]=value4(control>>4);
        stimulus[21:18]=shifts[3:0];
        stimulus[53:50]=shifts[7:4];
        check_result();
      end
    for(integer bit_index=0;bit_index<65;bit_index++)
      for(integer value=0;value<4;value++)
        if(coverage[bit_index][value]==0) $fatal(1,"RETIRE_DECODE_COVERAGE bit=%0d value=%0d",bit_index,value);
    if(!known_results || !unknown_results) $fatal(1,"RETIRE_DECODE_RESULT_COVERAGE");
    $display("RETIRE_DECODE_PASS checks=%0d known=%0d unknown=%0d covered_bits=65",checks,known_results,unknown_results);
    $finish;
  end
endmodule
''')
        executable = out/(mode+'.vvp')
        result = subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb','-o',executable,bench],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=120)
        (out/(mode+'_build.log')).write_text(result.stdout)
        result = subprocess.run([shutil.which('vvp') or 'vvp',executable],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=180)
        simulation = out/(mode+'_four_state.log'); simulation.write_text(result.stdout)
        match = re.search(r'RETIRE_DECODE_PASS checks=(\d+) known=(\d+) unknown=(\d+) covered_bits=65',result.stdout)
        assert match
        record = dict(mode=mode,passed=True,input_bits=65,output_bits=32,input_constraints=[],
            four_state_checks=int(match[1]),known_results=int(match[2]),unknown_results=int(match[3]),
            every_input_bit_all_four_states=True,formal_log_sha256=digest(log),
            four_state_log_sha256=digest(simulation))
        records.append(record);print(json.dumps(record),flush=True)
    assert all(digest(path)==expected for path,expected in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        runner_sha256=digest(__file__),results=records),indent=2)+'\n')


if __name__ == '__main__':
    main()
