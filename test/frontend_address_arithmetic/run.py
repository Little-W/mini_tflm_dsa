#!/usr/bin/env python3
"""验证完整地址运算以及预取模块的全部公开输出和寄存器。"""
from pathlib import Path
import argparse
import json
import re
import runpy
import shlex
import sys
from common import ROOT, REFERENCE, UNIT, combinational_names, digest, execute, prepare, save, unchanged, worker

sys.path.insert(0, str(ROOT/'test'))
from four_state_inputs import coverage_declarations, coverage_tasks, parse_coverage

PROFILES = (
    dict(p_size=16, p_line_bytes=128, p_register_cache_request=1),
    dict(p_size=16, p_line_bytes=128, p_register_cache_request=0),
    dict(p_size=4, p_line_bytes=16, p_register_cache_request=1),
    dict(p_size=4, p_line_bytes=16, p_register_cache_request=0),
)


def options(mode, parameters):
    flags = ['-USYNTHESIS', '-UXILINX_FPGA'] if mode == 'generic' else ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
    return flags+[f'-G{name}={value}' for name,value in parameters.items()]


def geometry_connection(source):
    """检查正式几何模块的组基址端口使用已验证的完整输入字段。"""
    path=source/'rtl/npu/conv/conv_im2col_geometry.sv'
    match=re.search(r'conv_group_base_address\s+u_group_address\s*\((.*?)\)\s*;',path.read_text(),re.S)
    if match is None:raise RuntimeError('正式组基址实例缺失')
    actual=dict(re.findall(r'\.(\w+)\s*\(\s*([^()]*)\s*\)',match[1]))
    actual={name:value.strip() for name,value in actual.items()}
    expected=dict(i_input_base='i_c.input_base',i_channel_product='i_channel_product',
                  i_group_offset='i_c.group_offset',i_input_s16='i_c.input_s16',o_address='o_group_address_sum')
    if actual!=expected:raise RuntimeError('正式组基址连接与验证输入字段不一致')
    return dict(file=str(path.relative_to(source)),source_sha256=digest(path),ports=actual,passed=True)


def formal(out, snapshots):
    records=[]
    model=out/'arithmetic_model.sv'
    model.write_text(UNIT)
    for mode in ('generic','fpga'):
        folder=out/('arithmetic_'+mode);folder.mkdir(exist_ok=True)
        worker(['read_slang --top arithmetic_model '+shlex.join(options(mode,{})+list(map(str,[model,*snapshots['current']]))),
                'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                'prep -top arithmetic_model -flatten','sat -verify -prove equal 1'],folder,'proof')
        records.append(dict(kind='complete_arithmetic',mode=mode,passed=True,proof_sha256=digest(folder/'proof.log')))
        print('ARITHMETIC_PASS',mode,flush=True)
        for index,parameters in enumerate(PROFILES):
            folder=out/f'prefetch_{mode}_{index}';folder.mkdir(exist_ok=True)
            excluded=set();states={}
            for label in ('reference','current'):
                worker(['read_slang --top conv_im2col_prefetch '+shlex.join(options(mode,parameters)+list(map(str,snapshots[label]))),
                        'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                        'prep -top conv_im2col_prefetch -flatten','memory_map','opt -full',f'rename -top {label}',
                        'write_json '+shlex.quote(str(folder/(label+'_state.json'))),
                        'async2sync','opt -full','check -assert',
                        'write_rtlil '+shlex.quote(str(folder/(label+'.il')))],folder,label)
                module=json.loads((folder/(label+'_state.json')).read_text())['modules'][label]
                names,states[label]=combinational_names(module);excluded.update(names)
            blacklist=folder/'combinational_names.txt'
            blacklist.write_text('\n'.join(sorted(excluded))+'\n')
            result=worker(['read_rtlil '+shlex.quote(str(folder/'reference.il')),
                           'read_rtlil '+shlex.quote(str(folder/'current.il')),
                           'equiv_make -blacklist '+shlex.quote(str(blacklist))+' reference current equivalent',
                           'hierarchy -top equivalent','equiv_simple -short -seq 1','opt_clean',
                           'equiv_induct -seq 4','equiv_status -assert'],folder,'proof')
            match=re.search(r'Of those cells (\d+) are proven and (\d+) are unproven',result)
            if match is None or int(match[2]):raise RuntimeError(str(folder/'proof.log'))
            records.append(dict(kind='complete_prefetch',mode=mode,parameters=parameters,passed=True,
                equivalent_bits=int(match[1]),state_signals=states,unbounded_equivalence=True,
                proof_sha256=digest(folder/'proof.log')))
            print('PREFETCH_PASS',mode,index,match[1],flush=True)
    return records


def arithmetic_four_state(out,snapshots,mode):
    folder=out/('four_state_arithmetic_'+mode);folder.mkdir(exist_ok=True)
    model=folder/'model.sv';model.write_text(UNIT)
    width=32+32+16+1+35+17
    fields='{base,product,offset,sample_s16,coordinate,displacement}'
    text='''module tb;
logic [31:0] base,product;
logic [15:0] offset;
logic sample_s16;
logic [34:0] coordinate;
logic [16:0] displacement;
wire [130:0] actual,expected;
arithmetic_model u_model(.*,.equal());
localparam integer W=133;
integer checks=0,rng=32'h71ad923b;
logic [W-1:0] values;
'''+coverage_declarations('W')+coverage_tasks('W',fields)+'''
function automatic [31:0] random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
task automatic check;
 begin #1;observe_inputs();if(actual!==expected)$fatal(1,"Arithmetic output differs");checks++;end
endtask
initial begin
 initialize_input_coverage();
 for(integer v=0;v<4;v++)for(integer bit_index=0;bit_index<W;bit_index++)begin
  values='0;
  case(v)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  FIELDS=values;check();
 end
 for(integer cycle=0;cycle<32768;cycle++)begin
  for(integer part=0;part<(W+31)/32;part++)begin
   for(integer bit_index=part*32;bit_index<(part+1)*32&&bit_index<W;bit_index++)
    values[bit_index]=random_word()&1;
  end
  if(cycle%3==0)values[random_word()%W]=1'bx;
  if(cycle%5==0)values[random_word()%W]=1'bz;
  FIELDS=values;check();
 end
 check_input_coverage();$display("ARITHMETIC_FOUR_STATE_PASS samples=%0d comparisons=%0d",checks,checks*4);$finish;
end
endmodule
'''.replace('FIELDS',fields)
    if width!=133:raise RuntimeError('算术输入常量宽度与声明不一致')
    tb=folder/'tb.sv';tb.write_text(text)
    flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',folder/'sim',*snapshots['current'],model,tb],folder/'compile.log')
    result=execute(['vvp',folder/'sim'],folder/'run.log')
    match=re.search(r'ARITHMETIC_FOUR_STATE_PASS samples=(\d+) comparisons=(\d+)',result)
    if not match:raise RuntimeError(str(folder/'run.log'))
    return dict(mode=mode,passed=True,samples=int(match[1]),comparisons=int(match[2]),
                coverage=parse_coverage(result),log_sha256=digest(folder/'run.log'))


def prefetch_four_state(out,snapshots,mode,index):
    """使用真实展开端口宽度，全部输入逐位覆盖四态及逐周期输出比较。"""
    folder=out/f'four_state_prefetch_{mode}_{index}';folder.mkdir(exist_ok=True)
    parameters=PROFILES[index]
    module=json.loads((out/f'prefetch_{mode}_{index}'/'current_state.json').read_text())['modules']['current']
    ports=module['ports'];ins=[name for name,p in ports.items() if p['direction']=='input' and name not in ('i_clk','i_rst_n')]
    outs=[name for name,p in ports.items() if p['direction']=='output']
    width=sum(len(ports[name]['bits']) for name in ins)
    outputs=sum(len(ports[name]['bits']) for name in outs)
    source=next(path for path in snapshots['reference'] if path.name=='conv_im2col_prefetch.sv')
    renamed=folder/'reference_prefetch.sv'
    renamed.write_text(source.read_text().replace('module conv_im2col_prefetch','module reference_prefetch',1))
    declarations=['logic i_clk=0,i_rst_n=0;']
    for name in ins:declarations.append(f'logic [{len(ports[name]["bits"])-1}:0] {name};')
    for name in outs:
        for label in ('reference','current'):declarations.append(f'wire [{len(ports[name]["bits"])-1}:0] {label}_{name};')
    params=','.join(f'.{name}({value})' for name,value in parameters.items())
    for label,top in [('reference','reference_prefetch'),('current','conv_im2col_prefetch')]:
        connections=['.i_clk(i_clk)','.i_rst_n(i_rst_n)']+[f'.{name}({name})' for name in ins]+[f'.{name}({label}_{name})' for name in outs]
        declarations.append(f'{top} #({params}) u_{label}('+','.join(connections)+');')
    fields='{'+','.join(ins)+'}'
    observed='{'+','.join('current_'+name for name in outs)+'}'
    expected='{'+','.join('reference_'+name for name in outs)+'}'
    text='module tb;\n'+'\n'.join(declarations)+f'\nlocalparam integer W={width};\n'
    text+='integer rng=32\'h42b9e31d,checks=0,offers=0,phase4=0,flushes=0;logic [W-1:0] values;\n'
    text+=coverage_declarations('W')+coverage_tasks('W',fields)
    text+='''function automatic [31:0] random_word;
 rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
task automatic check;
 begin
  #1;observe_inputs();
  if(CURRENT!==EXPECTED)$fatal(1,"Prefetch outputs differ before edge cycle=%0d",checks);
  i_clk=1;#1;
  if(CURRENT!==EXPECTED)$fatal(1,"Prefetch outputs differ after edge cycle=%0d",checks);
  if(current_o_pf_valid===1'b1)offers++;
  if(current_o_prefetch_phase==4)phase4++;
  if(i_cfg_valid===1'b1 && i_cfg_ready===1'b1)flushes++;
  i_clk=0;checks++;
 end
endtask
initial begin
 initialize_input_coverage();FIELDS='0;check();i_rst_n=1;
 for(integer v=0;v<4;v++)for(integer bit_index=0;bit_index<W;bit_index++)begin
  values='0;case(v)0:values[bit_index]=0;1:values[bit_index]=1;2:values[bit_index]=1'bx;3:values[bit_index]=1'bz;endcase
  FIELDS=values;check();
 end
 for(integer cycle=0;cycle<8192;cycle++)begin
  for(integer part=0;part<(W+31)/32;part++)begin
   for(integer bit_index=part*32;bit_index<(part+1)*32&&bit_index<W;bit_index++)
    values[bit_index]=random_word()&1;
  end
  if(cycle%5==0)values[random_word()%W]=1'bx;
  if(cycle%7==0)values[random_word()%W]=1'bz;
  FIELDS=values;
  if(cycle%64<48)begin i_cfg_valid=0;i_cache_port_valid=1;i_cache_port_ready=1;end
  check();
 end
 if(phase4==0||flushes==0)$fatal(1,"Prefetch stage or configuration event was not exercised");
 check_input_coverage();$display("PREFETCH_FOUR_STATE_PASS cycles=%0d phase4=%0d offers=%0d configure=%0d",checks,phase4,offers,flushes);$finish;
end
endmodule
'''.replace('FIELDS',fields).replace('CURRENT',observed).replace('EXPECTED',expected)
    tb=folder/'tb.sv';tb.write_text(text)
    flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',folder/'sim',*snapshots['current'],renamed,tb],folder/'compile.log')
    result=execute(['vvp',folder/'sim'],folder/'run.log')
    match=re.search(r'PREFETCH_FOUR_STATE_PASS cycles=(\d+) phase4=(\d+) offers=(\d+) configure=(\d+)',result)
    if not match:raise RuntimeError(str(folder/'run.log'))
    return dict(mode=mode,parameters=parameters,passed=True,cycles=int(match[1]),
        output_bits=outputs,output_comparisons=2*int(match[1])*len(outs),
        coordinate_capture_events=int(match[2]),prefetch_offer_cycles=int(match[3]),configuration_events=int(match[4]),
        coverage=parse_coverage(result),log_sha256=digest(folder/'run.log'))


def prefetch_protocol(out,snapshots,mode,index):
    """按真实阶段分别推进核行片段和跨步窗口，并检查预取请求输出。"""
    previous=out/f'four_state_prefetch_{mode}_{index}'
    folder=out/f'protocol_prefetch_{mode}_{index}';folder.mkdir(exist_ok=True)
    source=(previous/'tb.sv').read_text()
    prefix=source[:source.index('\ninitial begin')]
    fields=re.search(r'initialize_input_coverage\(\);(\{[^\n]+\})=\x270;check\(\);',source)[1]
    text=prefix+'''
conv_im2col_pkg::conv_cfg_t directed_cfg;
integer verified_coordinates=0;
initial begin
 initialize_input_coverage();
 for(integer scenario=0;scenario<2;scenario++)begin
  i_rst_n=0;FIELDS='0;check();i_rst_n=1;
  directed_cfg='0;
  directed_cfg.input_h=64;directed_cfg.input_w=64;directed_cfg.input_c=8;
  directed_cfg.group_c=8;directed_cfg.kernel_h=3;directed_cfg.kernel_w=3;
  directed_cfg.output_h=32;directed_cfg.output_w=scenario==0?32:1;
  directed_cfg.stride_h=scenario==0?1:2;directed_cfg.stride_w=scenario==0?1:2;
  directed_cfg.dilation_h=1;directed_cfg.dilation_w=1;
  directed_cfg.windowed=1;directed_cfg.prefetch_enable=1;
  i_c=directed_cfg;i_cfg_valid=0;i_cfg_ready=1;
  i_rows_q=1;i_cols_q=8;i_tile_rows=1;i_tile_cols=8;
  i_ix=3;i_iy=4;i_request_y=4;i_incoming_ix=3;
  i_kx=2;i_kx0=2;i_ch=0;i_ch0=0;
  i_cache_port_ready=1;i_request_addr_q=32'h1000;i_cache_req_addr=32'h1000;
  i_request_index_valid_q=1;i_req_index_valid=1;
  i_prefetch_address_sum=32'h1100;i_prefetch_pixel_sum=17;i_pf_step_base=1;
  i_retire_last_row_q=31;i_second_last_row_q=30;
  i_last_output_col_q=scenario==0?31:0;i_second_last_col_q=scenario==0?30:0;
  for(integer step=0;step<18;step++)begin
   i_cache_port_valid=step==0;check();
   if(current_o_prefetch_phase==5)begin
    if(current_o_pf0_y!==(scenario==0?32'd5:32'd6))
      $fatal(1,"Prepared vertical coordinate differs scenario=%0d actual=%0d",scenario,current_o_pf0_y);
    verified_coordinates++;
   end
  end
 end
 if(offers!=2||verified_coordinates!=2)$fatal(1,"Required prefetch outputs were not produced");
 $display("PREFETCH_PROTOCOL_PASS cycles=%0d coordinates=%0d offers=%0d",checks,verified_coordinates,offers);$finish;
end
endmodule
'''.replace('FIELDS',fields)
    tb=folder/'tb.sv';tb.write_text(text)
    flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
    execute(['iverilog','-g2012',*flags,'-s','tb','-o',folder/'sim',*snapshots['current'],
             previous/'reference_prefetch.sv',tb],folder/'compile.log')
    result=execute(['vvp',folder/'sim'],folder/'run.log')
    match=re.search(r'PREFETCH_PROTOCOL_PASS cycles=(\d+) coordinates=(\d+) offers=(\d+)',result)
    if not match:raise RuntimeError(str(folder/'run.log'))
    return dict(mode=mode,parameters=PROFILES[index],passed=True,cycles=int(match[1]),
                verified_coordinates=int(match[2]),prefetch_offers=int(match[3]),log_sha256=digest(folder/'run.log'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--section',choices=['all','formal','four_state','protocol'],default='all')
    args=parser.parse_args();source=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    revision,snapshots,hashes=prepare(source,out,args.reference)
    connection=geometry_connection(source)
    report=dict(reference_commit=revision,source_sha256=hashes,external_input_assumptions=[])
    if args.section in ('all','formal'):
        report['formal']=formal(out,snapshots)
    else:
        report=json.loads((out/'summary.json').read_text())
        if report['source_sha256']!=hashes:raise RuntimeError('已保存形式结果对应的源码与当前源码不同')
    if args.section in ('all','four_state'):
        report['arithmetic_four_state']=[arithmetic_four_state(out,snapshots,mode) for mode in ('generic','fpga')]
        report['prefetch_four_state']=[prefetch_four_state(out,snapshots,mode,index) for mode in ('generic','fpga') for index in (0,1)]
    if args.section in ('all','protocol'):
        report['prefetch_protocol']=[prefetch_protocol(out,snapshots,mode,index) for mode in ('generic','fpga') for index in (0,1)]
    unchanged(source,hashes);report['sources_unchanged']=True;report['passed']=True
    if connection!=geometry_connection(source):raise RuntimeError('检查期间正式组基址连接发生变化')
    report['production_connection']=connection
    save(out/'summary.json',report)
    print(json.dumps({key:len(report.get(key,[])) for key in ('formal','arithmetic_four_state','prefetch_four_state','prefetch_protocol')}),flush=True)


if __name__=='__main__':main()
