`ifndef TEST_PARAMS_SVH
`define TEST_PARAMS_SVH
`define TC_SIZE_VALUE 16
`define TC_IA_CACHE_BLOCKS_VALUE 8
localparam int unsigned TC_SIZE = 16;
localparam int unsigned TC_IA_CACHE_BLOCKS = 8;
localparam int unsigned TC_K = 128;
localparam int unsigned TC_N = 32;
localparam int unsigned TC_M = 128;
localparam int unsigned TC_IA_REUSE_NUM = 0;
localparam int unsigned TC_W_REUSE_NUM = 0;
localparam bit TC_DATAFLOW_MODE = 1'b0;
localparam int unsigned TC_PS_FRAME_COUNT = 16;
localparam int unsigned TC_COMPARE_WORDS = 6352;
localparam int unsigned TC_MEM_WORDS = 6352;
localparam bit TC_CFG_16BITS_IA = 1'b0;
localparam bit TC_USE_PER_CHANNEL = 1'b0;
localparam logic [31:0] TC_LHS_BASE = 32'h00000100;
localparam logic [31:0] TC_RHS_BASE = 32'h00001100;
localparam logic [31:0] TC_BIAS_BASE = 32'h00002100;
localparam logic [31:0] TC_DST_BASE = 32'h00002300;
localparam logic [31:0] TC_LHS_ROW_STRIDE_B = 32'h00000020;
localparam logic [31:0] TC_RHS_ROW_STRIDE_B = 32'h00000020;
localparam logic [31:0] TC_DST_ROW_STRIDE_B = 32'h00000080;
localparam logic signed [31:0] TC_LHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_RHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_DST_ZP = 32'sd0;
localparam logic signed [31:0] TC_QMUL = 32'sd2147483647;
localparam logic signed [31:0] TC_QSHIFT = 32'sd0;
localparam logic signed [31:0] TC_ACT_MIN = -32'sd128;
localparam logic signed [31:0] TC_ACT_MAX = 32'sd127;
`endif
