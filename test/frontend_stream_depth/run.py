#!/usr/bin/env python3
"""验证流式字地址递增的完整结果，并比较实际 RTL 的资源和组合级数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
STREAM = Path('rtl/npu/conv/conv_im2col_stream.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def address_module(name, text):
    start = text.index("  assign stream_request_addr[p_word_shift-1:0] = '0;")
    end = text.index('  if (p_tile_count_w >= p_chunk_count_w)', start)
    return f'''module {name} #(parameter int p_word_shift=3)(
input logic [31:0] o_addr, output logic [31:0] stream_request_addr);
logic unused_stream_request_carry;
logic [31-p_word_shift:0] request_increment_i_value,request_increment_o_result;
logic request_increment_i_enable;
logic [31-p_word_shift:0] request_increment_reference;
logic [31-p_word_shift:0] request_increment_selected;
logic request_increment_reference_carry;
{text[start:end]}
endmodule
'''


def registered_address(name):
    return f'''module {name}_registered(input logic clk,input logic [31:0] i_address,
output logic [31:0] o_address);
logic [31:0] address_q,address_next;
always_ff @(posedge clk) begin address_q<=i_address;o_address<=address_next;end
{name} u_address(.o_addr(address_q),.stream_request_addr(address_next));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='9e3e5d6a6f47befe6c86aceacad7999923206458')
    parser.add_argument('--map', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = {path:(ROOT/path).read_text() for path in (STREAM,)}
    original = {path:subprocess.check_output(['git','show',f'{args.reference_ref}:{path}'],
                                            cwd=ROOT,text=True) for path in (STREAM,)}
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    common = dependencies([ROOT/'rtl/common/conditional_increment.sv',
                           ROOT/'rtl/common/parallel_prefix_add.sv'], ROOT)
    common = list(dict.fromkeys(common))
    units = {}
    for label,texts in (('reference',original),('candidate',current)):
        address = 'stream_address_'+label
        path = out/(label+'.sv')
        path.write_text(address_module(address,texts[STREAM])+registered_address(address))
        units[label]=path
    model = out/'address_comparison.sv'
    model.write_text('''module address_comparison #(parameter int SHIFT=3)(
input logic [31:0] address,output logic equivalent);
logic [31:0] expected,actual;
stream_address_reference #(.p_word_shift(SHIFT)) u_reference(address,expected);
stream_address_candidate #(.p_word_shift(SHIFT)) u_candidate(address,actual);
assign equivalent=expected===actual;
endmodule
module tb;
logic [31:0] address,saved;wire [3:0] equivalent;integer checks=0;
for(genvar k=0;k<4;k++)begin:g_profile
 address_comparison #(.SHIFT(k+2)) u_compare(address,equivalent[k]);
end
task automatic check;
 #1;if(equivalent!==4'b1111)$fatal(1,"Address result differs address=%b",address);
 checks++;
endtask
initial begin
 address='0;check();address='1;check();
 for(integer trial=0;trial<256;trial++)begin
  address=$urandom;saved=address;check();
  for(integer bit_index=0;bit_index<32;bit_index++)begin
   address=saved;address[bit_index]=1'bx;check();
   address=saved;address[bit_index]=1'bz;check();
  end
 end
 address='x;check();address='z;check();
 $display("ADDRESS_PASS checks=%0d profiles=4",checks);$finish;
end
endmodule
''')
    sources=[*common,*units.values(),model]
    proofs=[]
    for shift in (2,3,4,5):
        script,log=out/f'shift{shift}.ys',out/f'shift{shift}.log'
        script.write_text(f'read_slang --top address_comparison -DSYNTHESIS=1 -GSHIFT={shift} '+
            shlex.join(map(str,sources))+'\nsetattr -mod -unset keep_hierarchy\n'+
            'setattr -unset keep_hierarchy\nprep -top address_comparison -flatten\n'+
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('地址递增形式检查未完成')
        proofs.append({'word_shift':shift,'passed':True,'log_sha256':digest(log)})
    run(['iverilog','-g2012','-s','tb','-o',out/'test.vvp',*sources],out/'compile.log')
    run(['vvp',out/'test.vvp'],out/'four_state.log')
    assert 'ADDRESS_PASS checks=16644 profiles=4' in (out/'four_state.log').read_text()
    result={'passed':True,'input_assumptions':[], 'reference_commit':args.reference_ref,
            'formal_profiles':proofs,'four_state_cases_per_profile':16644,
            'source_sha256':{str(p):digest(ROOT/p) for p in current}}
    if args.map:
        cases={}
        for label,path in units.items():
            for kind in ('address',):
                name=f'{kind}_{label}'
                cases[name]={'top':f'stream_{kind}_{label}_registered',
                    'configuration':'Registered full input and output, unchanged pipeline latency',
                    'options':['-D','SYNTHESIS=1','-D','XILINX_FPGA=1'],
                    'sources':list(map(str,[*common,path]))}
        config=out/'cases.json';config.write_text(json.dumps(cases,indent=2)+'\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--case-config',config,
             '--cases',*cases,'--out',out/'pre','--through','pre_lut'],out/'synthesis.log')
        result['mapping']={}
        for name in cases:
            destination=out/'mapped'/name
            run([sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py',
                 '--source',out/'pre'/name,'--out',destination,'--mode','physical-cost',
                 '--delay-target-ps','6667','--wire-delay-ps','300','--max-lut-inputs','8',
                 '--small-lut-area-cost','1','--discard-abc9-temporaries'],out/(name+'_mapping.log'))
            metrics=json.loads((destination/'metrics.json').read_text())
            assert metrics['paths']['graph_complete']
            result['mapping'][name]={'resources':metrics['resources'],
                'longest_combinational_cells':metrics['paths']['longest_register_path_cells'],
                'metrics_sha256':digest(destination/'metrics.json')}
    for path,text in current.items():
        assert (ROOT/path).read_text()==text, f'检查期间源码发生变化：{path}'
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
