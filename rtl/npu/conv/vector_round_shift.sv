// SPDX-License-Identifier: Apache-2.0
// 有符号最近偶数舍入，移位过程同时保存保护位和舍弃位。
`default_nettype none
module vector_round_shift #(
  parameter bit REGISTER_MIDDLE = 1'b0,
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
  logic signed [65:0] middle_data, shift8, shift16, shift32;
  logic [2:0] middle_amount;
  logic increment;
  (* keep = "true" *) logic [7:0] byte_carry;
  (* keep = "true" *) logic [7:0] prefix_full [4];

  //! 1. 低位移位
  //! ----------------

  // 两个低位分别保存保护位和所有更低位的非零状态。
  assign shift0 = {value, 2'b00};
  assign shift1 = amount[0] ? {shift0[65], shift0[65:2], (|shift0[1:0])} : shift0;
  assign shift2 = amount[1] ? {{2{shift1[65]}}, shift1[65:3], (|shift1[2:0])} : shift1;
  assign shift4 = amount[2] ? {{4{shift2[65]}}, shift2[65:5], (|shift2[4:0])} : shift2;

  //! 2. 中间数据寄存
  //! --------------------

  generate
    if (REGISTER_MIDDLE) begin : g_middle_register
      logic signed [65:0] data;
      logic [2:0] remaining_amount;

      // 数据与剩余移位量在同一时钟边沿保存。
      always_ff @(posedge clk) begin
        data <= shift4;
        remaining_amount <= amount[5:3];
      end
      assign middle_data = data;
      assign middle_amount = remaining_amount;
    end else begin : g_middle_combinational
      assign middle_data = shift4;
      assign middle_amount = amount[5:3];
    end
  endgenerate

  //! 3. 高位移位与舍入
  //! ----------------------

  assign shift8 = middle_amount[0] ?
      {{8{middle_data[65]}}, middle_data[65:9], (|middle_data[8:0])} : middle_data;
  assign shift16 = middle_amount[1] ? {{16{shift8[65]}}, shift8[65:17], (|shift8[16:0])} : shift8;
  assign shift32 = middle_amount[2] ? {{32{shift16[65]}}, shift16[65:33], (|shift16[32:0])} : shift16;
  assign increment = shift32[1] && (shift32[0] || shift32[2]);
  assign floor_value = $signed(shift32[65:2]);

  // 高字节产生进位时，全部较低商位均为一，最低商位已经满足舍入条件。
  // 因此高字节只需检查保护位和低位全一条件。
  assign byte_carry[0] = increment;
  assign prefix_full[0][0] = shift32[1];
  for (genvar part = 0; part < 7; part++) begin : g_byte_full
    assign prefix_full[0][part+1] = &floor_value[part*8+:8];
  end
  // 每层合并等长的相邻区间，保留各层结果以限制所有字节进位的级数。
  for (genvar level = 0; level < 3; level++) begin : g_prefix_level
    for (genvar part = 0; part < 8; part++) begin : g_prefix_part
      if (part >= (1 << level)) begin : g_merge
        assign prefix_full[level+1][part] = prefix_full[level][part] &
            prefix_full[level][part-(1 << level)];
      end else begin : g_pass
        assign prefix_full[level+1][part] = prefix_full[level][part];
      end
    end
  end
  for (genvar part = 1; part < 8; part++) begin : g_byte_prefix
    assign byte_carry[part] = prefix_full[3][part];
  end

  // 八个字节并行递增，每个字节内部仅传播八位进位。
  for (genvar part = 0; part < 8; part++) begin : g_increment8
    logic unused_carry;
    logic [8:0] byte_result;
    assign {unused_carry, result[part*8+:8]} = byte_result;
    if (part == 0) begin : g_select_low_byte
      // 先并行准备两个字节结果，舍入条件只选择已经算好的数值。
      always_comb begin
        case (byte_carry[part])
          1'b0: byte_result =
              {1'b0, floor_value[part*8+:8]} + 9'd0;
          1'b1: byte_result =
              {1'b0, floor_value[part*8+:8]} + 9'd1;
          default: byte_result =
              {1'b0, floor_value[part*8+:8]} + 9'(byte_carry[part]);
        endcase
      end
    end else begin : g_high_byte
      assign byte_result =
          {1'b0, floor_value[part*8+:8]} + 9'(byte_carry[part]);
    end
  end
endmodule

`default_nettype wire
