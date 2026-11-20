`timescale 1ns/1ps
module kernel_prefetch_tb #(
    parameter int BUS_WIDTH = 64,
    parameter int COUNT_WIDTH = 29
) (
    input logic clk,rst_n,init_cfg,cfg_command_mode,cache_flush,
    input logic prefetch_valid,
    input logic [31:0] prefetch_base_addr,prefetch_p0,prefetch_q0,prefetch_rows,prefetch_valid_cols,
    input logic cfg_im2col, cfg_tile_packed,
    input logic [31:0] cfg_p0_base,cfg_q0_base,
    input logic load_weight_granted,send_weight_trigger,
    input logic [31:0] k,n,m,rhs_base,rhs_row_stride_b,
    input logic signed [31:0] rhs_zp,
    input logic use_16bits,
    input logic [31:0] ia_reuse_num,w_reuse_num,row_groups,row_tail_tiles,col_groups,col_tail_tiles,
    output logic prefetch_idle,load_weight_req,
    output logic ext_dma_start,ext_dma_is_write,ext_dma_linear_read_mode,ext_dma_im2col,
    output logic [31:0] ext_dma_p0,ext_dma_q0,ext_dma_group,ext_dma_base_addr,ext_dma_row_stride,ext_dma_rows_to_read,
    output logic [7:0] ext_dma_burst_len_m1,
    output logic ext_dma_slot_id,ext_dma_use_16bits,
    output logic signed [31:0] ext_dma_lhs_zp,
    input logic ext_dma_busy,ext_dma_done,ext_dma_wr_slot,
    input logic [3:0] ext_dma_wr_row,ext_dma_wr_col_base,
    input logic signed [15:0] ext_dma_wr_data [BUS_WIDTH/8],
    input logic ext_dma_wr_valid [BUS_WIDTH/8],
    output logic weight_sending_done,load_weight_done,store_weight_req,weight_data_valid,
    output logic signed [15:0] weight_out [16],
    output wire [1:0] dbg_top_state,dbg_ctrl_state,dbg_prefetch_state,dbg_valid_count,
    output wire dbg_transfer_active,dbg_transfer_prefetch,dbg_transfer_discard,
    output wire dbg_prefetch_capture,dbg_prefetch_start,dbg_cache_hit,dbg_discard,
    output wire dbg_load_commit,dbg_buf_send_start,dbg_load_busy,dbg_raw_done,
    output wire dbg_window_open,dbg_demand_confirmed,dbg_managed_mode,dbg_tile_packed,
    output wire [31:0] dbg_dma_valid_cols,
    output wire [47:0] dbg_loaded_count,dbg_sent_count,
    output wire [15:0] dbg_ram_write_en,dbg_ram_read_en
);
    logic o_prefetch_quiescent;
    kernel_loader #(.DATA_WIDTH(16),.SIZE(16),.BUS_WIDTH(BUS_WIDTH),.REG_WIDTH(32),.COUNT_WIDTH(COUNT_WIDTH)) dut (.*);
    assign dbg_top_state=dut.top_state;
    assign dbg_ctrl_state=dut.u_ctrl.state;
    assign dbg_prefetch_state=dut.prefetch_state;
    assign dbg_valid_count=dut.u_buf.valid_count;
    assign dbg_transfer_active=dut.transfer_active;
    assign dbg_transfer_prefetch=dut.transfer_prefetch;
    assign dbg_transfer_discard=dut.transfer_discard;
    assign dbg_prefetch_capture=dut.prefetch_capture;
    assign dbg_prefetch_start=dut.prefetch_dma_start;
    assign dbg_cache_hit=dut.cache_hit_fire;
    assign dbg_discard=dut.discard_fire;
    assign dbg_load_commit=dut.buf_load_commit;
    assign dbg_buf_send_start=dut.buf_send_start;
    assign dbg_load_busy=|dut.response_slots_active;
    assign dbg_raw_done=dut.raw_dma_done;
    assign dbg_window_open=dut.prefetch_window_open;
    assign dbg_demand_confirmed=dut.demand_confirmed;
    assign dbg_managed_mode=dut.managed_mode;
    assign dbg_tile_packed=dut.port_descriptor.tile_packed;
    assign dbg_dma_valid_cols=dut.port_descriptor.cols;
    assign dbg_loaded_count=dut.u_ctrl.loaded_count;
    assign dbg_sent_count=dut.u_ctrl.sent_count;
    for(genvar bank=0;bank<16;bank=bank+1) begin : g_monitor
        assign dbg_ram_write_en[bank]=dut.u_buf.g_column_ram[bank].u_column.i_wr_en;
        assign dbg_ram_read_en[bank]=dut.u_buf.emit_fire && !cache_flush;
    end
endmodule
