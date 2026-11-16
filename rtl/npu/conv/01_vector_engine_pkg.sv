// SPDX-License-Identifier: Apache-2.0
package vector_engine_pkg;
  typedef enum logic [3:0] {
    DW_S8 = 4'd0, AVGPOOL_S8 = 4'd1, MAXPOOL_S8 = 4'd2,
    MINPOOL_S8 = 4'd3, VEC_SUM = 4'd4, VEC_MAX = 4'd5,
    VEC_MIN = 4'd6, VEC_DOT = 4'd7, VEC_HADAMARD = 4'd8,
    ADD_S8 = 4'd9, SOFTMAX_S8 = 4'd10
  } vector_engine_op_t;

  typedef struct packed {
    logic signed [31:0] input1_offset, input2_offset;
    logic signed [31:0] input1_multiplier, input1_shift;
    logic signed [31:0] input2_multiplier, input2_shift;
    logic signed [31:0] left_shift;
    logic signed [31:0] output_multiplier, output_shift;
  } vector_add_cfg_t;

  typedef struct packed {
    logic [3:0] op;
    logic vector_s16;
    logic [31:0] length;
    logic [31:0] input_base, rhs_base, output_base, bias_base;
    logic [31:0] multiplier_base, shift_base;
    logic signed [31:0] output_offset, activation_min, activation_max;
    vector_add_cfg_t add;
    conv_im2col_pkg::conv_cfg_t image;
  } vector_engine_cfg_t;

  localparam logic [2:0] PE_MADD = 3'd0, PE_SUM = 3'd1,
    PE_MAX = 3'd2, PE_MIN = 3'd3, PE_MUL = 3'd4,
    PE_MUL_UU = 3'd5, PE_MUL_SU = 3'd6;
endpackage
