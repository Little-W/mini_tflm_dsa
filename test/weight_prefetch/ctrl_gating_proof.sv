// SPDX-License-Identifier: Apache-2.0
// 检查实际加载控制器的发送输出只能来自当前控制器发送请求。
module ctrl_gating_proof(input logic clk,rst_n,i_clear,i_trigger,i_valid,i_cfg_valid,i_granted,i_done);
 wire send_start;
 kernel_loader_ctrl #(.SIZE(16),.REG_WIDTH(32),.COUNT_WIDTH(29)) u_control (
  .clk(clk),.rst_n(rst_n),.clear(i_clear),.cfg_valid(i_cfg_valid),
  .cfg_k(32'd48),.cfg_n(32'd33),.cfg_m(32'd51),.cfg_rhs_base(32'h1000),.cfg_rhs_row_stride_b(32'd33),
  .cfg_rhs_zp(32'd0),.cfg_use_16bits(1'b0),.cfg_tile_packed(1'b0),
  .cfg_ia_reuse_num(32'd1),.cfg_w_reuse_num(32'd1),.cfg_row_groups(32'd3),.cfg_row_tail_tiles(32'd1),
  .cfg_col_groups(32'd4),.cfg_col_tail_tiles(32'd1),
  .load_weight_granted(i_granted),.send_weight_trigger(i_trigger),.buf_weight_data_valid(i_valid),
  .buf_weight_sending_done(i_done),.buf_load_ready(1'b1),.load_done(i_done),
  .buf_send_start(send_start)
 );
 always_comb assert(!send_start || i_trigger);
endmodule
