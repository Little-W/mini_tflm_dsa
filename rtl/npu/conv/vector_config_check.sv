// SPDX-License-Identifier: Apache-2.0
// 按阶段检查描述符；调用方在 done 有效前保持 cfg 稳定。
module vector_config_check #(
  parameter int TILE=16,
  parameter int MAX_TAPS=49,
  parameter int POOL_MAX_TAPS=256
) (
  input logic clk /* 模块工作时钟。 */,rst_n /* 低有效复位输入。 */,start /* 启动一次向量任务配置检查。 */,
  input logic i_input_range, // 为输入张量读取方式选择受检地址区间。
  input vector_engine_pkg::vector_engine_cfg_t cfg, // 检查完成前保持稳定的向量任务配置。
  output logic ready /* 能够接收新的配置检查请求。 */,done /* 本次配置检查完成。 */,error /* 配置字段、尺寸或地址范围检查失败。 */,
  output logic [31:0] kernel_count /* 卷积核或池化窗口包含的位置总数。 */,position_count /* 输出图像的空间位置总数。 */,
  output logic [63:0] input_bytes /* 输入数据需要占用的总字节数。 */,output_bytes /* 输出数据需要占用的总字节数。 */,weight_bytes /* 深度卷积权重需要占用的总字节数。 */,
  output logic [32:0] o_read_end[4] // 四个受检读取区间的右端地址，不包含该地址。
);
  import vector_engine_pkg::*;
  // 定宽范围先检查高位扩展，再比较低位边界。
  function automatic logic input_offset_valid(input logic signed [31:0] value);
    logic high_zero, high_one, low_nonzero;
    high_zero = !(|value[31:8]);
    high_one = &value[31:8];
    low_nonzero = |value[6:0];
    case (^value)
      1'b0, 1'b1: input_offset_valid =
          (high_zero && (!value[7] || !low_nonzero)) || (high_one && value[7] && low_nonzero);
      default: input_offset_valid = value >= -127 && value <= 128;
    endcase
  endfunction
  function automatic logic output_offset_valid(input logic signed [31:0] value);
    case (^value)
      1'b0, 1'b1: output_offset_valid = value[31:8] == {24{value[7]}};
      default: output_offset_valid = value >= -128 && value <= 127;
    endcase
  endfunction
  function automatic logic shift_valid(input logic signed [31:0] value, input bit positive);
    case (^value)
      1'b0, 1'b1: shift_valid =
          ((!(|value[31:5])) && (positive ? value[4:0] != 5'd31 : value[4:0] == 5'd0)) ||
          ((&value[31:5]) && (|value[4:0]));
      default: shift_valid = value >= -31 && value <= (positive ? 30 : 0);
    endcase
  endfunction
  function automatic logic left_shift_valid(input logic signed [31:0] value);
    case (^value)
      1'b0, 1'b1: left_shift_valid = !(|value[31:5]) && value[4:0] <= 5'd22;
      default: left_shift_valid = value >= 0 && value <= 22;
    endcase
  endfunction
  typedef enum logic [3:0] {IDLE,CALCULATE,CAPTURE,FIELDS,
    RANGE_SELECT,RANGE_ADD,RANGE_COMPARE,COMPLETE} state_t;
  state_t state;
  logic [2:0] phase,range_index;
  logic [31:0] input_pixels,multiply_a;
  logic [15:0] multiply_b;
  logic [31:0] multiply_low,multiply_high;
  logic [31:0] product_upper;
  wire [47:0] product_q={product_upper,multiply_low[15:0]};
  logic [15:0] range_dimension, range_padding;
  logic [15:0] range_dimension_saved, range_padding_saved;
  logic [16:0] range_sum, range_carry;
  logic [17:0] range_compare, range_i_a, range_i_b;
  logic unused_range_carry;
  logic output_coordinate_in_range;
  logic output_x_in_range, output_y_in_range;
  logic fields_ok,spatial,depthwise,binary_vector,add_s8,softmax_s8;
  logic static_fields_ok, static_fields_ok_q;
  logic kernel_limit_ok_q;
  logic activation_range_ok;
  logic [31:0] selected_base,range_base_q;
  logic [63:0] selected_bytes,range_bytes_q;
  logic selected_enable,range_enable_q,range_size_ok;
  logic [32:0] range_end_q,output_end_q;
  logic range_before_output, output_before_range;
  logic range_output_less, output_range_less;
  logic unused_range_output_equal, unused_output_range_equal;
  // 两个完整三十三位端点并行比较，输出范围检查直接使用无借位关系。
  unsigned_compare #(.p_width(33)) u_range_before_output (
      .i_a({1'b0,cfg.output_base}), .i_b(range_end_q),
      .o_less(range_output_less), .o_equal(unused_range_output_equal));
  unsigned_compare #(.p_width(33)) u_output_before_range (
      .i_a({1'b0,range_base_q}), .i_b(output_end_q),
      .o_less(output_range_less), .o_equal(unused_output_range_equal));
  assign range_before_output = !range_output_less;
  assign output_before_range = !output_range_less;
  logic [7:0] range_end_low;
  logic range_end_carry;
  logic [24:0] range_end_high;
  assign product_upper = multiply_high + {16'd0,multiply_low[31:16]};
  assign range_end_high = {1'b0, range_base_q[31:8]} +
      {1'b0, range_bytes_q[31:8]} + range_end_carry;
  // 两端均为有效 INT8 值时，仅比较低八位的有符号次序。
  assign activation_range_ok =
      (cfg.activation_min[31:8] == {24{cfg.activation_min[7]}}) &&
      (cfg.activation_max[31:8] == {24{cfg.activation_max[7]}}) &&
      ($signed(cfg.activation_min[7:0]) <= $signed(cfg.activation_max[7:0]));
  assign ready=state==IDLE;
  assign done=state==COMPLETE;
  assign spatial=cfg.op<=MINPOOL_S8;
  assign depthwise=cfg.op==DW_S8;
  assign add_s8=cfg.op==ADD_S8;
  assign softmax_s8=cfg.op==SOFTMAX_S8;
  assign binary_vector=cfg.op==VEC_DOT || cfg.op==VEC_HADAMARD || add_s8;
  wire [15:0] last_output_y=cfg.image.output_h-16'd1;
  wire [15:0] last_output_x=cfg.image.output_w-16'd1;
  always_comb begin
    multiply_a=0;multiply_b=0;
    case (phase)
      0: begin multiply_a={16'd0,cfg.image.kernel_h};multiply_b=cfg.image.kernel_w;end
      1: begin multiply_a={16'd0,cfg.image.output_h};multiply_b=cfg.image.output_w;end
      2: begin multiply_a={16'd0,cfg.image.input_h};multiply_b=cfg.image.input_w;end
      3: begin multiply_a=kernel_count;multiply_b=cfg.image.input_c;end
      4: begin multiply_a=input_pixels;multiply_b=cfg.image.input_c;end
      5: begin multiply_a=position_count;multiply_b=cfg.image.input_c;end
      6: begin multiply_a={16'd0,last_output_y};multiply_b=cfg.image.stride_h;end
      7: begin multiply_a={16'd0,last_output_x};multiply_b=cfg.image.stride_w;end
      default: ;
    endcase
  end
  // 纵、横坐标按乘积阶段共用范围检查器，分别保存检查结果。
  assign range_dimension = phase == 3'd6 ? cfg.image.input_h : cfg.image.input_w;
  assign range_padding = phase == 3'd6 ? cfg.image.pad_top : cfg.image.pad_left;
  assign range_sum = {1'b0, range_dimension_saved} ^ {1'b0, range_padding_saved} ^ ~product_q[16:0];
  assign range_carry = ({1'b0, range_dimension_saved} & {1'b0, range_padding_saved}) |
      (({1'b0, range_dimension_saved} ^ {1'b0, range_padding_saved}) & ~product_q[16:0]);
  assign range_i_a = {1'b0, range_sum};
  assign range_i_b = {range_carry, 1'b0};
  parallel_prefix_add #(.p_width(18), .p_group_width(4)) u_range (
      .i_a(range_i_a), .i_b(range_i_b), .i_carry(1'b0),
      .o_sum(range_compare), .o_carry(unused_range_carry)
  );
  assign output_coordinate_in_range = !(|product_q[47:17]) && range_compare[17];

  always_comb begin
    static_fields_ok=cfg.op<=SOFTMAX_S8;
    if (spatial) begin
      static_fields_ok=static_fields_ok && cfg.image.input_h!=0 && cfg.image.input_w!=0 && cfg.image.input_c!=0 &&
        cfg.image.output_h!=0 && cfg.image.output_w!=0 && cfg.image.kernel_h!=0 && cfg.image.kernel_w!=0 &&
        cfg.image.stride_h!=0 && cfg.image.stride_w!=0 &&
        cfg.image.dilation_h!=0 && cfg.image.dilation_w!=0 && !cfg.image.input_s16 && !cfg.vector_s16 &&
        activation_range_ok;
      if (depthwise) begin
        static_fields_ok=static_fields_ok && input_offset_valid(cfg.image.input_offset) &&
          output_offset_valid(cfg.output_offset) &&
          cfg.multiplier_base[1:0]==0 && cfg.shift_base[1:0]==0;
        if (cfg.bias_base!=0) static_fields_ok=static_fields_ok && cfg.bias_base[1:0]==0;
      end else begin
        static_fields_ok=static_fields_ok && cfg.image.input_offset==0 && cfg.output_offset==0 &&
          cfg.image.dilation_h==1 && cfg.image.dilation_w==1 &&
          cfg.image.pad_top<cfg.image.kernel_h && cfg.image.pad_left<cfg.image.kernel_w;
      end
    end else begin
      static_fields_ok=static_fields_ok && cfg.length!=0 && (add_s8 || softmax_s8 || cfg.output_base[1:0]==0);
      if (cfg.vector_s16) static_fields_ok=static_fields_ok && cfg.input_base[0]==0;
      if (binary_vector && cfg.vector_s16) static_fields_ok=static_fields_ok && cfg.rhs_base[0]==0;
      if (softmax_s8) static_fields_ok=static_fields_ok && !cfg.vector_s16 && cfg.length<=32'(TILE) && cfg.rhs_base[1:0]==0;
      if (add_s8) static_fields_ok=static_fields_ok && !cfg.vector_s16 &&
        input_offset_valid(cfg.add.input1_offset) &&
        input_offset_valid(cfg.add.input2_offset) &&
        cfg.add.input1_multiplier>=0 && cfg.add.input2_multiplier>=0 && cfg.add.output_multiplier>=0 &&
        shift_valid(cfg.add.input1_shift, 1'b0) &&
        shift_valid(cfg.add.input2_shift, 1'b0) &&
        left_shift_valid(cfg.add.left_shift) &&
        shift_valid(cfg.add.output_shift, 1'b1) &&
        output_offset_valid(cfg.output_offset) &&
        activation_range_ok;
    end
  end
  // 静态字段提前检查，乘积和末坐标在各自计算阶段完成后检查。
  always_ff @(posedge clk) begin
    static_fields_ok_q <= static_fields_ok;
  end
  assign fields_ok = static_fields_ok_q && (!spatial ||
      (kernel_limit_ok_q &&
       weight_bytes[63:32] == 0 && (depthwise || (output_y_in_range && output_x_in_range))));
  always_comb begin
    selected_base=0;selected_bytes=0;selected_enable=0;
    case (range_index)
      0: begin selected_base=cfg.output_base;selected_bytes=output_bytes;selected_enable=1;end
      1: begin selected_base=cfg.input_base;selected_bytes=input_bytes;selected_enable=1;end
      2: begin
        selected_base=cfg.rhs_base;
        selected_bytes=depthwise ? weight_bytes : softmax_s8 ? 64'd1024 : input_bytes;
        selected_enable=depthwise || binary_vector || softmax_s8;
      end
      3: begin
        selected_base=cfg.bias_base;selected_bytes={46'd0,cfg.image.input_c,2'b00};
        selected_enable=depthwise && cfg.bias_base!=0;
      end
      4: begin
        selected_base=cfg.multiplier_base;selected_bytes={46'd0,cfg.image.input_c,2'b00};
        selected_enable=depthwise;
      end
      5: begin
        selected_base=cfg.shift_base;selected_bytes={46'd0,cfg.image.input_c,2'b00};
        selected_enable=depthwise;
      end
      default: ;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE;error<=0;phase<=0;range_index<=0;
      kernel_count<=0;position_count<=0;input_pixels<=0;
      input_bytes<=0;output_bytes<=0;weight_bytes<=0;
      range_enable_q<=0;range_size_ok<=0;output_end_q<=0;
      kernel_limit_ok_q<=0;
    end else case (state)
      IDLE: if (start) begin
        error<=0;phase<=0;range_index<=0;
        if (spatial) state<=CALCULATE;
        else begin
          kernel_count<=0;position_count<=0;weight_bytes<=0;
          input_bytes<={32'd0,cfg.length}<<cfg.vector_s16;
          output_bytes<=(add_s8 || softmax_s8) ? {32'd0,cfg.length} :
              cfg.op==VEC_HADAMARD ? {30'd0,cfg.length,2'b00} : 64'd4;
          state<=FIELDS;
        end
      end
      // 两个十六位乘积分别寄存，CAPTURE 状态合并结果并保持固定检查周期。
      CALCULATE: begin
        // 核尺寸乘积已在前一阶段保存，提前记录配置上限检查结果。
        if (phase==3'd1) kernel_limit_ok_q <= (kernel_count <= 32'(depthwise ? MAX_TAPS : POOL_MAX_TAPS));
        state<=CAPTURE;
      end
      CAPTURE: begin
        case (phase)
          0: kernel_count<=product_q[31:0];
          1: position_count<=product_q[31:0];
          2: input_pixels<=product_q[31:0];
          3: weight_bytes<={16'd0,product_q};
          4: input_bytes<={16'd0,product_q};
          5: output_bytes<={16'd0,product_q};
          default: ;
        endcase
        if (phase==7) state<=FIELDS;
        else begin phase<=phase+1'b1;state<=CALCULATE;end
      end
      FIELDS: if (!fields_ok) begin error<=1;state<=COMPLETE;end
        else begin range_index<=0;state<=RANGE_SELECT;end
      RANGE_SELECT: begin
        range_enable_q<=selected_enable;
        state<=RANGE_ADD;
      end
      RANGE_ADD: begin
        range_size_ok<=range_bytes_q!=0 && range_bytes_q[63:32]==0;
        state<=RANGE_COMPARE;
      end
      RANGE_COMPARE: begin
        if (range_enable_q && (!range_size_ok || range_end_q[32] ||
            (range_index!=0 && !(range_before_output || output_before_range)))) begin
          error<=1;state<=COMPLETE;
        end else begin
          if (range_index==0) output_end_q<=range_end_q;
          if (range_index==5) state<=COMPLETE;
          else begin range_index<=range_index+1'b1;state<=RANGE_SELECT;end
        end
      end
      COMPLETE: state<=IDLE;
      default: begin error<=1;state<=COMPLETE;end
    endcase
  end

  // 准备数据只在对应阶段接收，异步复位由状态和有效资格统一处理。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else begin
      case (state)
        CALCULATE: begin
          range_dimension_saved <= range_dimension;
          range_padding_saved <= range_padding;
          multiply_low <= multiply_a[15:0] * multiply_b;
          multiply_high <= multiply_a[31:16] * multiply_b;
        end
        CAPTURE: begin
          case (phase)
            3'd6: output_y_in_range <= output_coordinate_in_range;
            3'd7: output_x_in_range <= output_coordinate_in_range;
            default: begin end
          endcase
        end
        RANGE_SELECT: begin
          range_base_q <= selected_base;
          range_bytes_q <= selected_bytes;
        end
        RANGE_ADD: begin
          range_end_q[7:0] <= range_end_low;
          range_end_q[32:8] <= range_end_high;
        end
        default: begin end
      endcase
    end
  end

  // 选择范围时先完成低字节求和，高位在下一状态使用已保存的进位。
  always_ff @(posedge clk) begin
    if (rst_n && state == RANGE_SELECT) begin
      {range_end_carry, range_end_low} <=
          {1'b0, selected_base[7:0]} + {1'b0, selected_bytes[7:0]};
    end
  end

  // 四个读取槽位复用检查阶段的完整末地址，未启用槽位保持零值。
  // 开始新配置、复位和错误完成均清零；调用方仅在检查成功后消费。
  always_ff @(posedge clk) begin
    if (!rst_n || (state == IDLE && start) || (state == COMPLETE && error)) begin
      for (int slot = 0; slot < 4; slot++) o_read_end[slot] <= '0;
    end else if (state == RANGE_COMPARE) begin
      case (range_index)
        3'd1: if (i_input_range || !spatial) o_read_end[0] <= range_end_q;
        3'd2: begin
          if (!i_input_range && depthwise) o_read_end[0] <= range_end_q;
          else if (!i_input_range && !spatial && (binary_vector || softmax_s8))
            o_read_end[1] <= range_end_q;
        end
        3'd3: if (!i_input_range && depthwise && cfg.bias_base != 0)
            o_read_end[1] <= range_end_q;
        3'd4: if (!i_input_range && depthwise) o_read_end[2] <= range_end_q;
        3'd5: if (!i_input_range && depthwise) o_read_end[3] <= range_end_q;
        default: begin end
      endcase
    end
  end
endmodule
