#!/usr/bin/env python3
"""检查实际通道裁剪、有效位、暂停和清空逻辑的完整输入及四态控制。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def actual_tail(source):
    first=source.index('    // 各字节独立比较')
    return source[first:source.index('\nendmodule',first)]


def unit(source):
    ports='''(
    input logic clk,rst_n,i_en,i_clear,i_valid,i_lane_enable,
    input logic signed [34:0] rounded_q,
    input logic signed [31:0] i_activation_min,i_activation_max,
    output logic o_valid,
    output logic signed [7:0] o_s8,
    output logic signed [15:0] o_s16
);\n'''
    current='module lane_tail '+ports+'''
    localparam integer p_stages=7;
    logic [6:0] valid_q;
    logic [5:0] lane_enable_q;
    logic [1:0] bound_less;
    assign o_valid=valid_q[6];
'''+actual_tail(source)+'\nendmodule\n'
    reference='module lane_reference '+ports+'''
    logic [6:0] valid_model;
    logic [5:0] enable_model;
    logic signed [34:0] low_bound,high_bound;
    assign low_bound={{3{i_activation_min[31]}},i_activation_min};
    assign high_bound={{3{i_activation_max[31]}},i_activation_max};
    assign o_valid=valid_model[6];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            valid_model<=0;enable_model<=0;o_s8<=0;o_s16<=0;
        end else if(i_clear)begin
            valid_model<=0;enable_model<=0;o_s8<=0;o_s16<=0;
        end else if(i_en)begin
            valid_model<={valid_model[5:0],i_valid};
            enable_model<={enable_model[4:0],i_valid&&i_lane_enable};
            if(!enable_model[5])begin o_s8<=0;o_s16<=0;end
            else begin
                if(rounded_q<low_bound)begin
                    o_s8<=i_activation_min[7:0];o_s16<=i_activation_min[15:0];
                end else if(rounded_q>high_bound)begin
                    o_s8<=i_activation_max[7:0];o_s16<=i_activation_max[15:0];
                end else begin
                    o_s8<=(rounded_q < -35'sd128) ? -8'sd128 :
                           (rounded_q > 35'sd127) ? 8'sd127 : rounded_q[7:0];
                    o_s16<=(rounded_q < -35'sd32768) ? -16'sd32768 :
                            (rounded_q > 35'sd32767) ? 16'sd32767 : rounded_q[15:0];
                end
            end
        end
    end
endmodule
'''
    proof='module lane_tail_proof '+ports+'''
    wire valid_reference;
    wire signed [7:0] s8_reference;
    wire signed [15:0] s16_reference;
    lane_tail u_actual(.*);
    lane_reference u_reference(.*, .o_valid(valid_reference),.o_s8(s8_reference),.o_s16(s16_reference));
    always_comb if(rst_n)begin
        assert({o_valid,o_s8,o_s16}=={valid_reference,s8_reference,s16_reference});
    end
endmodule
'''
    return current+reference+proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'rtl/npu/writeback/requant_compute_lane.sv';source=path.read_text()
    model=out/'model.sv';model.write_text(unit(source))
    script=out/'proof.ys';log=out/'proof.log'
    script.write_text('read_slang --top lane_tail_proof '+shlex.quote(str(model))+'\n'+
        'prep -top lane_tail_proof -flatten\nasync2sync\nmemory_map\nchformal -lower\nopt -full\n'+
        'sat -seq 2 -tempinduct -maxsteps 10 -set-at 1 rst_n 0 -prove-asserts -verify -timeout 60\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
            stdout=stream,stderr=subprocess.STDOUT,check=True)
    assert 'Induction step proven' in log.read_text()
    bench=out/'tb.sv';bench.write_text('''module tb;
    reg clk=0,rst_n=0,i_en=1,i_clear=0,i_valid=0,i_lane_enable=0;
    reg signed [34:0] rounded_q=0;
    reg signed [31:0] i_activation_min=0,i_activation_max=0;
    wire valid_a,valid_b;
    wire signed [7:0] s8_a,s8_b;
    wire signed [15:0] s16_a,s16_b;
    lane_tail u_actual(.*,.o_valid(valid_a),.o_s8(s8_a),.o_s16(s16_a));
    lane_reference u_reference(.*,.o_valid(valid_b),.o_s8(s8_b),.o_s16(s16_b));
    integer checks=0,valid_checks=0,data_checks=0;
    function automatic reg symbol(input integer value);
        case(value)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
    endfunction
    task check;
        if({valid_a,s8_a,s16_a} !== {valid_b,s8_b,s16_b})
            $fatal(1,"量化裁剪或控制行为不一致 sample=%0d",checks);
        checks++;
        if(valid_a===1'b1)valid_checks++;
        if(valid_a===1'b1 && s8_a!==0)data_checks++;
    endtask
    initial begin
        #1;clk=1;#1;clk=0;
        for(integer sample=0;sample<65536;sample++)begin
            rst_n=(sample<4 || sample%1024==0)?1'b0:
                (sample%1024<768 ? 1'b1 : symbol((sample>>10)%4));
            i_en=symbol((sample>>2)%4);i_clear=symbol((sample>>4)%4);
            i_valid=symbol((sample>>6)%4);i_lane_enable=symbol((sample>>8)%4);
            rounded_q={$urandom,$urandom};i_activation_min=$urandom;i_activation_max=$urandom;
            if(sample%7==0)begin i_activation_min=-128;i_activation_max=127;end
            if(sample%7==1)begin i_activation_min=-32768;i_activation_max=32767;end
            #1;check();clk=1;#1;check();clk=0;
        end
        if(valid_checks<100 || data_checks<10)$fatal(1,"有效结果覆盖不足");
        $display("PASS cycles=65536 comparisons=%0d valid_checks=%0d data_checks=%0d",checks,valid_checks,data_checks);$finish;
    end
endmodule
''')
    simulation=out/'simulation';simlog=out/'four_state.log'
    with simlog.open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(simulation),str(model),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['vvp',str(simulation)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    assert 'PASS cycles=65536 comparisons=131072' in simlog.read_text()
    coverage=re.search(r'valid_checks=(\d+) data_checks=(\d+)',simlog.read_text())
    assert coverage is not None
    assert source==path.read_text()
    result={'passed':True,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'formal_input_value_bits':99,'formal_inputs_constrained':False,'outputs_compared_bits':25,
        'four_state_control_bits':5,'four_state_cycles':65536,'four_state_comparisons':131072,
        'four_state_valid_checks':int(coverage[1]),'four_state_active_data_checks':int(coverage[2]),
        'latency_enabled_edges':7,'log_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (log,simlog)}}
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
