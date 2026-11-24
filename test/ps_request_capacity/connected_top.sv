// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保留部分和帧存储、任务端口选择和物理共享 RAM 的组合连接。
module ps_shared_connected #(
    parameter int MAX_FRAME_ROWS=256, FRAME_COUNT=16, POOL_BYTES=49152, BANK_BYTES=8192,
    parameter int DECODE_FIFO_ROWS=8, EXTERNAL_RAM=1, DIRECTORY_ROWS=1024,
    parameter int p_bank_bytes=BANK_BYTES, p_total_bytes=POOL_BYTES+BANK_BYTES,
    parameter int p_addr_width=$clog2(p_total_bytes/16), RAM_ADDR_BITS=p_addr_width,
    parameter int p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1)
) (
    input wire clk ,
    input wire rst_n ,
    input wire cfg_valid ,
    input wire [31:0] cfg_pool_bank_words ,
    input wire [31:0] cfg_pool_bank_count ,
    input wire [31:0] cfg_directory_stride ,
    input wire frame_request ,
    input wire frame_accept ,
    input wire [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id ,
    input wire [31:0] frame_rows ,
    input wire [31:0] frame_reserve_rows ,
    input wire [2:0] frame_word_cap ,
    input wire frame_init ,
    input wire frame_final ,
    input wire force_raw_i ,
    output wire frame_ready ,
    output wire frame_pressure ,
    output reg capacity_fault ,
    output reg frame_complete ,
    input wire write_valid ,
    input wire [511:0] write_data ,
    input wire write_frame_end ,
    input wire replay_trigger ,
    output wire [511:0] replay_data ,
    output reg replay_valid ,
    input wire logic i_access_enable ,
    input wire logic i_cfg_valid ,
    input wire logic [p_bank_count_width-1:0] i_cfg_ia_banks ,
    output logic o_capacity_fault ,
    input wire logic [1:0] i_ia_read_en ,
    input wire logic [1:0] i_ia_write_en ,
    input wire logic [p_addr_width-1:0] i_ia_read_addr [2],
    input wire logic [p_addr_width-1:0] i_ia_write_addr [2],
    output logic [127:0] o_ia_read_data [2],
    input wire logic [127:0] i_ia_write_data [2],
    input wire logic [127:0] i_ia_shared_write_data ,
    input wire logic [15:0] i_ia_write_mask [2],
    input logic run_vector ,
    input wire logic [3:0] vector_i_ps_read_en ,
    input wire logic [3:0] vector_i_ps_write_en ,
    input wire logic [p_addr_width-1:0] vector_i_ps_read_addr [4],
    input wire logic [p_addr_width-1:0] vector_i_ps_write_addr [4],
    input wire logic [127:0] vector_i_ps_write_data [4],
    output logic [127:0] vector_ps_read_data [4]
);
    logic [3:0] ram_read_en ;
    logic [RAM_ADDR_BITS-1:0] ram_read_addr [0:3];
    logic [127:0] ram_read_data [0:3];
    logic [3:0] ram_write_en ;
    logic [RAM_ADDR_BITS-1:0] ram_write_addr [0:3];
    logic [127:0] ram_write_data [0:3];
    logic [3:0] i_ps_read_en ;
    logic [3:0] i_ps_write_en ;
    logic [p_addr_width-1:0] i_ps_read_addr [4];
    logic [p_addr_width-1:0] i_ps_write_addr [4];
    logic [127:0] i_ps_write_data [4];
    ps_frame_store #(
        .MAX_FRAME_ROWS(MAX_FRAME_ROWS),.FRAME_COUNT(FRAME_COUNT),.POOL_BYTES(POOL_BYTES),
        .BANK_BYTES(BANK_BYTES),.DECODE_FIFO_ROWS(DECODE_FIFO_ROWS),.EXTERNAL_RAM(1),
        .p_fixed_ps_channels(1),.DIRECTORY_ROWS(DIRECTORY_ROWS),.RAM_ADDR_BITS(RAM_ADDR_BITS)
    ) u_ps_store (
        .clk(clk),
        .rst_n(rst_n),
        .cfg_valid(cfg_valid),
        .cfg_pool_bank_words(cfg_pool_bank_words),
        .cfg_pool_bank_count(cfg_pool_bank_count),
        .cfg_directory_stride(cfg_directory_stride),
        .ram_read_en(ram_read_en),
        .ram_read_addr(ram_read_addr),
        .ram_read_data(ram_read_data),
        .ram_write_en(ram_write_en),
        .ram_write_addr(ram_write_addr),
        .ram_write_data(ram_write_data),
        .frame_request(frame_request),
        .frame_accept(frame_accept),
        .frame_id(frame_id),
        .frame_rows(frame_rows),
        .frame_reserve_rows(frame_reserve_rows),
        .frame_word_cap(frame_word_cap),
        .frame_init(frame_init),
        .frame_final(frame_final),
        .force_raw_i(force_raw_i),
        .frame_ready(frame_ready),
        .frame_pressure(frame_pressure),
        .capacity_fault(capacity_fault),
        .frame_complete(frame_complete),
        .write_valid(write_valid),
        .write_data(write_data),
        .write_frame_end(write_frame_end),
        .replay_trigger(replay_trigger),
        .replay_data(replay_data),
        .replay_valid(replay_valid)
    );
    assign i_ps_read_en = run_vector ? vector_i_ps_read_en : ram_read_en;
    assign i_ps_read_addr = run_vector ? vector_i_ps_read_addr : ram_read_addr;
    assign i_ps_write_en = run_vector ? vector_i_ps_write_en : ram_write_en;
    assign i_ps_write_addr = run_vector ? vector_i_ps_write_addr : ram_write_addr;
    assign i_ps_write_data = run_vector ? vector_i_ps_write_data : ram_write_data;
    assign vector_ps_read_data=ram_read_data;
    ia_ps_channel_ram #(.p_bank_bytes(p_bank_bytes),.p_total_bytes(p_total_bytes),
        .p_shared_write_stage(1),.p_ia_nonempty_writes(1)) u_shared_ram (
        .clk(clk),
        .rst_n(rst_n),
        .i_access_enable(i_access_enable),
        .i_cfg_valid(i_cfg_valid),
        .i_cfg_ia_banks(i_cfg_ia_banks),
        .o_capacity_fault(o_capacity_fault),
        .i_ia_read_en(i_ia_read_en),
        .i_ia_write_en(i_ia_write_en),
        .i_ia_read_addr(i_ia_read_addr),
        .i_ia_write_addr(i_ia_write_addr),
        .o_ia_read_data(o_ia_read_data),
        .i_ia_write_data(i_ia_write_data),
        .i_ia_shared_write_data(i_ia_shared_write_data),
        .i_ia_write_mask(i_ia_write_mask),
        .i_ps_read_en(i_ps_read_en),
        .i_ps_write_en(i_ps_write_en),
        .i_ps_read_addr(i_ps_read_addr),
        .i_ps_write_addr(i_ps_write_addr),
        .o_ps_read_data(ram_read_data),
        .i_ps_write_data(i_ps_write_data)
    );
endmodule
`default_nettype wire
