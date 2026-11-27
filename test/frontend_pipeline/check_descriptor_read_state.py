#!/usr/bin/env python3
"""检查请求寄存后的重复读取取消、准备项归属和单拍范围。"""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/conv_descriptor_read_state.sv'
    reference = HERE/'descriptor_read_state_reference.sv'
    header = source.read_text().split(');', 1)[0]
    ports = re.findall(r'\b(input|output)(?: wire)? logic\s+((?:\[[^\]]+\])*)\s*(\w+)\s*(?:,|//)', header)
    inputs = [(w,n) for d,w,n in ports if d=='input' and n!='i_request_tag']
    outputs = [(w,n) for d,w,n in ports if d=='output']
    assert len(inputs)==20 and len(outputs)==6, ports
    params='parameter int p_word_shift=3,p_lanes=8,p_narrow_lanes=4,parameter bit p_enabled=1'
    pc='.p_word_shift(p_word_shift),.p_lanes(p_lanes),.p_narrow_lanes(p_narrow_lanes),.p_enabled(p_enabled)'
    model='module comparison #('+params+') (\n'+',\n'.join('input logic '+w+' '+n for w,n in inputs)+',\noutput logic o_equivalent);\n'
    model+='\n'.join('logic '+w+' '+prefix+n+';' for prefix in ['actual_','reference_'] for w,n in outputs)+'\n'
    model+='logic [31:p_word_shift] request_tag_q;\nalways_ff @(posedge i_clk) if(i_request_write) request_tag_q<=i_incoming_address[31:p_word_shift];\n'
    for module,prefix in [('conv_descriptor_read_state','actual_'),('reference_descriptor_read_state','reference_')]:
        connections=['.'+n+'('+n+')' for _,n in inputs]+['.i_request_tag(request_tag_q)']+['.'+n+'('+prefix+n+')' for _,n in outputs]
        model+=module+' #('+pc+') u_'+prefix[:-1]+'('+','.join(connections)+');\n'
    model+='assign o_equivalent=((u_actual.compare_valid_q && u_actual.tag_equal)===u_reference.cancel_q)&&'+'&&'.join('(actual_'+n+'===reference_'+n+')' for _,n in outputs)+';\nendmodule\n'
    m=out/'comparison.sv';m.write_text(model)
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources=resolver['with_dependencies']([source,reference,m],ROOT)
    hashes={str(p.relative_to(ROOT)):digest(p) for p in resolver['input_files'](sources,ROOT) if p.is_relative_to(ROOT)}
    formal=[]
    cases=[(shift,lanes,narrow,1) for shift in [2,3,4] for lanes in [8,16] for narrow in [4,8]]+[(shift,8,4,0) for shift in [2,3,4]]
    for shift,lanes,narrow,enabled in cases:
        name=f'word{1<<shift}_lanes{lanes}_narrow{narrow}_enabled{enabled}';script=out/(name+'.ys');log=out/(name+'.log')
        script.write_text(shlex.join(['read_slang','--top','comparison','-DSYNTHESIS=1',f'-Gp_word_shift={shift}',f'-Gp_lanes={lanes}',f'-Gp_narrow_lanes={narrow}',f'-Gp_enabled={enabled}',*map(str,sources)])+'\nprep -top comparison -flatten\nasync2sync\ndffunmap\nsat -verify -seq 2 -tempinduct -maxsteps 8 -set-init-zero -prove o_equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
        if 'SUCCESS!' not in log.read_text():raise RuntimeError('描述符读取状态归纳检查未完成')
        formal.append({'word_bytes':1<<shift,'lanes':lanes,'narrow_lanes':narrow,'enabled':enabled,'passed':True,'log_sha256':digest(log)})
        print('DESCRIPTOR_READ_STATE_FORMAL_PASS '+name,flush=True)
    data_inputs=[(w,n) for w,n in inputs if n not in ['i_clk','i_rst_n']]
    names=','.join(n for _,n in data_inputs)
    widths=coverage.expanded_widths(out,'localparam int p_word_shift=3;',
        '\n'.join('logic '+w+' '+n+';' for w,n in data_inputs),[n for _,n in data_inputs])
    input_width=sum(widths.values())
    offsets={};offset=0
    for width,name in reversed(data_inputs):
        bits=1 if not width else int(re.fullmatch(r'\[(\d+):0\]',width).group(1))+1
        offsets[name]=(offset,bits);offset+=bits
    directed=[]
    for name in ['i_accept','i_commit','i_read_fire','i_prepared_valid','i_request_write','i_request_pending','i_one_row','i_fast','i_group_fits']:
        first,bits=offsets[name];directed.append(f"stimulus[{first}+: {bits}]=1;")
    first,bits=offsets['i_columns'];directed.append(f"stimulus[{first}+: {bits}]=32'd1;")
    first,bits=offsets['i_incoming_address'];directed.append(f"stimulus[{first}+: {bits}]=(sample%16==15 ? 32'h108:32'h100);")
    for name in ['i_accept','i_commit','i_request_write']:
        first,bits=offsets[name];directed.append(f"if(sample%16==14)stimulus[{first}+: {bits}]=0;")
    connections=','.join('.'+n+'('+('clk' if n=='i_clk' else 'rst_n' if n=='i_rst_n' else n)+')' for _,n in inputs)
    tb='''module tb;
localparam int p_word_shift=3;
logic clk=0,rst_n=0,equivalent;
'''+ '\n'.join('logic '+w+' '+n+';' for w,n in data_inputs)+'''
localparam int p_input_width='''+str(input_width)+''';
logic [p_input_width-1:0] stimulus;
assign {'''+names+'''}=stimulus;
comparison u_compare('''+connections+''',.o_equivalent(equivalent));
integer rng=32'h41986523;
integer cancellation_count=0;
integer accepted_writes=0,held_writes=0,request_writes=0,request_holds=0,accept_commit=0;
function automatic integer random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
initial begin
  stimulus='0;#1;clk=1;#1;clk=0;rst_n=1;
  stimulus='1;#1;clk=1;#1;clk=0;
  for(integer sample=0;sample<16384;sample++)begin
    for(integer bit_index=0;bit_index<p_input_width;bit_index++)stimulus[bit_index]=1'(random_word());
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5,6,7:stimulus[sample%p_input_width]=1'bx;
      8,9,10,11:stimulus[sample%p_input_width]=1'bz;
      12,13,14,15:begin stimulus='0;'''+''.join(directed)+'''end
      default:begin end
    endcase
    rst_n=(sample%101)!=100;
    #1;
    if(i_accept===1'b1)accepted_writes++;else held_writes++;
    if(i_request_write===1'b1)request_writes++;else request_holds++;
    if(i_accept===1'b1 && i_commit===1'b1)accept_commit++;
    clk=1;#1;
    if(equivalent!==1'b1)$fatal(1,"descriptor read state mismatch sample=%0d",sample);
    if(u_compare.actual_o_request_cancel===1'b1)cancellation_count=cancellation_count+1;
    clk=0;
  end
  if(accepted_writes==0 || held_writes==0 || request_writes==0 || request_holds==0 || accept_commit==0)
    $fatal(1,"descriptor write and hold coverage is incomplete");
  $display("READ_STATE_EVENTS accepted_writes=%0d held_writes=%0d request_writes=%0d request_holds=%0d accept_commit=%0d",
      accepted_writes,held_writes,request_writes,request_holds,accept_commit);
  if(cancellation_count==0)$fatal(1,"descriptor cancellation coverage is empty");
  $display("DESCRIPTOR_READ_STATE_FOUR_STATE_PASS comparisons=16384 cancellations=%0d",cancellation_count);$finish;
end
endmodule
'''
    tb=tb.replace('initial begin',coverage.declarations('p_input_width')+'initial begin'+coverage.initialize('p_input_width',names),1)
    tb=tb.replace('    rst_n=(sample%101)!=100;',coverage.sample('p_input_width')+'    rst_n=(sample%101)!=100;',1)
    tb=tb.replace('  if(cancellation_count==0)',coverage.finish('p_input_width')+'  if(cancellation_count==0)',1)
    bench=out/'tb.sv';bench.write_text(tb);four=[]
    for profile,defs in [('generic',[]),('synthesis',['-DSYNTHESIS=1'])]:
        log=out/(profile+'.log');binary=out/(profile+'.vvp')
        with log.open('w') as stream:
            subprocess.run(['iverilog','-g2012',*defs,'-s','tb','-o',str(binary),*map(str,sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
            subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
        if 'DESCRIPTOR_READ_STATE_FOUR_STATE_PASS' not in log.read_text():raise RuntimeError('描述符读取状态四态检查未完成')
        four.append({'profile':profile,'comparisons':16384,'passed':True,'coverage':coverage.result(log,widths),
            'cancellations':int(re.search(r'cancellations=(\d+)',log.read_text()).group(1)),
            'update_events':{key:int(value) for key,value in re.findall(r'(accepted_writes|held_writes|request_writes|request_holds|accept_commit)=(\d+)',log.read_text())},
            'log_sha256':digest(log)})
        print('DESCRIPTOR_READ_STATE_FOUR_STATE_PASS '+profile,flush=True)
    if any(digest(ROOT/n)!=value for n,value in hashes.items()):raise RuntimeError('检查期间源码发生变化')
    result={'passed':True,'initial_state':'zero initialized comparison registers; unrestricted input values and update events','formal':formal,'four_state':four,'source_sha256':hashes}
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('DESCRIPTOR_READ_STATE_PASS formal=15 four_state=32768',flush=True)


if __name__=='__main__':
    main()
