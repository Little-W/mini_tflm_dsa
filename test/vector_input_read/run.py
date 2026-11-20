#!/usr/bin/env python3
"""验证生产向量输入银行读取的逐位等价、四态行为和局部映射资源。"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
sys.path.insert(0, str(ROOT/'test'))
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage
from netlist_metrics import connected_paths


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def extract(source):
    begin = source.index('    for (genvar bank=0;bank<PE_COUNT;bank++) begin : g_bank',
                         source.index('begin : g_input_lane_banks'))
    end = source.index('  end else begin : g_input_lane_fallback', begin)
    return source[begin:end], source[:begin]+source[end:]


def unit(source, name, tile=16, pe_count=8, dma_size=64):
    body, _ = extract(source)
    return f'''module {name} (
    input logic [{32*tile-1}:0] data,
    input logic [$clog2({dma_size}):0] vector_base,
    input logic [$clog2({tile}+{pe_count}+1)-1:0] compute_index,
    input logic [$clog2({tile}+1)-1:0] active,
    input logic state, global_pool,
    output wire [{16*pe_count-1}:0] lanes, operands
);
localparam int TILE={tile}, PE_COUNT={pe_count}, DMA_SIZE={dma_size};
localparam int INPUT_INDEX_W=$clog2(DMA_SIZE);
localparam int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1);
localparam int BANK_SHIFT=$clog2(PE_COUNT), BANK_ROWS=DMA_SIZE/PE_COUNT;
localparam logic EXECUTE=1'b1;
wire signed [15:0] input_buf [DMA_SIZE], input_lane [PE_COUNT];
logic signed [15:0] bank_current [PE_COUNT], bank_next [PE_COUNT];
for(genvar entry=0;entry<DMA_SIZE;entry++) begin : g_input
    if(entry<2*TILE) assign input_buf[entry]=data[16*entry+:16];
    else assign input_buf[entry]=16'sd0;
end
generate
''' + body + '''endgenerate
for(genvar lane=0;lane<PE_COUNT;lane++) begin : g_output
    wire enabled=(TILE_INDEX_W+1)'(compute_index)+(TILE_INDEX_W+1)'(lane)<
        (TILE_INDEX_W+1)'(active);
    assign lanes[16*lane+:16]=input_lane[lane];
    assign operands[16*lane+:16]=enabled ? input_lane[lane] : 16'sd0;
end
endmodule
'''


def miter(tile, pe_count, dma_size):
    return f'''module miter (
    input logic [{32*tile-1}:0] data,
    input logic [$clog2({dma_size}):0] vector_base,
    input logic [$clog2({tile}+{pe_count}+1)-1:0] compute_index,
    input logic [$clog2({tile}+1)-1:0] active,
    input logic state, global_pool,
    output wire equal
);
wire [{16*pe_count-1}:0] reference_lanes, current_lanes;
wire [{16*pe_count-1}:0] reference_operands, current_operands;
reference_unit u_reference(.data,.vector_base,.compute_index,.active,.state,.global_pool,
    .lanes(reference_lanes),.operands(reference_operands));
current_unit u_current(.data,.vector_base,.compute_index,.active,.state,.global_pool,
    .lanes(current_lanes),.operands(current_operands));
assign equal=(reference_lanes==current_lanes) && (reference_operands==current_operands);
endmodule
'''


FOUR_STATE = '''module tb;
logic [511:0] data;
logic [6:0] vector_base;
logic [4:0] compute_index,active;
logic state,global_pool;
wire [127:0] reference_lanes,current_lanes,reference_operands,current_operands;
reference_unit u_reference(.data,.vector_base,.compute_index,.active,.state,.global_pool,
    .lanes(reference_lanes),.operands(reference_operands));
current_unit u_current(.data,.vector_base,.compute_index,.active,.state,.global_pool,
    .lanes(current_lanes),.operands(current_operands));
integer address,pattern,bit_index,word_index,digit,seed,checks;
logic [1:0] symbol;
initial begin
    seed=32'h4514abcd;
    checks=0;
    for(pattern=0;pattern<16;pattern=pattern+1) begin
        case(pattern%4)
            0: state=1'b0;
            1: state=1'b1;
            2: state=1'bx;
            3: state=1'bz;
        endcase
        case(pattern/4)
            0: global_pool=1'b0;
            1: global_pool=1'b1;
            2: global_pool=1'bx;
            3: global_pool=1'bz;
        endcase
        case(pattern%8)
            0: begin active=0; compute_index=0; end
            1: begin active=4; compute_index=0; end
            2: begin active=4; compute_index=1; end
            3: begin active=8; compute_index=8; end
            4: begin active=16; compute_index=31; end
            5: begin active=4; compute_index=0; end
            6: begin active=5'b001x0; compute_index=5'b000x0; end
            7: begin active=5'b001z0; compute_index=5'b00z00; end
        endcase
        for(word_index=0;word_index<32;word_index=word_index+1) begin
            data[16*word_index+:16]=$random(seed);
            if((word_index+pattern)%5==0) data[16*word_index+:4]=4'bx01z;
            if((word_index+pattern)%7==0) data[16*word_index+8+:4]=4'bz10x;
        end
        for(address=0;address<16384;address=address+1) begin
            digit=address;
            for(bit_index=0;bit_index<7;bit_index=bit_index+1) begin
                symbol=2'(digit%4);
                case(symbol)
                    0: vector_base[bit_index]=1'b0;
                    1: vector_base[bit_index]=1'b1;
                    2: vector_base[bit_index]=1'bx;
                    3: vector_base[bit_index]=1'bz;
                endcase
                digit=digit/4;
            end
            #1;
            if(reference_lanes!==current_lanes || reference_operands!==current_operands)
                $fatal(1,"输入银行四态比较不一致：地址=%b，模式=%0d",vector_base,pattern);
            checks=checks+1;
        end
    end
    $display("PASS checks=%0d",checks);
    $finish;
end
endmodule
'''


def synth_script(source, output, cost, library):
    return f'''read_slang --top current_unit {shlex.quote(str(source))}
synth_xilinx -top current_unit -family xc7 -nodsp -nosrl -noiopad -noclkbuf -run begin:map_luts
read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v
read_verilog -lib -overwrite +/xilinx/cells_xtra.v
opt_expr -mux_undef -noclkinv
read_verilog -icells -lib -specify +/xilinx/abc9_model.v
scratchpad -set abc9.xaiger 1
scratchpad -set abc9.verify 1
abc9 -W 500 -lut {shlex.quote(str(library))} -D 6667
clean
techmap -map +/xilinx/lut_map.v -map +/xilinx/cells_map.v -D LUT_WIDTH=6
xilinx_dffopt
opt_lut_ins -tech xilinx
synth_xilinx -top current_unit -family xc7 -noiopad -noclkbuf -run finalize:
check -assert
write_json {shlex.quote(str(output))}
stat
'''


def port_depth(module):
    """用独立边界寄存器统计组合端口之间的单元数，不修改综合网表。"""
    next_bit=max(bit for net in module['netnames'].values()
                 for bit in net['bits'] if isinstance(bit,int))+1
    for name,port in module['ports'].items():
        for index,bit in enumerate(port['bits']):
            if not isinstance(bit,int):
                continue
            connection={'C':['0'],'CE':['1'],'R':['0']}
            if port['direction']=='input':
                connection.update({'Q':[bit],'D':['0']})
            else:
                connection.update({'D':[bit],'Q':[next_bit]})
                next_bit+=1
            module['cells'][f'boundary_{name}_{index}']={
                'type':'FDRE','parameters':{},'connections':connection,
                'port_directions':{'C':'input','CE':'input','R':'input','D':'input','Q':'output'}}
    result=connected_paths(module,limit=1,group_limit=1)
    assert result['graph_complete']
    return result['longest_register_path_cells']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='1c3dae2642b89a3c5c4cd593bd087a330cd443e5')
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    current=(ROOT/SOURCE).read_text()
    reference=read_rtl_source(f'{args.reference}:{SOURCE}',cwd=ROOT,text=True)
    assert extract(current)[1]==extract(reference)[1], '读取区域外的 RTL 必须保持一致'
    formal=[]
    for tile,pe_count,dma_size in [(16,8,64),(16,8,32),(8,4,32)]:
        label=f'{tile}_{pe_count}_{dma_size}'
        source=out/f'formal_{label}.sv'
        source.write_text(unit(reference,'reference_unit',tile,pe_count,dma_size)+
                          unit(current,'current_unit',tile,pe_count,dma_size)+
                          miter(tile,pe_count,dma_size))
        script=out/f'formal_{label}.ys'
        script.write_text(f'read_slang --top miter {source}\nprep -top miter -flatten\n'
                          'opt -full\nsat -prove equal 1 -verify -set-def-inputs\n')
        stage=run_stage(script,out/f'formal_{label}.log',dict(os.environ))
        formal.append({'tile':tile,'pe_count':pe_count,'dma_size':dma_size,
                       'compared_bits':32*pe_count,'passed':True,**stage})
    four_source=out/'four_state.sv'
    four_source.write_text(unit(reference,'reference_unit')+unit(current,'current_unit')+FOUR_STATE)
    binary=out/'four_state.vvp'
    with (out/'four_state_build.log').open('w') as log:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(four_source)],
                       check=True,stdout=log,stderr=subprocess.STDOUT)
    with (out/'four_state.log').open('w') as log:
        subprocess.run(['vvp',str(binary)],check=True,stdout=log,stderr=subprocess.STDOUT)
    checks=int(re.search(r'PASS checks=(\d+)',(out/'four_state.log').read_text()).group(1))
    mapping=[]
    delays=[127,238,407,472,631,642]
    for cost in (0.75,1.0):
        library=out/f'lut_cost_{cost:g}.lut'
        library.write_text(''.join(f'{n} {cost if n<6 else 1:g} '+
                                  ' '.join(map(str,delays[:n]))+'\n' for n in range(1,7)))
        for name,rtl in [('reference',reference),('current',current)]:
            # 面积比较只导出 PE 操作数，银行内部输出仍参与上面的完整形式比较。
            source=out/f'map_{name}.sv'
            text=unit(rtl,'current_unit')
            text=text.replace('lanes, operands','operands').replace(
                '    assign lanes[16*lane+:16]=input_lane[lane];\n','')
            source.write_text(text)
            prefix=f'{name}_{cost:g}'
            netlist=out/f'{prefix}.json'
            script=out/f'{prefix}.ys'
            script.write_text(synth_script(source,netlist,cost,library))
            stage=run_stage(script,out/f'{prefix}.log',dict(os.environ))
            module=json.loads(netlist.read_text())['modules']['current_unit']
            counts=collections.Counter(cell['type'] for cell in module['cells'].values())
            mapping.append({'variant':name,'small_lut_cost':cost,
                            'lut_cells':sum(count for kind,count in counts.items() if kind.startswith('LUT')),
                            'cell_counts':dict(sorted(counts.items())),
                            'port_to_port_combinational_cells':port_depth(module),**stage})
    summary={'passed':True,'reference_revision':args.reference,
             'source_sha256':{'reference':sha256(reference.encode()),'current':sha256(current.encode())},
             'unchanged_surrounding_rtl':True,'formal_input_constraints':None,
             'formal':formal,'four_state_checks':checks,
             'four_state_address_patterns':4**7,'mapping':mapping}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
