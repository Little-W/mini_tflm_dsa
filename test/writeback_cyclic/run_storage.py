#!/usr/bin/env python3
"""提取正式 FIFO 的存储和读选择逻辑，验证全部地址、读写碰撞与字节映射。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def storage_module(source, formal=False):
    source = source[:source.index('module vec_s8_to_fifo_linear')]
    constants = source[source.index('  localparam integer PTR_WIDTH'):source.index('  reg [COUNT_WIDTH-1:0] bank_count')]
    memory = source[source.index('  assign read_issue_bank'):source.index('  always @(posedge clk)')]
    output = source[source.index('  integer valid_cols_i;'):source.index('\nendmodule')]
    header = '''module fifo_storage_extracted #(
    parameter integer VLEN=16, BANKS=32, BUS_WIDTH=64,
    parameter bit p_cyclic_storage=0,
    parameter integer BW=$clog2(BANKS), RW=$clog2(VLEN),
    parameter integer NB=BUS_WIDTH/8, BEATS=VLEN/NB,
    parameter integer EW=(BEATS<=1)?1:$clog2(BEATS),
    parameter integer DW=p_cyclic_storage ? BEATS*8 : VLEN*8,
    parameter integer AW=$clog2(p_cyclic_storage ? BANKS*VLEN : BANKS*BEATS)
) (
    input logic clk, in_valid, write_bank_blocked, ram_read_en,
    input logic [BW-1:0] write_bank, read_bank,
    input logic [RW-1:0] write_ptr, issue_read_ptr,
    input logic [EW-1:0] issue_beat_idx,
    input logic issue_transpose_mode,
    input logic [VLEN*8-1:0] in_vec_s8,
    output logic [BUS_WIDTH-1:0] output_data,
    output logic [NB-1:0] output_mask,
    output logic [NB-1:0] o_wr_en,
    output logic [NB-1:0][AW-1:0] o_wr_addr, o_rd_addr,
    output logic [NB-1:0][DW-1:0] o_wr_data
);
'''
    declarations = '''
    logic [VLEN*8-1:0] ram_rd_data [ROW_BANKS];
    logic [p_mem_data_width-1:0] ram_wr_data [ROW_BANKS];
    logic [MEM_ADDR_W-1:0] ram_wr_addr, ram_rd_addr [ROW_BANKS];
    logic [BANK_WIDTH-1:0] read_issue_bank;
    logic [PTR_WIDTH-1:0] read_issue_row, read_ptr;
    logic [BEAT_WIDTH-1:0] read_issue_beat, beat_idx;
    logic read_issue_transpose, ram_write_en, transpose_mode_tmp;
    wire coalesce_enable=1'b0, co_active=1'b0, stream_active=1'b1;
    wire transpose_mode_eff=1'b0;
    wire [8:0] co_row='0, co_next_row='0;
    wire [BEAT_WIDTH-1:0] co_beat='0, co_next_beat='0;
    wire [BANK_WIDTH-1:0] co_issue_bank='0;
    wire [MEM_ADDR_W-1:0] co_ram_addr='0;
    wire [COUNT_WIDTH-1:0] active_read_count=COUNT_WIDTH'(VLEN);
    wire [COUNT_WIDTH-1:0] output_col_count=COUNT_WIDTH'(VLEN);
'''
    sample = '''
    always_ff @(posedge clk) begin
        if (ram_read_en) begin
            read_ptr <= issue_read_ptr;
            beat_idx <= issue_beat_idx;
            transpose_mode_tmp <= issue_transpose_mode;
        end
    end
'''
    if formal:
        sample = '''
    assign read_ptr=issue_read_ptr;
    assign beat_idx=issue_beat_idx;
    assign transpose_mode_tmp=issue_transpose_mode;
'''
        memory = memory.replace('vec_s8_fifo_row_ram #(',
            'fifo_storage_tag #(.p_cyclic(p_use_cyclic_storage), .p_bank(ram_bank), .p_bytes(NB), .p_vlen(VLEN),')
    monitor = '''
    for(genvar bank=0;bank<ROW_BANKS;bank++) begin : g_monitor
        if(p_use_cyclic_storage) begin : g_cyclic
            assign o_wr_en[bank]=g_cyclic_storage.gen_fifo_ram[bank].fifo_ram_i_wr_en;
            assign o_wr_addr[bank]=g_cyclic_storage.gen_fifo_ram[bank].fifo_ram_i_wr_addr;
            assign o_wr_data[bank]=g_cyclic_storage.gen_fifo_ram[bank].fifo_ram_i_wr_data;
            assign o_rd_addr[bank]=g_cyclic_storage.gen_fifo_ram[bank].fifo_ram_i_rd_addr;
        end else begin : g_row
            assign o_wr_en[bank]=g_row_storage.gen_fifo_ram[bank].fifo_ram_i_wr_en;
            assign o_wr_addr[bank]=g_row_storage.gen_fifo_ram[bank].fifo_ram_i_wr_addr;
            assign o_wr_data[bank]=g_row_storage.gen_fifo_ram[bank].fifo_ram_i_wr_data;
            assign o_rd_addr[bank]=g_row_storage.gen_fifo_ram[bank].fifo_ram_i_rd_addr;
        end
    end
'''
    return header+constants+declarations+sample+memory+monitor+output+'\nendmodule\n'


TAG = '''
module fifo_storage_tag #(
    parameter p_cyclic=0, p_bank=0, p_bytes=8, p_vlen=16,
    parameter DATA_WIDTH=128, DEPTH=64, ADDR_WIDTH=6
)(input clk, wr_en, rd_en,
  input [ADDR_WIDTH-1:0] wr_addr, rd_addr,
  input [DATA_WIDTH-1:0] wr_data,
  output logic [DATA_WIDTH-1:0] rd_data);
    always_comb begin
        for(int byte_index=0;byte_index<DATA_WIDTH/8;byte_index++) begin
            if(p_cyclic) rd_data[byte_index*8+:8]=8'((int'(rd_addr)%p_vlen)*p_vlen+
                byte_index*p_bytes+((p_bank+p_vlen-int'(rd_addr)%p_vlen)%p_bytes));
            else rd_data[byte_index*8+:8]=8'(((int'(rd_addr)%(p_vlen/p_bytes))*p_bytes+p_bank)*p_vlen+byte_index);
        end
    end
endmodule
'''

FORMAL = '''
module fifo_storage_formal #(parameter BUS_WIDTH=64, BANKS=32)(
    input clk, in_valid, write_bank_blocked, ram_read_en, issue_transpose_mode,
    input [$clog2(BANKS)-1:0] write_bank, read_bank, probe_tile,
    input [3:0] write_ptr, issue_read_ptr, probe_row, probe_col,
    input [$clog2(16/(BUS_WIDTH/8))-1:0] issue_beat_idx,
    input [127:0] in_vec_s8
);
    localparam NB=BUS_WIDTH/8, BEATS=16/NB, BW=$clog2(BANKS),
        OLD_AW=$clog2(BANKS*BEATS), NEW_AW=$clog2(BANKS*16);
    wire [NB-1:0] old_en,new_en,old_mask,new_mask;
    wire [NB-1:0][OLD_AW-1:0] old_wr_addr,old_rd_addr;
    wire [NB-1:0][NEW_AW-1:0] new_wr_addr,new_rd_addr;
    wire [NB-1:0][127:0] old_wr_data;
    wire [NB-1:0][BEATS*8-1:0] new_wr_data;
    wire [BUS_WIDTH-1:0] old_data,new_data;
    fifo_storage_extracted #(.BUS_WIDTH(BUS_WIDTH),.BANKS(BANKS),.p_cyclic_storage(0)) old_storage(
        .*,.output_data(old_data),.output_mask(old_mask),.o_wr_en(old_en),
        .o_wr_addr(old_wr_addr),.o_rd_addr(old_rd_addr),.o_wr_data(old_wr_data));
    fifo_storage_extracted #(.BUS_WIDTH(BUS_WIDTH),.BANKS(BANKS),.p_cyclic_storage(1)) new_storage(
        .*,.output_data(new_data),.output_mask(new_mask),.o_wr_en(new_en),
        .o_wr_addr(new_wr_addr),.o_rd_addr(new_rd_addr),.o_wr_data(new_wr_data));
    wire old_hit=old_en[int'(probe_row)%NB] &&
        old_wr_addr[int'(probe_row)%NB]==OLD_AW'(int'(probe_tile)*BEATS+int'(probe_row)/NB);
    wire new_hit=new_en[(int'(probe_row)+int'(probe_col))%NB] &&
        new_wr_addr[(int'(probe_row)+int'(probe_col))%NB]==NEW_AW'(int'(probe_tile)*16+int'(probe_row));
    always_comb begin
        assert(old_hit==new_hit);
        if(old_hit) begin
            assert(old_wr_data[int'(probe_row)%NB][int'(probe_col)*8+:8]==
                new_wr_data[(int'(probe_row)+int'(probe_col))%NB][(int'(probe_col)/NB)*8+:8]);
            assert(new_wr_data[(int'(probe_row)+int'(probe_col))%NB][(int'(probe_col)/NB)*8+:8]==
                in_vec_s8[int'(probe_col)*8+:8]);
        end
        assert(old_data==new_data);
        assert(old_mask==new_mask);
        for(int lane=0;lane<NB;lane++) begin
            assert(old_rd_addr[lane]/BEATS==read_bank);
            assert(new_rd_addr[lane]/16==read_bank);
            assert(new_data[lane*8+:8]==(issue_transpose_mode ?
                8'((int'(issue_beat_idx)*NB+lane)*16+int'(issue_read_ptr)) :
                8'(int'(issue_read_ptr)*16+int'(issue_beat_idx)*NB+lane)));
        end
    end
endmodule
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--verilator',default='verilator-modern')
    p.add_argument('--fpga',action='store_true')
    p.add_argument('--worker',type=Path)
    args=p.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)))
        return
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    path=ROOT/'rtl/npu/writeback/vec_s8_to_fifo.sv'
    source=path.read_text()
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=out/'lut6_2.sv'
    model_text=re.search(r'^module LUT6_2\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b','',model_text,flags=re.S)+'\n')
    extracted=out/'fifo_storage_extracted.sv';extracted.write_text(storage_module(source))
    formal=out/'fifo_storage_formal.sv';formal.write_text(storage_module(source,True)+TAG+FORMAL)
    summary={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'fpga':args.fpga,'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
        'primitive_model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'runs':[]}
    for bus in (32,64):
        folder=out/f'bus{bus}';folder.mkdir(exist_ok=True)
        script=folder/'proof.ys'
        defines='-D XILINX_FPGA -D VERIFIC' if args.fpga else '-D ASIC_SYNTHESIS'
        script.write_text(f'read_slang --top fifo_storage_formal -GBUS_WIDTH={bus} {defines} '+str(formal)+' '+str(model)+
            '\nprep -top fifo_storage_formal -flatten\nopt_clean\nchformal -lower\n'
            'sat -prove-asserts -verify -show-inputs\n')
        with (folder/'formal.log').open('w') as log:
            result=subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],stdout=log,stderr=subprocess.STDOUT)
        text=(folder/'formal.log').read_text()
        if result.returncode or 'SAT proof finished - no model found: SUCCESS' not in text:
            raise RuntimeError(text[-8000:])
        command=[args.verilator,'--binary','--timing','--assert','-Wno-fatal','--top-module','tb_fifo_storage',
            f'-DTB_BUS_WIDTH={bus}','--Mdir',str(folder/'obj'),'-j','2',
            *(['-DXILINX_FPGA'] if args.fpga else ['-DASIC_SYNTHESIS']),
            str(ROOT/'rtl/common/REGFILE.v'),str(path),str(extracted),str(model),str(HERE/'tb_fifo_storage.sv')]
        with (folder/'build.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run([str(folder/'obj/Vtb_fifo_storage')],capture_output=True,text=True,timeout=120)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'FIFO_STORAGE_PASS cycles=(\d+) checked_bytes=(\d+) collisions=(\d+) holds=(\d+)',result.stdout)
        if result.returncode or not match:raise RuntimeError(result.stdout+result.stderr)
        summary['runs'].append({'bus_width':bus,'formal_passed':True,'simulation_passed':True,
            'cycles':int(match[1]),'checked_bytes':int(match[2]),'collisions':int(match[3]),'holds':int(match[4]),
            'logical_capacity_bits':32*16*16*8})
        print(json.dumps(summary['runs'][-1]),flush=True)
    summary['source_unchanged']=hashlib.sha256(path.read_bytes()).hexdigest()==summary['source_sha256']
    summary['passed']=summary['source_unchanged']
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not summary['passed']:raise RuntimeError('FIFO source changed during verification')


if __name__=='__main__':main()
