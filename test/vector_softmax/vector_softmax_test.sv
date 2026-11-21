// SPDX-License-Identifier: Apache-2.0
module vector_softmax_test #(
  parameter int MAX_DEPTH=16,
  parameter int IW=MAX_DEPTH<=1 ? 1 : $clog2(MAX_DEPTH),
  parameter bit INPUT_REGISTERED=1'b0
) (
  input logic clk,rst_n,start,
  input logic [31:0] depth,
  output logic ready,done,
  output logic [1:0] error,
  output logic [7:0] input_index,
  input logic signed [7:0] input_data,
  output logic lut_req_valid,
  input logic lut_req_ready,
  output logic [7:0] lut_index,
  input logic lut_rsp_valid,
  input logic [31:0] lut_rsp_data,
  input logic lut_rsp_error,
  output logic exp_we,
  output logic [7:0] exp_index,
  output logic signed [31:0] exp_wdata,
  input logic signed [31:0] exp_rdata,
  output logic out_we,
  output logic [7:0] out_index,
  output logic signed [7:0] out_data
);
  logic [IW-1:0] core_input_index,core_exp_index,core_out_index;
  logic signed [31:0] mul_a,mul_b;
  logic signed [63:0] mul_product;
  logic signed [7:0] registered_input;
  assign input_index=8'(core_input_index);
  assign exp_index=8'(core_exp_index);
  assign out_index=8'(core_out_index);
  assign mul_product=mul_a*mul_b;
  // 同步读取接口在时钟边沿保存当前输入地址对应的字节。
  always_ff @(posedge clk) registered_input <= input_data;
  vector_softmax #(.MAX_DEPTH(MAX_DEPTH),.INPUT_REGISTERED(INPUT_REGISTERED)) dut (
    .clk,.rst_n,.start,.depth,.ready,.done,.error,
    .input_index(core_input_index),.input_data(INPUT_REGISTERED ? registered_input : input_data),
    .lut_req_valid,.lut_req_ready,.lut_index,
    .lut_rsp_valid,.lut_rsp_data,.lut_rsp_error,
    .exp_we,.exp_index(core_exp_index),.exp_wdata,.exp_rdata,
    .out_we,.out_index(core_out_index),.out_data,
    .mul_a,.mul_b,.mul_product
  );
endmodule
