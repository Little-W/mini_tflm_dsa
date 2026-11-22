`default_nettype none

// 任务配置流水、共享容量检查和输出分组准备。
module npu_task_configuration #(
    parameter int unsigned p_bus_width = 32'd64,
    parameter int unsigned p_data_width = 32'd16,
    parameter int unsigned p_dim_count_width = 32'd16,
    parameter int unsigned p_enable_is_mode = 32'd1,
    parameter int unsigned p_enable_per_channel = 32'd1,
    parameter bit p_frame_exec_enabled = 1'h1,
    parameter int unsigned p_ia_cache_blocks = 32'd4,
    parameter int unsigned p_ia_compact_enable = 32'd1,
    parameter int unsigned p_ia_data_width = 32'd16,
    parameter int unsigned p_ia_reuse_num_max = 32'd32,
    parameter int unsigned p_ia_reuse_w = 32'd6,
    parameter int unsigned p_is_bias_valid_w = 32'd10,
    parameter int unsigned p_kernel_data_width = 32'd16,
    parameter int unsigned p_oa_fifo_banks = 32'd32,
    parameter int unsigned p_oa_s16_fifo_banks = 32'd4,
    parameter int unsigned p_ps_frame_count_width = 32'd5,
    parameter int unsigned p_ps_required_width = 32'd15,
    parameter int unsigned p_ps_row_count_width = 32'd10,
    parameter int unsigned p_ps_storage_rows = 32'd799,
    parameter int unsigned p_reg_width = 32'd32,
    parameter int unsigned p_shared_bank_bytes = 32'd8192,
    parameter int unsigned p_shared_physical_banks = 32'd7,
    parameter int unsigned p_shared_physical_banks_width = 32'd3,
    parameter int unsigned p_shared_ps_directory_rows = 32'd1024,
    parameter bit p_shared_ram_enabled = 1'h1,
    parameter int unsigned p_shared_total_bytes = 32'd57344,
    parameter int unsigned p_size = 32'd16,
    parameter int unsigned p_size_shift = 32'd4,
    parameter int unsigned p_vector_shared_ia_banks = 32'd1,
    parameter int unsigned p_w_reuse_num_max = 32'd16,
    parameter int unsigned p_w_reuse_w = 32'd5,
    localparam int unsigned p_s8_reserve_width = (p_oa_fifo_banks <= 1) ? 1 : $clog2(p_oa_fifo_banks + 1),
    localparam int unsigned p_s16_reserve_width = (p_oa_s16_fifo_banks <= 1) ? 1 : $clog2(p_oa_s16_fifo_banks + 1)
) (
    input logic [p_reg_width-1:0] i_bias_base,
    input logic i_cfg_16bits_ia,
    input logic i_cfg_16x8,
    input logic [p_reg_width-1:0] i_cfg_col_groups,
    input logic [p_reg_width-1:0] i_cfg_col_tail_tiles,
    input conv_im2col_pkg::conv_cfg_t i_cfg_conv,
    input logic i_cfg_conv_enable,
    input logic i_cfg_dataflow_mode,
    input logic i_cfg_dataflow_mode_eff,
    input logic [p_reg_width-1:0] i_cfg_ia_reuse_num,
    input logic i_cfg_rhs_tile_packed,
    input logic [p_reg_width-1:0] i_cfg_row_groups,
    input logic [p_reg_width-1:0] i_cfg_row_tail_tiles,
    input logic [31:0] i_cfg_shared_ia_banks,
    input logic i_cfg_start_event,
    input logic [p_reg_width-1:0] i_cfg_w_reuse_num,
    input logic clk,
    input conv_im2col_pkg::conv_cfg_t i_conv_cfg_q,
    input logic rst_n,
    input logic i_ctrl_sa_ready,
    input logic [p_reg_width-1:0] i_dst_base,
    input logic [p_reg_width-1:0] i_dst_row_stride_b,
    input logic i_frame_mode_q,
    input logic i_frame_scheduler_ready,
    input logic [p_reg_width-1:0] i_k,
    input logic [p_reg_width-1:0] i_lhs_base,
    input logic [p_reg_width-1:0] i_lhs_row_stride_b,
    input logic signed [p_reg_width-1:0] i_lhs_zp,
    input logic [p_reg_width-1:0] i_m,
    input logic [p_reg_width-1:0] i_n,
    input logic [31:0] i_ps_control_q,
    input logic signed [p_reg_width-1:0] i_q_mult_pt,
    input logic signed [p_reg_width-1:0] i_q_shift_pt,
    input logic [p_reg_width-1:0] i_rhs_base,
    input logic [p_reg_width-1:0] i_rhs_col_stride_b,
    input logic signed [p_reg_width-1:0] i_rhs_zp,
    input logic i_run_conv,
    input logic i_run_lhs_tile_packed,
    input logic i_run_rhs_tile_packed,
    input logic i_use_per_channel,
    input logic i_use_per_channel_eff,
    input logic i_vector_start_fire,
    output logic [31:0] o_active_ia_cache_blocks,
    output logic [31:0] o_active_ps_bank_count,
    output logic [31:0] o_active_ps_bank_depth,
    output logic o_cfg_16bits_ia_eff,
    output logic o_cfg_16x8_q [0:2],
    output logic [p_reg_width-1:0] o_cfg_ia_reuse_q [0:2],
    output logic [p_reg_width-1:0] o_cfg_n_q [0:2],
    output logic o_cfg_stage2_fire,
    output logic [p_reg_width-1:0] o_cfg_stream_k_q [0:2],
    output logic [p_reg_width-1:0] o_cfg_stream_m_q [0:2],
    output logic o_cfg_use16_q [0:2],
    output logic [2:0] o_cfg_valid_q,
    output logic [p_reg_width-1:0] o_cfg_w_reuse_q [0:2],
    output logic [31:0] o_conv_range_base [4],
    output logic [32:0] o_conv_range_end [4],
    output logic o_direct_output_cfg,
    output logic [1:0] o_frame_config_error,
    output logic [31:0] o_frame_slice_tiles_s2,
    output logic [p_reg_width-1:0] o_ia_reuse_num_eff,
    output logic [p_is_bias_valid_w-1:0] o_is_bias_group_rows_target,
    output logic [4:0] o_oa_chunk_cols_pre,
    output logic o_oa_is_coalesce_pre,
    output logic o_oa_ws_coalesce_pre,
    output logic [p_s8_reserve_width-1:0] o_output_reserve_banks,
    output logic [p_s16_reserve_width-1:0] o_output_s16_ready_threshold,
    output logic [p_s16_reserve_width-1:0] o_output_s16_reserve_banks,
    output logic [p_s8_reserve_width-1:0] o_output_s8_ready_threshold,
    output logic [63:0] o_ps_admission_rows,
    output logic o_ps_force_raw_q,
    output logic [2:0] o_ps_word_cap_q,
    output logic o_run_16x8,
    output logic o_run_compact,
    output logic signed [p_reg_width-1:0] o_run_compact_offset,
    output logic o_run_is_mode,
    output logic [p_reg_width-1:0] o_run_k,
    output logic [p_reg_width-1:0] o_run_m,
    output logic [p_reg_width-1:0] o_run_n,
    output logic o_run_use_16bits,
    output logic o_shared_allocation_invalid,
    output logic [31:0] o_shared_ia_banks_q,
    output logic [p_reg_width-1:0] o_stream_k,
    output logic [p_reg_width-1:0] o_stream_m,
    output logic o_tiling_invalid,
    output logic o_use_frame_commands_s2,
    output logic [p_reg_width-1:0] o_w_reuse_num_eff
);

    localparam int CAP_ROWS_W = $clog2(p_ia_reuse_num_max * p_size + 1);
    localparam int CAP_FRAMES_W = $clog2(p_w_reuse_num_max + 1);
    localparam int CAP_WORDS_W = $clog2(4 * p_ia_reuse_num_max * p_size + 1);
`ifdef GEMMORA_INT8_PROFILE
    localparam bit CONV_CORE_SUPPORTED = 1'b0;
`endif
`ifndef GEMMORA_INT8_PROFILE
    localparam bit CONV_CORE_SUPPORTED = p_data_width >= 16 && (p_bus_width == 32 || p_bus_width == 64) && p_reg_width == 32 && p_enable_per_channel != 0;
`endif
    localparam int unsigned IA_SHAPE_REQUIRED_WIDTH = p_ia_reuse_w > 5 ? p_ia_reuse_w : 5;
    localparam int unsigned IA_SHAPE_WIDTH =
    IA_SHAPE_REQUIRED_WIDTH < p_reg_width ? IA_SHAPE_REQUIRED_WIDTH : p_reg_width;
    localparam bit PS_REQUIRE_RAW_CAPACITY = 1'b1;
    localparam int unsigned p_compute_output_stages = 1;
    localparam int unsigned DIRECT_OUTPUT_EXTRA_BANKS =
    (p_size - 1 + p_compute_output_stages + requant_pkg::REQUANT_LATENCY + p_size - 1) / p_size;
    localparam int OA_REUSE_ROWS_WIDTH=$clog2(p_oa_fifo_banks+2);
    localparam int OA_DIRECT_AVAILABLE_BANKS=p_oa_fifo_banks>DIRECT_OUTPUT_EXTRA_BANKS ?
    p_oa_fifo_banks-DIRECT_OUTPUT_EXTRA_BANKS : 0;

    logic [p_shared_physical_banks_width-1:0] active_ps_bank_count_q;
    logic [31:0] active_ps_pool_bytes;
    logic [p_is_bias_valid_w-1:0] cfg_bias_rows_target_s2;
    logic [2:0] cfg_capacity_phase;
    logic signed [p_reg_width-1:0] cfg_compact_offset_q [0:2];
    logic cfg_compact_q [0:2];
    logic [p_reg_width-1:0] cfg_k_q [0:2];
    logic [p_reg_width-1:0] cfg_m_q [0:2];
    logic cfg_mode_q [0:2];
    logic [p_reg_width-1:0] cfg_ps_col_tiles_s0;
    logic [p_ps_frame_count_width-1:0] cfg_ps_frames_s1;
    logic [p_reg_width-1:0] cfg_ps_r_s0;
    logic [p_ps_required_width-1:0] cfg_ps_required_s2;
    logic [p_reg_width-1:0] cfg_ps_row_tiles_s0;
    logic [p_ps_row_count_width-1:0] cfg_ps_rows_s1;
    logic [p_reg_width-1:0] cfg_ps_w_s0;
    logic cfg_stream_compact;
    logic cfg_stream_is_mode;
    logic signed [p_reg_width-1:0] cfg_stream_offset;
    logic cfg_stream_source_s8;
    logic [32:0] column_sum_i_a;
    logic [32:0] column_sum_i_b;
    logic [8:0] conv_bias_end_high;
    logic [24:0] conv_bias_end_low;
    logic conv_config_invalid;
    logic conv_dimension_invalid;
    logic [31:0] conv_group_end;
    logic [31:0] conv_input_area;
    logic [47:0] conv_input_bytes;
    logic conv_input_end_carry;
    logic [8:0] conv_input_end_high;
    logic [24:0] conv_input_end_low;
    logic [31:0] conv_input_high;
    logic [15:0] conv_input_high_merged;
    logic [31:0] conv_input_low;
    logic [16:0] conv_input_middle_q;
    logic [16:0] conv_input_middle_sum;
    logic conv_input_range_invalid;
    logic [31:0] conv_kernel_area;
    logic [47:0] conv_kernel_elements;
    logic [31:0] conv_kernel_high;
    logic [15:0] conv_kernel_high_merged;
    logic [31:0] conv_kernel_low;
    logic [16:0] conv_kernel_middle_q;
    logic [16:0] conv_kernel_middle_sum;
    logic [8:0] conv_mult_end_high;
    logic [24:0] conv_mult_end_low;
    logic [31:0] conv_output_area;
    logic [31:0] conv_parameter_bytes_low;
    logic conv_parameter_range_invalid;
    logic [3:0] conv_range_end_carry;
    logic [8:0] conv_rhs_end_high;
    logic [24:0] conv_rhs_end_low;
    logic conv_rhs_range_invalid;
    logic [8:0] conv_shift_end_high;
    logic [24:0] conv_shift_end_low;
    logic conv_syntax_invalid;
    logic conv_validation_invalid;
    logic [p_reg_width-1:0] ext_ia_capacity;
    logic ext_ia_capacity_equal;
    logic ext_ia_capacity_less;
    logic ext_r_legal;
    logic [p_ia_reuse_w-1:0] ext_r_small;
    logic ext_w_legal;
    logic [p_w_reuse_w-1:0] ext_w_small;
    logic [1:0] frame_config_error_calc;
    logic [31:0] frame_slice_tiles_calc;
    logic [p_reg_width-1:0] ia_reuse_num_eff_s1;
    logic [p_reg_width-1:0] ia_reuse_shape_i_value;
    logic ia_reuse_shape_o_valid;
    logic legacy_window_shape_s2;
    logic [4:0] oa_cfg_chunk_choice;
    logic [3:0] oa_cfg_chunk_fit;
    logic [p_reg_width+3:0] oa_cfg_k_limit;
    logic oa_cfg_narrow_chunk;
    logic [OA_REUSE_ROWS_WIDTH-1:0] oa_cfg_reuse_limit;
    logic [OA_REUSE_ROWS_WIDTH-1:0] oa_cfg_reuse_rows;
    logic [OA_REUSE_ROWS_WIDTH-1:0] oa_cfg_row_tiles;
    logic oa_cfg_rows_exceed;
    logic [p_reg_width-1:0] oa_is_alignment_mask;
    logic oa_is_coalesce_q;
    logic oa_ws_coalesce_q;
    logic oa_ws_reserve_fits;
    logic [OA_REUSE_ROWS_WIDTH-1:0] oa_ws_reuse_rows_pre;
    logic [31:0] output_reserve_calc;
    logic [31:0] output_reserve_i_a;
    logic [31:0] output_reserve_i_b;
    logic output_reserve_i_carry;
    logic output_reserve_o_carry;
    logic [31:0] output_reserve_uncapped;
    logic [31:0] output_s16_reserve_uncapped;
    logic ps_admission_bank_capacity_fits;
    logic [63:0] ps_admission_bank_words;
    logic [63:0] ps_admission_rows_calc;
    logic [63:0] ps_admission_words;
    logic ps_capacity_config_invalid;
    logic ps_capacity_config_invalid_calc;
    logic [63:0] ps_capacity_required_bytes;
    logic [32:0] ps_column_sum;
    logic ps_column_sum_overflow;
    logic ps_config_force_raw;
    logic [2:0] ps_config_word_cap;
    logic ps_configuration_invalid;
    logic ps_cross_k_required;
    logic [CAP_FRAMES_W-1:0] ps_frames_bounded;
    logic [CAP_FRAMES_W-1:0] ps_frames_bounded_calc;
    logic [CAP_ROWS_W-1:0] ps_group_rows_bounded;
    logic [5:0] ps_lhs_exp_s2;
    logic signed [p_reg_width-1:0] ps_lhs_offset_s2;
    logic ps_lhs_source_s16_s2;
    logic [63:0] ps_live_frames;
    logic ps_long_bank_capacity_fits;
    logic [CAP_WORDS_W+CAP_FRAMES_W-1:0] ps_long_bank_total;
    logic ps_long_capacity_fits;
    logic ps_long_capacity_fits_calc;
    logic ps_long_capacity_fits_q;
    logic [63:0] ps_long_frame_bank_words;
    logic [63:0] ps_long_frame_words;
    logic [63:0] ps_max_frame_rows;
    logic [63:0] ps_output_column_tiles;
    logic [5:0] ps_product_exp_s2;
    logic ps_raw_bank_capacity_fits;
    logic [CAP_WORDS_W+CAP_FRAMES_W-1:0] ps_raw_bank_total;
    logic ps_raw_capacity_fits;
    logic ps_raw_capacity_fits_calc;
    logic ps_raw_capacity_fits_q;
    logic [63:0] ps_raw_frame_bank_words;
    logic [31:0] ps_retained_k_s2;
    logic [5:0] ps_rhs_exp_s2;
    logic [CAP_ROWS_W-1:0] ps_rows_bounded;
    logic [CAP_ROWS_W-1:0] ps_rows_bounded_calc;
    logic [CAP_ROWS_W+CAP_FRAMES_W-1:0] ps_rows_frames;
    logic ps_s24_bound_s2;
    logic ps_stream_rows_equal;
    logic ps_stream_rows_less;
    logic [31:0] ps_unchecked_group_rows;
    logic [CAP_ROWS_W-1:0] ps_unchecked_rows;
    logic requested_allocation_invalid;
    logic [31:0] requested_ps_bank_count;
    logic [31:0] requested_shared_ia_banks;
    logic [63:0] rhs_allocation_bytes;
    logic [31:0] rhs_extent_m;
    logic [31:0] rhs_extent_n;
    logic [32:0] rhs_product_cross;
    logic [63:0] rhs_product_diagonal;
    logic [31:0] rhs_product_hh;
    logic [23:0] rhs_product_high_merged;
    logic [23:0] rhs_product_high_q;
    logic [23:0] rhs_product_high_sum;
    logic [31:0] rhs_product_hl;
    logic [31:0] rhs_product_lh;
    logic [31:0] rhs_product_ll;
    logic [24:0] rhs_product_low_sum;
    logic [24:0] rhs_product_middle_q;
    logic shared_allocation_invalid_q;
    logic tiling_invalid_calc;
    logic unused_column_sum_carry;
    logic use_frame_commands_calc;
    logic [p_reg_width-1:0] w_reuse_num_eff_s1;
    logic [p_reg_width-1:0] w_reuse_shape_i_value;
    logic w_reuse_shape_o_valid;

    assign o_conv_range_base[0] = 32'(i_rhs_base);
    assign o_conv_range_base[1] = 32'(i_bias_base);
    assign o_conv_range_base[2] = i_use_per_channel ? 32'(i_q_mult_pt) : 32'd0;
    assign o_conv_range_base[3] = i_use_per_channel ? 32'(i_q_shift_pt) : 32'd0;
    // 各段算术保留原有宽度，准备相位只选择对应的完整结果。
    assign rhs_product_high_sum = rhs_product_diagonal[63:40] +
        24'(rhs_product_cross[32:24]);
    assign rhs_product_high_merged = rhs_product_high_q + 24'(rhs_product_middle_q[24]);
    assign conv_input_high_merged = conv_input_high[31:16] + 16'(conv_input_middle_q[16]);
    assign conv_kernel_high_merged = conv_kernel_high[31:16] + 16'(conv_kernel_middle_q[16]);
    assign rhs_product_low_sum = {1'b0, rhs_product_diagonal[39:16]} +
        {1'b0, rhs_product_cross[23:0]};
    assign conv_input_middle_sum = {1'b0, conv_input_low[31:16]} +
        {1'b0, conv_input_high[15:0]};
    assign conv_kernel_middle_sum = {1'b0, conv_kernel_low[31:16]} +
        {1'b0, conv_kernel_high[15:0]};
assign conv_parameter_bytes_low = {30'(i_m), 2'b00};
    assign conv_rhs_end_low = {1'b0, 24'(i_rhs_base)} + {1'b0, rhs_allocation_bytes[23:0]};
    assign conv_input_end_low = {1'b0, i_conv_cfg_q.input_base[23:0]} + {1'b0, conv_input_bytes[23:0]};
    assign conv_bias_end_low = {1'b0, 24'(i_bias_base)} + {1'b0, conv_parameter_bytes_low[23:0]};
    assign conv_mult_end_low = {1'b0, 24'(i_q_mult_pt)} + {1'b0, conv_parameter_bytes_low[23:0]};
    assign conv_shift_end_low = {1'b0, 24'(i_q_shift_pt)} + {1'b0, conv_parameter_bytes_low[23:0]};
    assign conv_rhs_end_high = {1'b0, 8'(i_rhs_base >> 24)} +
        {1'b0, rhs_allocation_bytes[31:24]} + 9'(conv_range_end_carry[0]);
    assign conv_input_end_high = {1'b0, i_conv_cfg_q.input_base[31:24]} +
        {1'b0, conv_input_bytes[31:24]} + 9'(conv_input_end_carry);
    assign conv_bias_end_high = {1'b0, 8'(i_bias_base >> 24)} +
        {1'b0, conv_parameter_bytes_low[31:24]} + 9'(conv_range_end_carry[1]);
    assign conv_mult_end_high = {1'b0, 8'(i_q_mult_pt >> 24)} +
        {1'b0, conv_parameter_bytes_low[31:24]} + 9'(conv_range_end_carry[2]);
    assign conv_shift_end_high = {1'b0, 8'(i_q_shift_pt >> 24)} +
        {1'b0, conv_parameter_bytes_low[31:24]} + 9'(conv_range_end_carry[3]);
    assign conv_group_end = 32'(i_conv_cfg_q.group_offset) + 32'(i_conv_cfg_q.group_c);
assign conv_syntax_invalid = (!CONV_CORE_SUPPORTED ||
         (i_cfg_dataflow_mode && (p_enable_is_mode == 0 || p_kernel_data_width < 16)) ||
         !i_cfg_16bits_ia || i_cfg_16x8 || i_conv_cfg_q.input_s16 || i_run_lhs_tile_packed ||
         (i_lhs_zp != 0) || (i_rhs_zp != 0) ||
         i_conv_cfg_q.input_h == 0 || i_conv_cfg_q.input_w == 0 || i_conv_cfg_q.input_c == 0 ||
         i_conv_cfg_q.kernel_h == 0 || i_conv_cfg_q.kernel_w == 0 || i_conv_cfg_q.group_c == 0 ||
         i_conv_cfg_q.output_h == 0 || i_conv_cfg_q.output_w == 0 ||
         i_conv_cfg_q.stride_h == 0 || i_conv_cfg_q.stride_w == 0 ||
         i_conv_cfg_q.dilation_h == 0 || i_conv_cfg_q.dilation_w == 0 ||
         (conv_group_end > 32'(i_conv_cfg_q.input_c)) ||
         $signed(i_conv_cfg_q.input_offset) < -127 || $signed(i_conv_cfg_q.input_offset) > 128);
assign conv_config_invalid = i_run_conv && conv_validation_invalid;
assign requested_shared_ia_banks = i_cfg_shared_ia_banks == 0 ?
        (p_shared_ram_enabled && !cfg_stream_compact ? 32'd2 : 32'd1) : i_cfg_shared_ia_banks;
assign requested_ps_bank_count = p_shared_ram_enabled ?
        (requested_shared_ia_banks < p_shared_physical_banks ?
         32'(p_shared_physical_banks) - requested_shared_ia_banks : 32'd1) : 32'd4;
assign requested_allocation_invalid = p_shared_ram_enabled &&
        (requested_shared_ia_banks == 0 || requested_shared_ia_banks > p_shared_physical_banks - 4 ||
         (requested_shared_ia_banks != 1 && requested_shared_ia_banks != 2 && requested_shared_ia_banks != 4));
assign o_active_ia_cache_blocks = p_shared_ram_enabled ?
        o_shared_ia_banks_q * (p_shared_bank_bytes / 512) : 32'(p_ia_cache_blocks);
assign active_ps_pool_bytes = p_shared_ram_enabled ?
        32'(p_shared_total_bytes) - o_shared_ia_banks_q * 32'(p_shared_bank_bytes) : 32'(`GEMMORA_PS_POOL_BYTES);
assign o_active_ps_bank_count = p_shared_ram_enabled ? 32'(active_ps_bank_count_q) : 32'd4;
assign o_active_ps_bank_depth = p_shared_ram_enabled ?
        32'(p_shared_bank_bytes / 16) : active_ps_pool_bytes >> 6;
assign o_shared_allocation_invalid = shared_allocation_invalid_q;
assign o_cfg_16bits_ia_eff = (p_ia_data_width > 8) ? i_cfg_16bits_ia : 1'b0;
assign cfg_stream_is_mode = i_cfg_16x8 ? 1'b0 : i_cfg_dataflow_mode_eff;
assign cfg_stream_source_s8 = cfg_stream_is_mode ||
            (i_cfg_conv_enable ? !i_cfg_conv.input_s16 : !(o_cfg_16bits_ia_eff || i_cfg_16x8));
assign cfg_stream_offset = cfg_stream_is_mode ? i_rhs_zp :
            (i_cfg_conv_enable ? p_reg_width'($signed(i_cfg_conv.input_offset)) : i_lhs_zp);
        assign cfg_stream_compact = (p_ia_compact_enable != 0) && (p_ia_data_width == 16) &&
            cfg_stream_source_s8 && ($signed(cfg_stream_offset) >= -127) &&
            ($signed(cfg_stream_offset) <= 128);
assign ps_configuration_invalid = p_ps_storage_rows != 0 &&
            o_cfg_n_q[2] > p_reg_width'(p_size) && 32'(cfg_ps_required_s2) > p_ps_storage_rows;
assign cfg_ps_row_tiles_s0 = (o_cfg_stream_k_q[0] >> p_size_shift) +
            p_reg_width'((o_cfg_stream_k_q[0] & p_reg_width'(p_size-1)) != 0);
assign cfg_ps_col_tiles_s0 = (o_cfg_stream_m_q[0] >> p_size_shift) +
            p_reg_width'((o_cfg_stream_m_q[0] & p_reg_width'(p_size-1)) != 0);
assign cfg_ps_r_s0 = o_cfg_ia_reuse_q[0] < cfg_ps_row_tiles_s0 ?
            o_cfg_ia_reuse_q[0] : cfg_ps_row_tiles_s0;
assign cfg_ps_w_s0 = o_cfg_w_reuse_q[0] < cfg_ps_col_tiles_s0 ?
            o_cfg_w_reuse_q[0] : cfg_ps_col_tiles_s0;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                o_shared_ia_banks_q <= 32'd1;
                active_ps_bank_count_q <= p_shared_physical_banks_width'(
                    p_shared_ram_enabled ? p_shared_physical_banks-1 : 4);
                shared_allocation_invalid_q <= 1'b0;
            end else if (i_vector_start_fire && p_shared_ram_enabled) begin
                o_shared_ia_banks_q <= 32'(p_vector_shared_ia_banks);
                active_ps_bank_count_q <= p_shared_physical_banks_width'(
                    p_shared_physical_banks - p_vector_shared_ia_banks);
                shared_allocation_invalid_q <= 1'b0;
            end else if (i_cfg_start_event) begin
                // 配置接收时并行保存分配结果，后续容量检查直接使用寄存结果。
                o_shared_ia_banks_q <= requested_shared_ia_banks;
                active_ps_bank_count_q <= p_shared_physical_banks_width'(requested_ps_bank_count);
                shared_allocation_invalid_q <= requested_allocation_invalid;
            end
        end
        assign o_cfg_stage2_fire = o_cfg_valid_q[2] && cfg_capacity_phase==3'd7 &&
                                 i_ctrl_sa_ready && i_frame_scheduler_ready;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) cfg_capacity_phase <= 0;
            else if (!o_cfg_valid_q[2] || o_cfg_stage2_fire) cfg_capacity_phase <= 0;
            else if (cfg_capacity_phase != 3'd7) cfg_capacity_phase <= cfg_capacity_phase + 1'b1;
        end
        // 配置阶段用独立的 16 位部分乘积计算张量范围，随后分段归并进位。
        always_ff @(posedge clk) begin
            if (i_cfg_start_event) begin
                rhs_extent_n <= i_cfg_rhs_tile_packed ?
                    32'((64'(i_n) + 64'(p_size) - 64'd1) >> p_size_shift) : 32'(i_n);
                rhs_extent_m <= i_cfg_rhs_tile_packed ?
                    32'((64'(i_m) + 64'(p_size) - 64'd1) >> p_size_shift) : 32'(i_m);
            end
            if (o_cfg_valid_q[0]) begin
                rhs_product_ll <= rhs_extent_n[15:0] * rhs_extent_m[15:0];
                rhs_product_lh <= rhs_extent_n[15:0] * rhs_extent_m[31:16];
                rhs_product_hl <= rhs_extent_n[31:16] * rhs_extent_m[15:0];
                rhs_product_hh <= rhs_extent_n[31:16] * rhs_extent_m[31:16];
                conv_input_area <= i_conv_cfg_q.input_h * i_conv_cfg_q.input_w;
                conv_kernel_area <= i_conv_cfg_q.kernel_h * i_conv_cfg_q.kernel_w;
                conv_output_area <= i_conv_cfg_q.output_h * i_conv_cfg_q.output_w;
            end
            if (o_cfg_valid_q[1]) begin
                rhs_product_diagonal <= {rhs_product_hh, rhs_product_ll};
                rhs_product_cross <= {1'b0, rhs_product_lh} + {1'b0, rhs_product_hl};
                conv_input_low <= conv_input_area[15:0] * i_conv_cfg_q.input_c;
                conv_input_high <= conv_input_area[31:16] * i_conv_cfg_q.input_c;
                conv_kernel_low <= conv_kernel_area[15:0] * i_conv_cfg_q.group_c;
                conv_kernel_high <= conv_kernel_area[31:16] * i_conv_cfg_q.group_c;
            end
            if (o_cfg_valid_q[2]) begin
                case (cfg_capacity_phase)
                    3'd0: begin
                        // 独立寄存器保存各段和，下一相位只归并已保存的进位。
                        rhs_product_high_q <= rhs_product_high_sum;
                        rhs_product_middle_q <= rhs_product_low_sum;
                        conv_input_middle_q <= conv_input_middle_sum;
                        conv_kernel_middle_q <= conv_kernel_middle_sum;
                    end
                    3'd1: begin
                        rhs_allocation_bytes <= {
                            rhs_product_high_merged,
                            rhs_product_middle_q[23:0], rhs_product_diagonal[15:0]} <<
                            (i_run_rhs_tile_packed ? (2 * p_size_shift) : 0);
                        conv_input_bytes <= {
                            conv_input_high_merged,
                            conv_input_middle_q[15:0], conv_input_low[15:0]};
                        conv_kernel_elements <= {
                            conv_kernel_high_merged,
                            conv_kernel_middle_q[15:0], conv_kernel_low[15:0]};
                    end
                    3'd2: begin
                        // 范围寄存器按位段分别使能，进位独立保存供下一相位使用。
                        o_conv_range_end[0][23:0] <= conv_rhs_end_low[23:0];
                        o_conv_range_end[1][23:0] <= conv_bias_end_low[23:0];
                        o_conv_range_end[2][23:0] <= conv_mult_end_low[23:0];
                        o_conv_range_end[3][23:0] <= conv_shift_end_low[23:0];
                        conv_range_end_carry <= {conv_shift_end_low[24], conv_mult_end_low[24],
                            conv_bias_end_low[24], conv_rhs_end_low[24]};
                        conv_input_end_carry <= conv_input_end_low[24];
                        conv_dimension_invalid <= 64'(conv_output_area) != 64'(i_k) ||
                            64'(conv_kernel_elements) != 64'(i_n);
                    end
                    3'd3: begin
                        o_conv_range_end[0][32:24] <= conv_rhs_end_high ^ {rhs_allocation_bytes[32], 8'd0};
                        o_conv_range_end[1][32:24] <= conv_bias_end_high ^ {i_m[30], 8'd0};
                        o_conv_range_end[2][32:24] <= conv_mult_end_high ^ {i_m[30], 8'd0};
                        o_conv_range_end[3][32:24] <= conv_shift_end_high ^ {i_m[30], 8'd0};
                        conv_input_range_invalid <= (|conv_input_bytes[47:32]) ||
                            conv_input_end_high[8];
                        conv_rhs_range_invalid <= (|rhs_allocation_bytes[63:32]) ||
                            conv_rhs_end_high[8];
                        conv_parameter_range_invalid <= (|(32'(i_m) >> 30)) ||
                            conv_bias_end_high[8] ||
                            (i_use_per_channel && (conv_mult_end_high[8] || conv_shift_end_high[8]));
                    end
                    3'd4: conv_validation_invalid <= conv_syntax_invalid ||
                        conv_input_range_invalid || conv_rhs_range_invalid ||
                        conv_parameter_range_invalid || conv_dimension_invalid;
                    default: begin end
                endcase
            end
        end
        // 相同配置值共用幂次检查，供容量与输出合并逻辑使用。
        // 容量检查限制有效复用数，输出合并最多使用16行，幂次判断仅需覆盖相应低位。

        assign ia_reuse_shape_i_value = o_cfg_ia_reuse_q[2];
        onehot_check #(.p_width(IA_SHAPE_WIDTH), .p_allow_zero(1'b1)) u_ia_reuse_shape (
          .i_value(IA_SHAPE_WIDTH'(ia_reuse_shape_i_value)),
          .o_valid(ia_reuse_shape_o_valid)
        );
        assign w_reuse_shape_i_value = o_cfg_w_reuse_q[2];
        onehot_check #(.p_width(p_reg_width), .p_allow_zero(1'b1)) u_w_reuse_shape (
          .i_value(w_reuse_shape_i_value),
          .o_valid(w_reuse_shape_o_valid)
        );
        assign legacy_window_shape_s2 = w_reuse_shape_o_valid;
assign use_frame_commands_calc = p_frame_exec_enabled &&
            (!ps_long_capacity_fits || !legacy_window_shape_s2 || i_ps_control_q[1]);
        // 容量结果在相位一保存，帧调度资格在相位二保存，供后续配置阶段共同使用。
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n)
                o_use_frame_commands_s2 <= 1'b0;
            else if (o_cfg_valid_q[2] && cfg_capacity_phase == 3'd2)
                o_use_frame_commands_s2 <= use_frame_commands_calc;
        end
assign frame_slice_tiles_calc = i_ps_control_q[3:2] == 2'd3 ? o_cfg_ia_reuse_q[2] :
            i_ps_control_q[3:2] == 2'd2 ? ((o_cfg_ia_reuse_q[2] < 2) ? o_cfg_ia_reuse_q[2] : 32'd2) :
            i_ps_control_q[3:2] == 2'd1 ? 32'd1 :
            ps_raw_capacity_fits ? o_cfg_ia_reuse_q[2] : 32'd1;
        // 容量比较完成后保存分片大小，后续目录行数计算从该寄存级开始。
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==2)
                o_frame_slice_tiles_s2 <= frame_slice_tiles_calc;
        end
        // 空闲状态、后台请求和故障状态共同限定新配置的接收。
        // ABI 2 由软件提供有效的输入复用数与权重窗口大小。
assign ia_reuse_num_eff_s1 = o_cfg_ia_reuse_q[1];
assign w_reuse_num_eff_s1 = o_cfg_w_reuse_q[1];
assign ext_r_small = o_cfg_ia_reuse_q[2][p_ia_reuse_w-1:0];
assign ext_w_small = o_cfg_w_reuse_q[2][p_w_reuse_w-1:0];
        assign ext_ia_capacity = cfg_compact_q[2] ? o_active_ia_cache_blocks : o_active_ia_cache_blocks >> 1;
        unsigned_compare #(.p_width(p_reg_width)) u_external_ia_capacity (
            .i_a(ext_ia_capacity), .i_b(o_cfg_ia_reuse_q[2]),
            .o_less(ext_ia_capacity_less), .o_equal(ext_ia_capacity_equal)
        );
assign ext_r_legal = (o_cfg_ia_reuse_q[2] >> p_ia_reuse_w)==0 && ext_r_small!=0 &&
            !ext_ia_capacity_less &&
            (ia_reuse_shape_o_valid || ext_r_small==25);
assign ext_w_legal = (o_cfg_w_reuse_q[2] >> p_w_reuse_w)==0 && ext_w_small!=0 &&
            ext_w_small<=p_w_reuse_w'(p_w_reuse_num_max) &&
            (p_frame_exec_enabled || w_reuse_shape_o_valid || ext_w_small==25);
`ifdef GEMPACT_PS_COMPRESS

assign ps_group_rows_bounded = ext_r_legal ?
            CAP_ROWS_W'(ext_r_small) << p_size_shift : '0;
        assign ps_unchecked_rows = CAP_ROWS_W'(ext_r_small) << p_size_shift;
        assign ps_unchecked_group_rows = 32'(ps_unchecked_rows);
        unsigned_compare #(.p_width(32)) u_ps_stream_row_bound (
            .i_a(o_cfg_stream_k_q[2]), .i_b(ps_unchecked_group_rows),
            .o_less(ps_stream_rows_less), .o_equal(ps_stream_rows_equal)
        );
        // 行数比较与容量资格并行完成，非法配置在最终选择处生成零行数。
assign ps_rows_bounded_calc = !ext_r_legal ? '0 : ps_stream_rows_less ?
            CAP_ROWS_W'(o_cfg_stream_k_q[2]) : CAP_ROWS_W'(ps_unchecked_group_rows);
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==0) begin
                ps_rows_bounded <= ps_rows_bounded_calc;
                ps_frames_bounded <= ps_frames_bounded_calc;
            end
        end
assign ps_max_frame_rows = 64'(ps_rows_bounded);
assign ps_output_column_tiles = 64'(ps_column_sum >> p_size_shift);
        // 三十三位保存完整取整结果，分组加法限制配置到调度器的进位深度。
        assign column_sum_i_a = {1'b0, o_cfg_stream_m_q[2]};
        assign column_sum_i_b = 33'(p_size - 1);
        parallel_prefix_add #(.p_width(33)) u_column_sum (
            .i_a(column_sum_i_a), .i_b(column_sum_i_b), .i_carry(1'b0),
            .o_sum(ps_column_sum), .o_carry(unused_column_sum_carry)
        );
assign ps_column_sum_overflow = 64'(o_cfg_stream_m_q[2]) > (64'hffffffffffffffff - 64'(p_size - 1));
        // 先比较未取整的列数与窗口上界，取整结果只保留容量计数需要的低位。
        assign ps_frames_bounded_calc = (!ext_w_legal || ps_column_sum_overflow) ? '0 :
            (64'(o_cfg_stream_m_q[2]) >= (64'(ext_w_small) << p_size_shift) ?
             CAP_FRAMES_W'(ext_w_small) : CAP_FRAMES_W'(ps_output_column_tiles));
assign ps_live_frames = 64'(ps_frames_bounded);
assign ps_rows_frames = ps_rows_bounded * ps_frames_bounded;
assign ps_capacity_required_bytes = 64'(ps_rows_frames) << 6;
assign ps_cross_k_required = 64'(o_cfg_n_q[2]) > 64'(p_size);
assign ps_raw_bank_total = CAP_WORDS_W'(ps_raw_frame_bank_words) * ps_frames_bounded;
assign ps_raw_capacity_fits_calc = !ps_cross_k_required ||
            (ps_capacity_required_bytes <= 64'(active_ps_pool_bytes) &&
             ps_raw_bank_capacity_fits);
assign ps_config_force_raw = PS_REQUIRE_RAW_CAPACITY || i_ps_control_q[0];
        // 偏置在末尾 K 分块后加入。按操作数格式和部分归约长度计算保留和的范围，
        // 使用二次幂比较完成容量检查。
assign ps_lhs_source_s16_s2 = i_run_conv ? i_conv_cfg_q.input_s16 : o_cfg_use16_q[2];
assign ps_lhs_offset_s2 = i_run_conv ?
            p_reg_width'($signed(i_conv_cfg_q.input_offset)) : i_lhs_zp;
assign ps_lhs_exp_s2 = ps_lhs_source_s16_s2 ? 6'd15 :
            ps_lhs_offset_s2 == 0 ? 6'd7 :
            ($signed(ps_lhs_offset_s2) >= -32'sd128 && $signed(ps_lhs_offset_s2) <= 32'sd128) ? 6'd8 : 6'd15;
assign ps_rhs_exp_s2 = i_rhs_zp == 0 ? 6'd7 :
            ($signed(i_rhs_zp) >= -32'sd128 && $signed(i_rhs_zp) <= 32'sd128) ? 6'd8 : 6'd15;
assign ps_product_exp_s2 = ps_lhs_exp_s2 + ps_rhs_exp_s2;
assign ps_retained_k_s2 = (o_cfg_n_q[2] - 32'd1) & ~32'(p_size - 1);
assign ps_s24_bound_s2 = ps_product_exp_s2 < 6'd23 &&
            ps_retained_k_s2 < (32'd1 << (6'd23 - ps_product_exp_s2));
        // 软件可根据固定层权重提供更小的范围；存储模块逐条检查编码记录的预留空间。
assign ps_config_word_cap = ps_config_force_raw ? 3'd4 :
            i_ps_control_q[5:4] == 2'd1 ? 3'd2 :
            (i_ps_control_q[5:4] == 2'd2 || ps_s24_bound_s2) ? 3'd3 : 3'd4;
        // 每帧的数据轮流写入已分配的物理存储银行，各活动帧分别预留银行内的最大用量。
assign ps_long_frame_words = ps_config_word_cap == 3'd2 ?
            (ps_max_frame_rows << 1) : ps_config_word_cap == 3'd3 ?
            (ps_max_frame_rows << 1) + ps_max_frame_rows : (ps_max_frame_rows << 2);
assign ps_long_bank_total = CAP_WORDS_W'(ps_long_frame_bank_words) * ps_frames_bounded;
assign ps_long_capacity_fits_calc = !ps_cross_k_required ||
            (32'(ps_config_word_cap) <= o_active_ps_bank_count &&
             ps_long_bank_capacity_fits &&
             (!p_shared_ram_enabled || 64'(ps_rows_frames) <= 64'(p_shared_ps_directory_rows)));
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==1) begin
                ps_raw_capacity_fits_q <= ps_raw_capacity_fits_calc;
                ps_long_capacity_fits_q <= ps_long_capacity_fits_calc;
            end
        end
        assign ps_raw_capacity_fits = ps_raw_capacity_fits_q;
        assign ps_long_capacity_fits = ps_long_capacity_fits_q;
assign ps_admission_rows_calc = o_use_frame_commands_s2 ?
            ((ps_max_frame_rows < (64'(o_frame_slice_tiles_s2) << p_size_shift)) ?
                ps_max_frame_rows : (64'(o_frame_slice_tiles_s2) << p_size_shift)) : ps_max_frame_rows;
        // 目录步长与分片选择分拍保存，配置提交后保持至下一项任务。
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==3)
                o_ps_admission_rows <= ps_admission_rows_calc;
        end
assign ps_admission_words = ps_config_word_cap == 3'd2 ?
            (o_ps_admission_rows << 1) : ps_config_word_cap == 3'd3 ?
            (o_ps_admission_rows << 1) + o_ps_admission_rows : (o_ps_admission_rows << 2);
        generate if (p_shared_ram_enabled) begin : g_ps_bank_reservation
            wire [63:0] raw_bank_words [0:p_shared_physical_banks-1];
            wire [63:0] long_bank_words [0:p_shared_physical_banks-1];
            wire [63:0] admission_bank_words [0:p_shared_physical_banks-1];
            assign raw_bank_words[0] = '0;
            assign long_bank_words[0] = '0;
            assign admission_bank_words[0] = '0;
            localparam int RESERVATION_WORDS_MAX=4*p_ia_reuse_num_max*p_size;
            localparam int RESERVATION_BITS=$clog2(RESERVATION_WORDS_MAX+p_shared_physical_banks);
            for (genvar count=1;count<p_shared_physical_banks;count++) begin : g_count
                if(count==p_shared_physical_banks-1 || count==p_shared_physical_banks-2 ||
                   count==p_shared_physical_banks-4) begin : g_legal
                    wire [RESERVATION_BITS-1:0] raw_words=RESERVATION_BITS'(ps_max_frame_rows<<2);
                    wire [RESERVATION_BITS-1:0] long_words=RESERVATION_BITS'(ps_long_frame_words);
                    wire [RESERVATION_BITS-1:0] admission_words=RESERVATION_BITS'(ps_admission_words);
                    wire [RESERVATION_BITS-1:0] raw_rounded = raw_words + RESERVATION_BITS'(count-1);
                    wire [RESERVATION_BITS-1:0] long_rounded = long_words + RESERVATION_BITS'(count-1);
                    wire [RESERVATION_BITS-1:0] admission_rounded = admission_words + RESERVATION_BITS'(count-1);
                    wire [RESERVATION_BITS-1:0] raw_bank_word_count = raw_rounded / RESERVATION_BITS'(count);
                    wire [RESERVATION_BITS-1:0] long_bank_word_count = long_rounded / RESERVATION_BITS'(count);
                    wire [RESERVATION_BITS-1:0] admission_bank_word_count = admission_rounded / RESERVATION_BITS'(count);
                    assign raw_bank_words[count]=ps_max_frame_rows>64'(p_ia_reuse_num_max*p_size) ?
                        {64{1'b1}} : 64'(raw_bank_word_count);
                    assign long_bank_words[count]=ps_long_frame_words>64'(RESERVATION_WORDS_MAX) ?
                        {64{1'b1}} : 64'(long_bank_word_count);
                    assign admission_bank_words[count]=ps_admission_words>64'(RESERVATION_WORDS_MAX) ?
                        {64{1'b1}} : 64'(admission_bank_word_count);
                end else begin : g_unused
                    assign raw_bank_words[count]={64{1'b1}};
                    assign long_bank_words[count]={64{1'b1}};
                    assign admission_bank_words[count]={64{1'b1}};
                end
            end
            assign ps_raw_frame_bank_words = raw_bank_words[o_active_ps_bank_count];
            assign ps_long_frame_bank_words = long_bank_words[o_active_ps_bank_count];
            assign ps_admission_bank_words = admission_bank_words[o_active_ps_bank_count];
        end else begin : g_ps_fixed_reservation
            assign ps_raw_frame_bank_words = ps_max_frame_rows;
            assign ps_long_frame_bank_words = (ps_long_frame_words + 64'd3) >> 2;
            assign ps_admission_bank_words = (ps_admission_words + 64'd3) >> 2;
        end endgenerate
        // 原始定宽部分和使用固定物理容量表，分组容量与配置检查分阶段寄存。
        // 总字节数与目录行数检查独立保留，存储块容量只比较对应的行数上限。
        generate if (p_shared_ram_enabled && PS_REQUIRE_RAW_CAPACITY) begin : g_ps_capacity_limits
            logic [CAP_ROWS_W-1:0] capacity_i_frame_rows;
            logic [CAP_FRAMES_W-1:0] capacity_i_frames;
            logic [31:0] capacity_i_bank_count;
            logic [31:0] capacity_i_frame_slice_tiles;
            logic capacity_i_use_frame_commands;
            logic capacity_o_frames_fit;
            logic capacity_o_admission_fit;
            assign capacity_i_frame_rows = ps_rows_bounded;
            assign capacity_i_frames = ps_frames_bounded;
            assign capacity_i_bank_count = o_active_ps_bank_count;
            assign capacity_i_frame_slice_tiles = o_frame_slice_tiles_s2;
            assign capacity_i_use_frame_commands = o_use_frame_commands_s2;
            ps_capacity_limits #(
                .p_max_rows(p_ia_reuse_num_max * p_size),
                .p_rows_width(CAP_ROWS_W),
                .p_frames_width(CAP_FRAMES_W),
                .p_total_banks(p_shared_physical_banks),
                .p_bank_bytes(p_shared_bank_bytes),
                .p_tile_shift(p_size_shift)
            ) u_capacity_limits (
                .i_frame_rows(capacity_i_frame_rows),
                .i_frames(capacity_i_frames),
                .i_bank_count(capacity_i_bank_count),
                .i_frame_slice_tiles(capacity_i_frame_slice_tiles),
                .i_use_frame_commands(capacity_i_use_frame_commands),
                .o_frames_fit(capacity_o_frames_fit),
                .o_admission_fit(capacity_o_admission_fit)
            );
            assign ps_raw_bank_capacity_fits = capacity_o_frames_fit;
            assign ps_long_bank_capacity_fits = capacity_o_frames_fit;
            assign ps_admission_bank_capacity_fits = capacity_o_admission_fit;
        end else begin : g_ps_capacity_arithmetic
            assign ps_raw_bank_capacity_fits = ps_frames_bounded == '0 ||
                (ps_raw_frame_bank_words <= 64'(4 * p_ia_reuse_num_max * p_size) &&
                 64'(ps_raw_bank_total) <= 64'(o_active_ps_bank_depth));
            assign ps_long_bank_capacity_fits = ps_frames_bounded == '0 ||
                (ps_long_frame_bank_words <= 64'(4 * p_ia_reuse_num_max * p_size) &&
                 64'(ps_long_bank_total) <= 64'(o_active_ps_bank_depth));
            assign ps_admission_bank_capacity_fits =
                ps_admission_bank_words <= 64'(o_active_ps_bank_depth);
        end endgenerate
assign ps_capacity_config_invalid_calc = (p_size == 16) &&
            (o_shared_allocation_invalid || active_ps_pool_bytes < 64 ||
             ((active_ps_pool_bytes % 64) != 0) ||
             (p_shared_ram_enabled && !cfg_compact_q[2] && o_shared_ia_banks_q < 2) ||
             (ps_cross_k_required && (!ps_admission_bank_capacity_fits ||
                                      32'(ps_config_word_cap) > o_active_ps_bank_count)) ||
             (!o_use_frame_commands_s2 && !ps_long_capacity_fits));
`else

        assign ps_raw_capacity_fits = 1'b1;
        assign ps_long_capacity_fits = 1'b1;
        assign ps_capacity_config_invalid_calc = ps_configuration_invalid;
        assign ps_config_force_raw = 1'b1;
        assign ps_config_word_cap = 3'd4;
        assign o_ps_admission_rows = 64'd0;
`endif
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==4)
                ps_capacity_config_invalid <= ps_capacity_config_invalid_calc;
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                    o_cfg_valid_q[0] <= 1'b0;
                    o_cfg_valid_q[1] <= 1'b0;
                    o_cfg_valid_q[2] <= 1'b0;
                    cfg_mode_q[0] <= 1'b0;
                    o_cfg_use16_q[0] <= 1'b0;
                    o_cfg_16x8_q[0] <= 1'b0;
                    cfg_compact_q[0] <= 1'b0;
                    cfg_compact_offset_q[0] <= '0;
                    cfg_k_q[0] <= '0;
                    cfg_m_q[0] <= '0;
                    o_cfg_n_q[0] <= '0;
                    o_cfg_stream_k_q[0] <= '0;
                    o_cfg_stream_m_q[0] <= '0;
                    o_cfg_ia_reuse_q[0] <= '0;
                    o_cfg_w_reuse_q[0] <= '0;
                    cfg_mode_q[1] <= 1'b0;
                    o_cfg_use16_q[1] <= 1'b0;
                    o_cfg_16x8_q[1] <= 1'b0;
                    cfg_compact_q[1] <= 1'b0;
                    cfg_compact_offset_q[1] <= '0;
                    cfg_k_q[1] <= '0;
                    cfg_m_q[1] <= '0;
                    o_cfg_n_q[1] <= '0;
                    o_cfg_stream_k_q[1] <= '0;
                    o_cfg_stream_m_q[1] <= '0;
                    o_cfg_ia_reuse_q[1] <= '0;
                    o_cfg_w_reuse_q[1] <= '0;
                    cfg_mode_q[2] <= 1'b0;
                    cfg_compact_q[2] <= 1'b0;
                    cfg_compact_offset_q[2] <= '0;
                    o_cfg_use16_q[2] <= 1'b0;
                    o_cfg_16x8_q[2] <= 1'b0;
                    cfg_k_q[2] <= '0;
                    cfg_m_q[2] <= '0;
                    o_cfg_n_q[2] <= '0;
                    o_cfg_stream_k_q[2] <= '0;
                    o_cfg_stream_m_q[2] <= '0;
                    o_cfg_ia_reuse_q[2] <= p_reg_width'(1);
                    o_cfg_w_reuse_q[2] <= p_reg_width'(1);
                    cfg_bias_rows_target_s2 <= p_is_bias_valid_w'(p_size);
                    cfg_ps_rows_s1 <= '0;
                    cfg_ps_frames_s1 <= '0;
                    cfg_ps_required_s2 <= '0;
                end else begin
                    if (o_cfg_stage2_fire) begin
                        o_cfg_valid_q[2] <= 1'b0;
                    end
                    if (o_cfg_valid_q[1] && !o_cfg_valid_q[2]) begin
                        o_cfg_valid_q[2] <= 1'b1;
                        o_cfg_valid_q[1] <= 1'b0;
                        cfg_mode_q[2] <= cfg_mode_q[1];
                        o_cfg_use16_q[2] <= o_cfg_use16_q[1];
                        o_cfg_16x8_q[2] <= o_cfg_16x8_q[1];
                        cfg_compact_q[2] <= cfg_compact_q[1];
                        cfg_compact_offset_q[2] <= cfg_compact_offset_q[1];
                        cfg_k_q[2] <= cfg_k_q[1];
                        cfg_m_q[2] <= cfg_m_q[1];
                        o_cfg_n_q[2] <= o_cfg_n_q[1];
                        o_cfg_stream_k_q[2] <= o_cfg_stream_k_q[1];
                        o_cfg_stream_m_q[2] <= o_cfg_stream_m_q[1];
                        o_cfg_ia_reuse_q[2] <= ia_reuse_num_eff_s1;
                        o_cfg_w_reuse_q[2] <= w_reuse_num_eff_s1;
                        cfg_bias_rows_target_s2 <= p_is_bias_valid_w'(ia_reuse_num_eff_s1 << p_size_shift);
                        cfg_ps_required_s2 <= p_ps_required_width'(cfg_ps_rows_s1) *
                                              p_ps_required_width'(cfg_ps_frames_s1);
                    end
                    if (o_cfg_valid_q[0] && !o_cfg_valid_q[1]) begin
                        o_cfg_valid_q[1] <= 1'b1;
                        o_cfg_valid_q[0] <= 1'b0;
                    cfg_mode_q[1] <= cfg_mode_q[0];
                    o_cfg_use16_q[1] <= o_cfg_use16_q[0];
                    o_cfg_16x8_q[1] <= o_cfg_16x8_q[0];
                    cfg_compact_q[1] <= cfg_compact_q[0];
                    cfg_compact_offset_q[1] <= cfg_compact_offset_q[0];
                    cfg_k_q[1] <= cfg_k_q[0];
                    cfg_m_q[1] <= cfg_m_q[0];
                        o_cfg_n_q[1] <= o_cfg_n_q[0];
                        o_cfg_stream_k_q[1] <= o_cfg_stream_k_q[0];
                        o_cfg_stream_m_q[1] <= o_cfg_stream_m_q[0];
                        o_cfg_ia_reuse_q[1] <= o_cfg_ia_reuse_q[0];
                        o_cfg_w_reuse_q[1] <= o_cfg_w_reuse_q[0];
                        cfg_ps_rows_s1 <= p_ps_row_count_width'(((cfg_ps_r_s0 + 1) << p_size_shift) - 1);
                        cfg_ps_frames_s1 <= p_ps_frame_count_width'(cfg_ps_w_s0 + 1);
                    end
                    if (i_cfg_start_event) begin
                        o_cfg_valid_q[0] <= 1'b1;
                        cfg_mode_q[0] <= cfg_stream_is_mode;
                        o_cfg_use16_q[0] <= o_cfg_16bits_ia_eff | i_cfg_16x8;
                        o_cfg_16x8_q[0] <= i_cfg_16x8;
                        cfg_compact_q[0] <= cfg_stream_compact;
                        cfg_compact_offset_q[0] <= cfg_stream_offset;
                    cfg_k_q[0] <= i_k;
                    cfg_m_q[0] <= i_m;
                        o_cfg_n_q[0] <= i_n;
                        o_cfg_stream_k_q[0] <= cfg_stream_is_mode ? i_m : i_k;
                        o_cfg_stream_m_q[0] <= cfg_stream_is_mode ? i_k : i_m;
                        o_cfg_ia_reuse_q[0] <= i_cfg_ia_reuse_num;
                        o_cfg_w_reuse_q[0] <= i_cfg_w_reuse_num;
                    end
                end
            end
        // 使用已保存的任务配置计算物理槽号，帧命令接收时保存计算结果。
        // 输出预留覆盖阵列尾部、计算输出寄存和量化流水。

assign output_reserve_uncapped = (!o_use_frame_commands_s2 && o_direct_output_cfg) ?
            output_reserve_calc : 32'(o_cfg_ia_reuse_q[2]);
assign output_s16_reserve_uncapped = 32'(o_cfg_ia_reuse_q[2]);
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                o_run_is_mode <= 1'b0;
                o_run_use_16bits <= 1'b0;
                o_run_16x8 <= 1'b0;
                o_run_compact <= 1'b0;
                o_run_compact_offset <= '0;
                o_ps_force_raw_q <= 1'b1;
                o_ps_word_cap_q <= 3'd4;
                o_run_k <= '0;
                o_run_m <= '0;
                o_run_n <= '0;
                o_stream_k <= '0;
                o_stream_m <= '0;
                o_ia_reuse_num_eff <= p_reg_width'(1);
                o_output_reserve_banks <= p_s8_reserve_width'(1);
                o_output_s16_reserve_banks <= p_s16_reserve_width'(1);
                o_output_s8_ready_threshold <= p_s8_reserve_width'(p_oa_fifo_banks-1);
                o_output_s16_ready_threshold <= p_s16_reserve_width'(p_oa_s16_fifo_banks-1);
                o_w_reuse_num_eff <= p_reg_width'(1);
                o_is_bias_group_rows_target <= p_is_bias_valid_w'(p_size);
            end else if (o_cfg_stage2_fire) begin
                o_run_is_mode <= cfg_mode_q[2];
                o_run_use_16bits <= o_cfg_use16_q[2];
                o_run_16x8 <= o_cfg_16x8_q[2];
                o_run_compact <= cfg_compact_q[2];
                o_run_compact_offset <= cfg_compact_offset_q[2];
                o_ps_force_raw_q <= ps_config_force_raw;
                o_ps_word_cap_q <= ps_config_word_cap;
                o_run_k <= cfg_k_q[2];
                o_run_m <= cfg_m_q[2];
                o_run_n <= o_cfg_n_q[2];
                o_stream_k <= o_cfg_stream_k_q[2];
                o_stream_m <= o_cfg_stream_m_q[2];
                o_ia_reuse_num_eff <= o_cfg_ia_reuse_q[2];
                // 预留数量在配置提交时限制到实际容量，运行期间只比较有效计数位。
                o_output_reserve_banks <= (output_reserve_uncapped >= 32'(p_oa_fifo_banks)) ?
                    p_s8_reserve_width'(p_oa_fifo_banks) : p_s8_reserve_width'(output_reserve_uncapped);
                o_output_s16_reserve_banks <= (output_s16_reserve_uncapped >= 32'(p_oa_s16_fifo_banks)) ?
                    p_s16_reserve_width'(p_oa_s16_fifo_banks) : p_s16_reserve_width'(output_s16_reserve_uncapped);
                // 预留数量和空闲阈值在同一配置边沿保存，运行期不再执行容量减法。
                o_output_s8_ready_threshold <= output_reserve_uncapped == 32'd0 ?
                    p_s8_reserve_width'(p_oa_fifo_banks-1) :
                    output_reserve_uncapped >= 32'(p_oa_fifo_banks) ? '0 :
                    p_s8_reserve_width'(32'(p_oa_fifo_banks) - output_reserve_uncapped);
                o_output_s16_ready_threshold <= output_s16_reserve_uncapped == 32'd0 ?
                    p_s16_reserve_width'(p_oa_s16_fifo_banks-1) :
                    output_s16_reserve_uncapped >= 32'(p_oa_s16_fifo_banks) ? '0 :
                    p_s16_reserve_width'(32'(p_oa_s16_fifo_banks) - output_s16_reserve_uncapped);
                o_w_reuse_num_eff <= o_cfg_w_reuse_q[2];
                o_is_bias_group_rows_target <= cfg_bias_rows_target_s2;
            end
        end
        // 配置接收时保存最终预留量，运行阶段直接使用已完成的计数。
        assign output_reserve_i_a = 32'(o_cfg_ia_reuse_q[2]);
        assign output_reserve_i_b = 32'(DIRECT_OUTPUT_EXTRA_BANKS);
        assign output_reserve_i_carry = 1'b0;
        parallel_prefix_add #(.p_width(32)) u_output_reserve_add (
            .i_a(output_reserve_i_a), .i_b(output_reserve_i_b), .i_carry(output_reserve_i_carry),
            .o_sum(output_reserve_calc), .o_carry(output_reserve_o_carry)
        );
assign tiling_invalid_calc = conv_config_invalid || ps_capacity_config_invalid || !ext_r_legal || !ext_w_legal ||
            ((p_oa_fifo_banks < p_ia_reuse_num_max) && !o_cfg_16x8_q[2] &&
             o_cfg_ia_reuse_q[2] > p_oa_fifo_banks) ||
            (o_cfg_16x8_q[2] && o_cfg_ia_reuse_q[2] > p_oa_s16_fifo_banks) ||
            (i_ps_control_q[31:6] != 0) || (i_ps_control_q[5:4] == 2'd3) ||
            (!p_frame_exec_enabled && i_ps_control_q != 0) ||
            i_cfg_row_groups == 0 || i_cfg_col_groups == 0 || i_cfg_row_tail_tiles == 0 || i_cfg_col_tail_tiles == 0 ||
            i_cfg_row_tail_tiles > o_cfg_ia_reuse_q[2] || i_cfg_col_tail_tiles > o_cfg_w_reuse_q[2] ||
            (i_cfg_row_groups >> p_dim_count_width) != 0 || (i_cfg_col_groups >> p_dim_count_width) != 0;
assign frame_config_error_calc = (i_lhs_base == 0 || i_rhs_base == 0 || i_dst_base == 0) ? 2'b10 :
            ((o_tiling_invalid || i_lhs_row_stride_b == 0 || i_rhs_col_stride_b == 0 || i_dst_row_stride_b == 0 ||
              (i_use_per_channel_eff && i_q_mult_pt == 0 && i_q_shift_pt == 0)) ? 2'b01 : 2'b00);
        always_ff @(posedge clk) begin
            if (o_cfg_valid_q[2] && cfg_capacity_phase==5)
                o_tiling_invalid <= tiling_invalid_calc;
            if (o_cfg_valid_q[2] && cfg_capacity_phase==6)
                o_frame_config_error <= frame_config_error_calc;
        end
    // 配置阶段准备输出分组，运行期间直接使用已保存的容量选择。

    // 两个操作数先限制到容量加一，再求最小值；该值完整保留容量判断所需的信息。
    // 先比较未取整的行数，使向上取整仅在容量计数位宽内传播进位。
    assign oa_cfg_k_limit = (p_reg_width+4)'(p_reg_width'(p_oa_fifo_banks)) << 4;
    assign oa_cfg_rows_exceed = (p_reg_width+4)'(cfg_k_q[2]) > oa_cfg_k_limit;
    assign oa_cfg_row_tiles = oa_cfg_rows_exceed ? OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks+1) :
        OA_REUSE_ROWS_WIDTH'(cfg_k_q[2] >> 4) + OA_REUSE_ROWS_WIDTH'(|cfg_k_q[2][3:0]);
    assign oa_cfg_reuse_limit = o_cfg_ia_reuse_q[2] > p_reg_width'(p_oa_fifo_banks) ?
        OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks+1) : OA_REUSE_ROWS_WIDTH'(o_cfg_ia_reuse_q[2]);
    assign oa_cfg_reuse_rows = oa_cfg_row_tiles < oa_cfg_reuse_limit ?
        oa_cfg_row_tiles : oa_cfg_reuse_limit;
    assign oa_is_alignment_mask = (o_cfg_ia_reuse_q[2] << 4) - p_reg_width'(1);
    // 各分组容量条件并行形成，较大分组满足时，其较小分组也必然满足。
    assign oa_cfg_chunk_fit[0] = o_cfg_w_reuse_q[2] >= 2 && cfg_m_q[2] >= 32 &&
        oa_ws_reuse_rows_pre <= OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks >> 1);
    assign oa_cfg_chunk_fit[1] = o_cfg_w_reuse_q[2] >= 4 && cfg_m_q[2] >= 64 &&
        oa_ws_reuse_rows_pre <= OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks >> 2);
    assign oa_cfg_chunk_fit[2] = o_cfg_w_reuse_q[2] >= 8 && cfg_m_q[2] >= 128 &&
        oa_ws_reuse_rows_pre <= OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks >> 3);
    assign oa_cfg_chunk_fit[3] = o_cfg_w_reuse_q[2] >= 16 && cfg_m_q[2] >= 256 &&
        oa_ws_reuse_rows_pre <= OA_REUSE_ROWS_WIDTH'(p_oa_fifo_banks >> 4);
    assign oa_cfg_narrow_chunk = cfg_k_q[2] > 1 && cfg_k_q[2] < 16 && oa_cfg_chunk_fit[0];
    assign oa_cfg_chunk_choice = {
        oa_cfg_chunk_fit[3] && !oa_cfg_narrow_chunk,
        oa_cfg_chunk_fit[2] && !oa_cfg_chunk_fit[3] && !oa_cfg_narrow_chunk,
        oa_cfg_chunk_fit[1] && !oa_cfg_chunk_fit[2] && !oa_cfg_narrow_chunk,
        oa_cfg_narrow_chunk || (oa_cfg_chunk_fit[0] && !oa_cfg_chunk_fit[1]),
        !oa_cfg_chunk_fit[0]
    };
assign o_oa_ws_coalesce_pre = !i_frame_mode_q && oa_ws_coalesce_q;
assign o_oa_is_coalesce_pre = !i_frame_mode_q && oa_is_coalesce_q;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            oa_ws_reuse_rows_pre<=0;
            o_oa_chunk_cols_pre<=1;
            oa_ws_coalesce_q<=0;
            oa_is_coalesce_q<=0;
            oa_ws_reserve_fits<=0;
            o_direct_output_cfg<=0;
        end else if (o_cfg_valid_q[2]) begin
            case (cfg_capacity_phase)
                3'd0: begin
                    // 容量加一表示该组无法合并写出。
                    oa_ws_reuse_rows_pre <= oa_cfg_reuse_rows;
                end
                3'd1: begin
                    o_oa_chunk_cols_pre <= oa_cfg_chunk_choice;
                end
                3'd2: begin
                    oa_ws_coalesce_q<=(p_size==16) && (p_enable_is_mode!=0) && !cfg_mode_q[2] && !o_cfg_16x8_q[2] &&
                        cfg_k_q[2]!=0 && o_cfg_ia_reuse_q[2]<=16 && o_oa_chunk_cols_pre>=2 &&
                        (cfg_m_q[2] & ((p_reg_width'(o_oa_chunk_cols_pre)<<4)-1'b1))==0 && i_dst_row_stride_b==cfg_m_q[2];
                    oa_is_coalesce_q<=(p_size==16) && (p_enable_is_mode!=0) && cfg_mode_q[2] && !o_cfg_16x8_q[2] &&
                        cfg_k_q[2]!=0 && cfg_m_q[2]!=0 && o_cfg_ia_reuse_q[2]>=2 && o_cfg_ia_reuse_q[2]<=16 &&
                        o_cfg_ia_reuse_q[2]<=p_oa_fifo_banks &&
                        ia_reuse_shape_o_valid &&
                        (cfg_m_q[2] & oa_is_alignment_mask)==0 &&
                        (i_dst_base & oa_is_alignment_mask)==0 &&
                        (i_dst_row_stride_b & oa_is_alignment_mask)==0;
                    case (o_oa_chunk_cols_pre)
                        5'd16: oa_ws_reserve_fits<=oa_ws_reuse_rows_pre<=OA_REUSE_ROWS_WIDTH'(OA_DIRECT_AVAILABLE_BANKS>>4);
                        5'd8: oa_ws_reserve_fits<=oa_ws_reuse_rows_pre<=OA_REUSE_ROWS_WIDTH'(OA_DIRECT_AVAILABLE_BANKS>>3);
                        5'd4: oa_ws_reserve_fits<=oa_ws_reuse_rows_pre<=OA_REUSE_ROWS_WIDTH'(OA_DIRECT_AVAILABLE_BANKS>>2);
                        5'd2: oa_ws_reserve_fits<=oa_ws_reuse_rows_pre<=OA_REUSE_ROWS_WIDTH'(OA_DIRECT_AVAILABLE_BANKS>>1);
                        default: oa_ws_reserve_fits<=oa_ws_reuse_rows_pre<=OA_REUSE_ROWS_WIDTH'(OA_DIRECT_AVAILABLE_BANKS);
                    endcase
                end
                3'd3: begin
                    o_direct_output_cfg<=!cfg_mode_q[2] && !o_cfg_16x8_q[2] && !i_use_per_channel_eff && i_bias_base=='0 &&
                        o_cfg_n_q[2]<=p_reg_width'(p_size) && o_cfg_n_q[2]!=0 &&
                        o_cfg_ia_reuse_q[2]<=p_reg_width'(OA_DIRECT_AVAILABLE_BANKS) &&
                        (!oa_ws_coalesce_q || oa_ws_reserve_fits);
                end
                default: ;
            endcase
        end
    end

endmodule

`default_nettype wire
