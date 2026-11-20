// SPDX-License-Identifier: Apache-2.0
module shared_quant_top (
  input logic clk, rst_n, init_cfg, dw_enable, in_valid, in_tile_done,
  input logic signed [31:0] matrix_multiplier, matrix_shift,
  input logic signed [31:0] output_offset, activation_minimum, activation_maximum,
  input logic signed [31:0] input_data[16],
  input logic dw_valid, dw_tag,
  output logic dw_ready, dw_out_valid, dw_out_tag, matrix_out_valid,
  input logic signed [31:0] dw_multiplier[16],
  input logic [5:0] dw_right[16],
  input logic [15:0] dw_mask,
  output logic signed [7:0] output_data[16]
);
  vec_requant #(
    .BUS_WIDTH(64),.VLEN(16),.MAX_IA_REUSE(1),
    .ENABLE_PER_CHANNEL(1),.ENABLE_IS_MODE(1),.ENABLE_S16(1'b1),
    .p_compute_lanes(16),.p_input_rows(16)
  ) u_quant (
    .clk(clk),.rst_n(rst_n),.init_cfg(init_cfg),
    .cfg_per_channel(1'b0),.cfg_dataflow_mode(1'b0),.cfg_s16(1'b0),
    .activation_min_in(activation_minimum),.activation_max_in(activation_maximum),
    .dst_offset_in(output_offset),.multiplier_in(matrix_multiplier),.shift_in(matrix_shift),
    .k(32'd32),.m(32'd16),.ia_reuse_num_in(32'd1),
    .load_quant_granted(1'b0),.dma_raw_data(64'd0),.dma_raw_valid(1'b0),
    .i_group_start(1'b0),.i_group_rows(32'd0),
    .i_dw_enable(dw_enable),.i_dw_valid(dw_valid),.o_dw_ready(dw_ready),
    .i_dw_tag(dw_tag),.i_dw_accumulator(input_data),.i_dw_multiplier(dw_multiplier),
    .i_dw_right(dw_right),.i_dw_mask(dw_mask),
    .i_dw_offset(output_offset),.i_dw_minimum(activation_minimum),.i_dw_maximum(activation_maximum),
    .o_dw_valid(dw_out_valid),.o_dw_tag(dw_out_tag),
    .in_valid(in_valid),.in_tile_done(in_tile_done),.in_vec_s32(input_data),
    .out_valid(matrix_out_valid),.out_vec_s8(output_data)
  );
endmodule
