`default_nettype none
// 两个完整分时量化实例接收相同行序，第二个实例的生产者增加一个寄存边沿。
module requant_time_share_tb #(
    parameter int p_bus_width = 64,
    parameter int p_vlen = 16,
    parameter int p_lanes = 2,
    parameter int p_reuse = 32
) (
    input logic clk, rst_n, init_cfg,
    input logic cfg_per_channel, cfg_is, cfg_s16,
    input logic signed [31:0] cfg_min, cfg_max, cfg_offset, cfg_multiplier, cfg_shift,
    input logic [31:0] cfg_rows, cfg_columns, cfg_reuse,
    input logic group_start,
    input logic [31:0] group_rows,
    input logic input_valid, input_tile_done,
    input logic signed [31:0] input_data [p_vlen],
    input logic [1:0] dma_granted, dma_raw_valid,
    input logic [p_bus_width-1:0] dma_raw_data [2],
    output logic [1:0] group_ready, params_ready, dma_request, dma_start,
    output logic [31:0] dma_addr [2],
    output logic [7:0] dma_burst [2],
    output logic [1:0] output_valid, output_tile_done,
    output logic signed [7:0] output_s8 [2][p_vlen],
    output logic signed [15:0] output_s16 [2][p_vlen]
);
    logic staged_valid_q, staged_tile_done_q;
    logic signed [31:0] staged_data_q [p_vlen];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            staged_valid_q <= 1'b0;
            staged_tile_done_q <= 1'b0;
            for (int lane = 0; lane < p_vlen; lane++) staged_data_q[lane] <= '0;
        end else if (init_cfg) begin
            staged_valid_q <= 1'b0;
            staged_tile_done_q <= 1'b0;
        end else begin
            staged_valid_q <= input_valid;
            staged_tile_done_q <= input_tile_done;
            for (int lane = 0; lane < p_vlen; lane++) staged_data_q[lane] <= input_data[lane];
        end
    end

    for (genvar variant = 0; variant < 2; variant++) begin : g_variant
        logic quant_i_valid, quant_i_tile_done;
        logic signed [31:0] quant_i_data [p_vlen];
        assign quant_i_valid = (variant == 0) ? input_valid : staged_valid_q;
        assign quant_i_tile_done = (variant == 0) ? input_tile_done : staged_tile_done_q;
        assign quant_i_data = (variant == 0) ? input_data : staged_data_q;

        vec_requant #(
            .BUS_WIDTH(p_bus_width), .VLEN(p_vlen), .MAX_IA_REUSE(p_reuse),
            .ENABLE_S16(1'b1), .p_compute_lanes(p_lanes), .p_input_rows(p_vlen*p_reuse)
        ) u_quant (
            .clk(clk), .rst_n(rst_n), .init_cfg(init_cfg),
            .cfg_per_channel(cfg_per_channel), .cfg_dataflow_mode(cfg_is), .cfg_s16(cfg_s16),
            .activation_min_in(cfg_min), .activation_max_in(cfg_max), .dst_offset_in(cfg_offset),
            .multiplier_in(cfg_multiplier), .shift_in(cfg_shift),
            .k(cfg_rows), .m(cfg_columns), .ia_reuse_num_in(cfg_reuse),
            .i_group_start(group_start), .i_group_rows(group_rows), .o_group_ready(group_ready[variant]),
            .load_quant_req(dma_request[variant]), .load_quant_granted(dma_granted[variant]),
            .quant_params_valid(params_ready[variant]), .dma_start(dma_start[variant]),
            .dma_is_write(), .dma_linear_read_mode(), .dma_base_addr(dma_addr[variant]),
            .dma_row_stride(), .dma_rows_to_read(), .dma_burst_len_m1(dma_burst[variant]),
            .dma_slot_id(), .dma_use_16bits(), .dma_lhs_zp(),
            .dma_raw_data(dma_raw_data[variant]), .dma_raw_valid(dma_raw_valid[variant]),
            .in_valid(quant_i_valid), .in_tile_done(quant_i_tile_done), .in_vec_s32(quant_i_data),
            .out_valid(output_valid[variant]), .out_tile_done(output_tile_done[variant]),
            .out_vec_s8(output_s8[variant]), .out_vec_s16(output_s16[variant]),
            .quant_multiplier_lane(), .quant_shift_lane()
        );
    end
endmodule
`default_nettype wire
