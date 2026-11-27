#!/usr/bin/env python3
"""验证完整请求上下文拆分的位向量等价和四态传播。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys
import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REFERENCE = 'f292e57fcf08d4562f06e879a8e198cd3c408736'
SOURCE = ROOT/'rtl/npu/conv/conv_im2col_request_context.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fields = json.loads((HERE/'request_context_fields.json').read_text())
    reference = HERE/'request_context_reference.sv'
    if digest(reference) != fields['reference_sha256']:
        raise RuntimeError('请求上下文参考内容与记录不同')
    inputs = [row for row in fields['ports'] if row[0] == 'input']
    outputs = [row for row in fields['ports'] if row[0] == 'output']
    parameters = [('p_coord_width', '35'), ('p_line_bytes', '128'), ('p_register_descriptor', "1'b1")]
    model_header = 'module context_comparison #(\n'+',\n'.join(
        'parameter '+('bit' if name=='p_register_descriptor' else 'int')+' '+name+'='+value
        for name,value in parameters)+') (\n'
    model_header += ',\n'.join('input wire '+row[1]+' '+row[2] for row in inputs)
    model_header += ',\noutput logic o_equivalent\n);\n'
    declarations = '\n'.join(row[1]+' '+prefix+row[2]+';' for prefix in ('actual_', 'reference_') for row in outputs)
    parameter_connections = ','.join('.'+name+'('+name+')' for name,_ in parameters)
    connections = ','.join('.'+row[2]+'('+row[2]+')' for row in inputs)
    model = out/'comparison.sv'
    model.write_text(model_header+declarations+'\n'+
        '\n'.join(module+' #('+parameter_connections+') u_'+prefix+'('+connections+','+
                   ','.join('.'+row[2]+'('+prefix+'_'+row[2]+')' for row in outputs)+');'
                   for module,prefix in [('conv_im2col_request_context','actual'),('reference_context','reference')])+
        '\nassign o_equivalent='+ '&&'.join('(actual_'+row[2]+'===reference_'+row[2]+')' for row in outputs)+
        ';\nendmodule\n')
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([SOURCE, reference, model], ROOT)
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in resolver['input_files'](sources,ROOT) if p.is_relative_to(ROOT)}
    formal = []
    for width in (33,35,40):
        for line in (16,128):
            for register in (0,1):
                name=f'coord{width}_line{line}_register{register}'
                script, log = out/(name+'.ys'), out/(name+'.log')
                script.write_text(shlex.join(['read_slang','--top','context_comparison','-DSYNTHESIS=1',
                    f'-Gp_coord_width={width}',f'-Gp_line_bytes={line}',f'-Gp_register_descriptor={register}',
                    *map(str,sources)])+'\nprep -top context_comparison -flatten\nsat -verify -prove o_equivalent 1\n')
                with log.open('w') as stream:
                    subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                                   stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
                if 'SUCCESS!' not in log.read_text(): raise RuntimeError('请求上下文形式证明未完成')
                formal.append(dict(coordinate_width=width,line_bytes=line,register_descriptor=register,
                                   passed=True,log_sha256=digest(log)))
                print('REQUEST_CONTEXT_FORMAL_PASS '+name,flush=True)
    bench = out/'tb.sv'
    input_names = ','.join(row[2] for row in inputs)
    widths=coverage.expanded_widths(out,
        "localparam int p_coord_width=35,p_line_bytes=128; localparam bit p_register_descriptor=1'b1;",
        '\n'.join(row[1]+' '+row[2]+';' for row in inputs),[row[2] for row in inputs],
        [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv'])
    input_width=sum(widths.values())
    tb = '''module tb;
localparam int p_coord_width=35,p_line_bytes=128;
localparam bit p_register_descriptor=1'b1;
'''+ '\n'.join(row[1]+' '+row[2]+';' for row in inputs)+'''
logic equivalent;
localparam int p_input_width='''+str(input_width)+''';
logic [p_input_width-1:0] stimulus;
assign {'''+input_names+'''}=stimulus;
context_comparison u_compare('''+connections+''',.o_equivalent(equivalent));
integer rng=32'h38264917;
function automatic integer random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
initial begin
  for(integer sample=0;sample<8192;sample++)begin
    for(integer bit_index=0;bit_index<p_input_width;bit_index+=32)
      stimulus[bit_index+:32]=random_word();
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
    if(equivalent!==1'b1)$fatal(1,"request context four-state mismatch sample=%0d",sample);
  end
  $display("REQUEST_CONTEXT_FOUR_STATE_PASS samples=8192");$finish;
end
endmodule
'''
    tb=tb.replace('initial begin',coverage.declarations('p_input_width')+'initial begin'+coverage.initialize('p_input_width',input_names),1)
    tb=tb.replace('    #1;',coverage.sample('p_input_width')+'    #1;',1)
    tb=tb.replace('  $display("REQUEST_CONTEXT_FOUR_STATE_PASS',coverage.finish('p_input_width')+'  $display("REQUEST_CONTEXT_FOUR_STATE_PASS',1)
    bench.write_text(tb)
    binary=out/'four_state.vvp';log=out/'four_state.log'
    with log.open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),*map(str,sources),str(bench)],
                       stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=3600)
    if 'REQUEST_CONTEXT_FOUR_STATE_PASS' not in log.read_text():raise RuntimeError('四态请求上下文检查未完成')
    if any(digest(ROOT/name)!=value for name,value in hashes.items()):raise RuntimeError('验证过程中源码发生变化')
    result=dict(passed=True,reference_commit=REFERENCE,formal=formal,four_state_samples=8192,
                four_state_log_sha256=digest(log),four_state_coverage=coverage.result(log,widths),source_sha256=hashes)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('REQUEST_CONTEXT_PASS formal=12 four_state=8192',flush=True)


if __name__=='__main__':
    main()
