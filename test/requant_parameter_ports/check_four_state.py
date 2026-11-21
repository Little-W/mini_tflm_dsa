#!/usr/bin/env python3
"""检查实际 WS 参数存储与串行读取端口的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RTL=Path('rtl/npu/writeback/vec_requant.sv')
PROFILES=[(4,32,1),(8,64,1),(16,64,2),(16,64,4),(16,128,2),(8,96,2)]

def unit(source,name):
    start=source.index('  if (((PARAM_BANKS & (PARAM_BANKS - 1)) == 0)')
    end=source.index('  // ----------------------------\n  // 主状态机',start)
    body=source[start:end]
    selected=''
    if 'g_serial_read' not in body:
        selected='''
    for(genvar lane=0;lane<p_compute_lanes;lane++) begin
        assign serial_product_multiplier[lane]=ch_product_multiplier_lane_r[serial_element_index[lane]];
        assign serial_product_amount[lane]=ch_product_amount_lane_r[serial_element_index[lane]];
    end
'''
    return f'''module {name} #(parameter VLEN=16,BUS_WIDTH=64,p_compute_lanes=2)(
    input logic clk,rsp_hskd,is_mode_r,load_phase,
    input logic [31:0] rd_beats_cnt,beats_expect,
    input logic [BUS_WIDTH/32-1:0][8:0] parameter_index,
    input logic [BUS_WIDTH/32-1:0][31:0] parameter_value,parameter_product_multiplier,
    input logic [BUS_WIDTH/32-1:0][6:0] parameter_product_amount,
    input logic [p_compute_lanes-1:0][$clog2(VLEN)-1:0] serial_element_index,
    output wire [VLEN*103+p_compute_lanes*39-1:0] result
);
    localparam VLEN_IDX_W=$clog2(VLEN),PARAM_BANKS=BUS_WIDTH/32,PH_MUL=1'b0;
    localparam p_serial_read_ports=p_compute_lanes;
    logic signed [31:0] ch_multiplier_lane_r[VLEN],ch_shift_lane_r[VLEN],ch_product_multiplier_lane_r[VLEN];
    logic [6:0] ch_product_amount_lane_r[VLEN];
    wire signed [31:0] serial_product_multiplier[p_compute_lanes];
    wire [6:0] serial_product_amount[p_compute_lanes];
    wire signed [31:0] serial_bank_multiplier[PARAM_BANKS][p_compute_lanes];
    wire [6:0] serial_bank_amount[PARAM_BANKS][p_compute_lanes];
{body}
{selected}
    for(genvar lane=0;lane<VLEN;lane++) begin
        assign result[lane*103+:103]={{ch_multiplier_lane_r[lane],ch_shift_lane_r[lane],ch_product_multiplier_lane_r[lane],ch_product_amount_lane_r[lane]}};
    end
    for(genvar lane=0;lane<p_compute_lanes;lane++) begin
        assign result[VLEN*103+lane*39+:39]={{serial_product_multiplier[lane],serial_product_amount[lane]}};
    end
endmodule
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--reference-root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    hashes={};models=[]
    for label,root in [('reference',a.reference_root),('current',a.source_root)]:
        src=root/RTL;hashes[label]=hashlib.sha256(src.read_bytes()).hexdigest()
        target=out/(label+'.sv');target.write_text(unit(src.read_text(),label));models.append(target)
    rows=[]
    for vlen,bus,lanes in PROFILES:
        folder=out/f'v{vlen}_b{bus}_l{lanes}';folder.mkdir(exist_ok=True)
        bench=folder/'tb.sv'
        bench.write_text(f'''module tb;
    localparam VLEN={vlen},BUS_WIDTH={bus},p_compute_lanes={lanes},PARAM_BANKS=BUS_WIDTH/32;
    logic clk=0,rsp_hskd,is_mode_r,load_phase;
    logic [31:0] rd_beats_cnt,beats_expect;
    logic [PARAM_BANKS-1:0][8:0] parameter_index;
    logic [PARAM_BANKS-1:0][31:0] parameter_value,parameter_product_multiplier;
    logic [PARAM_BANKS-1:0][6:0] parameter_product_amount;
    logic [p_compute_lanes-1:0][$clog2(VLEN)-1:0] serial_element_index;
    wire [VLEN*103+p_compute_lanes*39-1:0] expected,observed;
    reference #(VLEN,BUS_WIDTH,p_compute_lanes) u_reference(.*, .result(expected));
    current #(VLEN,BUS_WIDTH,p_compute_lanes) u_current(.*, .result(observed));
    logic [31:0] random_state=32'hbd137921;
    integer checks=0;
    function automatic logic [31:0] next_random(input logic [31:0] value);
        next_random={{value[30:0],value[31]^value[21]^value[1]^value[0]}};
    endfunction
    initial begin
        for(integer sample=0;sample<12000;sample++) begin
            clk=0;
            random_state=next_random(random_state);
            rsp_hskd=(sample<64)?1'b1:random_state[0];
            is_mode_r=(sample<64)?1'b0:random_state[1];
            load_phase=(sample<64)?1'(sample/VLEN):random_state[2];
            rd_beats_cnt=(sample<64)?0:{{28'b0,random_state[7:4]}};
            beats_expect=(sample<64)?32:{{27'b0,random_state[12:8]}};
            for(integer word=0;word<PARAM_BANKS;word++) begin
                random_state=next_random(random_state);
                parameter_index[word]=(sample<64)?9'(sample*PARAM_BANKS+word):9'(random_state);
                parameter_value[word]=random_state;
                parameter_product_multiplier[word]=~random_state;
                parameter_product_amount[word]=random_state[14:8];
            end
            for(integer lane=0;lane<p_compute_lanes;lane++) begin
                random_state=next_random(random_state);
                serial_element_index[lane]=$clog2(VLEN)'(random_state);
            end
            if(sample>=64) begin
                case(sample%13)
                    0: serial_element_index[0][sample%$clog2(VLEN)]=1'bx;
                    1: serial_element_index[0][sample%$clog2(VLEN)]=1'bz;
                    2: parameter_value[0][sample%32]=1'bx;
                    3: parameter_product_multiplier[0][sample%32]=1'bz;
                    4: parameter_product_amount[0][sample%7]=1'bx;
                    5: parameter_index[0][sample%9]=1'bz;
                    6: rsp_hskd=1'bx;
                    7: is_mode_r=1'bz;
                    8: load_phase=1'bx;
                    9: rd_beats_cnt[sample%8]=1'bx;
                    10: beats_expect[sample%8]=1'bz;
                    default: begin end
                endcase
            end
            #1;
            if(observed!==expected) $fatal(1,"read mismatch sample=%0d",sample);
            checks++;
            clk=1;#1;
            if(observed!==expected) $fatal(1,"write mismatch sample=%0d",sample);
            checks++;
        end
        $display("PASS cycles=12000 comparisons=%0d",checks);
        $finish;
    end
endmodule
''')
        log=folder/'run.log';binary=folder/'simulation'
        with log.open('w') as f:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),*map(str,models),str(ROOT/'rtl/common/regfile.v'),str(bench)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
            subprocess.run(['vvp',str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=120)
        assert 'PASS cycles=12000 comparisons=24000' in log.read_text()
        row={'vlen':vlen,'bus_width':bus,'compute_lanes':lanes,'passed':True,'cycles':12000,'comparisons':24000,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
        rows.append(row);print(json.dumps(row),flush=True)
    record={'passed':True,'source_sha256':hashes,'strict_four_state':True,'profiles':rows,'comparisons':sum(r['comparisons'] for r in rows)}
    (out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
if __name__=='__main__':main()
