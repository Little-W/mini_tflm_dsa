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
    logic configured;
    logic [BANK_COUNT_BITS-1:0] ia_banks_q;
    wire valid_configuration=(cfg_ia_banks==1 || cfg_ia_banks==2 || cfg_ia_banks==4) &&
        int'(cfg_ia_banks)<BANKS;
    logic [BANKS-1:0] read_en,write_en;
    logic [ROW_BITS-1:0] read_addr [0:BANKS-1],write_addr [0:BANKS-1];
    logic [127:0] write_data [0:BANKS-1];
    logic [15:0] write_mask [0:BANKS-1];
    wire [127:0] read_data [0:BANKS-1];
    logic access_fault;
    wire access_enabled=configured && !capacity_fault && !cfg_valid;
    logic [ROW_BITS-1:0] ia_read_row [0:1],ia_write_row [0:1];
    logic [1:0] ia_read_bank [0:1],ia_write_bank [0:1];
    logic [1:0] ia_read_range,ia_write_range;
    wire [BANKS-1:0] bank_fault;
    wire [BANKS-1:0] ia_read_selected [0:1],ps_read_selected [0:3];
    logic [BANKS-1:0] ia_read_selected_hold [0:1],ps_read_selected_hold [0:3];

    // The three legal IA allocations use fixed bit slices for bank and row.
    for(genvar p=0;p<2;p++) begin : g_ia_address
        logic [IA_ADDR_BITS-1:0] read_row_full,write_row_full;
        always_comb begin
            ia_read_bank[p]=0;ia_write_bank[p]=0;
            read_row_full=ia_read_addr[p];write_row_full=ia_write_addr[p];
            case(ia_banks_q)
                BANK_COUNT_BITS'(2): begin
                    ia_read_bank[p]={1'b0,ia_read_addr[p][0]};
                    ia_write_bank[p]={1'b0,ia_write_addr[p][0]};
                    read_row_full=ia_read_addr[p]>>1;write_row_full=ia_write_addr[p]>>1;
                end
                BANK_COUNT_BITS'(4): begin
                    ia_read_bank[p]=ia_read_addr[p][1:0];ia_write_bank[p]=ia_write_addr[p][1:0];
                    read_row_full=ia_read_addr[p]>>2;write_row_full=ia_write_addr[p]>>2;
                end
                default: ;
            endcase
            ia_read_row[p]=ROW_BITS'(read_row_full);ia_write_row[p]=ROW_BITS'(write_row_full);
            ia_read_range[p]=int'(read_row_full)<ROWS;
            ia_write_range[p]=int'(write_row_full)<ROWS;
        end
    end

    wire [3:0] ps_read_range,ps_write_range;
    for(genvar p=0;p<4;p++) begin : g_ps_range
        assign ps_read_range[p]=(ia_banks_q==BANK_COUNT_BITS'(1) && (int'(ps_read_addr[p])>>ROW_BITS)<BANKS-1) ||
            (ia_banks_q==BANK_COUNT_BITS'(2) && (int'(ps_read_addr[p])>>ROW_BITS)<BANKS-2) ||
            (ia_banks_q==BANK_COUNT_BITS'(4) && (int'(ps_read_addr[p])>>ROW_BITS)<BANKS-4);
        assign ps_write_range[p]=(ia_banks_q==BANK_COUNT_BITS'(1) && (int'(ps_write_addr[p])>>ROW_BITS)<BANKS-1) ||
            (ia_banks_q==BANK_COUNT_BITS'(2) && (int'(ps_write_addr[p])>>ROW_BITS)<BANKS-2) ||
            (ia_banks_q==BANK_COUNT_BITS'(4) && (int'(ps_write_addr[p])>>ROW_BITS)<BANKS-4);
    end

    wire ia_address_collision [0:1][0:1];
    wire ps_address_collision [0:3][0:3];
    for(genvar r=0;r<2;r++) begin : g_ia_collision
        for(genvar w=0;w<2;w++) begin : g_write
            assign ia_address_collision[r][w]=ia_read_addr[r]==ia_write_addr[w];
        end
    end
    for(genvar r=0;r<4;r++) begin : g_ps_collision
        for(genvar w=0;w<4;w++) begin : g_write
            assign ps_address_collision[r][w]=ps_read_addr[r]==ps_write_addr[w];
        end
    end

    // Each physical bank has fixed input ports and explicit first-port priority.
    for(genvar b=0;b<BANKS;b++) begin : g_port_route
        wire [5:0] read_request,write_request;
        wire [5:0] read_grant,write_grant;
        wire [5:0] read_hit,write_hit;
        logic [15:0] selected_mask;
        logic [127:0] selected_data;
        logic [ROW_BITS-1:0] selected_read_row,selected_write_row;
        wire [19:0] collision_terms;
        wire collision=|collision_terms;
        // IA and PS occupy disjoint banks. Logical-address comparisons can
        // therefore precede bank arbitration and are shared by every bank.
        for(genvar r=0;r<2;r++) begin : g_ia_collision
            for(genvar w=0;w<2;w++) begin : g_write
                assign collision_terms[2*r+w]=read_grant[r] && write_grant[w] &&
                    (|ia_write_mask[w]) && ia_address_collision[r][w];
            end
        end
        for(genvar r=0;r<4;r++) begin : g_ps_collision
            for(genvar w=0;w<4;w++) begin : g_write
                assign collision_terms[4+4*r+w]=read_grant[r+2] && write_grant[w+2] &&
                    ps_address_collision[r][w];
            end
        end
        for(genvar p=0;p<2;p++) begin : g_ia_port
            assign read_hit[p]=(b<4) && ia_read_bank[p]==2'(b);
            assign write_hit[p]=(b<4) && ia_write_bank[p]==2'(b);
            assign ia_read_selected[p][b]=read_hit[p];
            assign read_request[p]=access_enabled && ia_read_en[p] && ia_read_range[p] && read_hit[p];
            assign write_request[p]=access_enabled && ia_write_en[p] && ia_write_range[p] && write_hit[p];
        end
        for(genvar p=0;p<4;p++) begin : g_ps_port
            // Constant physical-bank offsets avoid a variable bank adder.
            assign read_hit[p+2]=(ia_banks_q==BANK_COUNT_BITS'(1) && b>=1 && (int'(ps_read_addr[p])>>ROW_BITS)==b-1) ||
                (ia_banks_q==BANK_COUNT_BITS'(2) && b>=2 && (int'(ps_read_addr[p])>>ROW_BITS)==b-2) ||
                (ia_banks_q==BANK_COUNT_BITS'(4) && b>=4 && (int'(ps_read_addr[p])>>ROW_BITS)==b-4);
            assign write_hit[p+2]=(ia_banks_q==BANK_COUNT_BITS'(1) && b>=1 && (int'(ps_write_addr[p])>>ROW_BITS)==b-1) ||
                (ia_banks_q==BANK_COUNT_BITS'(2) && b>=2 && (int'(ps_write_addr[p])>>ROW_BITS)==b-2) ||
                (ia_banks_q==BANK_COUNT_BITS'(4) && b>=4 && (int'(ps_write_addr[p])>>ROW_BITS)==b-4);
            assign ps_read_selected[p][b]=read_hit[p+2];
            assign read_request[p+2]=access_enabled && ps_read_en[p] && read_hit[p+2];
            assign write_request[p+2]=access_enabled && ps_write_en[p] && write_hit[p+2];
        end
        assign read_grant[0]=read_request[0];
        assign write_grant[0]=write_request[0];
        for(genvar p=1;p<6;p++) begin : g_priority
            assign read_grant[p]=read_request[p] && !(|read_request[p-1:0]);
            assign write_grant[p]=write_request[p] && !(|write_request[p-1:0]);
        end
        always_comb begin
            selected_read_row='0;selected_write_row='0;selected_mask='0;selected_data='0;
            for(int p=0;p<2;p++) begin
                selected_read_row |= ia_read_row[p] & {ROW_BITS{read_grant[p]}};
                selected_write_row |= ia_write_row[p] & {ROW_BITS{write_grant[p]}};
                selected_mask |= ia_write_mask[p] & {16{write_grant[p]}};
                selected_data |= ia_write_data[p] & {128{write_grant[p]}};
            end
            for(int p=0;p<4;p++) begin
                selected_read_row |= ps_read_addr[p][ROW_BITS-1:0] & {ROW_BITS{read_grant[p+2]}};
                selected_write_row |= ps_write_addr[p][ROW_BITS-1:0] & {ROW_BITS{write_grant[p+2]}};
                selected_mask |= {16{write_grant[p+2]}};
                selected_data |= ps_write_data[p] & {128{write_grant[p+2]}};
            end
        end
        assign read_en[b]=|read_request;
        assign write_en[b]=(|write_request) && !collision;
        assign read_addr[b]=selected_read_row;assign write_addr[b]=selected_write_row;
        assign write_mask[b]=collision ? 16'd0 : selected_mask;
        assign write_data[b]=selected_data;
        assign bank_fault[b]=collision || (|(read_request & ~read_grant)) || (|(write_request & ~write_grant));
    end
    always_comb begin
        access_fault=|bank_fault;
        if(access_enabled) begin
            access_fault |= |(ia_read_en & ~ia_read_range) || |(ia_write_en & ~ia_write_range) ||
                |(ps_read_en & ~ps_read_range) || |(ps_write_en & ~ps_write_range);
        end else if(|ia_read_en || |ia_write_en || |ps_read_en || |ps_write_en) access_fault=1;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            configured<=0;ia_banks_q<=1;capacity_fault<=0;
            for(int p=0;p<2;p++) ia_read_selected_hold[p]<=BANKS'(1);
            for(int p=0;p<4;p++) ps_read_selected_hold[p]<=BANKS'(1);
        end else begin
            if(cfg_valid) begin
                configured<=valid_configuration;
                if(valid_configuration) begin
                    ia_banks_q<=cfg_ia_banks;
                end
                capacity_fault<=!valid_configuration || access_fault;
            end else if(access_fault) capacity_fault<=1;
            if(access_enabled) begin
                for(int p=0;p<2;p++) if(ia_read_en[p]) ia_read_selected_hold[p]<=ia_read_selected[p];
                for(int p=0;p<4;p++) if(ps_read_en[p] && ps_read_range[p]) ps_read_selected_hold[p]<=ps_read_selected[p];
            end
        end
    end
    for(genvar p=0;p<2;p++) begin : g_ia_return
        logic [127:0] data;
        always_comb begin
            data='0;
            for(int b=0;b<BANKS;b++) data |= read_data[b] & {128{ia_read_selected_hold[p][b]}};
        end
        assign ia_read_data[p]=data;
    end
    for(genvar p=0;p<4;p++) begin : g_ps_return
        logic [127:0] data;
        always_comb begin
            data='0;
            for(int b=0;b<BANKS;b++) data |= read_data[b] & {128{ps_read_selected_hold[p][b]}};
        end
        assign ps_read_data[p]=data;
    end
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
`ifdef NPU_SIM_ASSERT
    initial begin
        if(BANK_BYTES<32 || (BANK_BYTES&(BANK_BYTES-1))!=0 || TOTAL_BYTES%BANK_BYTES!=0 || BANKS<4)
            $fatal(1,"Invalid shared SRAM dimensions");
    end
`endif
endmodule
