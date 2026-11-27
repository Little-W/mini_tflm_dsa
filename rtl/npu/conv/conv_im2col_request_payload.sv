// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行准备普通请求、连续像素首项和后续项的地址与像素位置，再作单级来源归并。
// 完整定宽加法保留地址回绕和未知输入语义，选择位由请求控制模块产生。
module conv_im2col_request_payload #(
  parameter int unsigned p_word_shift = 4 // 一个缓存读取字对应的字节地址低位数
) (
  input wire logic [2:0] i_select, // 普通请求、连续首项及后续项的独热选择
  input wire logic [31:0] i_address, // 普通请求的完整字节地址
  input wire logic [31:0] i_pixel, // 普通请求的完整像素位置
  input wire logic [31:0] i_seed_address, // 连续请求首项的完整字节地址
  input wire logic [31:0] i_seed_pixel, // 连续请求首项的完整像素位置
  input wire logic [31:0] i_saved_address, // 最近保存请求的完整字节地址
  input wire logic [31:0] i_saved_pixel, // 最近保存请求的完整像素位置
  output logic [31:0] o_address, // 选中请求的完整字节地址
  output logic [31:0] o_pixel // 选中请求的完整像素位置
);
  logic [31:p_word_shift] next_word;
  logic [31:0] next_pixel;
  logic [63:0] selected_payload;
  conditional_increment #(.p_width(32-p_word_shift),.p_group_width(6)) u_word_step (
    .i_value(i_saved_address[31:p_word_shift]), .i_enable(1'b1), .o_result(next_word)
  );
  conditional_increment #(.p_width(32),.p_group_width(6)) u_pixel_step (
    .i_value(i_saved_pixel), .i_enable(1'b1), .o_result(next_pixel)
  );
  onehot_mux #(.p_choices(3),.p_width(64),.p_preserve_groups(1'b1)) u_select (
    .i_select,
    .i_data({{next_word,{p_word_shift{1'b0}},next_pixel},
             {i_seed_address,i_seed_pixel},{i_address,i_pixel}}),
    .o_data(selected_payload)
  );
  always_comb begin
    {o_address,o_pixel} = selected_payload;
    // 明确选中单个候选时保留该候选的全部四态数据位。
    case (^{i_select,i_address,i_pixel,i_seed_address,i_seed_pixel,i_saved_address,i_saved_pixel})
      1'b0,1'b1: begin end
      default: begin
        case (i_select)
          3'b001: {o_address,o_pixel} = {i_address,i_pixel};
          3'b010: {o_address,o_pixel} = {i_seed_address,i_seed_pixel};
          3'b100: {o_address,o_pixel} = {next_word,{p_word_shift{1'b0}},next_pixel};
          default: begin end
        endcase
      end
    endcase
  end
endmodule

`default_nettype wire
