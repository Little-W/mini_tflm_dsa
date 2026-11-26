// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 描述符范围、填充和字命中各自完成后，独立选择下一运行状态。
module conv_im2col_descriptor_state #(
  parameter bit p_register_descriptor = 1'b0
) (
  input wire logic i_invalid, // 描述符参数超出有效范围。
  input wire logic i_fast, // 描述符具有已准备的快速路径数据。
  input wire logic i_padding, // 描述符首个输出位置为填充。
  input wire logic i_word_hit, // 描述符命中已保存或返回的缓存字。
  input wire logic i_cache_req_ready, // 缓存请求能够被接收。
  output conv_im2col_frontend_pkg::st_t o_state // 描述符接收后的运行状态。
);
  import conv_im2col_frontend_pkg::*;

  always_comb begin
    o_state = IDLE;
    if (i_invalid) begin
      o_state = IDLE;
    end else if (i_fast) begin
      if (p_register_descriptor) o_state = DESCRIPTOR_CHECK;
      else if (i_padding) o_state = ZERO_STREAM;
      else if (i_word_hit) o_state = STREAM;
      else o_state = i_cache_req_ready ? WAIT_WORD : FETCH;
    end else if (p_register_descriptor) o_state = P_HISTORY;
    else o_state = P_DECODE;
  end
endmodule
`default_nettype wire
