`timescale 1ns/1ps

// Each allocation bank is one synchronous 128-bit 1R1W SRAM.
module ia_ps_shared_ram #(
    parameter int BANK_BYTES = 2048,
    parameter int TOTAL_BYTES = 14336,
    parameter int IA_ADDR_BITS = $clog2(TOTAL_BYTES/16),
    parameter int PS_ADDR_BITS = $clog2(TOTAL_BYTES/16),
    parameter int BANK_COUNT_BITS = $clog2(TOTAL_BYTES/BANK_BYTES+1)
) (
    input logic clk, rst_n, cfg_valid,
    input logic [BANK_COUNT_BITS-1:0] cfg_ia_banks,
    output logic capacity_fault,
    input logic [1:0] ia_read_en, ia_write_en,
    input logic [IA_ADDR_BITS-1:0] ia_read_addr [0:1], ia_write_addr [0:1],
    output wire [127:0] ia_read_data [0:1],
    input logic [127:0] ia_write_data [0:1],
    input logic [15:0] ia_write_mask [0:1],
    input logic [3:0] ps_read_en, ps_write_en,
    input logic [PS_ADDR_BITS-1:0] ps_read_addr [0:3], ps_write_addr [0:3],
    output wire [127:0] ps_read_data [0:3],
    input logic [127:0] ps_write_data [0:3]
);
    localparam int BANKS=TOTAL_BYTES/BANK_BYTES;
    localparam int ROWS=BANK_BYTES/16;
    localparam int ROW_BITS=$clog2(ROWS);
    localparam int BANK_BITS=$clog2(BANKS)>0 ? $clog2(BANKS) : 1;
    logic configured;
    logic [BANK_COUNT_BITS-1:0] ia_banks_q;
    logic [1:0] ia_shift_q;
    wire valid_configuration=(cfg_ia_banks==1 || cfg_ia_banks==2 || cfg_ia_banks==4) &&
        int'(cfg_ia_banks)<BANKS;
    logic [BANKS-1:0] read_en,write_en;
    logic [ROW_BITS-1:0] read_addr [0:BANKS-1],write_addr [0:BANKS-1];
    logic [127:0] write_data [0:BANKS-1];
    logic [15:0] write_mask [0:BANKS-1];
    wire [127:0] read_data [0:BANKS-1];
    logic [BANK_BITS-1:0] ia_read_bank_q [0:1],ps_read_bank_q [0:3];
    logic access_fault;
    integer bank_index,port_index,selected_bank,selected_row;
    always_comb begin
        access_fault=0;selected_bank=0;selected_row=0;read_en='0;write_en='0;
        for(bank_index=0;bank_index<BANKS;bank_index++) begin
            read_addr[bank_index]=0;write_addr[bank_index]=0;
            write_data[bank_index]=0;write_mask[bank_index]=0;
        end
        if(configured && !capacity_fault && !cfg_valid) begin
            for(port_index=0;port_index<2;port_index++) begin
                if(ia_read_en[port_index]) begin
                    selected_bank=int'(ia_read_addr[port_index])&(int'(ia_banks_q)-1);
                    selected_row=int'(ia_read_addr[port_index])>>ia_shift_q;
                    if(selected_row>=ROWS) access_fault=1;
                    else if(read_en[selected_bank]) access_fault=1;
                    else begin
                        read_en[selected_bank]=1;read_addr[selected_bank]=ROW_BITS'(selected_row);
                    end
                end
                if(ia_write_en[port_index]) begin
                    selected_bank=int'(ia_write_addr[port_index])&(int'(ia_banks_q)-1);
                    selected_row=int'(ia_write_addr[port_index])>>ia_shift_q;
                    if(selected_row>=ROWS) access_fault=1;
                    else if(write_en[selected_bank]) access_fault=1;
                    else begin
                        write_en[selected_bank]=1;write_addr[selected_bank]=ROW_BITS'(selected_row);
                        write_data[selected_bank]=ia_write_data[port_index];write_mask[selected_bank]=ia_write_mask[port_index];
                    end
                end
            end
            for(port_index=0;port_index<4;port_index++) begin
                if(ps_read_en[port_index]) begin
                    selected_bank=int'(ia_banks_q)+(int'(ps_read_addr[port_index])>>ROW_BITS);
                    if(selected_bank>=BANKS) access_fault=1;
                    else if(read_en[selected_bank]) access_fault=1;
                    else begin
                        read_en[selected_bank]=1;read_addr[selected_bank]=ROW_BITS'(ps_read_addr[port_index]);
                    end
                end
                if(ps_write_en[port_index]) begin
                    selected_bank=int'(ia_banks_q)+(int'(ps_write_addr[port_index])>>ROW_BITS);
                    if(selected_bank>=BANKS) access_fault=1;
                    else if(write_en[selected_bank]) access_fault=1;
                    else begin
                        write_en[selected_bank]=1;write_addr[selected_bank]=ROW_BITS'(ps_write_addr[port_index]);
                        write_data[selected_bank]=ps_write_data[port_index];write_mask[selected_bank]=16'hffff;
                    end
                end
            end
        end else if(|ia_read_en || |ia_write_en || |ps_read_en || |ps_write_en) access_fault=1;
        for(bank_index=0;bank_index<BANKS;bank_index++) begin
            if(read_en[bank_index] && write_en[bank_index] && |write_mask[bank_index] &&
                read_addr[bank_index]==write_addr[bank_index]) begin
                access_fault=1;
                write_en[bank_index]=0;
                write_mask[bank_index]=0;
            end
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            configured<=0;ia_banks_q<=1;ia_shift_q<=0;capacity_fault<=0;
            for(int p=0;p<2;p++)ia_read_bank_q[p]<=0;
            for(int p=0;p<4;p++)ps_read_bank_q[p]<=0;
        end else begin
            if(cfg_valid) begin
                configured<=valid_configuration;
                if(valid_configuration) begin
                    ia_banks_q<=cfg_ia_banks;
                    ia_shift_q<=cfg_ia_banks==4 ? 2 : cfg_ia_banks==2 ? 1 : 0;
                end
                capacity_fault<=!valid_configuration || access_fault;
            end else if(access_fault) capacity_fault<=1;
            if(configured && !capacity_fault && !cfg_valid) begin
                for(int p=0;p<2;p++)if(ia_read_en[p])
                    ia_read_bank_q[p]<=BANK_BITS'(int'(ia_read_addr[p])&(int'(ia_banks_q)-1));
                for(int p=0;p<4;p++)if(ps_read_en[p] &&
                    int'(ia_banks_q)+(int'(ps_read_addr[p])>>ROW_BITS)<BANKS)
                    ps_read_bank_q[p]<=BANK_BITS'(int'(ia_banks_q)+(int'(ps_read_addr[p])>>ROW_BITS));
            end
        end
    end
    for(genvar p=0;p<2;p++) assign ia_read_data[p]=read_data[ia_read_bank_q[p]];
    for(genvar p=0;p<4;p++) assign ps_read_data[p]=read_data[ps_read_bank_q[p]];
    for(genvar b=0;b<BANKS;b++) begin : g_bank
`ifdef ASIC_SRAM
        wire [127:0] bit_write_mask;
        for(genvar byte_index=0;byte_index<16;byte_index++)
            assign bit_write_mask[byte_index*8+:8]={8{write_mask[b][byte_index]}};
        smic40_sram_1r1w #(.DATA_WIDTH(128),.DEPTH(ROWS),.ADDR_WIDTH(ROW_BITS),.MACRO_DEPTH(128)) u_ram (
            .clk(clk),.write_enable(write_en[b]),.write_address(write_addr[b]),
            .write_data(write_data[b]),.write_mask(bit_write_mask),
            .read_enable(read_en[b]),.read_address(read_addr[b]),.read_data(read_data[b]));
`else
        (* ram_style="block" *) logic [127:0] ram [0:ROWS-1];
        logic [127:0] read_data_q;
        always_ff @(posedge clk) begin
            if(write_en[b])
                for(int byte_index=0;byte_index<16;byte_index++)
                    if(write_mask[b][byte_index])ram[write_addr[b]][byte_index*8+:8]<=write_data[b][byte_index*8+:8];
            if(read_en[b])read_data_q<=ram[read_addr[b]];
        end
        assign read_data[b]=read_data_q;
`endif
    end
`ifndef SYNTHESIS
    initial begin
        if(BANK_BYTES<32 || (BANK_BYTES&(BANK_BYTES-1))!=0 || TOTAL_BYTES%BANK_BYTES!=0 || BANKS<4)
            $fatal(1,"Invalid shared SRAM dimensions");
    end
`endif
endmodule
