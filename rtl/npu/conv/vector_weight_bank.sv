// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 权重采用异步读取，计算单元在发射周期接收当前卷积核位置的数据。
module vector_weight_bank #(
  parameter integer DEPTH=49,
  parameter integer ADDRESS_BITS=$clog2(DEPTH)>0 ? $clog2(DEPTH) : 1
) (
  input wire clk, write_enable,
  input wire [31:0] write_address, read_address,
  input wire signed [7:0] write_data,
  output wire signed [7:0] read_data
);
  logic signed [7:0] data [DEPTH];
  always_ff @(posedge clk) begin
    if(write_enable && write_address<DEPTH) begin
      data[ADDRESS_BITS'(write_address)]<=write_data;
    end
  end
  assign read_data=read_address<DEPTH ? data[ADDRESS_BITS'(read_address)] : 8'sd0;
endmodule

`default_nettype wire
