// SPDX-License-Identifier: Apache-2.0
// Sequential descriptor validation. The caller holds cfg stable through done.
module vector_config_check #(
  parameter int TILE=16,
  parameter int MAX_TAPS=49,
  parameter int POOL_MAX_TAPS=256
) (
  input logic clk,rst_n,start,
  input vector_engine_pkg::vector_engine_cfg_t cfg,
  output logic ready,done,error,
  output logic [31:0] kernel_count,position_count,
  output logic [63:0] input_bytes,output_bytes,weight_bytes
);
  import vector_engine_pkg::*;
  typedef enum logic [3:0] {IDLE,CALCULATE,CAPTURE,FIELDS,
    RANGE_SELECT,RANGE_ADD,RANGE_COMPARE,COMPLETE} state_t;
  state_t state;
  logic [2:0] phase,range_index;
  logic [31:0] input_pixels,multiply_a;
  logic [15:0] multiply_b;
  (* use_dsp="yes" *) logic [31:0] multiply_low,multiply_high;
  (* use_dsp="no" *) wire [47:0] product_q={16'd0,multiply_low}+{multiply_high,16'd0};
  logic [47:0] last_y,last_x;
  logic [16:0] range_x_sum, range_y_sum;
  logic [16:0] range_x_carry, range_y_carry;
  logic [17:0] range_x_compare, range_y_compare;
  logic output_x_in_range, output_y_in_range;
  logic fields_ok,spatial,depthwise,binary_vector,add_s8,softmax_s8;
  logic [31:0] selected_base,range_base_q;
  logic [63:0] selected_bytes,range_bytes_q;
  logic selected_enable,range_enable_q,range_size_ok;
  logic [32:0] range_end_q,output_end_q;
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
  // 将尺寸、填充和末坐标反码先压缩为两项，单次进位给出严格小于关系。
  assign range_x_sum = {1'b0, cfg.image.input_w} ^ {1'b0, cfg.image.pad_left} ^ ~last_x[16:0];
  assign range_y_sum = {1'b0, cfg.image.input_h} ^ {1'b0, cfg.image.pad_top} ^ ~last_y[16:0];
  assign range_x_carry = ({1'b0, cfg.image.input_w} & {1'b0, cfg.image.pad_left}) |
      (({1'b0, cfg.image.input_w} ^ {1'b0, cfg.image.pad_left}) & ~last_x[16:0]);
  assign range_y_carry = ({1'b0, cfg.image.input_h} & {1'b0, cfg.image.pad_top}) |
      (({1'b0, cfg.image.input_h} ^ {1'b0, cfg.image.pad_top}) & ~last_y[16:0]);
  assign range_x_compare = {1'b0, range_x_sum} + {range_x_carry, 1'b0};
  assign range_y_compare = {1'b0, range_y_sum} + {range_y_carry, 1'b0};
  assign output_x_in_range = !(|last_x[47:17]) && range_x_compare[17];
  assign output_y_in_range = !(|last_y[47:17]) && range_y_compare[17];

  always_comb begin
    fields_ok=cfg.op<=SOFTMAX_S8;
    if (spatial) begin
      fields_ok=fields_ok && cfg.image.input_h!=0 && cfg.image.input_w!=0 && cfg.image.input_c!=0 &&
        cfg.image.output_h!=0 && cfg.image.output_w!=0 && cfg.image.kernel_h!=0 && cfg.image.kernel_w!=0 &&
        kernel_count<=32'(depthwise ? MAX_TAPS : POOL_MAX_TAPS) &&
        cfg.image.stride_h!=0 && cfg.image.stride_w!=0 &&
        cfg.image.dilation_h!=0 && cfg.image.dilation_w!=0 && !cfg.image.input_s16 && !cfg.vector_s16 &&
        weight_bytes[63:32]==0 && cfg.activation_min>=-128 && cfg.activation_max<=127 &&
        cfg.activation_min<=cfg.activation_max;
      if (depthwise) begin
        fields_ok=fields_ok && cfg.image.input_offset>=-127 && cfg.image.input_offset<=128 &&
          cfg.output_offset>=-128 && cfg.output_offset<=127 &&
          cfg.multiplier_base[1:0]==0 && cfg.shift_base[1:0]==0;
        if (cfg.bias_base!=0) fields_ok=fields_ok && cfg.bias_base[1:0]==0;
      end else begin
        fields_ok=fields_ok && cfg.image.input_offset==0 && cfg.output_offset==0 &&
          cfg.image.dilation_h==1 && cfg.image.dilation_w==1 &&
          cfg.image.pad_top<cfg.image.kernel_h && cfg.image.pad_left<cfg.image.kernel_w &&
          output_y_in_range && output_x_in_range;
      end
    end else begin
      fields_ok=fields_ok && cfg.length!=0 && (add_s8 || softmax_s8 || cfg.output_base[1:0]==0);
      if (cfg.vector_s16) fields_ok=fields_ok && cfg.input_base[0]==0;
      if (binary_vector && cfg.vector_s16) fields_ok=fields_ok && cfg.rhs_base[0]==0;
      if (softmax_s8) fields_ok=fields_ok && !cfg.vector_s16 && cfg.length<=32'(TILE) && cfg.rhs_base[1:0]==0;
      if (add_s8) fields_ok=fields_ok && !cfg.vector_s16 &&
        cfg.add.input1_offset>=-127 && cfg.add.input1_offset<=128 &&
        cfg.add.input2_offset>=-127 && cfg.add.input2_offset<=128 &&
        cfg.add.input1_multiplier>=0 && cfg.add.input2_multiplier>=0 && cfg.add.output_multiplier>=0 &&
        cfg.add.input1_shift>=-31 && cfg.add.input1_shift<=0 &&
        cfg.add.input2_shift>=-31 && cfg.add.input2_shift<=0 &&
        cfg.add.left_shift>=0 && cfg.add.left_shift<=22 &&
        cfg.add.output_shift>=-31 && cfg.add.output_shift<=30 &&
        cfg.output_offset>=-128 && cfg.output_offset<=127 &&
        cfg.activation_min>=-128 && cfg.activation_max<=127 && cfg.activation_min<=cfg.activation_max;
    end
  end
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
      // Independent registered 16-bit products avoid an unregistered DSP
      // cascade. CAPTURE combines them without changing validation latency.
      CALCULATE: begin
        multiply_low<=multiply_a[15:0]*multiply_b;
        multiply_high<=multiply_a[31:16]*multiply_b;
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
          6: last_y<=product_q;
          7: last_x<=product_q;
          default: ;
        endcase
        if (phase==7) state<=FIELDS;
        else begin phase<=phase+1'b1;state<=CALCULATE;end
      end
      FIELDS: if (!fields_ok) begin error<=1;state<=COMPLETE;end
        else begin range_index<=0;state<=RANGE_SELECT;end
      RANGE_SELECT: begin
        range_base_q<=selected_base;range_bytes_q<=selected_bytes;range_enable_q<=selected_enable;
        state<=RANGE_ADD;
      end
      RANGE_ADD: begin
        range_end_q<={1'b0,range_base_q}+{1'b0,range_bytes_q[31:0]};
        range_size_ok<=range_bytes_q!=0 && range_bytes_q[63:32]==0;
        state<=RANGE_COMPARE;
      end
      RANGE_COMPARE: begin
        if (range_enable_q && (!range_size_ok || range_end_q[32] ||
            (range_index!=0 && !(range_end_q<={1'b0,cfg.output_base} ||
                                 output_end_q<={1'b0,range_base_q})))) begin
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
endmodule
