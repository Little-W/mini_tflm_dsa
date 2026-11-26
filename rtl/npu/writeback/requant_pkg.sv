// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 定义量化流水延迟，并按输出精度准备乘数和移位量。
package requant_pkg;
    localparam int unsigned REQUANT_LATENCY = 7;
  // INT16 乘数采用最近偶数舍入，两个字节并行递增并保留正向饱和。
  function automatic logic signed [31:0] requant_prepare_multiplier(
      input logic signed [31:0] value, input logic use_s16);
    logic round_increment, high_increment;
    logic [15:0] rounded;
    logic unused_low_carry, unused_high_carry;
    begin
      round_increment = value[15] && ((|value[14:0]) || value[16]);
      high_increment = value[15] && (&value[23:16]);
      {unused_low_carry, rounded[7:0]} = {1'b0, value[23:16]} + 9'(round_increment);
      {unused_high_carry, rounded[15:8]} = {1'b0, value[31:24]} + 9'(high_increment);
      requant_prepare_multiplier = use_s16 ?
          ((value[31:16] == 16'h7fff) ? 32'sd32767 : 32'($signed(rounded))) : value;
    end
  endfunction

  // 两种输出精度共用六位模减法，范围判断保留各自的边界处理。
  function automatic logic [6:0] requant_prepare_amount(
      input logic signed [31:0] value, input logic use_s16);
    logic [5:0] amount_base, amount_difference;
    logic unused_borrow;
    begin
      amount_base = use_s16 ? 6'd15 : 6'd31;
      {unused_borrow, amount_difference} = {1'b0, amount_base} - {1'b0, value[5:0]};
      if (use_s16) begin
        if (value >= 32'sd15 || value[31:4] == 28'h8000000) requant_prepare_amount = 7'd0;
        else if (value < -32'sd48) requant_prepare_amount = 7'd63;
        else requant_prepare_amount = {1'b0, amount_difference};
      end else begin
        if (value > 32'sd0)
          requant_prepare_amount = (value[5:0] >= 6'd31) ? 7'd0 : {1'b0, amount_difference};
        else if (value == 32'sh80000000) requant_prepare_amount = 7'd31;
        else if (value < -32'sd32) requant_prepare_amount = 7'd64;
        else requant_prepare_amount = {1'b0, amount_difference};
      end
    end
  endfunction

endpackage

`default_nettype wire
