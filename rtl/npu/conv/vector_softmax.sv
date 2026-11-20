// SPDX-License-Identifier: Apache-2.0
// INT8 Softmax 使用预先生成的 Q31 指数表，并采用最近偶数舍入。
// 输入、指数值存储、DMA 和有符号乘法器由向量引擎提供。
`default_nettype none
module vector_softmax #(
  parameter int MAX_DEPTH = 16,
  parameter int IW = MAX_DEPTH <= 1 ? 1 : $clog2(MAX_DEPTH),
  parameter int unsigned MULTIPLIER_LATENCY = 0
) (
  input  wire logic clk, rst_n,
  input  wire logic start,
  input  wire logic [31:0] depth,
  output logic ready, done,
  output logic [1:0] error,
  output logic [IW-1:0] input_index,
  input  wire logic signed [7:0] input_data,
  output logic lut_req_valid,
  input  wire logic lut_req_ready,
  output logic [7:0] lut_index,
  input  wire logic lut_rsp_valid,
  input  wire logic [31:0] lut_rsp_data,
  input  wire logic lut_rsp_error,
  output logic exp_we,
  output logic [IW-1:0] exp_index,
  output logic signed [31:0] exp_wdata,
  input  wire logic signed [31:0] exp_rdata,
  output logic out_we,
  output logic [IW-1:0] out_index,
  output logic signed [7:0] out_data,
  output logic signed [31:0] mul_a, mul_b,
  input  wire logic signed [63:0] mul_product
);
  //! 0. 辅助定义
  //! -----------

  typedef enum logic [4:0] {
    IDLE, FIND_MAX, LUT_REQUEST, LUT_WAIT, NORMALIZE, RECIP_INIT,
    RECIP_ERROR, RECIP_UPDATE, RECIP_SCALE, OUTPUT_MULT, OUTPUT_STORE, FINISH,
    RECIP_INIT_WAIT, RECIP_ERROR_WAIT, RECIP_UPDATE_WAIT, RECIP_ROUND, MULTIPLY_WAIT, LUT_DRAIN,
    NORMALIZE_COMMIT
  } state_t;
  state_t c_st, reciprocal_return;
  logic signed [31:0] reciprocal_q31;
  localparam int MW = MULTIPLIER_LATENCY < 2 ? 1 : $clog2(MULTIPLIER_LATENCY+1);
  logic [MW-1:0] multiply_wait_count;
  logic multiply_output;
  localparam int CW = MAX_DEPTH < 2 ? 1 : $clog2(MAX_DEPTH+1);
  logic [CW-1:0] count;
  logic [IW-1:0] index;
  logic signed [7:0] maximum;
  logic [31:0] sum;
  logic lut_accept_fire;
  logic sum_clear_fire;
  logic sum_i_vld;
  logic sum_i_clear;
  logic [19:0] sum_i_value;
  logic sum_i_increment;
  logic [31:0] sum_o_value;
  logic signed [31:0] half_denominator, estimate, residual, reciprocal;
  logic [1:0] iteration;
  logic [5:0] result_shift;
  logic signed [32:0] reciprocal_quotient_q;
  logic reciprocal_increment_q;
  logic signed [17:0] output_shift_base_q;
  logic [5:0] leading_zeros;
  logic [31:0] normalized_minus_one;

  logic normalization_invalid;
  logic norm8_zero;
  logic [31:0] norm8;
  logic norm8_zero_q;
  logic [31:0] norm8_q;
  logic norm4_zero;
  logic [31:0] norm4;
  logic norm2_zero;
  logic [31:0] norm2;
  logic norm1_zero;
  logic [31:0] norm1;
  logic signed [32:0] reciprocal_input_quotient;
  logic reciprocal_input_increment;
  logic signed [17:0] output_input_value;
  logic signed [17:0] output_shift8;
  logic signed [17:0] output_shift4;
  logic signed [17:0] output_shift2;
  logic signed [17:0] output_shift1;
  logic output_increment;
  logic [8:0] output_small;
  logic [31:0] reciprocal_rounded_word;
  logic [3:0] reciprocal_byte_carry;
  logic reciprocal_above_range;
  logic signed [31:0] reciprocal_rounded_q31;
  logic signed [33:0] update_scaled;
  logic signed [31:0] update_saturated;
  logic [31:0] estimate_lhs, estimate_rhs, estimate_next;
  logic [16:0] estimate_low;
  logic [15:0] estimate_high_direct, estimate_high_increment;
  logic signed [32:0] reciprocal_scaled;
  logic signed [31:0] reciprocal_saturated;

  //! 1. 输入处理
  //! -----------

  // 有效累计值位于 [2^19, 2^31)，所需左移量为一至十二位。
  // 八位粗移位先寄存，四位、两位和一位细移位在下一周期合并。
  assign normalization_invalid = sum[31] || !(|sum[30:19]);
  assign norm8_zero = (sum[31:24] == 0);
  assign norm8 = norm8_zero ? {sum[23:0], 8'b0} : sum;
  always_ff @(posedge clk) begin
    if (c_st == NORMALIZE) begin
      norm8_q <= norm8;
      norm8_zero_q <= norm8_zero;
    end
  end
  assign norm4_zero =(norm8_q[31:28]==0);
  assign norm4 =norm4_zero ? {norm8_q[27:0],4'b0} : norm8_q;
  assign norm2_zero =(norm4[31:30]==0);
  assign norm2 =norm2_zero ? {norm4[29:0],2'b0} : norm4;
  assign norm1_zero =!norm2[31];
  assign norm1 =norm1_zero ? {norm2[30:0],1'b0} : norm2;
  assign leading_zeros = {2'b00, norm8_zero_q, norm4_zero, norm2_zero, norm1_zero};
  assign normalized_minus_one={1'b0,norm1[30:0]};

  // 接收乘积时保存商、保护位和舍弃位信息，随后寄存阶段完成舍入。
  assign reciprocal_input_quotient = mul_product[63:31];
  assign reciprocal_input_increment = mul_product[30] && ((|mul_product[29:0]) || mul_product[31]);

  // 深度不超过 256 时，输出右移量为 54 至 62。接收边沿先固定移出 48 位，
  // 后续组合逻辑完成剩余移位；保护位和舍弃位保留最近偶数舍入所需信息。
  assign output_input_value = {mul_product[63:48], mul_product[47], (|mul_product[46:0])};
  assign output_shift8 =result_shift[3] ?
      {{8{output_shift_base_q[17]}},output_shift_base_q[17:9],(|output_shift_base_q[8:0])} : output_shift_base_q;
  assign output_shift4 =result_shift[2] ?
      {{4{output_shift8[17]}},output_shift8[17:5],(|output_shift8[4:0])} : output_shift8;
  assign output_shift2 =result_shift[1] ?
      {{2{output_shift4[17]}},output_shift4[17:3],(|output_shift4[2:0])} : output_shift4;
  assign output_shift1 =result_shift[0] ?
      {output_shift2[17],output_shift2[17:2],(|output_shift2[1:0])} : output_shift2;
  assign output_increment =output_shift1[1] && (output_shift1[0] || output_shift1[2]);
  assign output_small ={1'b0,output_shift1[9:2]}+9'(output_increment);

  // 正向饱和条件由舍入前的商确定，商等于最大值时输出仍为最大值。
  // 四个字节分别递增，低位全一条件并行提供各字节的进位。
  assign reciprocal_above_range = !reciprocal_quotient_q[32] &&
      (reciprocal_quotient_q[31] || (&reciprocal_quotient_q[30:0]));
  assign reciprocal_byte_carry[0] = reciprocal_increment_q;
  for (genvar part = 0; part < 4; part++) begin : g_reciprocal_round
    logic unused_carry;
    if (part > 0) begin : g_carry
      assign reciprocal_byte_carry[part] = reciprocal_increment_q &&
          (&reciprocal_quotient_q[8*part-1:0]);
    end
    assign {unused_carry, reciprocal_rounded_word[8*part +: 8]} =
        {1'b0, reciprocal_quotient_q[8*part +: 8]} + 9'(reciprocal_byte_carry[part]);
  end
  assign reciprocal_rounded_q31 = reciprocal_above_range ?
      32'sh7fff_ffff : $signed(reciprocal_rounded_word);
  assign update_scaled ={reciprocal_q31,2'b00};
  assign update_saturated =
      update_scaled[33:31]!={3{update_scaled[31]}} ?
      (update_scaled[33] ? 32'sh8000_0000 : 32'sh7fff_ffff) : update_scaled[31:0];
  // 初值和迭代更新共用模加法，高半字预先计算两种进位结果。
  assign estimate_lhs = (c_st == RECIP_INIT_WAIT) ? 32'd1515870810 : estimate;
  assign estimate_rhs = (c_st == RECIP_INIT_WAIT) ? reciprocal_q31 : update_saturated;
  assign estimate_low = {1'b0, estimate_lhs[15:0]} + {1'b0, estimate_rhs[15:0]};
  assign estimate_high_direct = estimate_lhs[31:16] + estimate_rhs[31:16];
  assign estimate_high_increment = estimate_lhs[31:16] + estimate_rhs[31:16] + 16'd1;
  assign estimate_next = {estimate_low[16] ? estimate_high_increment : estimate_high_direct,
                          estimate_low[15:0]};
  assign reciprocal_scaled ={estimate,1'b0};
  assign reciprocal_saturated =
      reciprocal_scaled[32:31]!={2{reciprocal_scaled[31]}} ?
      (reciprocal_scaled[32] ? 32'sh8000_0000 : 32'sh7fff_ffff) : reciprocal_scaled[31:0];

  // 响应边沿保存指数数据及舍入增量，下一边沿完成累加。
  assign lut_accept_fire = (c_st == LUT_WAIT) && lut_rsp_valid && !lut_rsp_error && !lut_rsp_data[31];
  assign sum_clear_fire = (c_st == IDLE) && start;
  assign sum_i_vld = lut_accept_fire;
  assign sum_i_clear = sum_clear_fire;
  assign sum_i_value = lut_rsp_data[31:12];
  assign sum_i_increment = lut_rsp_data[11] && ((|lut_rsp_data[10:0]) || lut_rsp_data[12]);
  assign sum = sum_o_value;

  //! 2. 更新状态与数据
  //! -----------------

  vector_softmax_accumulator u_sum (
      .clk        (clk),
      .rst_n      (rst_n),
      .i_clear    (sum_i_clear),
      .i_vld      (sum_i_vld),
      .i_value    (sum_i_value),
      .i_increment(sum_i_increment),
      .o_sum      (sum_o_value)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c_st <= IDLE;
      reciprocal_return <= IDLE;
      reciprocal_q31 <= '0;
      count <= '0;
      index <= '0;
      maximum <= -8'sd128;
      multiply_wait_count <= '0;
      multiply_output <= 1'b0;
      half_denominator <= '0;
      estimate <= '0;
      residual <= '0;
      reciprocal <= '0;
      iteration <= '0;
      result_shift <= '0;
      output_shift_base_q <= '0;
      error <= '0;
    end else begin
      case (c_st)
        IDLE: begin
          if (start) begin
            error <= '0;
            count <= CW'(depth);
            index <= '0;
            maximum <= -8'sd128;
            if (depth == 32'd0 || depth > 32'(MAX_DEPTH)) begin
              error <= 2'b01;
              c_st <= FINISH;
            end else begin
              c_st <= FIND_MAX;
            end
          end
        end
        FIND_MAX: begin
          if (input_data > maximum) begin
            maximum <= input_data;
          end
          if ((CW'(index) + CW'(1)) < count) begin
            index <= index + IW'(1);
          end else begin
            index <= '0;
            c_st <= LUT_REQUEST;
          end
        end
        LUT_REQUEST: begin
          if (lut_req_ready) begin
            c_st <= LUT_WAIT;
          end
        end
        LUT_WAIT: begin
          if (lut_rsp_valid) begin
            if (lut_rsp_error || lut_rsp_data[31]) begin
              error <= 2'b10;
              c_st <= FINISH;
            end else if ((CW'(index) + CW'(1)) < count) begin
              index <= index + IW'(1);
              c_st <= LUT_REQUEST;
            end else begin
              c_st <= LUT_DRAIN;
            end
          end
        end
        // 最后一个指数在此边沿完成累加，随后归一化使用完整的累计结果。
        LUT_DRAIN: begin
          c_st <= NORMALIZE;
        end
        NORMALIZE: begin
          if (normalization_invalid) begin
            error <= 2'b01;
            c_st <= FINISH;
          end else begin
            c_st <= NORMALIZE_COMMIT;
          end
        end
        NORMALIZE_COMMIT: begin
          half_denominator <= {2'b01, normalized_minus_one[30:2],
              (normalized_minus_one[1] && normalized_minus_one[0])};
          result_shift <= 6'(7'd66 - {1'b0, leading_zeros});
          iteration <= '0;
          c_st <= RECIP_INIT;
        end
        RECIP_INIT: begin
          reciprocal_return <= RECIP_INIT_WAIT;
          if (MULTIPLIER_LATENCY == 0) begin
            reciprocal_quotient_q <= reciprocal_input_quotient;
            reciprocal_increment_q <= reciprocal_input_increment;
            c_st <= RECIP_ROUND;
          end else begin
            multiply_wait_count <= MW'(MULTIPLIER_LATENCY);
            multiply_output <= 1'b0;
            c_st <= MULTIPLY_WAIT;
          end
        end
        RECIP_INIT_WAIT: begin
          estimate <= $signed(estimate_next);
          c_st <= RECIP_ERROR;
        end
        RECIP_ERROR: begin
          reciprocal_return <= RECIP_ERROR_WAIT;
          if (MULTIPLIER_LATENCY == 0) begin
            reciprocal_quotient_q <= reciprocal_input_quotient;
            reciprocal_increment_q <= reciprocal_input_increment;
            c_st <= RECIP_ROUND;
          end else begin
            multiply_wait_count <= MW'(MULTIPLIER_LATENCY);
            multiply_output <= 1'b0;
            c_st <= MULTIPLY_WAIT;
          end
        end
        RECIP_ERROR_WAIT: begin
          residual <= 32'sh2000_0000 - reciprocal_q31;
          c_st <= RECIP_UPDATE;
        end
        RECIP_UPDATE: begin
          reciprocal_return <= RECIP_UPDATE_WAIT;
          if (MULTIPLIER_LATENCY == 0) begin
            reciprocal_quotient_q <= reciprocal_input_quotient;
            reciprocal_increment_q <= reciprocal_input_increment;
            c_st <= RECIP_ROUND;
          end else begin
            multiply_wait_count <= MW'(MULTIPLIER_LATENCY);
            multiply_output <= 1'b0;
            c_st <= MULTIPLY_WAIT;
          end
        end
        RECIP_UPDATE_WAIT: begin
          estimate <= $signed(estimate_next);
          if (iteration == 2'd2) begin
            c_st <= RECIP_SCALE;
          end else begin
            iteration <= iteration + 2'd1;
            c_st <= RECIP_ERROR;
          end
        end
        RECIP_ROUND: begin
          reciprocal_q31 <= reciprocal_rounded_q31;
          c_st <= reciprocal_return;
        end
        RECIP_SCALE: begin
          reciprocal <= reciprocal_saturated;
          index <= '0;
          c_st <= OUTPUT_MULT;
        end
        OUTPUT_MULT: begin
          if (MULTIPLIER_LATENCY == 0) begin
            output_shift_base_q <= output_input_value;
            c_st <= OUTPUT_STORE;
          end else begin
            multiply_wait_count <= MW'(MULTIPLIER_LATENCY);
            multiply_output <= 1'b1;
            c_st <= MULTIPLY_WAIT;
          end
        end
        MULTIPLY_WAIT: begin
          if (multiply_wait_count == MW'(1)) begin
            if (multiply_output) begin
              output_shift_base_q <= output_input_value;
              c_st <= OUTPUT_STORE;
            end else begin
              reciprocal_quotient_q <= reciprocal_input_quotient;
              reciprocal_increment_q <= reciprocal_input_increment;
              c_st <= RECIP_ROUND;
            end
          end else begin
            multiply_wait_count <= multiply_wait_count - MW'(1);
          end
        end
        OUTPUT_STORE: begin
          if ((CW'(index) + CW'(1)) < count) begin
            index <= index + IW'(1);
            c_st <= OUTPUT_MULT;
          end else begin
            c_st <= FINISH;
          end
        end
        FINISH: begin
          c_st <= IDLE;
        end
        default: begin
          error <= 2'b10;
          c_st <= FINISH;
        end
      endcase
    end
  end

  //! 3. 生成输出
  //! -----------

  always_comb begin
    mul_a = '0;
    mul_b = '0;
    case (c_st)
      RECIP_INIT: begin
        mul_a = half_denominator;
        mul_b = -32'sd1010580540;
      end
      RECIP_ERROR: begin
        mul_a = half_denominator;
        mul_b = estimate;
      end
      RECIP_UPDATE: begin
        mul_a = estimate;
        mul_b = residual;
      end
      OUTPUT_MULT: begin
        mul_a = reciprocal;
        mul_b = exp_rdata;
      end
      default: ;
    endcase
    if (output_shift_base_q[17]) begin
      out_data = -8'sd128;
    end else if ((|output_shift1[17:10]) || output_small >= 9'd255) begin
      out_data = 8'sd127;
    end else begin
      out_data = {~output_small[7], output_small[6:0]};
    end
  end

  assign ready = c_st == IDLE;
  assign done = c_st == FINISH;
  assign input_index = IW'(index);
  assign lut_req_valid = c_st == LUT_REQUEST;
  assign lut_index = 8'($signed(32'(maximum)) - $signed(32'(input_data)));
  assign exp_we = lut_accept_fire;
  assign exp_index = IW'(index);
  assign exp_wdata = $signed(lut_rsp_data);
  assign out_we = c_st == OUTPUT_STORE;
  assign out_index = IW'(index);

`ifdef NPU_SIM_ASSERT
  initial if (MAX_DEPTH<1 || MAX_DEPTH>256) $fatal(1,"Softmax depth must be in [1,256]");
`endif
endmodule

// 指数累加器先保存数据及舍入进位，再在下一边沿更新三十二位累计结果。
module vector_softmax_accumulator #(
`ifdef XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`else
`ifdef SYNTHESIS
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`else
    parameter bit p_use_dsp = 1'b1
`endif
`else
    parameter bit p_use_dsp = 1'b0
`endif
`endif
) (
    input  wire logic        clk,
    input  wire logic        rst_n,
    input  wire logic        i_clear,
    input  wire logic        i_vld,
    input  wire logic [19:0] i_value,
    input  wire logic        i_increment,
    output logic [31:0] o_sum
);
    //! 0. 辅助定义
    //! -----------

    logic add_pending;
    logic sum_clear;

    //! 1. 输入处理
    //! -----------

    assign sum_clear = !rst_n || i_clear;

    //! 2. 保存输入与累计结果
    //! ---------------------

    // 任务初始化同时清除累计结果和待处理标志，新的有效数据不会跨任务保留。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            add_pending <= 1'b0;
        end else if (i_clear) begin
            add_pending <= 1'b0;
        end else begin
            add_pending <= i_vld;
        end
    end

    if (p_use_dsp) begin : g_dsp
        logic [29:0] dsp_i_a;
        logic [17:0] dsp_i_b;
        logic [47:0] dsp_i_c;
        logic [24:0] dsp_i_d;
        logic [47:0] dsp_i_pcin;
        logic [6:0] dsp_i_opmode;
        logic [4:0] dsp_i_inmode;
        logic [3:0] dsp_i_alumode;
        logic [2:0] dsp_i_carry_select;
        logic dsp_i_carry;
        logic dsp_i_en;
        logic dsp_i_reset;
        logic dsp_i_zero;
        logic dsp_i_one;
        logic [47:0] dsp_o_result;
        logic [29:0] unused_acout;
        logic [17:0] unused_bcout;
        logic [47:0] unused_pcout;
        logic [3:0] unused_carryout;
        logic unused_carrycascout;
        logic unused_multsignout;
        logic unused_overflow;
        logic unused_underflow;
        logic unused_patterndetect;
        logic unused_patternbdetect;

        assign dsp_i_a = '0;
        assign dsp_i_b = '0;
        assign dsp_i_c = {28'd0, i_value};
        assign dsp_i_d = '0;
        assign dsp_i_pcin = '0;
        assign dsp_i_opmode = 7'b0101100;
        assign dsp_i_inmode = '0;
        assign dsp_i_alumode = '0;
        assign dsp_i_carry_select = '0;
        assign dsp_i_carry = i_increment;
        assign dsp_i_en = add_pending;
        assign dsp_i_reset = sum_clear;
        assign dsp_i_zero = 1'b0;
        assign dsp_i_one = 1'b1;
        assign o_sum = dsp_o_result[31:0];

        // C 和 CARRYIN 分别保存指数整数部分与舍入进位；P 执行二者与旧 P 的求和。
        // 累加使能来自已保存的有效标志，数据和控制均经过寄存阶段。
        DSP48E1 #(
            .AREG(0), .ACASCREG(0), .BREG(0), .BCASCREG(0), .ADREG(0),
            .CREG(1), .DREG(0), .MREG(0), .PREG(1), .CARRYINREG(1),
            .CARRYINSELREG(0), .INMODEREG(0), .OPMODEREG(0), .ALUMODEREG(0),
            .USE_DPORT("FALSE"), .USE_MULT("NONE"), .USE_SIMD("ONE48")
        ) u_dsp (
            .CLK(clk), .A(dsp_i_a), .ACIN(dsp_i_a), .B(dsp_i_b), .BCIN(dsp_i_b),
            .C(dsp_i_c), .D(dsp_i_d), .PCIN(dsp_i_pcin),
            .OPMODE(dsp_i_opmode), .INMODE(dsp_i_inmode), .ALUMODE(dsp_i_alumode),
            .CARRYIN(dsp_i_carry), .CARRYINSEL(dsp_i_carry_select),
            .CARRYCASCIN(dsp_i_zero), .MULTSIGNIN(dsp_i_zero),
            .CEA1(dsp_i_zero), .CEA2(dsp_i_zero), .CEAD(dsp_i_zero),
            .CEB1(dsp_i_zero), .CEB2(dsp_i_zero), .CEC(dsp_i_one),
            .CECARRYIN(dsp_i_one), .CED(dsp_i_zero), .CEM(dsp_i_zero), .CEP(dsp_i_en),
            .CECTRL(dsp_i_zero), .CEINMODE(dsp_i_zero), .CEALUMODE(dsp_i_zero),
            .RSTA(dsp_i_zero), .RSTB(dsp_i_zero), .RSTC(dsp_i_zero), .RSTD(dsp_i_zero),
            .RSTM(dsp_i_zero), .RSTP(dsp_i_reset), .RSTALLCARRYIN(dsp_i_zero),
            .RSTCTRL(dsp_i_zero), .RSTINMODE(dsp_i_zero), .RSTALUMODE(dsp_i_zero),
            .P(dsp_o_result), .ACOUT(unused_acout), .BCOUT(unused_bcout),
            .PCOUT(unused_pcout), .CARRYOUT(unused_carryout),
            .CARRYCASCOUT(unused_carrycascout), .MULTSIGNOUT(unused_multsignout),
            .OVERFLOW(unused_overflow), .UNDERFLOW(unused_underflow),
            .PATTERNDETECT(unused_patterndetect), .PATTERNBDETECT(unused_patternbdetect)
        );
    end else begin : g_generic
        logic [19:0] value_stage;
        logic increment_stage;
        logic [31:0] sum;

        always_ff @(posedge clk) begin
            value_stage <= i_value;
            increment_stage <= i_increment;
            if (sum_clear) begin
                sum <= '0;
            end else if (add_pending) begin
                sum <= sum + {12'd0, value_stage} + {31'd0, increment_stage};
            end
        end
        assign o_sum = sum;
    end
endmodule

`default_nettype wire
