// SPDX-License-Identifier: Apache-2.0
// 独立向量回归连接真实矩阵量化模块，逐周期检查共享请求与返回。
module vector_shared_quant_test #(
  parameter int TILE=16, BUS_WIDTH=64
) (
  input logic clk, rst_n,
  input logic quant_req_valid,
  output logic quant_req_ready,
  input logic quant_req_tag,
  input logic signed [31:0] quant_req_accumulator[TILE],
  input logic signed [31:0] quant_req_multiplier[TILE],
  input logic [5:0] quant_req_right[TILE],
  input logic [TILE-1:0] quant_req_mask,
  input logic signed [31:0] quant_req_offset, quant_req_minimum, quant_req_maximum,
  output logic quant_rsp_valid, quant_rsp_tag,
  output logic signed [7:0] quant_rsp_data[TILE]
);
  logic signed [31:0] matrix_data[TILE];
  logic matrix_valid;
  for (genvar lane=0;lane<TILE;lane++) assign matrix_data[lane]='0;

  vec_requant #(
    .BUS_WIDTH(BUS_WIDTH),.VLEN(TILE),.MAX_IA_REUSE(1),
    .ENABLE_PER_CHANNEL(1),.ENABLE_IS_MODE(1),.ENABLE_S16(1'b1),
    .p_compute_lanes(TILE),.p_input_rows(TILE)
  ) u_shared (
    .clk(clk),.rst_n(rst_n),.init_cfg(1'b0),
    .cfg_per_channel(1'b0),.cfg_dataflow_mode(1'b0),.cfg_s16(1'b0),
    .activation_min_in(-32'sd128),.activation_max_in(32'sd127),.dst_offset_in(32'sd0),
    .multiplier_in(32'sd0),.shift_in(32'sd0),.k(32'd0),.m(32'd0),.ia_reuse_num_in(32'd1),
    .load_quant_granted(1'b0),.dma_raw_data('0),.dma_raw_valid(1'b0),
    .i_group_start(1'b0),.i_group_rows(32'd0),
    .i_dw_enable(1'b1),.i_dw_valid(quant_req_valid),.o_dw_ready(quant_req_ready),
    .i_dw_tag(quant_req_tag),.i_dw_accumulator(quant_req_accumulator),
    .i_dw_multiplier(quant_req_multiplier),.i_dw_right(quant_req_right),.i_dw_mask(quant_req_mask),
    .i_dw_offset(quant_req_offset),.i_dw_minimum(quant_req_minimum),.i_dw_maximum(quant_req_maximum),
    .o_dw_valid(quant_rsp_valid),.o_dw_tag(quant_rsp_tag),
    .in_valid(1'b0),.in_tile_done(1'b0),.in_vec_s32(matrix_data),
    .out_valid(matrix_valid),.out_vec_s8(quant_rsp_data)
  );
  always_ff @(posedge clk) if (rst_n) assert(!matrix_valid);
endmodule
