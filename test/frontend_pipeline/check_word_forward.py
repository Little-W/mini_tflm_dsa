#!/usr/bin/env python3
"""验证七组地址候选与保存字转发接口的逐项结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REFERENCE_SHA256 = 'cc1be5debbf705ca097d4926916f743ae374bb5588355cdd42903e5de1bef753'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/conv_descriptor_addresses.sv'
    reference = HERE/'word_forward_reference.sv'
    if digest(reference) != REFERENCE_SHA256:
        raise RuntimeError('完整标签计算参考模型与记录不同')
    header = source.read_text().split(');', 1)[0]
    ports = re.findall(r'\b(input|output) logic\s+((?:\[[^\]]+\])*)\s*(\w+)\s*(?:,|//)', header)
    inputs = [(width, name) for direction, width, name in ports if direction == 'input']
    outputs = [(width, name) for direction, width, name in ports
               if direction == 'output' and name != 'o_word_candidates']
    assert len(inputs) == 22 and len(outputs) == 5, ports
    params = 'parameter int p_word_shift=3, parameter bit p_register_descriptor=1,p_preview_registered=1, parameter integer p_forced_forward=-1'
    parameter_connections = '.p_word_shift(p_word_shift),.p_register_descriptor(p_register_descriptor),.p_preview_registered(p_preview_registered)'
    model = 'module comparison #('+params+') (\n'+',\n'.join('input logic '+w+' '+n for w,n in inputs)+',\noutput logic o_equivalent);\n'
    model += '\n'.join('logic '+w+' '+prefix+n+';' for prefix in ['actual_','reference_'] for w,n in outputs)+'\n'
    model += "logic effective_forward;\nassign effective_forward=p_forced_forward<0 ? i_word_forward : 1'(p_forced_forward);\nlogic [31:0] reference_word_address;\nassign reference_word_address=effective_forward ? {i_addr[31:p_word_shift],{p_word_shift{1'b0}}}:i_word_addr;\n"
    for module, prefix in [('conv_descriptor_addresses','actual_'),('reference_word_addresses','reference_')]:
        connections = ['.'+n+'('+('reference_word_address' if module.startswith('reference') and n=='i_word_addr' else 'effective_forward' if n=='i_word_forward' else n)+')' for _,n in inputs if not (module.startswith('reference') and n=='i_word_forward')]
        connections += ['.'+n+'('+prefix+n+')' for _,n in outputs]
        model += module+' #('+parameter_connections+') u_'+prefix[:-1]+'('+','.join(connections)+');\n'
    model += 'assign o_equivalent='+' && '.join('(actual_'+n+'===reference_'+n+')' for _,n in outputs)+';\nendmodule\n'
    modelpath=out/'comparison.sv';modelpath.write_text(model)
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources=resolver['with_dependencies']([source,reference,modelpath],ROOT)
    hashes={str(p.relative_to(ROOT)):digest(p) for p in resolver['input_files'](sources,ROOT) if p.is_relative_to(ROOT)}
    formal=[]
    for shift in [2,3,4]:
        for register, preview in [(0,0),(1,0),(1,1)]:
            for forward in [0,1]:
                name=f'word{1<<shift}_registered{register}_preview{preview}_forward{forward}'
                script=out/(name+'.ys');log=out/(name+'.log')
                script.write_text(shlex.join(['read_slang','--top','comparison','-DSYNTHESIS=1',f'-Gp_word_shift={shift}',f'-Gp_register_descriptor={register}',f'-Gp_preview_registered={preview}',f'-Gp_forced_forward={forward}',*map(str,sources)])+'\nprep -top comparison -flatten\nsat -verify -prove o_equivalent 1\n')
                with log.open('w') as stream:
                    subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
                if 'SUCCESS!' not in log.read_text():raise RuntimeError('标签转发形式证明未完成')
                formal.append({'word_bytes':1<<shift,'register_descriptor':register,'preview_registered':preview,'forwarded':forward,'passed':True,'log_sha256':digest(log)})
                print('WORD_FORWARD_FORMAL_PASS '+name,flush=True)
    names=','.join(n for _,n in inputs)
    widths=coverage.expanded_widths(out,'localparam int p_word_shift=3;',
        '\n'.join('logic '+w+' '+n+';' for w,n in inputs),[n for _,n in inputs])
    input_width=sum(widths.values())
    tb='''module tb;
parameter integer p_word_shift=3;
logic equivalent;
'''+ '\n'.join('logic '+w+' '+n+';' for w,n in inputs)+'''
localparam integer p_input_width='''+str(input_width)+''';
logic [p_input_width-1:0] stimulus;
assign {'''+names+'''}=stimulus;
comparison #(.p_word_shift(p_word_shift)) u_compare('''+','.join('.'+n+'('+n+')' for _,n in inputs)+''',.o_equivalent(equivalent));
integer rng=32'h68149237;
function automatic integer random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
initial begin
  for(integer sample=0;sample<8192;sample++)begin
    for(integer bit_index=0;bit_index<p_input_width;bit_index++)stimulus[bit_index]=1'(random_word());
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5,6,7:stimulus[sample%p_input_width]=1'bx;
      8,9,10,11:stimulus[sample%p_input_width]=1'bz;
      default:begin end
    endcase
    #1;
    if(equivalent!==1'b1)$fatal(1,"word forward mismatch sample=%0d",sample);
  end
  $display("WORD_FORWARD_FOUR_STATE_PASS samples=8192");$finish;
end
endmodule
'''
    tb=tb.replace('initial begin',coverage.declarations('p_input_width')+'initial begin'+coverage.initialize('p_input_width',names),1)
    tb=tb.replace('    #1;',coverage.sample('p_input_width')+'    #1;',1)
    tb=tb.replace('  $display("WORD_FORWARD_FOUR_STATE_PASS',coverage.finish('p_input_width')+'  $display("WORD_FORWARD_FOUR_STATE_PASS',1)
    bench=out/'tb.sv';bench.write_text(tb)
    four=[]
    for shift in [2,3,4]:
        binary=out/f'four_state{shift}.vvp';log=out/f'four_state{shift}.log'
        with log.open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb',f'-Ptb.p_word_shift={shift}','-o',str(binary),*map(str,sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
            subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=900)
        if 'WORD_FORWARD_FOUR_STATE_PASS' not in log.read_text():raise RuntimeError('标签转发四态验证未完成')
        four.append({'word_bytes':1<<shift,'comparisons':8192,'passed':True,'coverage':coverage.result(log,widths),'log_sha256':digest(log)})
        print('WORD_FORWARD_FOUR_STATE_PASS '+str(1<<shift),flush=True)
    if any(digest(ROOT/n)!=value for n,value in hashes.items()):raise RuntimeError('检查过程中源码发生变化')
    result={'passed':True,'formal':formal,'four_state':four,'source_sha256':hashes}
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('WORD_FORWARD_PASS formal=18 four_state=24576',flush=True)


if __name__=='__main__':
    main()
