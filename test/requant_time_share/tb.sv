`default_nettype none
module requant_time_share_tb #(
    parameter int p_bus_width=64,
    parameter int p_vlen=16,
    parameter int p_lanes=4,
    parameter int p_reuse=32
) (
    input logic clk, rst_n, init_cfg,
    input logic cfg_per_channel, cfg_is, cfg_s16,
    input logic signed [31:0] cfg_min, cfg_max, cfg_offset, cfg_multiplier, cfg_shift,
    input logic [31:0] cfg_rows, cfg_columns, cfg_reuse,
    input logic group_start,
    input logic [31:0] group_rows,
    input logic input_valid, input_tile_done,
    input logic signed [31:0] input_data[p_vlen],
    input logic [1:0] dma_granted, dma_raw_valid,
    input logic [p_bus_width-1:0] dma_raw_data[2],
    output wire [1:0] group_ready, params_ready, dma_request, dma_start,
    output wire [31:0] dma_addr[2],
    output wire [7:0] dma_burst[2],
    output wire [1:0] output_valid, output_tile_done,
    output wire signed [7:0] output_s8[2][p_vlen],
    output wire signed [15:0] output_s16[2][p_vlen]
);
    for(genvar variant=0;variant<2;variant++)begin:g_variant
        vec_requant #(.BUS_WIDTH(p_bus_width),.VLEN(p_vlen),.MAX_IA_REUSE(p_reuse),
            .ENABLE_S16(1'b1),.p_compute_lanes(variant==0 ? p_vlen : p_lanes),
            .p_input_rows(p_vlen*p_reuse)) u_quant (
            .clk(clk),.rst_n(rst_n),.init_cfg(init_cfg),
            .cfg_per_channel(cfg_per_channel),.cfg_dataflow_mode(cfg_is),.cfg_s16(cfg_s16),
            .activation_min_in(cfg_min),.activation_max_in(cfg_max),.dst_offset_in(cfg_offset),
            .multiplier_in(cfg_multiplier),.shift_in(cfg_shift),
            .k(cfg_rows),.m(cfg_columns),.ia_reuse_num_in(cfg_reuse),
            .i_group_start(group_start),.i_group_rows(group_rows),.o_group_ready(group_ready[variant]),
            .load_quant_req(dma_request[variant]),.load_quant_granted(dma_granted[variant]),
            .quant_params_valid(params_ready[variant]),.dma_start(dma_start[variant]),
            .dma_is_write(),.dma_linear_read_mode(),.dma_base_addr(dma_addr[variant]),
            .dma_row_stride(),.dma_rows_to_read(),.dma_burst_len_m1(dma_burst[variant]),
            .dma_slot_id(),.dma_use_16bits(),.dma_lhs_zp(),
            .dma_raw_data(dma_raw_data[variant]),.dma_raw_valid(dma_raw_valid[variant]),
            .in_valid(input_valid),.in_tile_done(input_tile_done),.in_vec_s32(input_data),
            .out_valid(output_valid[variant]),.out_tile_done(output_tile_done[variant]),
            .out_vec_s8(output_s8[variant]),.out_vec_s16(output_s16[variant]),
            .quant_multiplier_lane(),.quant_shift_lane()
        );
    end
endmodule
`default_nettype wire
