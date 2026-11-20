module read_mode_control #(
    parameter bit CONV_SUPPORTED=1'b1,
    parameter int REG_WIDTH=32, IM2COL_SIZE=16, SLOT_W=6, RD_TAG_WIDTH=3,
    parameter int CONV_RW=$clog2(IM2COL_SIZE+1)
) (
    input logic clk, rst_n, cfg_fire, conv_enable, dma_range_enable,
    input logic accept_read, rd_im2col, fe_error, fe_tile_ready,
    input logic fe_done, fe_tile_error, fe_busy, guard_idle, mux_idle,
    input logic [RD_TAG_WIDTH-1:0] rd_tag,
    input logic [31:0] rd_p0, rd_q0, rd_group,
    input logic [REG_WIDTH-1:0] rd_rows_to_read, rd_valid_cols,
    input logic [SLOT_W-1:0] rd_slot_id,
    output logic [511:0] formal_state,
    output logic formal_read_guard
);
    logic job_conv, @@MODE_NAME@@;
    logic conv_active, conv_pending, conv_finished, conv_command_error;
    logic conv_done_r, conv_done_error, descriptor_error, command_im2col;
    logic [RD_TAG_WIDTH-1:0] conv_tag_q;
    logic [31:0] p0_q, q0_q, group_q;
    logic [CONV_RW-1:0] rows_q, cols_q;
    logic [SLOT_W-1:0] slot_q;
@@CONTROL@@
    assign formal_state={@@STATE@@};
    assign formal_read_guard=@@GUARD@@;
endmodule
