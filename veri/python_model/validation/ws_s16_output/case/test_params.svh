`ifndef TEST_PARAMS_SVH
`define TEST_PARAMS_SVH
`define TC_SIZE_VALUE 16
`define TC_IA_CACHE_BLOCKS_VALUE 4
localparam int unsigned TC_SIZE = 16;
localparam int unsigned TC_IA_CACHE_BLOCKS = 4;
localparam int unsigned TC_K = 3;
localparam int unsigned TC_N = 494;
localparam int unsigned TC_M = 7;
localparam int unsigned TC_IA_REUSE_NUM = 0;
localparam int unsigned TC_W_REUSE_NUM = 0;
localparam bit TC_DATAFLOW_MODE = 1'b0;
localparam int unsigned TC_PS_FRAME_COUNT = 16;
localparam int unsigned TC_COMPARE_WORDS = 1819;
localparam int unsigned TC_MEM_WORDS = 4096;
localparam bit TC_CFG_16BITS_IA = 1'b1;
localparam bit TC_USE_PER_CHANNEL = 1'b0;
localparam logic [31:0] TC_LHS_BASE = 32'h00000100;
localparam logic [31:0] TC_RHS_BASE = 32'h00000d00;
localparam logic [31:0] TC_BIAS_BASE = 32'h00001b00;
localparam logic [31:0] TC_DST_BASE = 32'h00001c00;
localparam logic [31:0] TC_LHS_ROW_STRIDE_B = 32'h000003dc;
localparam logic [31:0] TC_RHS_ROW_STRIDE_B = 32'h000001ee;
localparam logic [31:0] TC_DST_ROW_STRIDE_B = 32'h0000000e;
localparam logic signed [31:0] TC_LHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_RHS_ZP = 32'sd0;
localparam logic signed [31:0] TC_DST_ZP = 32'sd0;
localparam logic signed [31:0] TC_QMUL = 32'sd2122065762;
localparam logic signed [31:0] TC_QSHIFT = 32'sd0;
localparam logic signed [31:0] TC_ACT_MIN = -32'sd31782;
localparam logic signed [31:0] TC_ACT_MAX = 32'sd19938;
`endif
