module ia_prefetch_tb #(parameter bit ORDERED_JOB = 0) (
    input logic clk, rst_n, init_cfg,
    input logic cfg_im2col, cfg_tile_packed, cfg_compact, cfg_preserve_cache, cache_flush,
    input logic cfg_prefetch_enable,
    input logic [31:0] cfg_global_reduction,
    input logic signed [31:0] cfg_compact_offset,
    input logic [31:0] cfg_p0_base, cfg_q0_base, cfg_cache_slot_base,
    input logic [31:0] k, n, m, lhs_base, lhs_row_stride_b,
    input logic signed [31:0] lhs_zp,
    input logic use_16bits, bias_by_row_mode,
    input logic [31:0] ia_reuse_num, w_reuse_num,
    input logic [31:0] row_groups, row_tail_tiles, col_groups, col_tail_tiles,
    output logic load_ia_req,
    input logic load_ia_granted, send_ia_trigger,
    output logic ext_dma_start, ext_dma_im2col,
    output logic [31:0] ext_dma_p0, ext_dma_q0, ext_dma_group,
    output logic [31:0] ext_dma_base_addr, ext_dma_row_stride, ext_dma_rows_to_read,
    output logic [7:0] ext_dma_burst_len_m1,
    output logic [2:0] ext_dma_slot_id,
    output logic ext_dma_use_16bits,
    output logic signed [31:0] ext_dma_lhs_zp,
    input logic ext_dma_busy, ext_dma_done,
    input logic [2:0] ext_dma_wr_slot,
    input logic [3:0] ext_dma_wr_row, ext_dma_wr_col_base,
    input logic signed [15:0] ext_dma_wr_data [4],
    input logic ext_dma_wr_valid [4],
    input logic ext_dma_wr_use_16bits,
    output logic signed [15:0] ia_out [16],
    output logic lane_valid [16],
    output logic idle, complete, compact_active, cache_hit,
    output logic prefetch_idle, prefetch_enabled, prefetch_launch, prefetch_inflight, prefetch_issue,
    output logic prefetch_pending, demand_complete, demand_request, group_start,
    output logic [31:0] active_valid_cols,
    output logic ia_data_valid, ia_sending_done, ia_row_valid,
    output logic [31:0] ps_frame_rows, ps_frame_id,
    output logic ps_frame_init, ps_frame_final
);
    ia_loader #(.CACHE_BLOCKS(4), .COMPACT_S8(1), .PS_FRAME_COUNT(16), .ORDERED_JOB(ORDERED_JOB)) u_loader (
        .*, .ext_dma_is_write(), .ext_dma_linear_read_mode(),
        .cfg_cache_blocks(32'd0), .bias_at_end(1'b0), .bias_load_sleep(),
        .ram_port_wr_en(), .ram_port_wr_addr(), .ram_port_wr_data(), .ram_port_wr_mask(),
        .ram_port_rd_en(), .ram_port_rd_addr(), .ram_port_rd_data('{default:'0}),
        .ia_is_init_data(), .ia_calc_done(), .ia_tile_start(),
        .ia_output_pending(), .bias_sleep(), .bias_switch(), .bias_last_loop(), .ia_l1_switch()
    );
    assign idle = (u_loader.state == 2'b00);
    assign complete = u_loader.ctrl_all_done;
    assign compact_active = u_loader.cfg_compact_q;
    assign cache_hit = u_loader.cache_hit_event;
    assign prefetch_enabled = u_loader.prefetch_enable_q;
    assign prefetch_launch = u_loader.prefetch_start;
    assign prefetch_issue = u_loader.prefetch_issue;
    assign prefetch_inflight = u_loader.prefetch_inflight;
    assign prefetch_pending = u_loader.prefetch_pending;
    assign demand_complete = u_loader.tl_tile_done;
    assign demand_request = u_loader.ctrl_load_req;
    assign group_start = u_loader.cache_l1_start;
    assign active_valid_cols = u_loader.active_valid_cols;
    for (genvar lane = 0; lane < 16; lane++) begin : g_valid
        assign lane_valid[lane] = u_loader.u_cache_mgr.ram_rd_en_d1[lane];
    end
endmodule
