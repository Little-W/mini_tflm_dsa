// SPDX-License-Identifier: Apache-2.0
// INT8 Softmax with a prepared Q31 exponential table and nearest-even arithmetic.
// Tensor and exponential storage, DMA and the signed multiplier belong to VCE.
module vector_softmax #(
  parameter int MAX_DEPTH = 16,
  parameter int IW = MAX_DEPTH <= 1 ? 1 : $clog2(MAX_DEPTH)
) (
  input  logic clk, rst_n,
  input  logic start,
  input  logic [31:0] depth,
  output logic ready, done,
  output logic [1:0] error,
  output logic [IW-1:0] input_index,
  input  logic signed [7:0] input_data,
  output logic lut_req_valid,
  input  logic lut_req_ready,
  output logic [7:0] lut_index,
  input  logic lut_rsp_valid,
  input  logic [31:0] lut_rsp_data,
  input  logic lut_rsp_error,
  output logic exp_we,
  output logic [IW-1:0] exp_index,
  output logic signed [31:0] exp_wdata,
  input  logic signed [31:0] exp_rdata,
  output logic out_we,
  output logic [IW-1:0] out_index,
  output logic signed [7:0] out_data,
  output logic signed [31:0] mul_a, mul_b,
  input  logic signed [63:0] mul_product
);
  typedef enum logic [3:0] {
    IDLE, FIND_MAX, LUT_REQUEST, LUT_WAIT, NORMALIZE, RECIP_INIT,
    RECIP_ERROR, RECIP_UPDATE, RECIP_SCALE, OUTPUT_MULT, OUTPUT_STORE, FINISH
  } state_t;
  state_t state;
  logic [31:0] count, index;
  logic signed [7:0] maximum;
  logic [31:0] sum;
  logic signed [31:0] half_denominator, estimate, residual, reciprocal;
  logic [1:0] iteration;
  logic [5:0] result_shift;
  logic signed [63:0] output_product, output_rounded;
  logic [5:0] leading_zeros;
  logic [31:0] normalized_minus_one;
  logic signed [63:0] half_sum;

  function automatic logic signed [63:0] rne_shift(
      input logic signed [63:0] value, input logic [5:0] shift);
    logic signed [63:0] quotient;
    logic [63:0] mask, remainder, halfway;
    quotient = value >>> shift;
    mask = (64'd1 << shift)-1;
    remainder = $unsigned(value) & mask;
    halfway = 64'd1 << (shift-1'b1);
    if (shift==0) return value;
    return quotient + 64'(remainder>halfway ||
                           (remainder==halfway && quotient[0]));
  endfunction

  function automatic logic signed [31:0] q31_product(
      input logic signed [63:0] product);
    logic signed [63:0] rounded;
    rounded = rne_shift(product,6'd31);
    if (rounded>64'sh7fff_ffff) return 32'sh7fff_ffff;
    return 32'(rounded);
  endfunction

  function automatic logic signed [31:0] sat_left(
      input logic signed [31:0] value, input logic [1:0] shift);
    logic signed [63:0] scaled;
    scaled = $signed(64'(value)) <<< shift;
    if (scaled>64'sh7fff_ffff) return 32'sh7fff_ffff;
    if (scaled< -64'sh8000_0000) return 32'sh8000_0000;
    return 32'(scaled);
  endfunction

  always_comb begin
    leading_zeros=6'd32;
    for (int bit_index=0;bit_index<32;bit_index++)
      if (sum[bit_index]) leading_zeros=6'(31-bit_index);
    normalized_minus_one=(sum << leading_zeros)-32'h8000_0000;
    half_sum=$signed({32'b0,normalized_minus_one})+64'sh7fff_ffff;
    mul_a=0;mul_b=0;
    case (state)
      RECIP_INIT: begin mul_a=half_denominator;mul_b=-32'sd1010580540;end
      RECIP_ERROR: begin mul_a=half_denominator;mul_b=estimate;end
      RECIP_UPDATE: begin mul_a=estimate;mul_b=residual;end
      OUTPUT_MULT: begin mul_a=reciprocal;mul_b=exp_rdata;end
      default: ;
    endcase
    output_rounded=rne_shift(output_product,result_shift);
    if (output_rounded>=64'sd255) out_data=8'sd127;
    else if (output_rounded<=0) out_data=-8'sd128;
    else out_data=8'(output_rounded-64'sd128);
  end

  assign ready=state==IDLE;
  assign done=state==FINISH;
  assign input_index=IW'(index);
  assign lut_req_valid=state==LUT_REQUEST;
  assign lut_index=8'($signed(32'(maximum))-$signed(32'(input_data)));
  assign exp_we=state==LUT_WAIT && lut_rsp_valid && !lut_rsp_error && !lut_rsp_data[31];
  assign exp_index=IW'(index);
  assign exp_wdata=$signed(lut_rsp_data);
  assign out_we=state==OUTPUT_STORE;
  assign out_index=IW'(index);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE;count<=0;index<=0;maximum<=-8'sd128;sum<=0;
      half_denominator<=0;estimate<=0;residual<=0;reciprocal<=0;
      iteration<=0;result_shift<=0;output_product<=0;error<=0;
    end else case (state)
      IDLE: if (start) begin
        error<=0;count<=depth;index<=0;maximum<=-8'sd128;sum<=0;
        if (depth==0 || depth>32'(MAX_DEPTH)) begin error<=2'b01;state<=FINISH;end
        else state<=FIND_MAX;
      end
      FIND_MAX: begin
        if (input_data>maximum) maximum<=input_data;
        if (index+1<count) index<=index+1;
        else begin index<=0;state<=LUT_REQUEST;end
      end
      LUT_REQUEST: if (lut_req_ready) state<=LUT_WAIT;
      LUT_WAIT: if (lut_rsp_valid) begin
        if (lut_rsp_error || lut_rsp_data[31]) begin error<=2'b10;state<=FINISH;end
        else begin
          sum<=sum+32'(rne_shift($signed({1'b0,lut_rsp_data}),6'd12));
          if (index+1<count) begin index<=index+1;state<=LUT_REQUEST;end
          else state<=NORMALIZE;
        end
      end
      NORMALIZE: begin
        if (sum==0 || sum[31] || leading_zeros>6'd12) begin error<=2'b01;state<=FINISH;end
        else begin
          half_denominator<=32'(rne_shift(half_sum,6'd1));
          result_shift<=6'(7'd66-{1'b0,leading_zeros});
          iteration<=0;state<=RECIP_INIT;
        end
      end
      RECIP_INIT: begin
        estimate<=32'sd1515870810+q31_product(mul_product);
        state<=RECIP_ERROR;
      end
      RECIP_ERROR: begin
        residual<=32'sh2000_0000-q31_product(mul_product);
        state<=RECIP_UPDATE;
      end
      RECIP_UPDATE: begin
        estimate<=estimate+sat_left(q31_product(mul_product),2'd2);
        if (iteration==2) state<=RECIP_SCALE;
        else begin iteration<=iteration+1'b1;state<=RECIP_ERROR;end
      end
      RECIP_SCALE: begin reciprocal<=sat_left(estimate,2'd1);index<=0;state<=OUTPUT_MULT;end
      OUTPUT_MULT: begin output_product<=mul_product;state<=OUTPUT_STORE;end
      OUTPUT_STORE: begin
        if (index+1<count) begin index<=index+1;state<=OUTPUT_MULT;end
        else state<=FINISH;
      end
      FINISH: state<=IDLE;
      default: begin error<=2'b10;state<=FINISH;end
    endcase
  end
`ifdef NPU_SIM_ASSERT
  initial if (MAX_DEPTH<1 || MAX_DEPTH>256) $fatal(1,"Softmax depth must be in [1,256]");
`endif
endmodule
