#!/usr/bin/env python3
"""测量组基址、像素求和及完整预取模块的寄存器组合路径。"""
from pathlib import Path
import argparse
import json
import re
import sys
from common import ROOT, REFERENCE, digest, execute, prepare, save, unchanged

sys.path.insert(0,str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def accepted_y(name,cell,port):
    origin=cell.get('attributes',{}).get('fpga_register_origin','')
    if 'accepted_coordinate_q[1]' in origin:return True
    match=re.search(r'accepted_coordinate_q\[0\] \[(\d+)\]',origin)
    return match is not None and int(match[1])>=35


def arithmetic_wrapper(kind,current):
    if kind=='group':
        ports=''' input logic [31:0] i_base, // 输入字节基址
 input logic [31:0] i_product, // 像素与通道乘积
 input logic [15:0] i_offset, // 组内元素偏移
 input logic i_s16, // 两字节元素标志'''
        declarations='logic [31:0] base_q,product_q,sum;logic [15:0] offset_q;logic s16_q;'
        updates='base_q<=i_base;product_q<=i_product;offset_q<=i_offset;s16_q<=i_s16;'
        expression=('conv_group_base_address u_group(.i_input_base(base_q),.i_channel_product(product_q),'
          '.i_group_offset(offset_q),.i_input_s16(s16_q),.o_address(sum));' if current else
          "assign sum=base_q+((product_q+32'(offset_q))<<s16_q);")
    else:
        ports=''' input logic [31:0] i_product, // 行像素乘积
 input logic [34:0] i_coordinate, // 输入横坐标位表示'''
        declarations='logic [31:0] product_q,sum;logic [34:0] coordinate_q;'
        updates='product_q<=i_product;coordinate_q<=i_coordinate;'
        expression=("conv_full_address_add u_pixel(.i_a(product_q),.i_b(32'(coordinate_q)),.o_sum(sum));" if current else
                    "assign sum=product_q+32'(coordinate_q);")
    return '''// 测量真实定宽算术，全部操作数和完整结果均设置寄存器边界。
module measure(
 input logic clk, // 测量时钟
PORTS
 output logic [31:0] o_sum // 保存的完整计算结果
);
DECLARATIONS
always_ff @(posedge clk)begin UPDATES o_sum<=sum;end
EXPRESSION
endmodule
'''.replace('PORTS',ports).replace('DECLARATIONS',declarations).replace('UPDATES',updates).replace('EXPRESSION',expression)


def prefetch_wrapper(ports):
    declarations=[];signals=[];updates=[];connections=[]
    for name,port in ports.items():
        width=len(port['bits']);direction=port['direction'];dimensions=f'[{width-1}:0]'
        comma=',' if name!=list(ports)[-1] else ''
        declarations.append(f' {direction} logic {dimensions} {name}{comma} // 预取模块公开信号 {name}')
        if name in ('i_clk','i_rst_n'):connections.append(f'.{name}({name})');continue
        signals.append(f'logic {dimensions} {name}_q;')
        connections.append(f'.{name}({name}_q)')
        updates.append(f'{name}_q<={name};' if direction=='input' else f'{name}<={name}_q;')
    return ('// 完整预取模块，全部外部组合输入和输出采用寄存器边界。\nmodule measure(\n'+
       '\n'.join(declarations)+'\n);\n'+'\n'.join(signals)+
       '\nalways_ff @(posedge i_clk)begin\n'+'\n'.join(updates)+'\nend\n'+
       'conv_im2col_prefetch #(.p_size(16),.p_line_bytes(128),.p_register_cache_request(1)) u_prefetch(\n'+
       ',\n'.join(connections)+'\n);\nendmodule\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference',default=REFERENCE)
    parser.add_argument('--validation',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',default=['group','pixel','prefetch'])
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();source=args.source_root.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    revision,snapshots,hashes=prepare(source,out,args.reference)
    cases={}
    for kind in args.cases:
        for label in ('reference','current'):
            key=kind+'_'+label;folder=out/key;folder.mkdir(exist_ok=True)
            if kind=='prefetch':
                module=json.loads((args.validation/'prefetch_generic_0/current_state.json').read_text())['modules']['current']
                text=prefetch_wrapper(module['ports'])
            else:text=arithmetic_wrapper(kind,label=='current')
            wrapper=folder/'measure.sv';wrapper.write_text(text)
            supplied=[path for path in snapshots[label] if not (source/'rtl/common'/path.name).exists()]
            cases[key]=dict(top='measure',sources=list(map(str,[wrapper,*supplied])),
                options=['-DSYNTHESIS=1','-DXILINX_FPGA=1'],configuration=kind+' 的完整寄存器输入和输出')
    config=out/'cases.json';save(config,cases)
    command=[sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--source-root',source,
             '--case-config',config,'--cases',*cases,'--out',out/'pre','--through','pre_lut']
    if args.resume:command.append('--resume')
    execute(command,out/'prepare.log',timeout=1800)
    report=dict(reference_commit=revision,source_sha256=hashes,cases={})
    for key in cases:
        folder=out/'mapped'/key
        command=[sys.executable,ROOT/'scripts/fpga/remap_fpga_luts.py','--source',out/'pre'/key,
            '--out',folder,'--mode','physical-cost','--delay-target-ps','6667',
            '--wire-delay-ps','300','--max-lut-inputs','8','--discard-abc9-temporaries']
        if args.resume:command.append('--resume')
        execute(command,out/(key+'.log'),timeout=1800)
        module=json.loads((folder/'mapped.json').read_text())['modules']['measure']
        origins=register_origins(out/'pre'/key/'pre_lut.il','measure')
        for cell,origin in origins.items():
            if cell in module['cells']:module['cells'][cell].setdefault('attributes',{})['fpga_register_origin']=origin
        full=connected_paths(module,limit=8,group_limit=8)
        selected={}
        if key.startswith('prefetch'):
            selected['accepted_y']=connected_paths(module,limit=8,group_limit=8,root_filter=accepted_y)
            if not selected['accepted_y']['longest_register_path_cells']:
                raise RuntimeError('预取纵坐标寄存器未参与完整路径检查')
        summary=json.loads((folder/'summary.json').read_text())
        if not full['graph_complete'] or not summary['functional_verification']['passed']:
            raise RuntimeError('完整组合路径或综合映射验证未完成')
        result=dict(resources=summary['resources'],complete_paths=full,selected_paths=selected,
                    mapped_sha256=digest(folder/'mapped.json'),mapped_functional_verification=summary['functional_verification'])
        report['cases'][key]=result
        save(out/'measurement.json',report)
        print(key,summary['resources']['logic_lut_cells'],full['longest_register_path_cells'],
              {name:value['longest_register_path_cells'] for name,value in selected.items()},flush=True)
    unchanged(source,hashes);report['sources_unchanged']=True;save(out/'measurement.json',report)


if __name__=='__main__':main()
