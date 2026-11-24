#!/usr/bin/env python3
"""Prove burst-length candidates and compare their strict four-state behavior."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/dma/axi_linear_block_dma.sv'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(text, name):
    begin = text.index('    logic [REG_WIDTH-1:0] wr_segment_addr [2];')
    end = text.index('    wire wr_tail_beat', begin)
    body = text[begin:end]
    return f'''module {name} #(parameter integer BUS_WIDTH=64, DMA_MAX_BYTES=2048)(
    input logic [31:0] wr_cmd_segment_addr, wr_data_segment_addr,
    input logic [8:0] wr_cmd_beat_cnt, wr_beat_cnt,
    input logic [7:0] wr_cfg_burst_len_m1,
    input logic [$clog2(BUS_WIDTH/8)-1:0] wr_cmd_row_offset, wr_row_offset,
    output logic [17:0] selected
);
    localparam integer REG_WIDTH=32, BEAT_CNT_W=9, ADDR_LSB=$clog2(BUS_WIDTH/8);
    localparam integer MAX_BURST_BEATS=DMA_MAX_BYTES/(BUS_WIDTH/8);
    typedef logic [8:0] beat_count_t;
    wire [8:0] wr_cfg_burst_len_ext={{1'b0,wr_cfg_burst_len_m1}};
    wire [8:0] wr_cfg_cross_last=wr_cfg_burst_len_ext+9'd1;
    wire wr_row_cross=wr_row_offset!='0;
{body}
    assign selected={{wr_selected_last_beat[1],wr_selected_last_beat[0]}};
endmodule
'''


def observe_configuration(text, candidate):
    marker = '    output logic wr_error\n);'
    if text.count(marker) != 1:
        raise ValueError('Expected one complete linear DMA interface')
    text = text.replace(marker, '    output logic wr_error,\n'
                        '    output logic [8:0] formal_cross_last\n);')
    expression = ('wr_cfg_cross_last' if candidate else
                  "beat_count_t'(wr_cfg_burst_len_m1) + beat_count_t'(1)")
    end = text.index('endmodule')
    return text[:end] + f'    assign formal_cross_last = {expression};\n' + text[end:]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,default=SOURCE)
    parser.add_argument('--sizes',type=int,nargs='+',default=[16,64])
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    inputs={'reference':str(args.reference.resolve()),'candidate':str(args.candidate.resolve())}
    hashes={name:sha(path) for name,path in inputs.items()}
    sources=[]
    for name,path in inputs.items():
        target=out/(name+'.sv');target.write_text(model(Path(path).read_text(),name));sources.append(target)
    miter=out/'miter.sv'
    miter.write_text('''module burst_miter #(parameter integer BUS_WIDTH=64, DMA_MAX_BYTES=2048)(
    input logic [31:0] wr_cmd_segment_addr,wr_data_segment_addr,
    input logic [8:0] wr_cmd_beat_cnt,wr_beat_cnt,
    input logic [7:0] wr_cfg_burst_len_m1,
    input logic [$clog2(BUS_WIDTH/8)-1:0] wr_cmd_row_offset,wr_row_offset,
    output logic o_equal
);
    wire [17:0] expected,observed;
    reference #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) reference_dut(.selected(expected),.*);
    candidate #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) candidate_dut(.selected(observed),.*);
    assign o_equal=expected==observed;
endmodule
''')
    bench=out/'tb.sv'
    bench.write_text('''module tb;
    parameter integer BUS_WIDTH=64,DMA_MAX_BYTES=2048;
    localparam integer OFFSET_WIDTH=$clog2(BUS_WIDTH/8);
    logic [31:0] wr_cmd_segment_addr,wr_data_segment_addr;
    logic [8:0] wr_cmd_beat_cnt,wr_beat_cnt;
    logic [7:0] wr_cfg_burst_len_m1;
    logic [OFFSET_WIDTH-1:0] wr_cmd_row_offset,wr_row_offset;
    wire [17:0] expected,observed;
    integer count=0,rng=32'h14b68a9d;
    reference #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) reference_dut(.selected(expected),.*);
    candidate #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) candidate_dut(.selected(observed),.*);
    task automatic check;
        #1;
        if(expected!==observed) $fatal(1,"Burst length mismatch sample=%0d expected=%h observed=%h",count,expected,observed);
        count++;
    endtask
    initial begin
        for(integer sample=0;sample<8192;sample++) begin
            wr_cmd_segment_addr=$random(rng);wr_data_segment_addr=$random(rng);
            wr_cmd_beat_cnt=$random(rng);wr_beat_cnt=$random(rng);
            wr_cfg_burst_len_m1=8'(sample);wr_cmd_row_offset=OFFSET_WIDTH'(sample);
            wr_row_offset=$random(rng);
            if(sample%3==0) wr_cmd_beat_cnt=9'(wr_cfg_burst_len_m1)+9'(sample%4);
            if(sample%5==0) wr_beat_cnt=9'(wr_cfg_burst_len_m1)+9'(sample%4);
            if(sample%7==0) wr_cmd_segment_addr[11:0]=12'hff8;
            if(sample%11==0) wr_data_segment_addr[11:0]=12'h000;
            check();
            wr_cmd_row_offset[sample%OFFSET_WIDTH]=1'bx;
            wr_row_offset[(sample+1)%OFFSET_WIDTH]=1'bz;check();
            if(sample%2==0) wr_cfg_burst_len_m1[sample%8]=1'bz;
            if(sample%3==0) wr_cmd_beat_cnt[sample%9]=1'bx;
            if(sample%5==0) wr_beat_cnt[sample%9]=1'bz;
            if(sample%7==0) wr_cmd_segment_addr[sample%12]=1'bx;
            if(sample%11==0) wr_data_segment_addr[(sample+3)%12]=1'bz;
            check();
        end
        $display("BURST_LENGTH_PASS comparisons=%0d",count);$finish;
    end
endmodule
''')
    rows=[]
    for bus,maximum in ((32,4),(32,1024),(64,8),(64,2048),(128,16),(128,4096),(256,8192),(1024,32768)):
        folder=out/f'b{bus}_m{maximum}';folder.mkdir(exist_ok=True)
        script=folder/'formal.ys'
        script.write_text('read_slang --top burst_miter '+f'-GBUS_WIDTH={bus} -GDMA_MAX_BYTES={maximum} '+shlex.join(map(str,[*sources,miter]))+'\nprep -top burst_miter -flatten\nsat -prove o_equal 1 -verify\n')
        commands=[([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],'formal.log'),
                  (['iverilog','-g2012','-s','tb',f'-Ptb.BUS_WIDTH={bus}',f'-Ptb.DMA_MAX_BYTES={maximum}','-o',str(folder/'sim'),*map(str,[*sources,bench])],'compile.log'),
                  (['vvp',str(folder/'sim')],'run.log')]
        for command,logname in commands:
            result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,cwd=ROOT,timeout=120)
            (folder/logname).write_text(result.stdout)
            if result.returncode:raise RuntimeError(result.stdout[-8000:])
        assert 'SUCCESS' in (folder/'formal.log').read_text()
        matched=re.search(r'BURST_LENGTH_PASS comparisons=(\d+)',(folder/'run.log').read_text());assert matched
        row=dict(bus_width=bus,dma_max_bytes=maximum,passed=True,four_state_comparisons=int(matched[1]),formal_log_sha256=sha(folder/'formal.log'),four_state_log_sha256=sha(folder/'run.log'));rows.append(row);print(json.dumps(row),flush=True)
    observed={}
    for name,path in inputs.items():
        target=out/(name+'_state.sv')
        target.write_text(observe_configuration(Path(path).read_text(),name=='candidate'))
        observed[name]=target
    # Prove the saved cross-length relation together with every public output,
    # shared state bit and expanded descriptor-memory bit.
    command=[sys.executable,str(ROOT/'test/frontend_depth_timing/linear_check.py'),
             '--reference',str(observed['reference']),'--candidate',str(observed['candidate']),
             '--sizes',*map(str,args.sizes),'--out',str(out/'complete_dma')]
    subprocess.run(command,cwd=ROOT,check=True)
    complete=json.loads((out/'complete_dma/summary.json').read_text())
    assert complete['passed']
    assert hashes=={name:sha(path) for name,path in inputs.items()}
    (out/'summary.json').write_text(json.dumps(dict(passed=True,input_files=inputs,source_sha256=hashes,
        tool_sha256=sha(Path(__file__)),input_assumptions=[],profiles=rows,
        saved_relation='wr_cfg_cross_last == zero_extend(wr_cfg_burst_len_m1) + 1',
        complete_dma=complete),indent=2)+'\n')


if __name__=='__main__':main()
