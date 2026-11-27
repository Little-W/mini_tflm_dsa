// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行解码正式输入与已保存请求的释放行号，最后选择完整的三十二位释放序号。
// 位[17:0]保存行号，位[21:18]保存右移量，位22表示禁止释放。
module conv_cache_retire_decode (
  input wire logic i_use_incoming, // 当前处理采用正式输入请求的元数据
  input wire logic [31:0] i_incoming, // 正式输入请求的完整释放描述
  input wire logic [31:0] i_saved, // 已保存请求的完整释放描述
  output logic [31:0] o_retire // 处理请求对应的完整释放序号
);
  logic [1:0][31:0] payload;
  logic [1:0][17:0] low_shift, full_shift;
  logic [31:0] selected_payload;
  logic [31:0] parallel_result;

  assign payload = {i_incoming, i_saved};
  for (genvar source_index = 0; source_index < 2; source_index++) begin : g_source
    conv_cache_retire_shift #(.p_step(1)) u_low (
      .i_row(payload[source_index][17:0]), .i_shift(payload[source_index][19:18]),
      .o_row(low_shift[source_index])
    );
    conv_cache_retire_shift #(.p_step(4)) u_high (
      .i_row(low_shift[source_index]), .i_shift(payload[source_index][21:20]),
      .o_row(full_shift[source_index])
    );
  end
  for (genvar bit_index = 0; bit_index < 18; bit_index++) begin : g_bit
    conv_cache_retire_select u_select (
      .i_use_incoming(i_use_incoming), .i_incoming_disabled(i_incoming[22]),
      .i_saved_disabled(i_saved[22]), .i_incoming_bit(full_shift[1][bit_index]),
      .i_saved_bit(full_shift[0][bit_index]), .o_bit(parallel_result[bit_index])
    );
  end
  conv_cache_retire_select u_upper (
    .i_use_incoming(i_use_incoming), .i_incoming_disabled(i_incoming[22]),
    .i_saved_disabled(i_saved[22]), .i_incoming_bit(1'b0), .i_saved_bit(1'b0),
    .o_bit(parallel_result[18])
  );
  assign parallel_result[31:19] = {13{parallel_result[18]}};

  always_comb begin
    selected_payload = i_saved;
    if (i_use_incoming) selected_payload = i_incoming;
    o_retire = parallel_result;
    // 完整移位量含有未知位时，保持语言规定的三十二位移位结果。
    case (^selected_payload[21:18])
      1'b0, 1'b1: begin end
      default: o_retire = selected_payload[22] ? 32'hffff_ffff :
          ({14'd0, selected_payload[17:0]} >> selected_payload[21:18]);
    endcase
  end
endmodule

`default_nettype wire
