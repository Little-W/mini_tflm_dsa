`default_nettype none

// 逐通道量化、偏置读取、输出分组和写回控制。
module npu_output_pipeline #(
    parameter int unsigned p_bus_width = 32'd64,
    parameter int unsigned p_dim_count_width = 32'd16,
    parameter bit p_dw_shared_quant_enable = 1'h0,
    parameter int unsigned p_enable_is_mode = 32'd1,
    parameter int unsigned p_enable_per_channel = 32'd1,
    parameter int unsigned p_ia_reuse_num_max = 32'd32,
    parameter int unsigned p_is_bias_row_w = 32'd9,
    parameter int unsigned p_is_bias_valid_w = 32'd10,
    parameter int unsigned p_oa_fifo_banks = 32'd32,
    parameter int unsigned p_oa_s16_fifo_banks = 32'd4,
    parameter int unsigned p_reg_width = 32'd32,
    parameter int unsigned p_requant_max_ia_reuse = 32'd32,
    parameter int unsigned p_size = 32'd16,
    parameter int unsigned p_requant_compute_lanes = 32'd2,
    parameter int unsigned p_s16_reserve_width = 32'd3,
    parameter int unsigned p_s8_reserve_width = 32'd6
) (
    input logic signed [31:0] i_acc_data_out [p_size],
    input logic i_acc_data_valid,
    input logic signed [p_reg_width-1:0] i_act_max,
    input logic signed [p_reg_width-1:0] i_act_min,
    input logic [p_reg_width-1:0] i_bias_base,
    input logic signed [31:0] i_bias_group_scalar,
    input logic i_bias_sleep,
    input logic i_bias_switch,
    input logic i_cfg_dataflow_mode_eff,
    input logic clk,
    input logic signed [31:0] i_compute_bias_latched [p_size],
    input logic rst_n,
    input logic i_direct_output_cfg,
    input logic [p_reg_width-1:0] i_dst_row_stride_b,
    input logic signed [p_reg_width-1:0] i_dst_zp,
    input logic signed [31:0] i_dw_quant_accumulator [p_size],
    input logic [p_size-1:0] i_dw_quant_mask,
    input logic signed [31:0] i_dw_quant_maximum,
    input logic signed [31:0] i_dw_quant_minimum,
    input logic signed [31:0] i_dw_quant_multiplier [p_size],
    input logic signed [31:0] i_dw_quant_offset,
    input logic i_dw_quant_req_tag,
    input logic i_dw_quant_req_valid,
    input logic [5:0] i_dw_quant_right [p_size],
    input logic [31:0] i_exec_dst_base,
    input logic i_exec_init_oa,
    input logic i_exec_init_requant,
    input logic [31:0] i_exec_k,
    input logic [31:0] i_exec_m,
    input logic signed [31:0] i_exec_q_mult,
    input logic signed [31:0] i_exec_q_shift,
    input logic [31:0] i_exec_stream_k,
    input logic [31:0] i_exec_stream_m,
    input logic i_frame_mode_q,
    input logic [p_reg_width-1:0] i_ia_reuse_num_eff,
    input logic i_init_cfg_ia,
    input logic i_init_cfg_oa,
    input logic [p_is_bias_valid_w-1:0] i_is_bias_group_rows_target,
    input logic i_is_mode,
    input logic i_load_quant_granted,
    input logic [4:0] i_oa_chunk_cols_pre,
    input logic i_oa_dma_busy,
    input logic i_oa_dma_done,
    input logic i_oa_dma_src_wready,
    input logic i_oa_is_coalesce_pre,
    input logic i_oa_ws_coalesce_pre,
    input logic [p_s8_reserve_width-1:0] i_output_reserve_banks,
    input logic [p_s16_reserve_width-1:0] i_output_s16_ready_threshold,
    input logic [p_s16_reserve_width-1:0] i_output_s16_reserve_banks,
    input logic [p_s8_reserve_width-1:0] i_output_s8_ready_threshold,
    input logic i_ps_capacity_fault,
    input logic [p_bus_width-1:0] i_quant_dma_raw_data,
    input logic i_quant_dma_raw_valid,
    input logic [31:0] i_requant_group_rows,
    input logic i_requant_group_start,
    input logic i_run_16x8,
    input logic i_run_vector,
    input logic i_send_ia_trigger,
    input logic i_tile_calc_over,
    input logic i_use_per_channel_eff,
    input logic i_write_oa_granted,
    input logic i_ws_final_bias,
    output logic o_direct_final_stream,
    output logic o_dw_quant_req_ready,
    output logic o_dw_quant_rsp_tag,
    output logic o_dw_quant_rsp_valid,
    output logic o_fifo_full_flag,
    output logic [p_is_bias_row_w-1:0] o_is_bias_read_idx,
    output logic o_load_quant_req,
    output logic o_oa_calc_over,
    output logic [p_reg_width-1:0] o_oa_dma_base_addr,
    output logic [7:0] o_oa_dma_burst_len_m1,
    output logic [p_reg_width-1:0] o_oa_dma_row_stride,
    output logic [p_reg_width-1:0] o_oa_dma_rows_to_read,
    output logic [p_bus_width-1:0] o_oa_dma_src_wdata,
    output logic [p_bus_width/8-1:0] o_oa_dma_src_wmask,
    output logic o_oa_dma_src_wvalid,
    output logic o_oa_dma_start,
    output logic [p_reg_width-1:0] o_quant_dma_base_addr,
    output logic [7:0] o_quant_dma_burst_len_m1,
    output logic signed [p_reg_width-1:0] o_quant_dma_lhs_zp,
    output logic o_quant_dma_linear_read_mode,
    output logic [p_reg_width-1:0] o_quant_dma_row_stride,
    output logic [p_reg_width-1:0] o_quant_dma_rows_to_read,
    output logic o_quant_dma_slot_id,
    output logic o_quant_dma_start,
    output logic o_quant_dma_use_16bits,
    output logic o_quant_params_valid,
    output logic o_requant_group_ready,
    output logic signed [7:0] o_requant_out [p_size],
    output logic o_write_oa_req
);

    localparam int unsigned p_bias_compare_width = (p_reg_width > 32) ? p_reg_width : 32;
    localparam int unsigned p_bias_count_bits =
    (p_is_bias_valid_w < p_reg_width) ? p_is_bias_valid_w : p_reg_width;
    localparam int unsigned p_bias_mask_groups = (p_bias_count_bits + 3) / 4;
    localparam int unsigned p_bias_high_groups = (p_reg_width - p_bias_count_bits + 3) / 4;

    logic [p_bus_width-1:0] fifo_output_data;
    logic [p_bus_width/8-1:0] fifo_output_mask;
    logic fifo_output_ready;
    logic fifo_output_req;
    logic fifo_output_switch_row;
    logic fifo_output_valid;
    logic fifo_s16_full_flag;
    logic [p_bus_width-1:0] fifo_s16_output_data;
    logic [p_bus_width/8-1:0] fifo_s16_output_mask;
    logic fifo_s16_output_req;
    logic fifo_s16_output_switch_row;
    logic fifo_s16_output_valid;
    logic fifo_s8_full_flag;
    logic [p_bus_width-1:0] fifo_s8_output_data;
    logic [p_bus_width/8-1:0] fifo_s8_output_mask;
    logic fifo_s8_output_req;
    logic fifo_s8_output_switch_row;
    logic fifo_s8_output_valid;
    logic [$clog2(p_size)-1:0] fifo_vec_valid_num_col;
    logic [$clog2(p_size)-1:0] fifo_vec_valid_num_row;
    logic [p_size*16-1:0] in_vec_s16;
    logic [p_size*8-1:0] in_vec_s8;
    logic [p_reg_width-1:0] is_bias_advance_sum;
    logic is_bias_current_equal;
    logic is_bias_current_less;
    logic [p_reg_width-1:0] is_bias_exec_m_ext;
    logic [p_is_bias_valid_w-1:0] is_bias_first_rows_valid;
    logic [p_reg_width-1:0] is_bias_full_group_base;
    logic [p_reg_width-1:0] is_bias_group_base;
    logic [p_reg_width-1:0] is_bias_group_base_plus;
    logic [p_reg_width-1:0] is_bias_group_base_step;
    logic [p_reg_width-1:0] is_bias_group_rows_target_ext;
    logic is_bias_group_step_is_last;
    logic is_bias_group_wrap_step;
    logic [(p_bias_high_groups > 0 ? p_bias_high_groups : 1)-1:0] is_bias_high_group_zero;
    logic [p_reg_width-1:0] is_bias_last_group_base;
    logic [p_reg_width-1:0] is_bias_last_group_base_calc;
    logic [p_is_bias_valid_w-1:0] is_bias_last_rows;
    logic [p_bias_count_bits:0] is_bias_low_difference;
    logic [p_bias_mask_groups-1:0] is_bias_mask_group_zero;
    logic is_bias_next_equal;
    logic is_bias_next_less;
    logic is_bias_row_clear;
    logic [p_is_bias_valid_w:0] is_bias_row_distance;
    logic [p_is_bias_row_w-1:0] is_bias_row_idx;
    logic [p_is_bias_row_w-1:0] is_bias_row_increment;
    logic [p_is_bias_row_w-1:0] is_bias_row_next;
    logic [p_is_bias_row_w-1:0] is_bias_row_step;
    logic is_bias_row_wrap;
    logic is_bias_rows_equal;
    logic is_bias_rows_fit;
    logic is_bias_rows_less;
    logic [p_is_bias_valid_w-1:0] is_bias_rows_valid;
    logic [p_is_bias_valid_w-1:0] is_bias_rows_valid_pending;
    logic [p_is_bias_valid_w-1:0] is_bias_rows_valid_step;
    logic signed [31:0] is_bias_scalar;
    logic [p_is_bias_valid_w-1:0] is_bias_tail_rows_calc;
    logic [p_reg_width-1:0] is_bias_tail_rows_raw;
    logic [p_reg_width-1:0] is_bias_target_mask_ext;
    logic load_quant_req_s8;
    logic [4:0] oa_coalesce_cols;
    logic [4:0] oa_coalesce_cols_pre;
    logic oa_coalesce_group_start;
    logic [4:0] oa_coalesce_rows;
    logic oa_row_coalesce;
    logic oa_row_coalesce_pre;
    logic quant_params_valid_s8;
    logic signed [31:0] requant_in_vec [p_size];
    logic signed [15:0] requant_out_s16 [p_size];
    logic requant_out_tile_done;
    logic requant_out_valid;
    logic write_done;

    // 逐通道量化
    assign is_bias_group_rows_target_ext = p_reg_width'(i_is_bias_group_rows_target);

    assign is_bias_rows_fit = is_bias_rows_less || is_bias_rows_equal;
        // 行数与组容量独立比较，完整保留执行行数的高位。
        unsigned_compare #(.p_width(p_bias_compare_width)) u_bias_rows_bound (
            .i_a(p_bias_compare_width'(i_exec_m)),
            .i_b(p_bias_compare_width'(is_bias_group_rows_target_ext)),
            .o_less(is_bias_rows_less), .o_equal(is_bias_rows_equal)
        );

        assign is_bias_exec_m_ext = p_reg_width'(i_exec_m);
        // 每四位独立产生零判断，跨组借位只归并这些短组结果。
        for (genvar group = 0; group < p_bias_mask_groups; group++) begin : g_bias_mask_zero
            localparam int unsigned p_first = 4 * group;
            localparam int unsigned p_bits = (p_bias_count_bits-p_first < 4) ? p_bias_count_bits-p_first : 4;
            assign is_bias_mask_group_zero[group] = ~|is_bias_group_rows_target_ext[p_first +: p_bits];
        end
        for (genvar group = 0; group < p_bias_high_groups; group++) begin : g_bias_high_zero
            localparam int unsigned p_first = p_bias_count_bits + 4 * group;
            localparam int unsigned p_bits = (p_reg_width-p_first < 4) ? p_reg_width-p_first : 4;
            assign is_bias_high_group_zero[group] = ~|is_bias_exec_m_ext[p_first +: p_bits];
        end
        if (p_bias_high_groups == 0) begin : g_bias_no_high_bits
            assign is_bias_high_group_zero = '1;
        end
        for (genvar bit_idx = 0; bit_idx < p_bias_count_bits; bit_idx++) begin : g_bias_mask_low
            if (bit_idx == 0) begin : g_first
                assign is_bias_target_mask_ext[bit_idx] = ~is_bias_group_rows_target_ext[bit_idx];
            end else if (bit_idx < 4) begin : g_low
                assign is_bias_target_mask_ext[bit_idx] = is_bias_group_rows_target_ext[bit_idx] ^
                    (~|is_bias_group_rows_target_ext[bit_idx-1:0]);
            end else if (bit_idx % 4 == 0) begin : g_boundary
                assign is_bias_target_mask_ext[bit_idx] = is_bias_group_rows_target_ext[bit_idx] ^
                    (&is_bias_mask_group_zero[bit_idx/4-1:0]);
            end else begin : g_later
                assign is_bias_target_mask_ext[bit_idx] = is_bias_group_rows_target_ext[bit_idx] ^
                    ((&is_bias_mask_group_zero[bit_idx/4-1:0]) &&
                     (~|is_bias_group_rows_target_ext[4*(bit_idx/4) +: bit_idx%4]));
            end
        end
        if (p_reg_width > p_bias_count_bits) begin : g_bias_mask_high
            assign is_bias_target_mask_ext[p_reg_width-1:p_bias_count_bits] =
                {(p_reg_width-p_bias_count_bits){is_bias_group_rows_target_ext == p_reg_width'(0)}};
        end
        assign is_bias_low_difference =
            {1'b0, is_bias_exec_m_ext[p_bias_count_bits-1:0]} -
            {1'b0, is_bias_group_rows_target_ext[p_bias_count_bits-1:0]};
        assign is_bias_full_group_base[p_bias_count_bits-1:0] =
            is_bias_low_difference[p_bias_count_bits-1:0];
        // 各高位字节并行准备减一结果，低位借位只选择保持值或减一值。
        for (genvar group = p_bias_count_bits; group < p_reg_width; group += 8) begin : g_bias_high
            localparam int unsigned p_bits = (p_reg_width-group < 8) ? p_reg_width-group : 8;
            logic [p_bits-1:0] decremented;
            logic borrow;
            logic low_nibble_zero;
            if (p_bits > 4) begin : g_low_nibble
                assign low_nibble_zero = ~|is_bias_exec_m_ext[group +: 4];
            end else begin : g_short_group
                assign low_nibble_zero = 1'b0;
            end
            for (genvar bit_idx = 0; bit_idx < p_bits; bit_idx++) begin : g_bit
                if (bit_idx == 0) begin : g_first
                    assign decremented[bit_idx] = ~is_bias_exec_m_ext[group+bit_idx];
                end else if (bit_idx <= 4) begin : g_low
                    assign decremented[bit_idx] = is_bias_exec_m_ext[group+bit_idx] ^
                        (~|is_bias_exec_m_ext[group +: bit_idx]);
                end else begin : g_high
                    assign decremented[bit_idx] = is_bias_exec_m_ext[group+bit_idx] ^
                        (low_nibble_zero && (~|is_bias_exec_m_ext[group+4 +: bit_idx-4]));
                end
            end
            if (group == p_bias_count_bits) begin : g_first_borrow
                assign borrow = is_bias_low_difference[p_bias_count_bits];
            end else begin : g_later_borrow
                assign borrow = is_bias_low_difference[p_bias_count_bits] &&
                    (&is_bias_high_group_zero[(group-p_bias_count_bits)/4-1:0]);
            end
            assign is_bias_full_group_base[group +: p_bits] = borrow ?
                decremented : is_bias_exec_m_ext[group +: p_bits];
        end
    assign is_bias_tail_rows_raw = i_exec_m & is_bias_target_mask_ext;
    assign is_bias_tail_rows_calc = (is_bias_tail_rows_raw == '0)
              ? i_is_bias_group_rows_target
              : is_bias_tail_rows_raw[p_is_bias_valid_w-1:0];
        // 尾组直接清除所选低位，整组末尾使用独立的借位选择计算。
    assign is_bias_last_group_base_calc = is_bias_rows_fit ? p_reg_width'(0) :
          (is_bias_tail_rows_raw == p_reg_width'(0)) ? is_bias_full_group_base :
          (is_bias_exec_m_ext & ~p_reg_width'(p_is_bias_valid_w'(is_bias_target_mask_ext)));
    assign is_bias_first_rows_valid = (i_exec_m == '0) ? p_is_bias_valid_w'(1) :
          !is_bias_rows_fit
              ? i_is_bias_group_rows_target
              : i_exec_m[p_is_bias_valid_w-1:0];
        assign is_bias_advance_sum = is_bias_group_base + p_reg_width'(is_bias_rows_valid);
        assign is_bias_group_base_plus = is_bias_advance_sum;
        // 当前组和候选下一组并行比较，回绕只选择已经完成的范围判断。
        unsigned_compare #(.p_width(p_reg_width)) u_bias_current_bound (
            .i_a(is_bias_group_base), .i_b(is_bias_last_group_base),
            .o_less(is_bias_current_less), .o_equal(is_bias_current_equal)
        );
        unsigned_compare #(.p_width(p_reg_width)) u_bias_next_bound (
            .i_a(is_bias_group_base_plus), .i_b(is_bias_last_group_base),
            .o_less(is_bias_next_less), .o_equal(is_bias_next_equal)
        );
    assign is_bias_group_wrap_step = !is_bias_current_less;
    assign is_bias_group_base_step = is_bias_group_wrap_step ? p_reg_width'(0) : is_bias_group_base_plus;
    assign is_bias_group_step_is_last = is_bias_group_wrap_step ? (is_bias_last_group_base == p_reg_width'(0)) : !is_bias_next_less;
    assign is_bias_rows_valid_step = is_bias_group_step_is_last ? is_bias_last_rows : i_is_bias_group_rows_target;
    assign is_bias_scalar = (i_is_mode && (i_bias_base != '0)) ? i_bias_group_scalar : 32'sd0;
        always_comb begin
            o_is_bias_read_idx = is_bias_row_idx;
            if (i_is_mode && i_acc_data_valid) begin
                if (is_bias_row_wrap)
                    o_is_bias_read_idx = '0;
                else
                    o_is_bias_read_idx = is_bias_row_idx + 1'b1;
            end
            // 组首读取由偏置缓冲区的 group_read_start 选择当前组基址。
            if (i_init_cfg_ia)
                o_is_bias_read_idx = '0;
        end
        assign is_bias_row_increment = is_bias_row_idx + p_is_bias_row_w'(1);
        // 扩展差值表示剩余行数，符号位和零值共同判断递增后的回绕。
        assign is_bias_row_distance = {1'b0, is_bias_rows_valid} +
            ~((p_is_bias_valid_w+1)'(is_bias_row_idx));
        assign is_bias_row_wrap = (is_bias_rows_valid <= p_is_bias_valid_w'(1)) ||
            is_bias_row_distance[p_is_bias_valid_w] || (is_bias_row_distance == '0);
        // 先计算保持、递增和回绕结果，组首触发只参与最后一级清零选择。
        assign is_bias_row_step = (i_is_mode && i_acc_data_valid) ?
            (is_bias_row_wrap ? p_is_bias_row_w'(0) : is_bias_row_increment) : is_bias_row_idx;
        assign is_bias_row_clear = i_init_cfg_ia || (i_is_mode && i_send_ia_trigger && !i_bias_sleep);
        assign is_bias_row_next = is_bias_row_clear ? p_is_bias_row_w'(0) : is_bias_row_step;
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) is_bias_row_idx <= '0;
            else is_bias_row_idx <= is_bias_row_next;
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                is_bias_group_base <= '0;
                is_bias_last_group_base <= '0;
                is_bias_last_rows <= p_is_bias_valid_w'(1);
                is_bias_rows_valid <= p_is_bias_valid_w'(1);
                is_bias_rows_valid_pending <= p_is_bias_valid_w'(1);
            end else begin
                if (i_init_cfg_ia) begin
                    is_bias_group_base <= '0;
                    is_bias_last_group_base <= is_bias_last_group_base_calc;
                    is_bias_last_rows <= is_bias_tail_rows_calc;
                    is_bias_rows_valid <= p_is_bias_valid_w'(1);
                    is_bias_rows_valid_pending <= is_bias_first_rows_valid;
                end else begin
                    if (i_is_mode && i_bias_switch) begin
                        is_bias_group_base <= is_bias_group_base_step;
                        is_bias_rows_valid_pending <= is_bias_rows_valid_step;
                    end
                    if (i_is_mode && i_send_ia_trigger && !i_bias_sleep) begin
                        is_bias_rows_valid <= is_bias_rows_valid_pending;
                    end
                end
            end
        end
    genvar rq_i;
    generate
        for (rq_i = 0; rq_i < p_size; rq_i = rq_i + 1) begin : gen_requant_in_vec
            logic signed [31:0] add_i_lhs;
            logic signed [31:0] add_i_rhs0;
            logic signed [31:0] add_i_rhs1;
            logic add_i_rhs_select;
            logic add_i_enable;
            logic signed [31:0] add_o_sum;
            assign add_i_lhs = i_acc_data_out[rq_i];
            assign add_i_rhs0 = i_compute_bias_latched[rq_i];
            assign add_i_rhs1 = is_bias_scalar;
            assign add_i_rhs_select = i_is_mode;
            assign add_i_enable = i_is_mode || i_ws_final_bias;
            assign requant_in_vec[rq_i] = add_o_sum;
            // 偏置选择和三十二位模加位于计算输出寄存与量化输入缓存之间。
            select_add #(.p_width(32)) u_bias_add (
                .i_lhs       (add_i_lhs),
                .i_rhs0      (add_i_rhs0),
                .i_rhs1      (add_i_rhs1),
                .i_rhs_select(add_i_rhs_select),
                .i_add_enable(add_i_enable),
                .o_sum       (add_o_sum)
            );
        end
    endgenerate
    assign o_load_quant_req = load_quant_req_s8;
    assign o_quant_params_valid = quant_params_valid_s8;
        vec_requant #(.BUS_WIDTH(p_bus_width),
            .VLEN        (p_size),
            .REG_WIDTH   (p_reg_width),
            .MAX_IA_REUSE(p_requant_max_ia_reuse),
            .p_compute_lanes(p_requant_compute_lanes),
            .p_parameter_output(1'b0),
            .p_input_rows(p_ia_reuse_num_max * p_size),
            .ENABLE_PER_CHANNEL(p_enable_per_channel),
            .ENABLE_IS_MODE(p_enable_is_mode),
            .ENABLE_S16(1)
    ) u_vec_requant (
        .i_dw_enable(i_run_vector && p_dw_shared_quant_enable),
        .i_dw_valid(i_dw_quant_req_valid), .o_dw_ready(o_dw_quant_req_ready),
        .i_dw_tag(i_dw_quant_req_tag), .i_dw_accumulator(i_dw_quant_accumulator),
        .i_dw_multiplier(i_dw_quant_multiplier), .i_dw_right(i_dw_quant_right),
        .i_dw_mask(i_dw_quant_mask), .i_dw_offset(i_dw_quant_offset),
        .i_dw_minimum(i_dw_quant_minimum), .i_dw_maximum(i_dw_quant_maximum),
        .o_dw_valid(o_dw_quant_rsp_valid), .o_dw_tag(o_dw_quant_rsp_tag),
        .i_group_start(i_requant_group_start),
        .i_group_rows(i_requant_group_rows),
        .o_group_ready(o_requant_group_ready),
        .clk               (clk),
        .rst_n             (rst_n),
        .init_cfg          (i_exec_init_requant),
        .cfg_per_channel   (i_use_per_channel_eff),
        .cfg_dataflow_mode (i_cfg_dataflow_mode_eff),
        .cfg_s16           (i_run_16x8),
        .activation_min_in (i_act_min),
        .activation_max_in (i_act_max),
        .dst_offset_in     (i_dst_zp),
        .multiplier_in     (i_exec_q_mult),
        .shift_in          (i_exec_q_shift),
        .load_quant_req    (load_quant_req_s8),
        .load_quant_granted(i_load_quant_granted),
        .quant_params_valid(quant_params_valid_s8),
            .k                 (i_exec_stream_k),
            .m                 (i_exec_stream_m),
            .ia_reuse_num_in   (i_ia_reuse_num_eff),
            .dma_start         (o_quant_dma_start),
            .dma_is_write      (),
            .dma_linear_read_mode(o_quant_dma_linear_read_mode),
            .dma_base_addr     (o_quant_dma_base_addr),
            .dma_row_stride    (o_quant_dma_row_stride),
            .dma_rows_to_read  (o_quant_dma_rows_to_read),
            .dma_burst_len_m1  (o_quant_dma_burst_len_m1),
            .dma_slot_id       (o_quant_dma_slot_id),
            .dma_use_16bits    (o_quant_dma_use_16bits),
            .dma_lhs_zp        (o_quant_dma_lhs_zp),
            .dma_raw_data      (i_quant_dma_raw_data),
            .dma_raw_valid     (i_quant_dma_raw_valid),
            .in_valid          (i_acc_data_valid && !i_ps_capacity_fault),
            .in_tile_done      (i_tile_calc_over),
            .in_vec_s32        (requant_in_vec),
        .out_valid         (requant_out_valid),
        .out_tile_done     (requant_out_tile_done),
            .out_vec_s8        (o_requant_out),
            .out_vec_s16       (requant_out_s16),
            .quant_multiplier_lane(),
            .quant_shift_lane()
        );
    genvar i;
    generate
        for (i = 0; i < p_size; i = i + 1) begin : gen_unpack_in_vec
            assign in_vec_s8[i*8+:8] = o_requant_out[i];
            assign in_vec_s16[i*16+:16] = requant_out_s16[i];
        end
    endgenerate
    assign fifo_output_req = i_run_16x8 ? fifo_s16_output_req : fifo_s8_output_req;
    assign fifo_output_valid = i_run_16x8 ? fifo_s16_output_valid : fifo_s8_output_valid;
    assign fifo_output_switch_row = i_run_16x8 ? fifo_s16_output_switch_row
                                             : fifo_s8_output_switch_row;
    assign fifo_output_mask = i_run_16x8 ? fifo_s16_output_mask : fifo_s8_output_mask;
    assign fifo_output_data = i_run_16x8 ? fifo_s16_output_data : fifo_s8_output_data;
    assign o_fifo_full_flag = i_run_16x8 ? fifo_s16_full_flag : fifo_s8_full_flag;
    assign o_direct_final_stream=!i_frame_mode_q && i_direct_output_cfg;
    assign oa_row_coalesce_pre = i_oa_ws_coalesce_pre || i_oa_is_coalesce_pre;
    assign oa_coalesce_cols_pre = i_is_mode ? i_ia_reuse_num_eff[4:0] : i_oa_chunk_cols_pre;
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            oa_row_coalesce <= 0;
            oa_coalesce_cols <= 0;
        end else if (i_init_cfg_oa) begin
            oa_row_coalesce <= oa_row_coalesce_pre;
            oa_coalesce_cols <= oa_coalesce_cols_pre;
        end
    end
    // 输出缓冲
    vec_s8_to_fifo #(.BUS_WIDTH(p_bus_width),
        .VLEN (p_size),
        .BANKS(p_oa_fifo_banks),
        .ENABLE_TRANSPOSE(p_enable_is_mode),
        // 任务配置只在控制器和帧调度器均空闲时更新，合并输出期间保持方向。
        .p_cyclic_storage(1'b1),
        .p_precomputed_watermark(1'b1)
    ) u_vec_s8_to_fifo (
        .clk              (clk),
        .rst_n            (rst_n),
        .in_valid         (requant_out_valid && !i_run_16x8),
        .in_tile_done     (requant_out_tile_done && !i_run_16x8),
        .in_vec_s8        (in_vec_s8),
        .oa_fifo_req      (fifo_s8_output_req),
        .transpose_mode   (i_is_mode),
        .coalesce_enable  (oa_row_coalesce),
        .coalesce_group_start(oa_coalesce_group_start),
        .coalesce_rows    (p_reg_width'(oa_coalesce_rows)),
        .coalesce_cols    (p_reg_width'(oa_coalesce_cols)),
        .reserve_banks    (32'(i_output_reserve_banks)),
        .i_ready_bank_threshold(32'(i_output_s8_ready_threshold)),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .vec_valid_num_row(fifo_vec_valid_num_row),
        .output_valid     (fifo_s8_output_valid),
        .output_row_switch(fifo_s8_output_switch_row),
        .output_ready     (fifo_output_ready && !i_run_16x8),
        .output_mask      (fifo_s8_output_mask),
        .output_data      (fifo_s8_output_data),
        .fifo_full_flag   (fifo_s8_full_flag)
    );
`ifdef GEMMORA_INT8_PROFILE
    assign fifo_s16_output_req=1'b0;
    assign fifo_s16_output_valid=1'b0;
    assign fifo_s16_output_switch_row=1'b0;
    assign fifo_s16_output_mask='0;
    assign fifo_s16_output_data='0;
    assign fifo_s16_full_flag=1'b0;
`else
    vec_s16_to_fifo #(.BUS_WIDTH(p_bus_width),
        .VLEN (p_size),
        .BANKS(p_oa_s16_fifo_banks),
        .p_precomputed_watermark(1'b1)
    ) u_vec_s16_to_fifo (
        .clk              (clk),
        .rst_n            (rst_n),
        .in_valid         (requant_out_valid && i_run_16x8),
        .in_tile_done     (requant_out_tile_done && i_run_16x8),
        .in_vec_s16       (in_vec_s16),
        .oa_fifo_req      (fifo_s16_output_req),
        .reserve_banks    (32'(i_output_s16_reserve_banks)),
        .i_ready_bank_threshold(32'(i_output_s16_ready_threshold)),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .output_valid     (fifo_s16_output_valid),
        .output_ready     (fifo_output_ready && i_run_16x8),
        .output_row_switch(fifo_s16_output_switch_row),
        .output_mask      (fifo_s16_output_mask),
        .output_data      (fifo_s16_output_data),
        .fifo_full_flag   (fifo_s16_full_flag)
    );
`endif
    // 输出写回
        oa_writer #(
            .VLEN      (p_size),
            .DATA_WIDTH(8),
            .REG_WIDTH (p_reg_width),
            .BUS_WIDTH (p_bus_width),
            .COUNT_WIDTH(p_dim_count_width),
            .ENABLE_IS_MODE(p_enable_is_mode)
        ) u_oa_writer (
        .clk              (clk),
        .rst_n            (rst_n),
        .init_cfg         (i_exec_init_oa),
        .oa_fifo_req      (fifo_output_req),
        .vec_valid_num_col(fifo_vec_valid_num_col),
        .vec_valid_num_row(fifo_vec_valid_num_row),
        .write_oa_req     (o_write_oa_req),
        .write_oa_granted (i_write_oa_granted),
            .dst_base         (i_exec_dst_base),
            .dst_row_stride_b (i_dst_row_stride_b),
            .k                (i_exec_k),
            .m                (i_exec_m),
        .ia_reuse_num     (i_ia_reuse_num_eff),
        .is_mode          (i_is_mode),
        .output_16bits    (i_run_16x8),
        .coalesce_enable  (oa_row_coalesce_pre),
        .coalesce_cols    (oa_coalesce_cols_pre),
        .coalesce_group_start(oa_coalesce_group_start),
        .coalesce_row_tiles(oa_coalesce_rows),
        .output_valid     (fifo_output_valid),
        .switch_row       (fifo_output_switch_row),
            .output_ready     (fifo_output_ready),
            .output_mask      (fifo_output_mask),
            .output_data      (fifo_output_data),
            .dma_start        (o_oa_dma_start),
            .dma_is_write     (),
            .dma_linear_read_mode(),
            .dma_base_addr    (o_oa_dma_base_addr),
            .dma_row_stride   (o_oa_dma_row_stride),
            .dma_rows_to_read (o_oa_dma_rows_to_read),
            .dma_burst_len_m1 (o_oa_dma_burst_len_m1),
            .dma_slot_id      (),
            .dma_use_16bits   (),
            .dma_lhs_zp       (),
            .dma_src_wdata    (o_oa_dma_src_wdata),
            .dma_src_wmask    (o_oa_dma_src_wmask),
            .dma_src_wvalid   (o_oa_dma_src_wvalid),
            .dma_src_wready   (i_oa_dma_src_wready),
            .dma_busy         (i_oa_dma_busy),
            .dma_done         (i_oa_dma_done),
            .write_done       (write_done),
            .oa_calc_over     (o_oa_calc_over)
        );

endmodule

`default_nettype wire
