// SPDX-License-Identifier: Apache-2.0
// 根据固定物理容量选择行数上限，在当前周期完成部分和存储容量检查。
`default_nettype none
module ps_capacity_limits #(
    parameter int p_max_rows = 1024,
    parameter int p_rows_width = $clog2(p_max_rows + 1),
    parameter int p_frames_width = 5,
    parameter int p_total_banks = 7,
    parameter int p_bank_bytes = 2048,
    parameter int p_tile_shift = 4
) (
    input  wire logic [p_rows_width-1:0]   i_frame_rows /* 一个待保留部分和帧的有效行数 */,
    input  wire logic [p_frames_width-1:0] i_frames /* 同时保留的部分和帧数 */,
    input  wire logic [31:0]               i_bank_count /* 当前分配给部分和的物理存储块数 */,
    input  wire logic [31:0]               i_frame_slice_tiles /* 单条帧命令沿流式行方向处理的矩阵块数 */,
    input  wire logic                      i_use_frame_commands /* 采用显式帧命令进行部分和调度 */,
    output logic                      o_frames_fit /* 全部活动帧满足当前物理存储容量 */,
    output logic                      o_admission_fit /* 单条待接收帧命令满足容量及切片限制 */
);
    //! 0. 常量与选择信号
    //! -----------------

    localparam int p_frame_codes = 1 << p_frames_width;
    localparam int p_bank_words = p_bank_bytes / 16;
    localparam int p_bank_count0 = p_total_banks - 1;
    localparam int p_bank_count1 = p_total_banks - 2;
    localparam int p_bank_count2 = p_total_banks - 4;

    logic [2:0] bank_select;
    logic bank_valid;
    logic [p_rows_width-1:0] row_limit_table [0:p_frame_codes-1];
    logic [p_rows_width-1:0] frame_row_limit;
    logic [p_rows_width-1:0] admission_row_limit;
    logic [31:0] admission_tile_limit;

    assign bank_select[0] = (i_bank_count == 32'(p_bank_count0));
    assign bank_select[1] = (i_bank_count == 32'(p_bank_count1));
    assign bank_select[2] = (i_bank_count == 32'(p_bank_count2));
    assign bank_valid = |bank_select;

    //! 1. 每个帧数对应的常量行数上限
    //! -----------------------------

    // 每行占用四个 128 位存储字，物理存储块轮流接收连续的数据字。
    // ceil(4*rows/banks)*frames <= depth 等价于
    // rows <= floor(banks*floor(depth/frames)/4)，除法均在参数展开时求值。
    assign row_limit_table[0] = '0;
    for (genvar frame_count = 1; frame_count < p_frame_codes; frame_count++) begin : g_frame_limit
        localparam int p_limit0 = (p_bank_count0 * (p_bank_words / frame_count)) / 4;
        localparam int p_limit1 = (p_bank_count1 * (p_bank_words / frame_count)) / 4;
        localparam int p_limit2 = (p_bank_count2 * (p_bank_words / frame_count)) / 4;
        localparam int p_rows0 = (p_limit0 < p_max_rows) ? p_limit0 : p_max_rows;
        localparam int p_rows1 = (p_limit1 < p_max_rows) ? p_limit1 : p_max_rows;
        localparam int p_rows2 = (p_limit2 < p_max_rows) ? p_limit2 : p_max_rows;

        assign row_limit_table[frame_count] =
            ({p_rows_width{bank_select[0]}} & p_rows_width'(p_rows0)) |
            ({p_rows_width{bank_select[1]}} & p_rows_width'(p_rows1)) |
            ({p_rows_width{bank_select[2]}} & p_rows_width'(p_rows2));
    end
    assign frame_row_limit = row_limit_table[i_frames];
    // 零个活动帧及索引零的空存储项沿用配置检查中的空集合结果。
    assign o_frames_fit = (i_frames == '0) || (i_bank_count == 32'd0) ||
        (bank_valid && (i_frame_rows <= frame_row_limit));

    //! 2. 单个命令的存储容量
    //! ---------------------

    assign admission_row_limit = row_limit_table[p_frames_width'(1)];
    assign admission_tile_limit = 32'(admission_row_limit) >> p_tile_shift;
    // 分帧命令使用 min(rows, slice_tiles*SIZE)，直接比较两个候选值的上限。
    assign o_admission_fit = (i_bank_count == 32'd0) ||
        (bank_valid && ((i_frame_rows <= admission_row_limit) ||
         (i_use_frame_commands && (i_frame_slice_tiles <= admission_tile_limit))));
endmodule
`default_nettype wire
