// SPDX-License-Identifier: Apache-2.0
package dw_pool_pkg;
  typedef enum logic [3:0] {
    DW_S8 = 4'd0, AVGPOOL_S8 = 4'd1, MAXPOOL_S8 = 4'd2,
    MINPOOL_S8 = 4'd3, VEC_SUM = 4'd4, VEC_MAX = 4'd5,
    VEC_MIN = 4'd6, VEC_DOT = 4'd7, VEC_HADAMARD = 4'd8
  } dw_pool_op_t;

  typedef struct packed {
    logic [3:0] op;
    logic vector_s16;
    logic [31:0] length;
    logic [31:0] input_base, rhs_base, output_base, bias_base;
    logic [31:0] multiplier_base, shift_base;
    logic signed [31:0] output_offset, activation_min, activation_max;
    conv_im2col_pkg::conv_cfg_t image;
  } dw_pool_cfg_t;

  localparam logic [2:0] PE_MADD = 3'd0, PE_SUM = 3'd1,
    PE_MAX = 3'd2, PE_MIN = 3'd3, PE_MUL = 3'd4;
endpackage
