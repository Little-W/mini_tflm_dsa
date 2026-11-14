`ifndef TEST_PARAMS_SVH
`define TEST_PARAMS_SVH
`define TC_SIZE_VALUE 16
`define TC_IA_CACHE_BLOCKS_VALUE 4
localparam int unsigned TC_SIZE = 16;
localparam int unsigned TC_IA_CACHE_BLOCKS = 4;
localparam int unsigned TC_K = 5;
localparam int unsigned TC_N = 19;
localparam int unsigned TC_M = 7;
localparam int unsigned TC_IA_REUSE_NUM = 0;
localparam int unsigned TC_W_REUSE_NUM = 0;
localparam bit TC_DATAFLOW_MODE = 1'b0;
localparam int unsigned TC_PS_FRAME_COUNT = 16;
localparam int unsigned TC_COMPARE_WORDS = 282;
localparam int unsigned TC_MEM_WORDS = 4096;
localparam bit TC_CFG_16BITS_IA = 1'b0;
localparam bit TC_USE_PER_CHANNEL = 1'b0;
localparam logic [31:0] TC_LHS_BASE = 32'h00000100;
localparam logic [31:0] TC_RHS_BASE = 32'h00000200;
localparam logic [31:0] TC_BIAS_BASE = 32'h00000300;
localparam logic [31:0] TC_DST_BASE = 32'h00000400;
localparam logic [31:0] TC_LHS_ROW_STRIDE_B = 32'h00000014;
localparam logic [31:0] TC_RHS_ROW_STRIDE_B = 32'h00000014;
localparam logic [31:0] TC_DST_ROW_STRIDE_B = 32'h00000008;
localparam logic signed [31:0] TC_LHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_RHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_DST_ZP = 32'sd0;
localparam logic signed [31:0] TC_QMUL = 32'sd2147483647;
localparam logic signed [31:0] TC_QSHIFT = 32'sd0;
localparam logic signed [31:0] TC_ACT_MIN = -32'sd128;
localparam logic signed [31:0] TC_ACT_MAX = 32'sd127;
`endif
