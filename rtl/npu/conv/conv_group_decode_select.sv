// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按运行状态及归约起点选择已经完成的组范围解码结果。
(* keep_hierarchy = "yes" *)
module conv_group_decode_select (
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前前端运行状态
  input wire logic i_q_nonzero, // 当前归约起点非零
  input wire logic i_group_shape, // 通道组支持按二次幂直接解码
  input wire logic i_group_three, // 当前通道组大小为三
  input wire logic i_q_before_limit, // 归约起点处于三通道快速解码范围
  input wire logic i_decode_match, // 通用解码已经到达当前归约起点
  output logic [3:0] o_select // 零起点、二次幂、三通道及通用解码的选择位
);
  import conv_im2col_frontend_pkg::*;
  logic decode_write;
  logic [3:0] decode_select;
  always_comb begin
    decode_write = 1'b0;
    decode_select = 4'b1000;
    unique case (1'b1)
      i_state[$clog2(P_DECODE)], i_state[$clog2(P_START)], i_state[$clog2(P_WAIT)]: ;
      i_state[$clog2(Q_DECODE)]: begin
        if (!i_q_nonzero) begin
          decode_write = 1'b1;
          decode_select = 4'b0001;
        end else if (i_group_shape) begin
          decode_write = 1'b1;
          decode_select = 4'b0010;
        end else if (i_group_three && i_q_before_limit) begin
          decode_write = 1'b1;
          decode_select = 4'b0100;
        end
      end
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: if (i_decode_match) decode_write = 1'b1;
      default: ;
    endcase
  end
  assign o_select = {4{decode_write}} & decode_select;
endmodule

`default_nettype wire
