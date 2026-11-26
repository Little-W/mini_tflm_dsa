// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 权重采用异步读取，计算单元在发射周期接收当前卷积核位置的数据。
module vector_weight_bank #(
  parameter integer DEPTH=49,
  parameter integer ADDRESS_BITS=$clog2(DEPTH)>0 ? $clog2(DEPTH) : 1
) (
  input wire clk /* 模块工作时钟。 */, write_enable /* 允许写入当前卷积核位置的权重。 */,
  input wire [31:0] write_address /* 待写权重的卷积核位置索引。 */, read_address /* 当前计算所需的卷积核位置索引。 */,
  input wire signed [7:0] write_data, // 写入的八位有符号权重。
  output wire signed [7:0] read_data // 异步读出的权重，索引越界时为零。
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
