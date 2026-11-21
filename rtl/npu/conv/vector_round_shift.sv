// SPDX-License-Identifier: Apache-2.0
// 有符号最近偶数舍入，移位过程同时保存保护位和舍弃位。
`default_nettype none
module vector_round_shift #(
  parameter bit REGISTER_MIDDLE = 1'b0,
  parameter bit REGISTER_INPUT = 1'b0,
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0,
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1,
`else
  parameter bit p_use_dsp = 1'b0,
`endif
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_lut = 1'b0
`elsif XILINX_FPGA
  parameter bit p_use_lut = 1'b1
`elsif SYNTHESIS
  parameter bit p_use_lut = 1'b1
`else
  parameter bit p_use_lut = 1'b0
`endif
) (
  input wire logic clk,
  input wire logic signed [63:0] value,
  input wire logic [5:0] amount,
  output logic signed [63:0] result,
  output logic signed [63:0] floor_value
);
  //! 0. 内部信号
  //! ----------------

  logic signed [65:0] shift0, shift1, shift2, shift4;
  logic signed [65:0] input_shift8, input_shift16, rounded_input, shift32;
  logic signed [63:0] selected_value;
  logic [5:0] selected_amount;
  logic signed [65:0] input_shift32;
  (* keep = 1 *) logic [4:0] discarded_groups;
  (* keep = 1 *) logic [5:0] discarded_bytes;
  logic increment;
  (* keep = 1 *) logic [7:0] byte_carry;

  //! 1. 低位移位
  //! ----------------

  // 模式选择在输入边沿完成，后续移位仅由保存的数值与移位量驱动。
  if (REGISTER_INPUT) begin : g_input_register
    always_ff @(posedge clk) begin
      selected_value <= value;
      selected_amount <= amount;
    end
  end else begin : g_input_combinational
    assign selected_value = value;
    assign selected_amount = amount;
  end

  // 两个低位分别保存保护位和所有更低位的非零状态。
  assign shift0 = {selected_value, 2'b00};
  assign shift1 = selected_amount[0] ? {shift0[65], shift0[65:2], (|shift0[1:0])} : shift0;
  assign shift2 = selected_amount[1] ? {{2{shift1[65]}}, shift1[65:3], (|shift1[2:0])} : shift1;
  assign shift4 = selected_amount[2] ? {{4{shift2[65]}}, shift2[65:5], (|shift2[4:0])} : shift2;
  assign input_shift8 = selected_amount[3] ? {{8{shift4[65]}}, shift4[65:9], (|shift4[8:0])} : shift4;
  assign input_shift16 = selected_amount[4] ? {{16{input_shift8[65]}}, input_shift8[65:17], (|input_shift8[16:0])} : input_shift8;

  // 各移位级分别归并新舍弃的数据位，最终一次合并，保存保护位之外的非零状态。
  assign discarded_groups[0] = selected_amount[1] && (|shift1[2:1]);
  assign discarded_groups[1] = selected_amount[2] && (|shift2[4:1]);
  assign discarded_groups[2] = selected_amount[3] && (|shift4[8:1]);
  // 每个八位片段先并行归并，使宽舍弃位归约保持平衡的组合层次。
  for (genvar part = 0; part < 2; part++) begin : g_discarded16
    assign discarded_bytes[part] = |input_shift8[8*part+1+:8];
  end
  for (genvar part = 0; part < 4; part++) begin : g_discarded32
    assign discarded_bytes[part+2] = |input_shift16[8*part+1+:8];
  end
  assign discarded_groups[3] = selected_amount[4] && (|discarded_bytes[1:0]);
  assign discarded_groups[4] = selected_amount[5] && (|discarded_bytes[5:2]);
  assign input_shift32[65:1] = selected_amount[5] ?
      {{32{input_shift16[65]}}, input_shift16[65:33]} : input_shift16[65:1];
  assign input_shift32[0] = |discarded_groups;

  //! 2. 中间数据寄存
  //! --------------------

  generate
    if (REGISTER_MIDDLE) begin : g_middle_register
      // 完整移位及保护位同时保存，舍入递增使用独立的寄存器间组合区间。
      always_ff @(posedge clk) begin
        rounded_input <= input_shift32;
      end
    end else begin : g_middle_combinational
      assign rounded_input = input_shift32;
    end
  endgenerate

  //! 3. 舍入递增
  //! ----------------

  assign shift32 = rounded_input;
  assign increment = shift32[1] && (shift32[0] || shift32[2]);
  assign floor_value = $signed(shift32[65:2]);

  // 高字节产生进位时，全部较低商位均为一，最低商位已经满足舍入条件。
  // 因此高字节只需检查保护位和低位全一条件。
  (* keep = "true" *) logic [7:0] byte_all_ones;
  (* keep = "true" *) logic lower_word_all_ones;
  for (genvar part = 0; part < 8; part++) begin : g_byte_all_ones
    assign byte_all_ones[part] = &floor_value[part*8+:8];
  end
  assign lower_word_all_ones = &byte_all_ones[3:0];
  assign byte_carry[0] = increment;
  for (genvar part = 1; part < 8; part++) begin : g_byte_prefix
    if (part < 4) begin : g_lower
      assign byte_carry[part] = shift32[1] && (&byte_all_ones[part-1:0]);
    end else if (part == 4) begin : g_word_boundary
      assign byte_carry[part] = shift32[1] && lower_word_all_ones;
    end else begin : g_upper
      assign byte_carry[part] = shift32[1] && lower_word_all_ones && (&byte_all_ones[part-1:4]);
    end
  end

  // 每个字节独立计算加一结果，舍入进位只选择已经完成的数值。
  // 可选的综合属性作用于同一八位加法表达式，保持各字节的四态算术语义。
  for (genvar part = 0; part < 8; part++) begin : g_increment8
    logic [7:0] byte_result;
    (* use_dsp = p_use_dsp ? "yes" : "no" *) logic [7:0] incremented_byte;
    assign incremented_byte = floor_value[part*8+:8] + 8'd1;
    assign result[part*8+:8] = byte_result;
    always_comb begin
      case (byte_carry[part])
        1'b0: byte_result = floor_value[part*8+:8] + 8'd0;
        1'b1: byte_result = incremented_byte;
        default: byte_result = floor_value[part*8+:8] + 8'(byte_carry[part]);
      endcase
    end
  end
endmodule

`default_nettype wire
