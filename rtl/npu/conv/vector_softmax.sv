// SPDX-License-Identifier: Apache-2.0
// INT8 Softmax with a prepared Q31 exponential table and nearest-even arithmetic.
// Tensor and exponential storage, DMA and the signed multiplier belong to VCE.
module vector_softmax #(
  parameter int MAX_DEPTH = 16,
  parameter int IW = MAX_DEPTH <= 1 ? 1 : $clog2(MAX_DEPTH),
  parameter int unsigned MULTIPLIER_LATENCY = 0
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
  typedef enum logic [4:0] {
    IDLE, FIND_MAX, LUT_REQUEST, LUT_WAIT, NORMALIZE, RECIP_INIT,
    RECIP_ERROR, RECIP_UPDATE, RECIP_SCALE, OUTPUT_MULT, OUTPUT_STORE, FINISH,
    RECIP_INIT_WAIT, RECIP_ERROR_WAIT, RECIP_UPDATE_WAIT, RECIP_ROUND, MULTIPLY_WAIT
  } state_t;
  state_t state, reciprocal_return;
  logic signed [31:0] reciprocal_q31;
  localparam int MW = MULTIPLIER_LATENCY < 2 ? 1 : $clog2(MULTIPLIER_LATENCY+1);
  logic [MW-1:0] multiply_wait_count;
  logic multiply_output;
  localparam int CW = MAX_DEPTH < 2 ? 1 : $clog2(MAX_DEPTH+1);
  logic [CW-1:0] count;
  logic [IW-1:0] index;
  logic signed [7:0] maximum;
  logic [31:0] sum;
  logic signed [31:0] half_denominator, estimate, residual, reciprocal;
  logic [1:0] iteration;
  logic [5:0] result_shift;
  logic signed [63:0] output_product, reciprocal_product_q;
  logic [5:0] leading_zeros;
  logic [31:0] normalized_minus_one;

  wire norm16_zero=(sum[31:16]==0);
  wire [31:0] norm16=norm16_zero ? {sum[15:0],16'b0} : sum;
  wire norm8_zero=(norm16[31:24]==0);
  wire [31:0] norm8=norm8_zero ? {norm16[23:0],8'b0} : norm16;
  wire norm4_zero=(norm8[31:28]==0);
  wire [31:0] norm4=norm4_zero ? {norm8[27:0],4'b0} : norm8;
  wire norm2_zero=(norm4[31:30]==0);
  wire [31:0] norm2=norm2_zero ? {norm4[29:0],2'b0} : norm4;
  wire norm1_zero=!norm2[31];
  wire [31:0] norm1=norm1_zero ? {norm2[30:0],1'b0} : norm2;
  assign leading_zeros=(sum==0) ? 6'd32 :
      {1'b0,norm16_zero,norm8_zero,norm4_zero,norm2_zero,norm1_zero};
  assign normalized_minus_one={1'b0,norm1[30:0]};

  // Accepted depths up to 256 give result_shift in [54,62]. The fixed
  // 48-bit shift retains the remaining quotient, guard and sticky bits.
  wire signed [17:0] output_shift48={output_product[63:48],output_product[47],(|output_product[46:0])};
  wire signed [17:0] output_shift8=result_shift[3] ?
      {{8{output_shift48[17]}},output_shift48[17:9],(|output_shift48[8:0])} : output_shift48;
  wire signed [17:0] output_shift4=result_shift[2] ?
      {{4{output_shift8[17]}},output_shift8[17:5],(|output_shift8[4:0])} : output_shift8;
  wire signed [17:0] output_shift2=result_shift[1] ?
      {{2{output_shift4[17]}},output_shift4[17:3],(|output_shift4[2:0])} : output_shift4;
  wire signed [17:0] output_shift1=result_shift[0] ?
      {output_shift2[17],output_shift2[17:2],(|output_shift2[1:0])} : output_shift2;
  wire output_increment=output_shift1[1] && (output_shift1[0] || output_shift1[2]);
  wire [8:0] output_small={1'b0,output_shift1[9:2]}+9'(output_increment);

  wire [20:0] exponential_rounded={1'b0,lut_rsp_data[31:12]}+
      21'(lut_rsp_data[11] && ((|lut_rsp_data[10:0]) || lut_rsp_data[12]));
  wire signed [33:0] reciprocal_rounded=
      $signed({reciprocal_product_q[63],reciprocal_product_q[63:31]})+
      34'(reciprocal_product_q[30] &&
          ((|reciprocal_product_q[29:0]) || reciprocal_product_q[31]));
  wire signed [31:0] reciprocal_rounded_q31=
      (!reciprocal_rounded[33] && (|reciprocal_rounded[32:31])) ?
      32'sh7fff_ffff : reciprocal_rounded[31:0];
  wire signed [33:0] update_scaled={reciprocal_q31,2'b00};
  wire signed [31:0] update_saturated=
      update_scaled[33:31]!={3{update_scaled[31]}} ?
      (update_scaled[33] ? 32'sh8000_0000 : 32'sh7fff_ffff) : update_scaled[31:0];
  wire signed [32:0] reciprocal_scaled={estimate,1'b0};
  wire signed [31:0] reciprocal_saturated=
      reciprocal_scaled[32:31]!={2{reciprocal_scaled[31]}} ?
      (reciprocal_scaled[32] ? 32'sh8000_0000 : 32'sh7fff_ffff) : reciprocal_scaled[31:0];

  always_comb begin
    mul_a=0;mul_b=0;
    case (state)
      RECIP_INIT: begin mul_a=half_denominator;mul_b=-32'sd1010580540;end
      RECIP_ERROR: begin mul_a=half_denominator;mul_b=estimate;end
      RECIP_UPDATE: begin mul_a=estimate;mul_b=residual;end
      OUTPUT_MULT: begin mul_a=reciprocal;mul_b=exp_rdata;end
      default: ;
    endcase
    if (output_product[63]) out_data=-8'sd128;
    else if ((|output_shift1[17:10]) || output_small>=9'd255) out_data=8'sd127;
    else out_data={~output_small[7],output_small[6:0]};
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
      state<=IDLE;reciprocal_return<=IDLE;reciprocal_q31<=0;count<=0;index<=0;maximum<=-8'sd128;sum<=0;
      multiply_wait_count<=0;multiply_output<=0;
      half_denominator<=0;estimate<=0;residual<=0;reciprocal<=0;
      iteration<=0;result_shift<=0;output_product<=0;error<=0;
    end else case (state)
      IDLE: if (start) begin
        error<=0;count<=CW'(depth);index<=0;maximum<=-8'sd128;sum<=0;
        if (depth==0 || depth>32'(MAX_DEPTH)) begin error<=2'b01;state<=FINISH;end
        else state<=FIND_MAX;
      end
      FIND_MAX: begin
        if (input_data>maximum) maximum<=input_data;
        if ((CW'(index)+CW'(1))<count) index<=index+1;
        else begin index<=0;state<=LUT_REQUEST;end
      end
      LUT_REQUEST: if (lut_req_ready) state<=LUT_WAIT;
      LUT_WAIT: if (lut_rsp_valid) begin
        if (lut_rsp_error || lut_rsp_data[31]) begin error<=2'b10;state<=FINISH;end
        else begin
          sum<=sum+32'(exponential_rounded);
          if ((CW'(index)+CW'(1))<count) begin index<=index+1;state<=LUT_REQUEST;end
          else state<=NORMALIZE;
        end
      end
      NORMALIZE: begin
        if (sum==0 || sum[31] || leading_zeros>6'd12) begin error<=2'b01;state<=FINISH;end
        else begin
          half_denominator<={2'b01,normalized_minus_one[30:2],
              (normalized_minus_one[1] && normalized_minus_one[0])};
          result_shift<=6'(7'd66-{1'b0,leading_zeros});
          iteration<=0;state<=RECIP_INIT;
        end
      end
      RECIP_INIT: begin
        reciprocal_return<=RECIP_INIT_WAIT;
        if (MULTIPLIER_LATENCY==0) begin
          reciprocal_product_q<=mul_product;
          state<=RECIP_ROUND;
        end else begin
          multiply_wait_count<=MW'(MULTIPLIER_LATENCY);
          multiply_output<=1'b0;
          state<=MULTIPLY_WAIT;
        end
      end
      RECIP_INIT_WAIT: begin
        estimate<=32'sd1515870810+reciprocal_q31;
        state<=RECIP_ERROR;
      end
      RECIP_ERROR: begin
        reciprocal_return<=RECIP_ERROR_WAIT;
        if (MULTIPLIER_LATENCY==0) begin
          reciprocal_product_q<=mul_product;
          state<=RECIP_ROUND;
        end else begin
          multiply_wait_count<=MW'(MULTIPLIER_LATENCY);
          multiply_output<=1'b0;
          state<=MULTIPLY_WAIT;
        end
      end
      RECIP_ERROR_WAIT: begin
        residual<=32'sh2000_0000-reciprocal_q31;
        state<=RECIP_UPDATE;
      end
      RECIP_UPDATE: begin
        reciprocal_return<=RECIP_UPDATE_WAIT;
        if (MULTIPLIER_LATENCY==0) begin
          reciprocal_product_q<=mul_product;
          state<=RECIP_ROUND;
        end else begin
          multiply_wait_count<=MW'(MULTIPLIER_LATENCY);
          multiply_output<=1'b0;
          state<=MULTIPLY_WAIT;
        end
      end
      RECIP_UPDATE_WAIT: begin
        estimate<=estimate+update_saturated;
        if (iteration==2) state<=RECIP_SCALE;
        else begin iteration<=iteration+1'b1;state<=RECIP_ERROR;end
      end
      RECIP_ROUND: begin reciprocal_q31<=reciprocal_rounded_q31;state<=reciprocal_return;end
      RECIP_SCALE: begin reciprocal<=reciprocal_saturated;index<=0;state<=OUTPUT_MULT;end
      OUTPUT_MULT: begin
        if (MULTIPLIER_LATENCY==0) begin
          output_product<=mul_product;
          state<=OUTPUT_STORE;
        end else begin
          multiply_wait_count<=MW'(MULTIPLIER_LATENCY);
          multiply_output<=1'b1;
          state<=MULTIPLY_WAIT;
        end
      end
      MULTIPLY_WAIT: begin
        if (multiply_wait_count==MW'(1)) begin
          if (multiply_output) begin
            output_product<=mul_product;
            state<=OUTPUT_STORE;
          end else begin
            reciprocal_product_q<=mul_product;
            state<=RECIP_ROUND;
          end
        end else multiply_wait_count<=multiply_wait_count-1'b1;
      end
      OUTPUT_STORE: begin
        if ((CW'(index)+CW'(1))<count) begin index<=index+1;state<=OUTPUT_MULT;end
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
