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
    input wire logic signed [31:0] i_acc_data_out [p_size], // 计算阵列返回的有符号累加结果向量。
    input wire logic i_acc_data_valid, // 计算阵列累加结果有效。
    input wire logic signed [p_reg_width-1:0] i_act_max, // 量化输出的有符号激活上限。
    input wire logic signed [p_reg_width-1:0] i_act_min, // 量化输出的有符号激活下限。
    input wire logic [p_reg_width-1:0] i_bias_base, // 偏置存储首地址，零值表示未配置偏置。
    input wire logic signed [31:0] i_bias_group_scalar, // 当前输入驻留分组同步读出的标量偏置。
    input wire logic i_bias_sleep, // 抑制输入驻留模式的偏置分组启动。
    input wire logic i_bias_switch, // 推进输入驻留模式的偏置分组。
    input wire logic i_cfg_dataflow_mode_eff, // 量化使用的数据流方式，一表示输入驻留。
    input wire logic clk, // 输出处理流水线的工作时钟。
    input wire logic signed [31:0] i_compute_bias_latched [p_size], // 计算阶段保存的逐通道偏置向量。
    input wire logic rst_n, // 低有效复位，清除输出处理的有效状态。
    input wire logic i_direct_output_cfg, // 允许最终结果直接进入输出写回。
    input wire logic [p_reg_width-1:0] i_dst_row_stride_b, // 外部输出矩阵相邻行的字节跨度。
    input wire logic signed [p_reg_width-1:0] i_dst_zp, // 量化结果需要加上的有符号输出零点。
    input wire logic signed [31:0] i_dw_quant_accumulator [p_size], // 深度卷积提交的有符号累加结果向量。
    input wire logic [p_size-1:0] i_dw_quant_mask, // 深度卷积量化请求的有效通道掩码。
    input wire logic signed [31:0] i_dw_quant_maximum, // 深度卷积量化结果的有符号上限。
    input wire logic signed [31:0] i_dw_quant_minimum, // 深度卷积量化结果的有符号下限。
    input wire logic signed [31:0] i_dw_quant_multiplier [p_size], // 深度卷积各通道的有符号量化乘数。
    input wire logic signed [31:0] i_dw_quant_offset, // 深度卷积量化结果需要加上的输出零点。
    input wire logic i_dw_quant_req_tag, // 随深度卷积量化结果返回的请求标签。
    input wire logic i_dw_quant_req_valid, // 深度卷积量化请求有效。
    input wire logic [5:0] i_dw_quant_right [p_size], // 深度卷积各通道乘积的右移位数。
    input wire logic [31:0] i_exec_dst_base, // 当前执行任务的输出起始字节地址。
    input wire logic i_exec_init_oa, // 初始化当前执行任务的输出写回控制。
    input wire logic i_exec_init_requant, // 初始化量化配置并清除偏置加法有效状态。
    input wire logic [31:0] i_exec_k, // 输出写回的行维度长度。
    input wire logic [31:0] i_exec_m, // 输出写回的列维度长度及输入驻留偏置范围。
    input wire logic signed [31:0] i_exec_q_mult, // 整张量量化乘数或逐通道乘数表首地址。
    input wire logic signed [31:0] i_exec_q_shift, // 整张量量化移位量或逐通道移位表首地址。
    input wire logic [31:0] i_exec_stream_k, // 量化输入流的行维度长度。
    input wire logic [31:0] i_exec_stream_m, // 量化输入流的列维度长度。
    input wire logic i_frame_mode_q, // 已保存的整帧输出处理模式。
    input wire logic [p_reg_width-1:0] i_ia_reuse_num_eff, // 当前输入复用组包含的输出行分块数。
    input wire logic i_init_cfg_ia, // 初始化输入驻留偏置读取与分组位置。
    input wire logic i_init_cfg_oa, // 保存输出缓冲的行合并配置。
    input wire logic [p_is_bias_valid_w-1:0] i_is_bias_group_rows_target, // 输入驻留模式每个偏置分组的目标行数。
    input wire logic i_is_mode, // 当前任务采用输入驻留数据流。
    input wire logic i_load_quant_granted, // 量化参数装载请求取得资源授予。
    input wire logic [4:0] i_oa_chunk_cols_pre, // 待保存的权重驻留输出合并列数。
    input wire logic i_oa_dma_busy, // 输出 DMA 仍在执行写入。
    input wire logic i_oa_dma_done, // 当前输出 DMA 写入完成。
    input wire logic i_oa_dma_src_wready, // 输出 DMA 可接收当前写入数据拍。
    input wire logic i_oa_is_coalesce_pre, // 输入驻留模式允许合并相邻输出行。
    input wire logic i_oa_ws_coalesce_pre, // 权重驻留模式允许合并相邻输出行。
    input wire logic [p_s8_reserve_width-1:0] i_output_reserve_banks, // 八位输出缓冲需要预留的存储体数。
    input wire logic [p_s16_reserve_width-1:0] i_output_s16_ready_threshold, // 十六位输出缓冲允许接收的占用阈值。
    input wire logic [p_s16_reserve_width-1:0] i_output_s16_reserve_banks, // 十六位输出缓冲需要预留的存储体数。
    input wire logic [p_s8_reserve_width-1:0] i_output_s8_ready_threshold, // 八位输出缓冲允许接收的占用阈值。
    input wire logic i_ps_capacity_fault, // 部分和容量异常，清除待处理的偏置结果。
    input wire logic [p_bus_width-1:0] i_quant_dma_raw_data, // DMA 返回的原始量化参数数据拍。
    input wire logic i_quant_dma_raw_valid, // DMA 返回的量化参数数据拍有效。
    input wire logic [31:0] i_requant_group_rows, // 即将送入量化器的分组行数。
    input wire logic i_requant_group_start, // 请求量化器预留下一组输入的处理容量。
    input wire logic i_run_16x8, // 当前任务采用十六位输出数据格式。
    input wire logic i_run_vector, // 当前执行向量任务，可使用共享深度卷积量化。
    input wire logic i_send_ia_trigger, // 触发当前输入分组并更新对应偏置读取位置。
    input wire logic i_tile_calc_over, // 当前累加结果为分块最后一行。
    input wire logic i_use_per_channel_eff, // 当前任务启用逐通道量化参数。
    input wire logic i_write_oa_granted, // 输出写回请求取得 DMA 资源授予。
    input wire logic i_ws_final_bias, // 当前权重驻留输出需要加入已保存偏置。
    output logic o_direct_final_stream, // 当前最终结果采用直接写回方式。
    output logic o_dw_quant_req_ready, // 共享量化器可接收深度卷积请求。
    output logic o_dw_quant_rsp_tag, // 深度卷积量化返回对应的请求标签。
    output logic o_dw_quant_rsp_valid, // 深度卷积量化结果有效。
    output logic o_fifo_full_flag, // 当前输出缓冲已达到需要暂停接收的容量阈值。
    output logic [p_is_bias_row_w-1:0] o_is_bias_read_idx, // 输入驻留分组下一次读取的标量偏置索引。
    output logic o_load_quant_req, // 请求装载逐通道量化参数。
    output logic o_oa_calc_over, // 当前任务的全部输出写回完成。
    output logic [p_reg_width-1:0] o_oa_dma_base_addr, // 当前输出 DMA 写入的起始字节地址。
    output logic [7:0] o_oa_dma_burst_len_m1, // 当前输出 DMA 每行的传输拍数减一。
    output logic [p_reg_width-1:0] o_oa_dma_row_stride, // 当前输出 DMA 相邻行起点的字节跨度。
    output logic [p_reg_width-1:0] o_oa_dma_rows_to_read, // 当前输出 DMA 需要写入的行数。
    output logic [p_bus_width-1:0] o_oa_dma_src_wdata, // 送往输出 DMA 的写入数据拍。
    output logic [p_bus_width/8-1:0] o_oa_dma_src_wmask, // 输出 DMA 数据拍的字节有效掩码。
    output logic o_oa_dma_src_wvalid, // 输出 DMA 写入数据拍有效。
    output logic o_oa_dma_start, // 启动当前输出 DMA 写入请求。
    output logic [p_reg_width-1:0] o_quant_dma_base_addr, // 当前量化参数 DMA 读取的起始字节地址。
    output logic [7:0] o_quant_dma_burst_len_m1, // 当前量化参数 DMA 的传输拍数减一。
    output logic signed [p_reg_width-1:0] o_quant_dma_lhs_zp, // 量化参数 DMA 的零点输入，固定为零。
    output logic o_quant_dma_linear_read_mode, // 量化参数 DMA 的线性读取方式标志。
    output logic [p_reg_width-1:0] o_quant_dma_row_stride, // 量化参数 DMA 相邻行起点的字节跨度。
    output logic [p_reg_width-1:0] o_quant_dma_rows_to_read, // 当前量化参数 DMA 需要读取的行数。
    output logic o_quant_dma_slot_id, // 量化参数 DMA 返回的目标槽号。
    output logic o_quant_dma_start, // 启动量化参数 DMA 读取请求。
    output logic o_quant_dma_use_16bits, // 量化参数 DMA 的十六位元素方式标志。
    output logic o_quant_params_valid, // 当前计算需要的量化参数已经准备完成。
    output logic o_requant_group_ready, // 量化器可接受下一组输入。
    output logic signed [7:0] o_requant_out [p_size], // 完成量化和激活限幅的八位结果向量。
    output logic o_write_oa_req // 请求取得输出 DMA 写回资源。
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
`ifdef SYNTHESIS
        logic is_bias_target_zero;
        // 完整掩码函数独立完成减一和零判断，尾部选择读取最终结果。
        npu_output_bias_mask #(.p_width(p_bias_count_bits)) u_bias_target_mask (
            .i_target(is_bias_group_rows_target_ext[p_bias_count_bits-1:0]),
            .o_mask(is_bias_target_mask_ext[p_bias_count_bits-1:0]),
            .o_zero(is_bias_target_zero)
        );
        if (p_reg_width > p_bias_count_bits) begin : g_bias_mask_high
            assign is_bias_target_mask_ext[p_reg_width-1:p_bias_count_bits] =
                {(p_reg_width-p_bias_count_bits){is_bias_target_zero}};
        end
`else
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
`endif
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
`ifdef SYNTHESIS
    // 低位完成组内计算，高位预先求减一值；尾组借位只参与最终选择。
    assign is_bias_last_group_base_calc[p_bias_count_bits-1:0] = is_bias_rows_fit ? '0 :
        (is_bias_tail_rows_raw == '0) ? is_bias_full_group_base[p_bias_count_bits-1:0] :
        (is_bias_exec_m_ext[p_bias_count_bits-1:0] &
         ~p_bias_count_bits'(p_is_bias_valid_w'(is_bias_target_mask_ext)));
    if (p_reg_width > p_bias_count_bits) begin : g_bias_last_high
        localparam int unsigned p_high_width = p_reg_width-p_bias_count_bits;
        logic [p_high_width-1:0] decremented;
        logic unused_high_zero;
        logic decrement_selected;
        npu_output_bias_mask #(.p_width(p_high_width)) u_decrement (
            .i_target(is_bias_exec_m_ext[p_reg_width-1:p_bias_count_bits]),
            .o_mask(decremented), .o_zero(unused_high_zero)
        );
        assign decrement_selected = (is_bias_tail_rows_raw == '0) &&
            is_bias_low_difference[p_bias_count_bits];
        assign is_bias_last_group_base_calc[p_reg_width-1:p_bias_count_bits] =
            is_bias_rows_fit ? '0 : decrement_selected ? decremented :
            is_bias_exec_m_ext[p_reg_width-1:p_bias_count_bits];
    end
`else
    assign is_bias_last_group_base_calc = is_bias_rows_fit ? p_reg_width'(0) :
          (is_bias_tail_rows_raw == p_reg_width'(0)) ? is_bias_full_group_base :
          (is_bias_exec_m_ext & ~p_reg_width'(p_is_bias_valid_w'(is_bias_target_mask_ext)));
`endif
    assign is_bias_first_rows_valid = (i_exec_m == '0) ? p_is_bias_valid_w'(1) :
          !is_bias_rows_fit
              ? i_is_bias_group_rows_target
              : i_exec_m[p_is_bias_valid_w-1:0];
        // 下一组高段的两种范围关系并行计算，低段进位只选择最终结果。
        npu_output_bias_advance #(
            .p_width(p_reg_width), .p_count_width(p_is_bias_valid_w)
        ) u_bias_advance (
            .i_base(is_bias_group_base), .i_rows(is_bias_rows_valid),
            .i_bound(is_bias_last_group_base), .o_sum(is_bias_advance_sum),
            .o_less(is_bias_next_less), .o_equal(is_bias_next_equal)
        );
        assign is_bias_group_base_plus = is_bias_advance_sum;
        // 当前组和候选下一组并行比较，回绕只选择已经完成的范围判断。
        unsigned_compare #(.p_width(p_reg_width)) u_bias_current_bound (
            .i_a(is_bias_group_base), .i_b(is_bias_last_group_base),
            .o_less(is_bias_current_less), .o_equal(is_bias_current_equal)
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
        npu_output_bias_row_select #(.p_width(p_is_bias_row_w)) u_bias_row_select (
            .i_step(is_bias_row_step), .i_init(i_init_cfg_ia), .i_mode(i_is_mode),
            .i_start(i_send_ia_trigger), .i_sleep(i_bias_sleep), .o_next(is_bias_row_next)
        );
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
    logic signed [31:0] bias_rhs [p_size];
    logic bias_clear, bias_valid, bias_tile_done;
    assign bias_clear = i_exec_init_requant || i_ps_capacity_fault;
    for (genvar lane = 0; lane < p_size; lane++) begin : g_bias_input
        assign bias_rhs[lane] = i_is_mode ? is_bias_scalar :
            (i_ws_final_bias ? i_compute_bias_latched[lane] : 32'sd0);
    end
    registered_vector_add #(.p_lanes(p_size)) u_bias_add (
        .clk(clk), .rst_n(rst_n), .i_clear(bias_clear),
        .i_valid(i_acc_data_valid), .i_tile_done(i_tile_calc_over),
        .i_lhs(i_acc_data_out), .i_rhs(bias_rhs),
        .o_valid(bias_valid), .o_tile_done(bias_tile_done), .o_sum(requant_in_vec)
    );
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
            .in_valid          (bias_valid),
            .in_tile_done      (bias_tile_done),
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
