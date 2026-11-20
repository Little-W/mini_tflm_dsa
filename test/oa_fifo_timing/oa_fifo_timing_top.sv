`default_nettype none

module oa_fifo_timing_top #(
    parameter int unsigned VLEN       = 16,
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned REG_WIDTH  = 32,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned ENABLE_IS_MODE = 1
) (
    input logic in_valid,
    input logic in_tile_done,
    input logic [VLEN*8-1:0] in_vec_s8,
    input logic [31:0] reserve_banks,
    input logic start_permitted,
    output logic fifo_full_flag,
    input logic clk,
    input logic rst_n,

    input  logic init_cfg,
    output logic write_oa_req,
    input  logic write_oa_granted,

    input logic [REG_WIDTH-1:0] dst_base,
    input logic [REG_WIDTH-1:0] dst_row_stride_b,
    input logic [REG_WIDTH-1:0] k,
    input logic [REG_WIDTH-1:0] m,
    input logic [REG_WIDTH-1:0] ia_reuse_num,
    input logic                 is_mode,
    input logic                 output_16bits,
    input logic                 coalesce_enable,
    input logic [4:0]           coalesce_cols,
    output logic                coalesce_group_start,
    output logic [4:0]          coalesce_row_tiles,

    output  logic                    oa_fifo_req,
    output logic [$clog2(VLEN)-1:0] vec_valid_num_col,
    output logic [$clog2(VLEN)-1:0] vec_valid_num_row,

    output  logic                   output_valid,
    output  logic                   switch_row,
    output logic                   output_ready,
    output  logic [BUS_WIDTH/8-1:0] output_mask,
    output  logic [BUS_WIDTH-1:0]   output_data,

    output logic                        dma_start,
    output logic                        dma_is_write,
    output logic                        dma_linear_read_mode,
    output logic [REG_WIDTH-1:0]        dma_base_addr,
    output logic [REG_WIDTH-1:0]        dma_row_stride,
    output logic [REG_WIDTH-1:0]        dma_rows_to_read,
    output logic [7:0]                  dma_burst_len_m1,
    output logic                        dma_slot_id,
    output logic                        dma_use_16bits,
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp,
    output logic [BUS_WIDTH-1:0]        dma_src_wdata,
    output logic [BUS_WIDTH/8-1:0]      dma_src_wmask,
    output logic                        dma_src_wvalid,
    input  logic                        dma_src_wready,
    input  logic                        dma_busy,
    input  logic                        dma_done,

    output logic write_done,
    output logic oa_calc_over
);

    logic [31:0] fifo_rows, fifo_cols;
    assign fifo_rows = 32'(coalesce_row_tiles);
    assign fifo_cols = 32'(coalesce_cols);
    oa_writer #(.VLEN(VLEN), .DATA_WIDTH(DATA_WIDTH), .REG_WIDTH(REG_WIDTH),
                .BUS_WIDTH(BUS_WIDTH), .COUNT_WIDTH(COUNT_WIDTH), .ENABLE_IS_MODE(ENABLE_IS_MODE)) u_writer (
        .clk(clk),
        .rst_n(rst_n),
        .init_cfg(init_cfg),
        .write_oa_req(write_oa_req),
        .write_oa_granted(write_oa_granted),
        .dst_base(dst_base),
        .dst_row_stride_b(dst_row_stride_b),
        .k(k),
        .m(m),
        .ia_reuse_num(ia_reuse_num),
        .is_mode(is_mode),
        .output_16bits(output_16bits),
        .coalesce_enable(coalesce_enable),
        .coalesce_cols(coalesce_cols),
        .coalesce_group_start(coalesce_group_start),
        .coalesce_row_tiles(coalesce_row_tiles),
        .oa_fifo_req(oa_fifo_req),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid(output_valid),
        .switch_row(switch_row),
        .output_ready(output_ready),
        .output_mask(output_mask),
        .output_data(output_data),
        .dma_start(dma_start),
        .dma_is_write(dma_is_write),
        .dma_linear_read_mode(dma_linear_read_mode),
        .dma_base_addr(dma_base_addr),
        .dma_row_stride(dma_row_stride),
        .dma_rows_to_read(dma_rows_to_read),
        .dma_burst_len_m1(dma_burst_len_m1),
        .dma_slot_id(dma_slot_id),
        .dma_use_16bits(dma_use_16bits),
        .dma_lhs_zp(dma_lhs_zp),
        .dma_src_wdata(dma_src_wdata),
        .dma_src_wmask(dma_src_wmask),
        .dma_src_wvalid(dma_src_wvalid),
        .dma_src_wready(dma_src_wready),
        .dma_busy(dma_busy),
        .dma_done(dma_done),
        .write_done(write_done),
        .oa_calc_over(oa_calc_over)
    );
    vec_s8_to_fifo_full #(.VLEN(VLEN), .BANKS(32), .BUS_WIDTH(BUS_WIDTH),
                         .ENABLE_TRANSPOSE(ENABLE_IS_MODE), .p_cyclic_storage(1'b1)) u_fifo (
        .clk(clk), .rst_n(rst_n), .start_permitted(start_permitted),
        .in_valid(in_valid), .in_tile_done(in_tile_done), .in_vec_s8(in_vec_s8),
        .oa_fifo_req(oa_fifo_req), .transpose_mode(is_mode), .coalesce_enable(coalesce_enable),
        .coalesce_group_start(coalesce_group_start), .coalesce_rows(fifo_rows),
        .coalesce_cols(fifo_cols), .reserve_banks(reserve_banks),
        .vec_valid_num_col(vec_valid_num_col), .vec_valid_num_row(vec_valid_num_row),
        .output_valid(output_valid), .output_ready(output_ready), .output_row_switch(switch_row),
        .output_mask(output_mask), .output_data(output_data), .fifo_full_flag(fifo_full_flag)
    );
endmodule
`default_nettype wire
