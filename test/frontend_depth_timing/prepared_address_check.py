#!/usr/bin/env python3
"""证明准备阶段的独热地址选择与实际地址分支逐位一致。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')
FLAGS = ('incoming_next_position_fast incoming_position_same_tap incoming_position_previous_row '
         'incoming_position_forward_tap incoming_position_backward_tap incoming_next_tile_fast '
         'incoming_skip_tap incoming_q_equal incoming_tap_wrap').split()
ADDRESSES = ('row_base_addr row_group_base next_row_addr next_row_group_base '
             'window_next_addr window_next_group_base').split()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def unit(source):
    spec = importlib.util.spec_from_file_location('range_write', Path(__file__).with_name('range_write_check.py'))
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    begin = source.index('  always_comb begin\n    incoming_tap=tap0;')
    end = source.index('  // 每个字节并行判断地址进位', begin)
    original = source[source.index('begin', begin):end]
    references=[]
    for target in ('incoming_addr', 'incoming_group_base'):
        renamed = re.sub(r'\b'+target+r'\s*=\s*([^;]+);',r'group_range_q <= \1;',original)
        body,_=parser.RangeStatements(renamed).statement(0)
        references.append('always_comb '+body.replace('result', 'expected_'+target)+'\n')
    begin = source.index('  always_comb begin\n    prepared_padding_select')
    end = source.index('  for (genvar target = 0; target < 2; target++) begin : g_prepared_word_target',begin)
    actual=source[begin:end]
    for target, index in (('address',0),('group_address',1)):
        if f'preparing_tile.{target} = REGISTER_DESCRIPTOR ? prepared_address[{index}] : ' not in source:
            raise RuntimeError('准备地址的实际连接与证明入口不符')
    ports=[*('input logic '+name for name in FLAGS), 'input logic[31:0] kx0_q',
           *('input logic[31:0] '+name for name in ADDRESSES),
           'input logic[6:0][1:0][31:0] incoming_address_sum','output logic equivalent']
    return ('module comparison(\n'+',\n'.join(ports)+');\n'
        'logic[8:0] prepared_padding_select;\nlogic[9:0] prepared_word_select;\n'
        'logic[9:0][1:0][31:0] prepared_address_candidate;\nlogic[1:0][31:0] prepared_address;\n'
        'logic[31:0] expected_incoming_addr,expected_incoming_group_base;\n'+actual+
        ''.join(references)+
        'assign equivalent=prepared_address=={expected_incoming_group_base,expected_incoming_addr};\nendmodule\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,default=ROOT)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=args.source_root.resolve()/SOURCE
    test=out/'comparison.sv';test.write_text(unit(source.read_text()))
    script=out/'proof.ys';log=out/'proof.log'
    script.write_text('read_slang --top comparison '+shlex.quote(str(test))+
        '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                       stdout=stream,stderr=subprocess.STDOUT,check=True)
    bench=out/'fourstate.sv'
    declarations='\n'.join('logic '+n+';' for n in FLAGS)+'\nlogic[31:0] kx0_q;\n'
    declarations+='\n'.join('logic[31:0] '+n+';' for n in ADDRESSES)
    declarations+='\nlogic[6:0][1:0][31:0] incoming_address_sum; logic equivalent;\n'
    stimulus='\n'.join(n+'=bits4();' for n in FLAGS)
    stimulus+='\n'+ '\n'.join(n+'=word4();' for n in ['kx0_q',*ADDRESSES])
    stimulus+='\n'+'\n'.join(f'incoming_address_sum[{i}][{j}]=word4();' for i in range(7) for j in range(2))
    bench.write_text('module tb;\n'+declarations+'\ncomparison dut(.*);\n'+r'''
function automatic logic bits4();
 case($urandom_range(0,3))
  0:bits4=0;
  1:bits4=1;
  2:bits4=1'bx;
  3:bits4=1'bz;
 endcase
endfunction
function automatic logic[31:0] word4();
 logic[31:0] value;
 value=$urandom;
 for(integer k=0;k<32;k=k+1) if($urandom_range(0,31)==0) value[k]=bits4();
 return value;
endfunction
initial begin
 for(integer trial=0;trial<8192;trial=trial+1) begin
'''+stimulus+r'''
  #1;
  if(dut.prepared_address !== {dut.expected_incoming_group_base,dut.expected_incoming_addr})
   $fatal(1,"prepared address selection mismatch");
 end
 $display("PREPARED_ADDRESS_FOURSTATE_PASS checks=8192");
 $finish;
end
endmodule
''')
    sim=out/'simulation'
    subprocess.run(['iverilog','-g2012','-s','tb','-o',str(sim),str(test),str(bench)],check=True,
                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    fourstate=out/'fourstate.log'
    with fourstate.open('w') as stream:
        subprocess.run(['vvp',str(sim)],stdout=stream,stderr=subprocess.STDOUT,check=True)
    report={'passed':True,'input_assumptions':[], 'source_sha256':{str(source):digest(source)},
            'formal_outputs':64,'fourstate_checks':8192,'proof_source_sha256':digest(test),
            'proof_log_sha256':digest(log),'fourstate_log_sha256':digest(fourstate)}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PREPARED_ADDRESS_SELECTION_PASS',out,flush=True)
if __name__=='__main__':main()
