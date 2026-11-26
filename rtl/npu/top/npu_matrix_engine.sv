`default_nettype none

// 矩阵任务的帧调度、操作数加载、阵列计算与结果处理。
module npu_matrix_engine #(
    parameter int unsigned p_addr_width = 32'd19,
    parameter int unsigned p_bias_dma_size = 32'd64,
    parameter int unsigned p_bus_width = 32'd64,
    parameter int unsigned p_data_width = 32'd16,
    parameter bit p_dw_shared_quant_enable = 1'h0,
    parameter int unsigned p_enable_is_mode = 32'd1,
    parameter int unsigned p_enable_per_channel = 32'd1,
    parameter bit p_frame_exec_enabled = 1'h1,
    parameter bit p_frame_prefetch_enable = 1'h1,
    parameter int unsigned p_ia_cache_blocks = 32'd4,
    parameter int unsigned p_ia_cache_slot_w = 32'd6,
    parameter int unsigned p_ia_compact_enable = 32'd1,
    parameter int unsigned p_ia_data_width = 32'd16,
    parameter int unsigned p_ia_max_cache_blocks = 32'd32,
    parameter int unsigned p_ia_slot_blocks = 32'd64,
    parameter int unsigned p_kernel_data_width = 32'd16,
    parameter int unsigned p_matrix_input_lanes = 32'd8,
    parameter int unsigned p_oa_fifo_banks_max = 32'd0,
    parameter int unsigned p_oa_s16_fifo_banks_max = 32'd4,
    parameter int unsigned p_ps_frame_count = 32'd16,
    parameter int unsigned p_ps_frame_id_w = 32'd4,
    parameter int unsigned p_ps_storage_rows = 32'd799,
    parameter int unsigned p_reg_width = 32'd32,
    parameter int unsigned p_shared_requant_lanes = 32'd2,
    parameter int unsigned p_shared_bank_bytes = 32'd8192,
    parameter int unsigned p_shared_ia_addr_width = 32'd12,
    parameter int unsigned p_shared_physical_banks = 32'd7,
    parameter int unsigned p_shared_physical_banks_width = 32'd3,
    parameter int unsigned p_shared_ps_addr_width = 32'd12,
    parameter int unsigned p_shared_ps_directory_rows = 32'd1024,
    parameter bit p_shared_ram_enabled = 1'h1,
    parameter int unsigned p_shared_total_bytes = 32'd57344,
    parameter int unsigned p_size = 32'd16,
    parameter int unsigned p_size_shift = 32'd4,
    parameter int unsigned p_vector_shared_ia_banks = 32'd1,
    parameter bit p_fixed_ps_channels = 1'h1
) (
    input wire logic i_abort_pending, // 当前任务正在等待终止和资源释放。
    input wire logic signed [p_reg_width-1:0] i_act_max, // 输出激活值的上限。
    input wire logic signed [p_reg_width-1:0] i_act_min, // 输出激活值的下限。
    input wire logic [p_reg_width-1:0] i_bias_base, // 偏置数组的字节基址。
    input wire logic i_bias_dma_busy, // 偏置 DMA：正在执行传输。
    input wire logic i_bias_dma_done, // 偏置 DMA：当前传输完成。
    input wire logic [$clog2(p_bias_dma_size)-1:0] i_bias_dma_wr_col_base, // 偏置 DMA：返回数据的首个写入列号。
    input wire logic signed [7:0] i_bias_dma_wr_data [p_bus_width/8], // 偏置 DMA：返回的逐通道写入数据。
    input wire logic [$clog2(p_bias_dma_size)-1:0] i_bias_dma_wr_row, // 偏置 DMA：返回数据的写入行号。
    input wire logic i_bias_dma_wr_slot, // 偏置 DMA：返回数据的缓存槽号。
    input wire logic i_bias_dma_wr_use_16bits, // 偏置 DMA：返回数据采用十六位元素。
    input wire logic i_bias_dma_wr_valid [p_bus_width/8], // 偏置 DMA：返回数据各通道的写入有效标志。
    input wire logic i_calc_start, // 开始接收新的计算任务。
    input wire logic i_cfg_16bits_ia, // 输入激活采用十六位元素。
    input wire logic i_cfg_16x8, // 选择十六位输入与八位权重的计算格式。
    input wire logic [p_reg_width-1:0] i_cfg_col_groups, // 驻留维度的分块组数，WS 对应输出列，IS 对应输出行。
    input wire logic [p_reg_width-1:0] i_cfg_col_tail_tiles, // 最后一个驻留维度分组的有效分块数。
    input wire conv_im2col_pkg::conv_cfg_t i_cfg_conv, // 卷积的图像、卷积核及步长配置。
    input wire logic i_cfg_conv_enable, // 启用卷积窗口展开。
    input wire logic i_cfg_dataflow_mode, // 请求的数据流模式，置位选择输入驻留。
    input wire logic i_cfg_dataflow_mode_eff, // 经过能力配置筛选的数据流模式。
    input wire logic [p_reg_width-1:0] i_cfg_ia_reuse_num, // 流式操作数分块的复用数量。
    input wire logic i_cfg_rhs_tile_packed, // 右操作数采用分块打包存储。
    input wire logic [p_reg_width-1:0] i_cfg_row_groups, // 流式维度的分块组数，WS 对应输出行，IS 对应输出列。
    input wire logic [p_reg_width-1:0] i_cfg_row_tail_tiles, // 最后一个流式维度分组的有效分块数。
    input wire logic [31:0] i_cfg_shared_ia_banks, // 为输入激活分配的共享存储分组数。
    input wire logic i_cfg_vector_enable, // 启用向量计算任务。
    input wire logic [p_reg_width-1:0] i_cfg_w_reuse_num, // 驻留操作数分块的复用数量。
    input wire logic clk, // 模块工作时钟。
    input wire conv_im2col_pkg::conv_cfg_t i_conv_cfg_q, // 已保存的卷积配置。
    input wire logic rst_n, // 低有效复位输入。
    input wire logic [p_reg_width-1:0] i_dst_base, // 输出矩阵的字节基址。
    input wire logic [p_reg_width-1:0] i_dst_row_stride_b, // 输出矩阵相邻行的字节间隔。
    input wire logic signed [p_reg_width-1:0] i_dst_zp, // 输出结果的量化零点。
    input wire logic signed [31:0] i_dw_quant_accumulator [p_size], // 逐通道深度卷积累加结果。
    input wire logic [p_size-1:0] i_dw_quant_mask, // 本次深度卷积量化请求的有效通道掩码。
    input wire logic signed [31:0] i_dw_quant_maximum, // 深度卷积量化输出的激活上限。
    input wire logic signed [31:0] i_dw_quant_minimum, // 深度卷积量化输出的激活下限。
    input wire logic signed [31:0] i_dw_quant_multiplier [p_size], // 各深度卷积通道使用的量化乘数。
    input wire logic signed [31:0] i_dw_quant_offset, // 深度卷积量化后的输出偏移。
    input wire logic i_dw_quant_req_tag, // 深度卷积量化请求的返回标签。
    input wire logic i_dw_quant_req_valid, // 深度卷积量化请求有效。
    input wire logic [5:0] i_dw_quant_right [p_size], // 各深度卷积通道使用的右移位数。
    input wire logic i_ia_dma_busy, // 输入激活 DMA：正在执行传输。
    input wire logic i_ia_dma_done, // 输入激活 DMA：当前传输完成。
    input wire logic [$clog2(p_size)-1:0] i_ia_dma_wr_col_base, // 输入激活 DMA：返回数据的首个写入列号。
    input wire logic signed [p_ia_data_width-1:0] i_ia_dma_wr_data [p_matrix_input_lanes], // 输入激活 DMA：返回的逐通道写入数据。
    input wire logic [$clog2(p_size)-1:0] i_ia_dma_wr_row, // 输入激活 DMA：返回数据的写入行号。
    input wire logic [p_ia_cache_slot_w-1:0] i_ia_dma_wr_slot, // 输入激活 DMA：返回数据的缓存槽号。
    input wire logic i_ia_dma_wr_use_16bits, // 输入激活 DMA：返回数据采用十六位元素。
    input wire logic i_ia_dma_wr_valid [p_matrix_input_lanes], // 输入激活 DMA：返回数据各通道的写入有效标志。
    input wire logic [127:0] i_ia_ram_read_data [0:1], // 输入激活共享存储：各端口返回的读取数据。
    input wire logic [p_reg_width-1:0] i_k, // 矩阵计算的输出行数。
    input wire logic i_kernel_dma_busy, // 卷积核 DMA：正在执行传输。
    input wire logic i_kernel_dma_done, // 卷积核 DMA：当前传输完成。
    input wire logic [$clog2(p_size)-1:0] i_kernel_dma_wr_col_base, // 卷积核 DMA：返回数据的首个写入列号。
    input wire logic signed [p_kernel_data_width-1:0] i_kernel_dma_wr_data [p_matrix_input_lanes], // 卷积核 DMA：返回的逐通道写入数据。
    input wire logic [$clog2(p_size)-1:0] i_kernel_dma_wr_row, // 卷积核 DMA：返回数据的写入行号。
    input wire logic i_kernel_dma_wr_slot, // 卷积核 DMA：返回数据的缓存槽号。
    input wire logic i_kernel_dma_wr_valid [p_matrix_input_lanes], // 卷积核 DMA：返回数据各通道的写入有效标志。
    input wire logic [p_reg_width-1:0] i_lhs_base, // 左操作数矩阵的字节基址。
    input wire logic [p_reg_width-1:0] i_lhs_row_stride_b, // 左操作数相邻行的字节间隔。
    input wire logic signed [p_reg_width-1:0] i_lhs_zp, // 左操作数的量化零点。
    input wire logic i_load_bias_granted, // 偏置读取已获得共享 DMA 资源授权。
    input wire logic i_load_ia_granted, // 输入激活读取已获得共享 DMA 资源授权。
    input wire logic i_load_quant_granted, // 量化参数读取已获得共享 DMA 资源授权。
    input wire logic i_load_weight_granted, // 卷积核读取已获得共享 DMA 资源授权。
    input wire logic [p_reg_width-1:0] i_m, // 矩阵计算的输出列数。
    input wire logic [p_reg_width-1:0] i_n, // 矩阵计算的归约长度。
    input wire logic i_oa_dma_busy, // 输出 DMA：正在执行传输。
    input wire logic i_oa_dma_done, // 输出 DMA：当前传输完成。
    input wire logic i_oa_dma_src_wready, // 输出 DMA：写入器能够接收新的数据。
    input wire logic i_operand_loader_flush_q, // 清除当前任务的操作数加载状态。
    input wire logic [31:0] i_ps_control_q, // 已保存的部分和容量及格式控制字段。
    input wire logic [127:0] i_ps_ram_read_data [0:3], // 部分和共享存储：各端口返回的读取数据。
    input wire logic signed [p_reg_width-1:0] i_q_mult_pt, // 逐张量量化乘数或逐通道乘数数组地址。
    input wire logic signed [p_reg_width-1:0] i_q_shift_pt, // 逐张量量化移位量或逐通道移位数组地址。
    input wire logic [p_bus_width-1:0] i_quant_dma_raw_data, // 量化参数 DMA 返回的原始总线数据。
    input wire logic i_quant_dma_raw_valid, // 量化参数 DMA 原始返回数据有效。
    input wire logic [p_reg_width-1:0] i_rhs_base, // 右操作数矩阵的字节基址。
    input wire logic [p_reg_width-1:0] i_rhs_col_stride_b, // 右操作数相邻列的字节间隔。
    input wire logic signed [p_reg_width-1:0] i_rhs_zp, // 右操作数的量化零点。
    input wire logic i_run_conv, // 当前已接收任务采用卷积模式。
    input wire logic i_run_lhs_tile_packed, // 当前任务的左操作数采用分块打包存储。
    input wire logic i_run_rhs_tile_packed, // 当前任务的右操作数采用分块打包存储。
    input wire logic i_run_vector, // 当前已接收任务采用向量模式。
    input wire logic i_sa_ready, // 计算阵列及其控制逻辑允许接收任务。
    input wire logic i_task_completion_accept, // 本周期接收任务完成响应的事件。
    input wire logic i_use_per_channel, // 请求使用逐通道量化参数。
    input wire logic i_vector_start_fire, // 本周期开始向量任务的事件。
    input wire logic i_write_oa_granted, // 输出数据写入已获得共享 DMA 资源授权。
    output logic [p_reg_width-1:0] o_bias_dma_base_addr, // 偏置 DMA：传输起始字节地址。
    output logic [7:0] o_bias_dma_burst_len_m1, // 偏置 DMA：每行突发的传输拍数减一。
    output logic signed [p_reg_width-1:0] o_bias_dma_lhs_zp, // 偏置 DMA：读取数据使用的量化零点。
    output logic o_bias_dma_linear_read_mode, // 偏置 DMA：选择线性读取布局。
    output logic [p_reg_width-1:0] o_bias_dma_row_stride, // 偏置 DMA：相邻数据行的字节间隔。
    output logic [p_reg_width-1:0] o_bias_dma_rows_to_read, // 偏置 DMA：本次传输需要读取的行数。
    output logic o_bias_dma_slot_id, // 偏置 DMA：读取结果写入的缓存槽号。
    output logic o_bias_dma_start, // 偏置 DMA：启动已获授权的传输。
    output logic o_bias_dma_use_16bits, // 偏置 DMA：按十六位元素组织读取结果。
    output logic o_cfg_16x8_q [0:2], // 各配置阶段采用十六位乘八位格式的标志。
    output logic [p_reg_width-1:0] o_cfg_ia_reuse_q [0:2], // 各配置阶段保存的流式操作数分块复用数量。
    output logic o_cfg_stage2_fire, // 配置准备的第三阶段完成事件。
    output logic [p_reg_width-1:0] o_cfg_stream_k_q [0:2], // 各配置阶段的流式维度长度，WS 为输出行数，IS 为输出列数。
    output logic [p_reg_width-1:0] o_cfg_stream_m_q [0:2], // 各配置阶段的驻留维度长度，WS 为输出列数，IS 为输出行数。
    output logic o_cfg_use16_q [0:2], // 各配置阶段采用十六位输入的标志。
    output logic [2:0] o_cfg_valid_q, // 三个配置准备阶段的有效标志。
    output logic [p_reg_width-1:0] o_cfg_w_reuse_q [0:2], // 各配置阶段保存的驻留分块复用数量。
    output logic o_controller_done_valid, // 矩阵调度控制器的完成响应有效。
    output logic [1:0] o_controller_err_code, // 矩阵调度控制器的完成错误码。
    output logic [31:0] o_conv_range_base [4], // 权重、偏置、乘数和移位数组的四个读取起始地址。
    output logic [32:0] o_conv_range_end [4], // 四个允许读取区间的右端地址，不包含该地址。
    output logic o_ctrl_sa_ready, // 矩阵调度控制器允许接收任务。
    output logic o_dw_quant_req_ready, // 共享量化器可以接收深度卷积请求。
    output logic o_dw_quant_rsp_tag, // 深度卷积量化响应对应的请求标签。
    output logic o_dw_quant_rsp_valid, // 深度卷积量化结果有效。
    output logic o_exec_dma_job_init, // 初始化本任务的 DMA 执行状态。
    output logic o_frame_mode_q, // 当前任务采用帧调度方式。
    output logic o_frame_scheduler_ready, // 帧调度器允许接收新任务。
    output logic [p_reg_width-1:0] o_ia_dma_base_addr, // 输入激活 DMA：传输起始字节地址。
    output logic [7:0] o_ia_dma_burst_len_m1, // 输入激活 DMA：每行突发的传输拍数减一。
    output logic [p_reg_width-1:0] o_ia_dma_group, // 输入激活 DMA：卷积请求所属的通道组号。
    output logic o_ia_dma_im2col, // 输入激活 DMA：启用卷积窗口展开读取。
    output logic signed [p_reg_width-1:0] o_ia_dma_lhs_zp, // 输入激活 DMA：读取数据使用的量化零点。
    output logic o_ia_dma_linear_read_mode, // 输入激活 DMA：选择线性读取布局。
    output logic [p_reg_width-1:0] o_ia_dma_p0, // 输入激活 DMA：卷积展开矩阵的输出位置起点。
    output logic [p_reg_width-1:0] o_ia_dma_q0, // 输入激活 DMA：卷积展开矩阵的归约位置起点。
    output logic [p_reg_width-1:0] o_ia_dma_row_stride, // 输入激活 DMA：相邻数据行的字节间隔。
    output logic [p_reg_width-1:0] o_ia_dma_rows_to_read, // 输入激活 DMA：本次传输需要读取的行数。
    output logic [p_ia_cache_slot_w-1:0] o_ia_dma_slot_id, // 输入激活 DMA：读取结果写入的缓存槽号。
    output logic o_ia_dma_start, // 输入激活 DMA：启动已获授权的传输。
    output logic o_ia_dma_use_16bits, // 输入激活 DMA：按十六位元素组织读取结果。
    output logic o_ia_prefetch_idle, // 输入激活预取逻辑已空闲。
    output logic [p_shared_ia_addr_width-1:0] o_ia_ram_read_addr [0:1], // 输入激活共享存储：各端口读取地址。
    output logic [1:0] o_ia_ram_read_en, // 输入激活共享存储：各端口读取使能。
    output logic [127:0] o_ia_ram_shared_write_data, // 输入激活共享存储：各写入端口共用的数据。
    output logic [p_shared_ia_addr_width-1:0] o_ia_ram_write_addr [0:1], // 输入激活共享存储：各端口写入地址。
    output logic [127:0] o_ia_ram_write_data [0:1], // 输入激活共享存储：各端口写入数据。
    output logic [1:0] o_ia_ram_write_en, // 输入激活共享存储：各端口写入使能。
    output logic [15:0] o_ia_ram_write_mask [0:1], // 输入激活共享存储：各端口的字节写入掩码。
    output logic [p_reg_width-1:0] o_ia_reuse_num_eff, // 当前容量允许的流式操作数分块复用数量。
    output logic o_inner_done_valid, // 内部执行控制器的完成响应有效。
    output logic [1:0] o_inner_err_code, // 内部执行控制器的完成错误码。
    output logic o_is_mode, // 当前矩阵任务采用输入驻留模式。
    output logic [p_reg_width-1:0] o_kernel_dma_base_addr, // 卷积核 DMA：传输起始字节地址。
    output logic [7:0] o_kernel_dma_burst_len_m1, // 卷积核 DMA：每行突发的传输拍数减一。
    output logic [p_reg_width-1:0] o_kernel_dma_group, // 卷积核 DMA：卷积请求所属的通道组号。
    output logic o_kernel_dma_im2col, // 卷积核 DMA：启用卷积窗口展开读取。
    output logic signed [p_reg_width-1:0] o_kernel_dma_lhs_zp, // 卷积核 DMA：读取数据使用的量化零点。
    output logic o_kernel_dma_linear_read_mode, // 卷积核 DMA：选择线性读取布局。
    output logic [p_reg_width-1:0] o_kernel_dma_p0, // 卷积核 DMA：卷积展开矩阵的输出位置起点。
    output logic [p_reg_width-1:0] o_kernel_dma_q0, // 卷积核 DMA：卷积展开矩阵的归约位置起点。
    output logic [p_reg_width-1:0] o_kernel_dma_row_stride, // 卷积核 DMA：相邻数据行的字节间隔。
    output logic [p_reg_width-1:0] o_kernel_dma_rows_to_read, // 卷积核 DMA：本次传输需要读取的行数。
    output logic o_kernel_dma_slot_id, // 卷积核 DMA：读取结果写入的缓存槽号。
    output logic o_kernel_dma_start, // 卷积核 DMA：启动已获授权的传输。
    output logic o_kernel_dma_use_16bits, // 卷积核 DMA：按十六位元素组织读取结果。
    output logic o_kernel_prefetch_idle, // 卷积核预取逻辑已空闲。
    output logic o_load_bias_req, // 偏置读取的 DMA 资源请求。
    output logic o_load_ia_req, // 输入激活读取的 DMA 资源请求。
    output logic o_load_quant_req, // 量化参数读取的 DMA 资源请求。
    output logic o_load_weight_req, // 卷积核读取的 DMA 资源请求。
    output logic [p_reg_width-1:0] o_oa_dma_base_addr, // 输出 DMA：传输起始字节地址。
    output logic [7:0] o_oa_dma_burst_len_m1, // 输出 DMA：每行突发的传输拍数减一。
    output logic [p_reg_width-1:0] o_oa_dma_row_stride, // 输出 DMA：相邻数据行的字节间隔。
    output logic [p_reg_width-1:0] o_oa_dma_rows_to_read, // 输出 DMA：本次传输需要写入的行数。
    output logic [p_bus_width-1:0] o_oa_dma_src_wdata, // 输出 DMA：送入写入器的数据。
    output logic [p_bus_width/8-1:0] o_oa_dma_src_wmask, // 输出 DMA：送入写入器的有效字节掩码。
    output logic o_oa_dma_src_wvalid, // 输出 DMA：送入写入器的数据有效。
    output logic o_oa_dma_start, // 输出 DMA：启动已获授权的传输。
    output logic o_ps_capacity_fault, // 部分和存储容量不足或访问越界。
    output logic [p_shared_ps_addr_width-1:0] o_ps_ram_read_addr [0:3], // 部分和共享存储：各端口读取地址。
    output logic [3:0] o_ps_ram_read_en, // 部分和共享存储：各端口读取使能。
    output logic [p_shared_ps_addr_width-1:0] o_ps_ram_write_addr [0:3], // 部分和共享存储：各端口写入地址。
    output logic [127:0] o_ps_ram_write_data [0:3], // 部分和共享存储：各端口写入数据。
    output logic [3:0] o_ps_ram_write_en, // 部分和共享存储：各端口写入使能。
    output logic [p_reg_width-1:0] o_quant_dma_base_addr, // 量化参数 DMA：传输起始字节地址。
    output logic [7:0] o_quant_dma_burst_len_m1, // 量化参数 DMA：每行突发的传输拍数减一。
    output logic signed [p_reg_width-1:0] o_quant_dma_lhs_zp, // 量化参数 DMA：读取数据使用的量化零点。
    output logic o_quant_dma_linear_read_mode, // 量化参数 DMA：选择线性读取布局。
    output logic [p_reg_width-1:0] o_quant_dma_row_stride, // 量化参数 DMA：相邻数据行的字节间隔。
    output logic [p_reg_width-1:0] o_quant_dma_rows_to_read, // 量化参数 DMA：本次传输需要读取的行数。
    output logic o_quant_dma_slot_id, // 量化参数 DMA：读取结果写入的缓存槽号。
    output logic o_quant_dma_start, // 量化参数 DMA：启动已获授权的传输。
    output logic o_quant_dma_use_16bits, // 量化参数 DMA：按十六位元素组织读取结果。
    output logic signed [7:0] o_requant_out [p_size], // 矩阵结果重新量化后的逐通道数据。
    output logic o_run_compact, // 当前任务使用紧凑的八位输入存储。
    output logic o_shared_allocation_invalid, // 输入激活与部分和的共享容量分配无效。
    output logic [31:0] o_shared_ia_banks_q, // 当前任务分配给输入激活的共享存储分组数。
    output logic o_write_oa_req // 输出数据写入的 DMA 资源请求。
);

    localparam int unsigned IA_REUSE_NUM_MAX =
    (p_ia_slot_blocks < 2) ? 1 : (p_ia_slot_blocks / 2);
    localparam int unsigned DIM_COUNT_WIDTH =
    (p_addr_width <= p_size_shift) ? 1 :
    (((p_addr_width - p_size_shift + 1) > p_reg_width) ? p_reg_width :
    (p_addr_width - p_size_shift + 1));
    localparam int unsigned W_REUSE_NUM_MAX =
    (p_ps_frame_count < 1) ? 1 : p_ps_frame_count;
    localparam int unsigned PS_ROW_COUNT_WIDTH = $clog2((IA_REUSE_NUM_MAX + 1) * p_size);
    localparam int unsigned PS_FRAME_COUNT_WIDTH = $clog2(W_REUSE_NUM_MAX + 2);
    localparam int unsigned PS_REQUIRED_WIDTH = PS_ROW_COUNT_WIDTH + PS_FRAME_COUNT_WIDTH;
    localparam int unsigned IA_REUSE_W =
    (IA_REUSE_NUM_MAX <= 1) ? 1 : ($clog2(IA_REUSE_NUM_MAX) + 1);
    localparam int unsigned W_REUSE_W =
    (W_REUSE_NUM_MAX <= 1) ? 1 : ($clog2(W_REUSE_NUM_MAX) + 1);
    localparam int unsigned OA_INITIAL_IA_REUSE =
    (p_ia_cache_blocks < 2) ? 1 : (p_ia_cache_blocks / 2);
    localparam int unsigned OA_LEGACY_BANKS_RAW = p_ps_frame_count * OA_INITIAL_IA_REUSE;
    localparam int unsigned OA_LEGACY_BANK_LIMIT =
    (p_enable_is_mode == 0 && p_enable_per_channel == 0) ? 16 : 32;
    localparam int unsigned OA_REQUIRED_BANKS = p_shared_ram_enabled ? IA_REUSE_NUM_MAX : 1;
    localparam int unsigned OA_FIFO_BANKS_RAW =
    (OA_LEGACY_BANKS_RAW < OA_REQUIRED_BANKS) ? OA_REQUIRED_BANKS : OA_LEGACY_BANKS_RAW;
    localparam int unsigned OA_AUTO_BANK_LIMIT =
    (OA_LEGACY_BANK_LIMIT < OA_REQUIRED_BANKS) ? OA_REQUIRED_BANKS : OA_LEGACY_BANK_LIMIT;
    localparam int unsigned OA_BANK_LIMIT =
    (p_oa_fifo_banks_max == 0) ? OA_AUTO_BANK_LIMIT : p_oa_fifo_banks_max;
    localparam int unsigned OA_FIFO_BANKS =
    (OA_FIFO_BANKS_RAW <= OA_BANK_LIMIT) ? OA_FIFO_BANKS_RAW : OA_BANK_LIMIT;
    localparam int unsigned p_s8_reserve_width = (OA_FIFO_BANKS <= 1) ? 1 : $clog2(OA_FIFO_BANKS + 1);
    localparam int unsigned OA_S16_FIFO_BANKS =
    (p_oa_s16_fifo_banks_max == 0 || OA_FIFO_BANKS <= p_oa_s16_fifo_banks_max) ?
    OA_FIFO_BANKS : p_oa_s16_fifo_banks_max;
    localparam int unsigned p_s16_reserve_width = (OA_S16_FIFO_BANKS <= 1) ? 1 : $clog2(OA_S16_FIFO_BANKS + 1);
    localparam int unsigned BIAS_GROUP_BLOCKS_MAX =
    (p_enable_is_mode != 0) ? IA_REUSE_NUM_MAX : 1;
    localparam int unsigned REQUANT_MAX_IA_REUSE =
    ((p_enable_is_mode != 0) && (p_enable_per_channel != 0)) ? IA_REUSE_NUM_MAX : 1;
    localparam int unsigned p_requant_compute_lanes =
    p_shared_requant_lanes;
    localparam int unsigned IS_BIAS_ROWS = BIAS_GROUP_BLOCKS_MAX * p_size;
    localparam int unsigned IS_BIAS_ROW_W = (IS_BIAS_ROWS <= 1) ? 1 : $clog2(IS_BIAS_ROWS);
    localparam int unsigned IS_BIAS_VALID_W =
    (IS_BIAS_ROWS <= 1) ? 1 : ($clog2(IS_BIAS_ROWS) + 1);
    localparam int unsigned p_controller_bias_w = (p_reg_width < 32) ? p_reg_width : 32;

typedef struct packed {
            logic [31:0] p0, q0, rows, cols;
            logic [2:0] sequence_id;
        } weight_prediction_t;
    logic signed [31:0] acc_data_out [p_size];
    logic acc_data_valid;
    logic [31:0] active_ia_cache_blocks;
    logic [31:0] active_ps_bank_count;
    logic [31:0] active_ps_bank_depth;
    logic signed [31:0] bias_data_hold [p_size];
    logic signed [31:0] bias_data_out [p_size];
    logic signed [31:0] bias_capture_data [p_size];
    logic signed [31:0] bias_group_scalar;
    logic bias_group_valid;
    logic bias_last_loop;
    logic bias_load_sleep;
    logic bias_sleep;
    logic bias_switch;
    logic bias_valid;
    logic bias_zero_o_equal;
    logic bias_base_nonzero;
    logic controller_bias_base_nonzero;
    logic capture_compute_bias;
    logic cfg_16bits_ia_eff;
    logic [p_reg_width-1:0] cfg_n_q [0:2];
    logic cfg_start_event;
    logic signed [31:0] compute_bias_in [p_size];
    logic signed [31:0] compute_bias_latched [p_size];
    logic compute_bias_sleep;
    logic [p_reg_width-1:0] controller_i_bias_base;
    logic ctrl_calc_start;
    logic direct_final_stream;
    logic direct_output_cfg;
    logic [31:0] exec_bias_address;
    logic [p_reg_width-1:0] bias_execution_address_i_base;
    logic [31:0] bias_execution_address_i_channel;
    logic [31:0] bias_execution_address_o_address;
    logic [31:0] exec_bias_base;
    logic exec_bias_present;
    logic [31:0] exec_channel;
    logic [31:0] exec_col_groups;
    logic [31:0] exec_col_tail;
    logic [31:0] exec_dst_base;
    logic [31:0] exec_ia_base;
    logic exec_init_oa;
    logic exec_init_requant;
    logic [31:0] exec_k;
    logic [31:0] exec_m;
    logic [31:0] exec_n;
    logic exec_oa_complete;
    logic signed [31:0] exec_q_mult;
    logic signed [31:0] exec_q_shift;
    logic [31:0] exec_row_groups;
    logic [31:0] exec_row_tiles;
    logic [31:0] exec_row_tail;
    logic [31:0] exec_stream_k;
    logic [31:0] exec_stream_m;
    logic [31:0] exec_w;
    logic [31:0] exec_weight_base;
    logic fifo_full_flag;
    logic frame_address_i_abort;
    logic [31:0] frame_address_i_column;
    logic [31:0] frame_address_i_dst_base;
    logic [31:0] frame_address_i_dst_stride;
    logic [31:0] frame_address_i_ia_base;
    logic frame_address_i_ia_packed;
    logic frame_address_i_ia_s16;
    logic [31:0] frame_address_i_ia_stride;
    logic frame_address_i_is_mode;
    logic frame_address_i_output_s16;
    logic [31:0] frame_address_i_p0;
    logic [31:0] frame_address_i_q0;
    logic frame_address_i_result_rdy;
    logic frame_address_i_start;
    logic [31:0] frame_address_i_total_depth;
    logic [31:0] frame_address_i_weight_base;
    logic frame_address_i_weight_packed;
    logic frame_address_i_weight_s16;
    logic [31:0] frame_address_i_weight_stride;
    logic [31:0] frame_address_o_dst_base;
    logic [31:0] frame_address_o_ia_base;
    logic frame_address_o_result_vld;
    logic frame_address_o_start_rdy;
    logic [31:0] frame_address_o_weight_base;
    logic [31:0] frame_cache_slot_base_calc;
    logic [p_ia_cache_slot_w-1:0] frame_cache_slot_base_q;
    logic frame_command_active;
    logic [31:0] frame_command_cols;
    logic [31:0] frame_command_column;
    logic frame_command_final;
    logic [p_ps_frame_id_w-1:0] frame_command_id;
    logic frame_command_init;
    logic [31:0] frame_command_k;
    logic [31:0] frame_command_p0;
    logic [31:0] frame_command_q0;
    logic frame_command_ready;
    logic [31:0] frame_command_reserve;
    logic [31:0] frame_command_rows;
    logic [2:0] frame_command_sequence;
    logic frame_command_start;
    logic frame_command_valid;
    logic frame_compute_seen;
    logic [1:0] frame_config_error;
    logic frame_dma_init_q;
    logic [31:0] frame_exec_cols;
    logic [31:0] frame_exec_column;
    logic frame_exec_final;
    logic frame_exec_init;
    logic [31:0] frame_exec_p0;
    logic [31:0] frame_exec_rows;
    logic frame_execute_start;
    logic frame_execution_started;
    logic [31:0] frame_lookahead_cols;
    logic [31:0] frame_lookahead_column;
    logic [31:0] frame_lookahead_k;
    logic [31:0] frame_lookahead_q0;
    logic frame_lookahead_valid;
    logic frame_output_armed;
    logic frame_output_seen;
    logic frame_ps_accepted;
    logic frame_scheduler_done;
    logic [1:0] frame_scheduler_error;
    logic [31:0] frame_slice_tiles_s2;
    logic frame_stationary_hit;
    logic frame_store_seen;
    logic frame_whole_rows_q;
    logic [p_reg_width-1:0] ia_base_eff;
    logic ia_calc_done;
    logic ia_data_valid;
    logic ia_is_init_data;
    logic ia_l1_switch;
    logic signed [p_ia_data_width-1:0] ia_out [p_size];
    logic ia_output_pending;
    logic ia_row_valid;
    logic ia_sending_done;
    logic [p_reg_width-1:0] ia_stride_eff;
    logic ia_tile_start;
    logic ia_use_16bits_eff;
    logic signed [p_reg_width-1:0] ia_zp_eff;
    logic init_cfg_bias;
    logic init_cfg_ia;
    logic init_cfg_oa;
    logic init_cfg_requant;
    logic init_cfg_weight;
    logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target;
    logic [IS_BIAS_ROW_W-1:0] is_bias_read_idx;
    logic kernel_loader_o_admission_request;
    logic kernel_loader_o_quiescent;
    logic load_bias_done;
    logic load_weight_done;
    logic [31:0] loader_frame_id;
    logic oa_calc_over;
    logic [4:0] oa_chunk_cols_pre;
    logic oa_is_coalesce_pre;
    logic oa_ws_coalesce_pre;
    logic [p_s8_reserve_width-1:0] output_reserve_banks;
    logic [p_s16_reserve_width-1:0] output_s16_ready_threshold;
    logic [p_s16_reserve_width-1:0] output_s16_reserve_banks;
    logic [p_s8_reserve_width-1:0] output_s8_ready_threshold;
    logic partial_sum_advance_ready;
    logic partial_sum_calc_over;
    logic [63:0] ps_admission_rows;
    logic ps_force_raw_q;
    logic ps_frame_complete;
    logic ps_frame_final;
    logic ps_frame_init;
    logic ps_frame_pressure;
    logic ps_frame_ready;
    logic [31:0] ps_frame_rows;
    logic [2:0] ps_word_cap_q;
    logic quant_params_valid;
    logic requant_group_ready;
    logic [31:0] requant_group_rows;
    logic requant_group_start;
    logic requant_output_group;
    logic run_16x8;
    logic signed [p_reg_width-1:0] run_compact_offset;
    logic run_is_mode;
    logic [p_reg_width-1:0] run_k;
    logic [p_reg_width-1:0] run_m;
    logic [p_reg_width-1:0] run_n;
    logic run_use_16bits;
    logic send_ia_trigger;
    logic send_weight_trigger;
    logic [31:0] stationary_column;
    logic [31:0] stationary_q0;
    logic stationary_valid;
    logic store_weight_req;
    logic [p_reg_width-1:0] stream_k;
    logic [p_reg_width-1:0] stream_m;
    logic tile_calc_over;
    logic tiling_invalid;
    logic matrix_storage_invalid, matrix_config_invalid;
    logic [1:0] matrix_frame_config_error;

    // 矩阵任务必须连接共享 IA 存储，非法配置使用既有错误完成流程。
    assign matrix_storage_invalid = !p_shared_ram_enabled;
    assign matrix_config_invalid = tiling_invalid || matrix_storage_invalid;
    assign matrix_frame_config_error = matrix_storage_invalid ? 2'b01 : frame_config_error;
    logic use_16bits;
    logic use_frame_commands_s2;
    logic use_per_channel_eff;
    logic [p_reg_width-1:0] w_reuse_num_eff;
    logic [p_reg_width-1:0] weight_base_eff;
    logic weight_commit;
    logic weight_data_valid;
    logic signed [p_kernel_data_width-1:0] weight_out [p_size];
    weight_prediction_t weight_prediction [0:3];
    logic [3:0] weight_prediction_valid;
    logic [31:0] weight_prefetch_base;
    logic weight_prefetch_valid;
    logic weight_sending_done;
    logic [p_reg_width-1:0] weight_stride_eff;
    logic weight_use_16bits_eff;
    logic signed [p_reg_width-1:0] weight_zp_eff;
    logic ws_final_bias;

        // 六、七个共享银行配置以两个量化通道处理整行，输入组缓存保留最大复用容量。
        // 更大银行配置保留全并行量化，使可寻址缓冲容量继续满足原有预算。

        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) frame_cache_slot_base_q <= '0;
            else if (frame_command_start)
                frame_cache_slot_base_q <= p_ia_cache_slot_w'(frame_cache_slot_base_calc);
        end
        // 接收帧命令时保存尺寸、起始位置和首末帧标志，执行期间使用同一份参数。
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                frame_exec_rows <= '0;
                frame_exec_cols <= '0;
                frame_exec_p0 <= '0;
                frame_exec_column <= '0;
                frame_exec_init <= 1'b0;
                frame_exec_final <= 1'b0;
            end else if (frame_command_start) begin
                frame_exec_rows <= frame_command_rows;
                frame_exec_cols <= frame_command_cols;
                frame_exec_p0 <= frame_command_p0;
                frame_exec_column <= frame_command_column;
                frame_exec_init <= frame_command_init;
                frame_exec_final <= frame_command_final;
            end
        end
    assign requant_output_group = o_frame_mode_q ? frame_exec_final : ia_output_pending;
    assign requant_group_start = send_ia_trigger && requant_output_group;
    assign requant_group_rows = o_frame_mode_q ? frame_exec_rows : ps_frame_rows;

    assign use_per_channel_eff = (p_enable_per_channel != 0)
                                 ? i_use_per_channel : 1'b0;
    assign ctrl_calc_start = (o_cfg_stage2_fire && !use_frame_commands_s2) || frame_execute_start;
        assign cfg_start_event = i_calc_start && i_sa_ready && !i_cfg_vector_enable;
        assign frame_cache_slot_base_calc =
            ((frame_command_p0 >> p_size_shift) +
             (frame_command_q0 >> p_size_shift) * o_ia_reuse_num_eff) &
            ((o_run_compact ? active_ia_cache_blocks << 1 : active_ia_cache_blocks) - 32'd1);
    assign o_is_mode = (p_enable_is_mode != 0) ? run_is_mode : 1'b0;
    assign ia_base_eff = o_is_mode ? i_rhs_base : i_lhs_base;
    assign ia_stride_eff = o_is_mode ? i_rhs_col_stride_b : i_lhs_row_stride_b;
    assign ia_zp_eff = o_is_mode ? i_rhs_zp : i_lhs_zp;
    assign ia_use_16bits_eff = ((p_ia_data_width > 8) && !o_is_mode) ? run_use_16bits : 1'b0;
    assign weight_base_eff = o_is_mode ? i_lhs_base : i_rhs_base;
    assign weight_stride_eff = o_is_mode ? i_lhs_row_stride_b : i_rhs_col_stride_b;
    assign weight_zp_eff = o_is_mode ? i_lhs_zp : i_rhs_zp;
    assign weight_use_16bits_eff = ((p_kernel_data_width > 8) && o_is_mode) ? run_use_16bits : 1'b0;
    assign ws_final_bias = p_frame_exec_enabled && !o_is_mode;
    assign compute_bias_sleep = o_frame_mode_q ? !frame_exec_init : bias_sleep;
    assign exec_stream_k = o_frame_mode_q ? frame_exec_rows : stream_k;
    assign exec_stream_m = o_frame_mode_q ? frame_exec_cols : stream_m;
    assign exec_n = o_frame_mode_q ? frame_command_k : run_n;
    assign exec_k = o_frame_mode_q ? (o_is_mode ? frame_exec_cols : frame_exec_rows) : run_k;
    assign exec_m = o_frame_mode_q ? (o_is_mode ? frame_exec_rows : frame_exec_cols) : run_m;
    assign exec_w = o_frame_mode_q ? 32'd1 : w_reuse_num_eff;
    assign exec_row_groups = o_frame_mode_q ? 32'd1 : i_cfg_row_groups;
    // 帧分块数量通过并行条件加一计算，配置接收周期保持不变。
    npu_frame_row_tiles #(.p_tile_size(p_size), .p_tile_shift(p_size_shift)) u_frame_row_tiles (
        .i_rows(frame_exec_rows), .o_tiles(exec_row_tiles)
    );
    assign exec_row_tail = o_frame_mode_q ? exec_row_tiles : i_cfg_row_tail_tiles;
    assign exec_col_groups = o_frame_mode_q ? 32'd1 : i_cfg_col_groups;
    assign exec_col_tail = o_frame_mode_q ? 32'd1 : i_cfg_col_tail_tiles;
    assign exec_channel = o_is_mode ? frame_exec_p0 : frame_exec_column;
        // 接收帧命令时保存三个地址的上下文，准备结果接收后启动计算控制器。
        assign frame_address_i_start = frame_command_start;
        assign frame_address_i_abort = i_abort_pending || cfg_start_event;
        assign frame_address_i_result_rdy = frame_command_active && o_ctrl_sa_ready && !i_abort_pending;
        assign frame_execute_start = frame_address_o_result_vld && frame_address_i_result_rdy;
        assign frame_address_i_p0 = frame_command_p0;
        assign frame_address_i_q0 = frame_command_q0;
        assign frame_address_i_column = frame_command_column;
        assign frame_address_i_total_depth = 32'(run_n);
        assign frame_address_i_ia_base = 32'(ia_base_eff);
        assign frame_address_i_ia_stride = 32'(ia_stride_eff);
        assign frame_address_i_ia_packed = o_is_mode ? i_run_rhs_tile_packed : i_run_lhs_tile_packed;
        assign frame_address_i_ia_s16 = ia_use_16bits_eff;
        assign frame_address_i_weight_base = 32'(weight_base_eff);
        assign frame_address_i_weight_stride = 32'(weight_stride_eff);
        assign frame_address_i_weight_packed = o_is_mode ? i_run_lhs_tile_packed : i_run_rhs_tile_packed;
        assign frame_address_i_weight_s16 = weight_use_16bits_eff;
        assign frame_address_i_dst_base = 32'(i_dst_base);
        assign frame_address_i_dst_stride = 32'(i_dst_row_stride_b);
        assign frame_address_i_is_mode = o_is_mode;
        assign frame_address_i_output_s16 = run_16x8;
        // 命令接收检查任务中止；配置接收时调度器空闲，没有有效帧命令。
        frame_address_prepare #(.p_size(p_size), .p_ready_mask_abort(1'b0)) u_frame_address (
            .clk(clk), .rst_n(rst_n), .i_start(frame_address_i_start), .i_abort(frame_address_i_abort),
            .o_start_rdy(frame_address_o_start_rdy), .i_result_rdy(frame_address_i_result_rdy),
            .o_result_vld(frame_address_o_result_vld),
            .i_p0(frame_address_i_p0), .i_q0(frame_address_i_q0), .i_column(frame_address_i_column),
            .i_total_depth(frame_address_i_total_depth),
            .i_ia_base(frame_address_i_ia_base), .i_ia_stride(frame_address_i_ia_stride),
            .i_ia_packed(frame_address_i_ia_packed), .i_ia_s16(frame_address_i_ia_s16),
            .i_weight_base(frame_address_i_weight_base), .i_weight_stride(frame_address_i_weight_stride),
            .i_weight_packed(frame_address_i_weight_packed), .i_weight_s16(frame_address_i_weight_s16),
            .i_dst_base(frame_address_i_dst_base), .i_dst_stride(frame_address_i_dst_stride),
            .i_is_mode(frame_address_i_is_mode), .i_output_s16(frame_address_i_output_s16),
            .o_ia_base(frame_address_o_ia_base), .o_weight_base(frame_address_o_weight_base),
            .o_dst_base(frame_address_o_dst_base)
        );
    assign exec_ia_base = o_frame_mode_q ? frame_address_o_ia_base : ia_base_eff;
    assign exec_weight_base = o_frame_mode_q ? frame_address_o_weight_base : weight_base_eff;
    // 偏置原始地址按六位并行检查，所有使用方复用完整位宽的非零结果。
    localparam int unsigned p_bias_zero_groups = (p_reg_width + 5) / 6;
    (* keep = 1 *) logic [p_bias_zero_groups-1:0] bias_nonzero_groups;
    logic bias_groups_zero;
    for (genvar group_index = 0; group_index < p_bias_zero_groups; group_index++) begin : g_bias_nonzero
        localparam int unsigned p_first = 6 * group_index;
        localparam int unsigned p_bits = p_reg_width-p_first < 6 ? p_reg_width-p_first : 6;
        logic group_zero;
        zero_reduce #(.p_width(p_bits)) u_group_zero (
            .i_value(i_bias_base[p_first +: p_bits]), .o_zero(group_zero)
        );
        assign bias_nonzero_groups[group_index] = !group_zero;
    end
    zero_reduce #(.p_width(p_bias_zero_groups)) u_bias_groups_zero (
        .i_value(bias_nonzero_groups), .o_zero(bias_groups_zero)
    );
    assign bias_base_nonzero = !bias_groups_zero;
    if (p_controller_bias_w == p_reg_width) begin : g_same_bias_width
        assign controller_bias_base_nonzero = bias_base_nonzero;
    end else begin : g_controller_bias_width
        localparam int unsigned p_groups = (p_controller_bias_w + 5) / 6;
        (* keep = 1 *) logic [p_groups-1:0] visible_nonzero_groups;
        logic visible_groups_zero;
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            localparam int unsigned p_first = 6 * group_index;
            localparam int unsigned p_bits = p_controller_bias_w-p_first < 6 ?
                p_controller_bias_w-p_first : 6;
            logic group_zero;
            zero_reduce #(.p_width(p_bits)) u_group_zero (
                .i_value(i_bias_base[p_first +: p_bits]), .o_zero(group_zero)
            );
            assign visible_nonzero_groups[group_index] = !group_zero;
        end
        zero_reduce #(.p_width(p_groups)) u_groups_zero (
            .i_value(visible_nonzero_groups), .o_zero(visible_groups_zero)
        );
        assign controller_bias_base_nonzero = !visible_groups_zero;
    end
    assign bias_execution_address_i_base = i_bias_base;
    assign bias_execution_address_i_channel = exec_channel;
    assign exec_bias_address = bias_execution_address_o_address;
    npu_bias_execution_address #(.p_base_width(p_reg_width)) u_bias_execution_address (
        .i_base(bias_execution_address_i_base), .i_channel(bias_execution_address_i_channel),
        .o_address(bias_execution_address_o_address)
    );
    assign exec_bias_base = o_frame_mode_q ?
            ((bias_base_nonzero && ((o_is_mode || ws_final_bias) ? frame_exec_final : frame_exec_init)) ?
                exec_bias_address : 32'd0) : i_bias_base;
    // 两种数据流的地址条件并行计算，模式选择在完整零值检查之后完成。
    npu_bias_address_zero #(.p_width(p_controller_bias_w)) u_bias_zero (
        .i_base(p_controller_bias_w'(i_bias_base)),
        .i_ws_channel(frame_exec_column), .i_is_channel(frame_exec_p0),
        .i_is_mode(o_is_mode), .o_zero(bias_zero_o_equal)
    );
    npu_bias_presence u_bias_presence (
        .i_frame_mode(o_frame_mode_q), .i_base_nonzero(bias_base_nonzero),
        .i_is_mode(o_is_mode), .i_ws_final_bias(ws_final_bias),
        .i_frame_final(frame_exec_final), .i_frame_init(frame_exec_init),
        .i_address_zero(bias_zero_o_equal),
        .i_visible_base_nonzero(controller_bias_base_nonzero), .o_present(exec_bias_present)
    );
        assign controller_i_bias_base = p_reg_width'(exec_bias_present);
    assign exec_dst_base = o_frame_mode_q ? frame_address_o_dst_base : i_dst_base;
    assign exec_q_mult = i_q_mult_pt +
            ((o_frame_mode_q && use_per_channel_eff) ? (exec_channel << 2) : 32'd0);
    assign exec_q_shift = i_q_shift_pt +
            ((o_frame_mode_q && use_per_channel_eff) ? (exec_channel << 2) : 32'd0);
    assign exec_init_requant = init_cfg_requant && (!o_frame_mode_q || frame_exec_final);
    assign exec_init_oa = init_cfg_oa && (!o_frame_mode_q || frame_exec_final);
    assign o_exec_dma_job_init = frame_dma_init_q || (init_cfg_ia && !o_frame_mode_q);
    assign exec_oa_complete = o_frame_mode_q ?
            (frame_command_active && frame_execution_started && (frame_compute_seen || partial_sum_calc_over) && (frame_store_seen || ps_frame_complete) &&
             (!frame_exec_final || frame_output_seen || (frame_output_armed && oa_calc_over))) : oa_calc_over;
        assign frame_command_ready = o_frame_mode_q && frame_address_o_start_rdy && ps_frame_ready && o_ctrl_sa_ready && !o_inner_done_valid && !i_abort_pending;
        assign frame_command_start = frame_command_valid && frame_command_ready;
        // 地址准备期间保持执行状态为空，计算完成信息只属于已经启动的当前帧。
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                frame_execution_started <= 1'b0;
            end else if (cfg_start_event || i_abort_pending || frame_command_start) begin
                frame_execution_started <= 1'b0;
            end else if (frame_execute_start) begin
                frame_execution_started <= 1'b1;
            end else if (!frame_command_active) begin
                frame_execution_started <= 1'b0;
            end
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                o_frame_mode_q <= 1'b0;
                frame_whole_rows_q <= 1'b0;
                frame_dma_init_q <= 1'b0;
                stationary_valid <= 1'b0; stationary_q0 <= '0; stationary_column <= '0; frame_stationary_hit <= 1'b0;
                frame_ps_accepted <= 1'b0; frame_compute_seen <= 1'b0; frame_store_seen <= 1'b0;
                frame_output_seen <= 1'b0; frame_output_armed <= 1'b0;
            end else begin
                frame_dma_init_q <= o_cfg_stage2_fire && use_frame_commands_s2 && !matrix_storage_invalid;
                if (o_cfg_stage2_fire) begin
                    o_frame_mode_q <= use_frame_commands_s2;
                    frame_whole_rows_q <= frame_slice_tiles_s2 == o_cfg_ia_reuse_q[2];
                    stationary_valid <= 1'b0;
                end else if (o_frame_mode_q && frame_execution_started && weight_commit) begin
                    stationary_valid <= 1'b1;
                    stationary_q0 <= frame_command_q0;
                    stationary_column <= frame_command_column;
                end
                if (frame_command_start) begin
                    frame_stationary_hit <= stationary_valid && stationary_q0 == frame_command_q0 &&
                                            stationary_column == frame_command_column;
                    frame_ps_accepted <= 1'b0; frame_compute_seen <= 1'b0; frame_store_seen <= 1'b0;
                    frame_output_seen <= 1'b0; frame_output_armed <= 1'b0;
                end else if (frame_command_active && frame_execution_started) begin
                    if (send_ia_trigger) frame_ps_accepted <= 1'b1;
                    if (partial_sum_calc_over) frame_compute_seen <= 1'b1;
                    if (ps_frame_complete) frame_store_seen <= 1'b1;
                    if (exec_init_oa) frame_output_armed <= 1'b1;
                    if (frame_output_armed && oa_calc_over) frame_output_seen <= 1'b1;
                end
            end
        end
        generate if (p_frame_exec_enabled) begin : g_frame_schedule
            ps_window_scheduler #(.SIZE(p_size), .FRAME_COUNT(p_ps_frame_count),
                                  .MAX_REUSE_TILES(IA_REUSE_NUM_MAX)) u_scheduler (
                .clk(clk), .rst_n(rst_n), .start(o_cfg_stage2_fire && use_frame_commands_s2),
                .stream_rows(o_cfg_stream_k_q[2]), .stationary_rows(o_cfg_stream_m_q[2]), .reduction(cfg_n_q[2]),
                .reuse_rows(o_cfg_ia_reuse_q[2]), .window_frames(o_cfg_w_reuse_q[2]),
                .slice_tiles(frame_slice_tiles_s2), .config_error(matrix_frame_config_error),
                .ready(o_frame_scheduler_ready), .done_valid(frame_scheduler_done),
                .done_ready(i_task_completion_accept && !i_run_vector), .err_code(frame_scheduler_error),
                .command_valid(frame_command_valid), .command_ready(frame_command_ready),
                .command_pressure(o_frame_mode_q && ps_frame_pressure),
                .command_complete(o_frame_mode_q && frame_command_active && o_inner_done_valid && o_inner_err_code == 0),
                .frame_id(frame_command_id), .p0(frame_command_p0), .q0(frame_command_q0),
                .column0(frame_command_column), .rows(frame_command_rows), .cols(frame_command_cols),
                .count_k(frame_command_k), .reserve_rows(frame_command_reserve),
                .frame_init(frame_command_init), .frame_final(frame_command_final),
                .command_active(frame_command_active),
                .lookahead_valid(frame_lookahead_valid), .lookahead_q0(frame_lookahead_q0),
                .lookahead_column(frame_lookahead_column), .lookahead_cols(frame_lookahead_cols),
                .lookahead_count_k(frame_lookahead_k));
        end else begin : g_no_frame_schedule
            assign o_frame_scheduler_ready = 1'b1;
            assign frame_scheduler_done = 1'b0; assign frame_scheduler_error = '0;
            assign frame_command_valid = 1'b0; assign frame_command_active = 1'b0;
            assign frame_command_id = '0; assign frame_command_p0 = '0; assign frame_command_q0 = '0;
            assign frame_command_column = '0; assign frame_command_rows = '0; assign frame_command_cols = '0;
            assign frame_command_k = '0; assign frame_command_reserve = '0;
            assign frame_command_init = 1'b0; assign frame_command_final = 1'b0;
            assign frame_lookahead_valid = 1'b0;
            assign frame_lookahead_q0 = 0; assign frame_lookahead_column = 0;
            assign frame_lookahead_cols = 0; assign frame_lookahead_k = 0;
        end endgenerate
        assign o_controller_done_valid = o_frame_mode_q ? frame_scheduler_done : o_inner_done_valid;
        assign o_controller_err_code = o_frame_mode_q ? frame_scheduler_error : o_inner_err_code;
    npu_controller #(
        .WEIGHT_WIDTH(p_kernel_data_width),
        .DATA_WIDTH  (p_ia_data_width),
        .SIZE        (p_size),
        .BUS_WIDTH   (p_bus_width),
        .REG_WIDTH   (p_reg_width)
    ) u_npu_controller (
        .clk              (clk),
        .rst_n            (rst_n),
        .calc_start       (ctrl_calc_start),
        .cfg_16bits_ia    (cfg_16bits_ia_eff | i_cfg_16x8),
        .cfg_dataflow_mode(i_cfg_dataflow_mode_eff),
        .cfg_tiling_error (matrix_config_invalid),
        .sa_ready         (o_ctrl_sa_ready),
        .partial_sum_calc_over(partial_sum_calc_over),
        .partial_sum_advance_ready(partial_sum_advance_ready),
        .tile_calc_over       (tile_calc_over),
            .init_cfg_ia          (init_cfg_ia),
        .init_cfg_weight      (init_cfg_weight),
        .init_cfg_bias        (init_cfg_bias),
        .init_cfg_requant     (init_cfg_requant),
        .init_cfg_oa          (init_cfg_oa),
        .use_16bits           (use_16bits),
        .lhs_base             (i_lhs_base),
        .rhs_base             (i_rhs_base),
        .dst_base             (i_dst_base),
        .bias_base            (controller_i_bias_base),
        .q_mult_pt            (i_q_mult_pt),
        .q_shift_pt           (i_q_shift_pt),
        .use_per_channel      (use_per_channel_eff),
        .k                    (i_k),
        .n                    (i_n),
        .m                    (i_m),
        .lhs_row_stride_b     (i_lhs_row_stride_b),
        .dst_row_stride_b     (i_dst_row_stride_b),
        .rhs_col_stride_b     (i_rhs_col_stride_b),
            // 输入加载器接口
            .send_ia_trigger      (send_ia_trigger),
            .ia_sending_done      (ia_sending_done),
            .ia_data_valid        (ia_data_valid),
            .ps_frame_ready       (ps_frame_ready),
                // 权重加载器接口
            .send_weight_trigger  (send_weight_trigger),
            .weight_commit(weight_commit),
        .weight_sending_done  (weight_sending_done),
        .weight_data_valid    (weight_data_valid),
        .weight_resident      (o_frame_mode_q && frame_stationary_hit),
            // 偏置加载器接口
            .bias_valid           (bias_group_valid),
            .bias_sleep           (bias_load_sleep),
            // 量化参数接口
            .quant_params_valid   ((quant_params_valid || (o_frame_mode_q && !frame_exec_final)) &&
                                   (!requant_output_group || requant_group_ready)),
        // 输出缓冲接口
        .fifo_full_flag       (fifo_full_flag && ia_output_pending),
            // 输出写回接口
            .oa_calc_over         (exec_oa_complete),
        // 任务完成握手接口
        .done_valid             (o_inner_done_valid),
        .done_ready             (o_frame_mode_q || (i_task_completion_accept && !i_run_vector)),
        .err_code             (o_inner_err_code)
    );
        // 输入加载器
            ia_loader #(
                .DATA_WIDTH  (p_ia_data_width),
                .SIZE        (p_size),
                .BUS_WIDTH   (p_bus_width),
                .DMA_LANES   (p_matrix_input_lanes),
                .REG_WIDTH   (p_reg_width),
                .COUNT_WIDTH (DIM_COUNT_WIDTH),
                .CACHE_BLOCKS(p_ia_max_cache_blocks),
                .COMPACT_S8(p_ia_compact_enable),
                .ORDERED_JOB(1'b1),
                .p_register_dma_request(1'b1),
                // 输入来自双模式 DMA，使用其固定的列位置和有效通道排列。
                .p_dma_source_layout(1'b1),
                .p_shared_write_stage(p_shared_ram_enabled && p_fixed_ps_channels),
                // 共享 RAM 逐字节使用写掩码，未写入字节可传递共用排列数据。
                .p_zero_masked_write_data(!(p_shared_ram_enabled && p_fixed_ps_channels)),
                .RAM_WORD_ADDR_WIDTH(p_shared_ia_addr_width),
                .PS_FRAME_COUNT(p_ps_frame_count)
            ) u_ia_loader (
        .clk             (clk),
        .rst_n           (rst_n),
        .init_cfg        (init_cfg_ia),
        .cfg_im2col(i_run_conv && !o_is_mode),
        .cfg_tile_packed(o_is_mode ? i_run_rhs_tile_packed : i_run_lhs_tile_packed),
        .cfg_compact(o_run_compact),
        .cfg_compact_offset(run_compact_offset),
        .cfg_cache_blocks(active_ia_cache_blocks),
        .cfg_preserve_cache(o_frame_mode_q),
        .cfg_prefetch_enable(p_frame_prefetch_enable && o_frame_mode_q && frame_whole_rows_q),
        .cfg_global_reduction(run_n),
        .prefetch_idle(o_ia_prefetch_idle),
        .cache_flush(i_operand_loader_flush_q),
        .cfg_p0_base(o_frame_mode_q ? frame_command_p0 : 32'd0),
        .cfg_q0_base(o_frame_mode_q ? frame_command_q0 : 32'd0),
        .cfg_cache_slot_base(o_frame_mode_q ? 32'(frame_cache_slot_base_q) : 32'd0),
        .load_ia_req     (o_load_ia_req),
        .load_ia_granted (i_load_ia_granted),
            .send_ia_trigger (send_ia_trigger),
            .k               (exec_stream_k),
            .n               (exec_n),
            .m               (exec_stream_m),
        .lhs_zp          (ia_zp_eff),
        .lhs_row_stride_b(ia_stride_eff),
        .lhs_base        (exec_ia_base),
        .use_16bits      (ia_use_16bits_eff),
        .bias_by_row_mode(o_is_mode),
        .bias_at_end(ws_final_bias),
        .ia_reuse_num    (o_ia_reuse_num_eff),
            .w_reuse_num     (exec_w),
        .row_groups (exec_row_groups),
        .row_tail_tiles (exec_row_tail),
        .col_groups (exec_col_groups),
        .col_tail_tiles (exec_col_tail),
            .ext_dma_start(o_ia_dma_start),
            .ext_dma_is_write(),
            .ext_dma_linear_read_mode(o_ia_dma_linear_read_mode),
            .ext_dma_im2col(o_ia_dma_im2col),
            .ext_dma_p0(o_ia_dma_p0),
            .ext_dma_q0(o_ia_dma_q0),
            .ext_dma_group(o_ia_dma_group),
            .ext_dma_base_addr(o_ia_dma_base_addr),
            .ext_dma_row_stride(o_ia_dma_row_stride),
            .ext_dma_rows_to_read(o_ia_dma_rows_to_read),
            .ext_dma_burst_len_m1(o_ia_dma_burst_len_m1),
            .ext_dma_slot_id(o_ia_dma_slot_id),
            .ext_dma_use_16bits(o_ia_dma_use_16bits),
            .ext_dma_lhs_zp(o_ia_dma_lhs_zp),
            .ext_dma_busy(i_ia_dma_busy),
            .ext_dma_done(i_ia_dma_done),
            .ext_dma_wr_slot(i_ia_dma_wr_slot),
            .ext_dma_wr_row(i_ia_dma_wr_row),
            .ext_dma_wr_col_base(i_ia_dma_wr_col_base),
            .ext_dma_wr_data(i_ia_dma_wr_data),
            .ext_dma_wr_valid(i_ia_dma_wr_valid),
            .ext_dma_wr_use_16bits(i_ia_dma_wr_use_16bits),
            .ram_port_wr_en(o_ia_ram_write_en), .ram_port_wr_addr(o_ia_ram_write_addr),
            .ram_port_wr_data(o_ia_ram_write_data), .ram_port_wr_mask(o_ia_ram_write_mask),
            .ram_shared_wr_data(o_ia_ram_shared_write_data),
            .ram_port_rd_en(o_ia_ram_read_en), .ram_port_rd_addr(o_ia_ram_read_addr),
            .ram_port_rd_data(i_ia_ram_read_data),
        .ia_sending_done(ia_sending_done),
        .ia_row_valid   (ia_row_valid),
        .ia_tile_start  (ia_tile_start),
        .ia_is_init_data(ia_is_init_data),
            .ia_calc_done   (ia_calc_done),
            .ia_out         (ia_out),
            .ia_data_valid  (ia_data_valid),
            .ps_frame_id(loader_frame_id),
            .ps_frame_rows  (ps_frame_rows),
            .ps_frame_init  (ps_frame_init),
            .ps_frame_final (ps_frame_final),
            .ia_output_pending(ia_output_pending),
            .bias_sleep     (bias_sleep),
            .bias_load_sleep(bias_load_sleep),
        .bias_switch    (bias_switch),
        .bias_last_loop (bias_last_loop),
        .ia_l1_switch   (ia_l1_switch)
    );
        // 权重预取使用当前任务配置，地址计算逐级寄存后送入加载器。

        generate if (p_frame_prefetch_enable) begin : g_weight_prediction
            wire packed_weights = o_is_mode ? i_run_lhs_tile_packed : i_run_rhs_tile_packed;
            wire [31:0] depth_tiles = (run_n + 32'(p_size-1)) >> p_size_shift;
            wire [31:0] factor_a = packed_weights ? frame_lookahead_column >> p_size_shift :
                                                      frame_lookahead_column;
            wire [31:0] factor_b = packed_weights ? depth_tiles : weight_stride_eff;
            wire [31:0] depth_offset = packed_weights ?
                ((frame_lookahead_q0 >> p_size_shift) << (2*p_size_shift + 32'(weight_use_16bits_eff))) :
                (frame_lookahead_q0 << weight_use_16bits_eff);
            wire same_prediction;
            // 两个完整坐标按组比较，预测接收资格只组合最终的一位结果。
            parallel_equal #(.p_width(64)) u_prediction_equal (
                .i_a({frame_lookahead_column, frame_lookahead_q0}),
                .i_b({frame_command_column, frame_command_q0}), .o_equal(same_prediction)
            );
            wire prediction_start = o_frame_mode_q && frame_command_active && frame_execution_started &&
                frame_lookahead_valid && !same_prediction;
            logic [31:0] product_low;
            logic [15:0] product_lh, product_hl;
            logic [15:0] product_high;
            logic [15:0] product_low_half;
            logic [31:0] relative_address;
            // 同一字段按流水阶段保存，阶段使能控制各数组元素的更新。
            logic [31:0] offset_q [2];
            logic [31:0] base_q [3];
            logic [31:0] relative_address_sum, prefetch_address_sum;
            logic packed_q [2];
            logic wide_q [2];
            // 相对地址和基地址分处两个寄存阶段，每个阶段独立完成一次加法。
            assign relative_address_sum = (packed_q[1] ?
                ({product_high,product_low_half} << (2*p_size_shift + 32'(wide_q[1]))) :
                {product_high,product_low_half}) + offset_q[1];
            assign prefetch_address_sum = base_q[2] + relative_address;
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    weight_prediction_valid <= '0;
                    frame_command_sequence <= '0;
                end else begin
                    if (frame_command_start) frame_command_sequence <= frame_command_sequence + 1'b1;
                    if (cfg_start_event || !frame_command_active || !frame_execution_started) weight_prediction_valid <= '0;
                    else weight_prediction_valid <= {weight_prediction_valid[2:0], prediction_start};
                end
            end
            always_ff @(posedge clk) begin
                if (prediction_start) begin
                    product_low <= factor_a[15:0] * factor_b[15:0];
                    product_lh <= factor_a[15:0] * factor_b[31:16];
                    product_hl <= factor_a[31:16] * factor_b[15:0];
                    offset_q[0] <= depth_offset;
                    base_q[0] <= weight_base_eff;
                    packed_q[0] <= packed_weights;
                    wide_q[0] <= weight_use_16bits_eff;
                    weight_prediction[0] <= '{p0:frame_lookahead_column, q0:frame_lookahead_q0,
                        rows:frame_lookahead_cols, cols:frame_lookahead_k,
                        sequence_id:frame_command_sequence};
                end
                if (weight_prediction_valid[0]) begin
                    product_high <= product_low[31:16] + product_lh + product_hl;
                    product_low_half <= product_low[15:0];
                    offset_q[1] <= offset_q[0];
                    base_q[1] <= base_q[0];
                    packed_q[1] <= packed_q[0];
                    wide_q[1] <= wide_q[0];
                    weight_prediction[1] <= weight_prediction[0];
                end
                if (weight_prediction_valid[1]) begin
                    relative_address <= relative_address_sum;
                    base_q[2] <= base_q[1];
                    weight_prediction[2] <= weight_prediction[1];
                end
                if (weight_prediction_valid[2]) begin
                    weight_prefetch_base <= prefetch_address_sum;
                    weight_prediction[3] <= weight_prediction[2];
                end
            end
            assign weight_prefetch_valid = frame_command_active && frame_execution_started && weight_prediction_valid[3] &&
                weight_prediction[3].sequence_id == frame_command_sequence;
        end else begin : g_no_weight_prediction
            assign weight_prediction_valid = '0;
            assign frame_command_sequence = '0;
            assign weight_prefetch_valid = 1'b0;
            assign weight_prefetch_base = '0;
            for (genvar stage=0; stage<4; stage++) assign weight_prediction[stage] = '0;
        end endgenerate
        // 权重加载器
            kernel_loader #(
                .DATA_WIDTH(p_kernel_data_width),
                .SIZE      (p_size),
                .BUS_WIDTH (p_bus_width),
                .DMA_LANES (p_matrix_input_lanes),
                .REG_WIDTH (p_reg_width),
                .COUNT_WIDTH(DIM_COUNT_WIDTH)
            ) u_kernel_loader (
        .clk                (clk),
        .rst_n              (rst_n),
        .init_cfg           (init_cfg_weight && !(o_frame_mode_q && frame_stationary_hit)),
        .cfg_command_mode   (p_frame_prefetch_enable && o_frame_mode_q),
        .cache_flush        (i_operand_loader_flush_q),
        .prefetch_valid     (weight_prefetch_valid),
        .prefetch_base_addr (weight_prefetch_base),
        .prefetch_p0        (weight_prediction[3].p0),
        .prefetch_q0        (weight_prediction[3].q0),
        .prefetch_rows      (weight_prediction[3].rows),
        .prefetch_valid_cols(weight_prediction[3].cols),
        .prefetch_idle      (o_kernel_prefetch_idle),
        .o_prefetch_quiescent(kernel_loader_o_quiescent),
        .o_admission_request(kernel_loader_o_admission_request),
        .cfg_im2col          (i_run_conv && o_is_mode),
        .cfg_tile_packed     (o_is_mode ? i_run_lhs_tile_packed : i_run_rhs_tile_packed),
        .cfg_p0_base         (o_frame_mode_q ? frame_command_column : 32'd0),
        .cfg_q0_base         (o_frame_mode_q ? frame_command_q0 : 32'd0),
        .load_weight_req    (o_load_weight_req),
        .load_weight_granted(i_load_weight_granted),
            .send_weight_trigger(send_weight_trigger),
            .k                  (exec_stream_k),
            .n                  (exec_n),
            .m                  (exec_stream_m),
        .rhs_zp             (weight_zp_eff),
        .rhs_base           (exec_weight_base),
        .rhs_row_stride_b   (weight_stride_eff),
        .ia_reuse_num       (o_ia_reuse_num_eff),
        .w_reuse_num        (exec_w),
        .row_groups (exec_row_groups),
        .row_tail_tiles (exec_row_tail),
        .col_groups (exec_col_groups),
        .col_tail_tiles (exec_col_tail),
            .use_16bits         (weight_use_16bits_eff),
            .ext_dma_start(o_kernel_dma_start),
            .ext_dma_is_write(),
            .ext_dma_linear_read_mode(o_kernel_dma_linear_read_mode),
            .ext_dma_im2col(o_kernel_dma_im2col),
            .ext_dma_p0(o_kernel_dma_p0),
            .ext_dma_q0(o_kernel_dma_q0),
            .ext_dma_group(o_kernel_dma_group),
            .ext_dma_base_addr(o_kernel_dma_base_addr),
            .ext_dma_row_stride(o_kernel_dma_row_stride),
            .ext_dma_rows_to_read(o_kernel_dma_rows_to_read),
            .ext_dma_burst_len_m1(o_kernel_dma_burst_len_m1),
            .ext_dma_slot_id(o_kernel_dma_slot_id),
            .ext_dma_use_16bits(o_kernel_dma_use_16bits),
            .ext_dma_lhs_zp(o_kernel_dma_lhs_zp),
            .ext_dma_busy(i_kernel_dma_busy),
            .ext_dma_done(i_kernel_dma_done),
            .ext_dma_wr_slot(i_kernel_dma_wr_slot),
            .ext_dma_wr_row(i_kernel_dma_wr_row),
            .ext_dma_wr_col_base(i_kernel_dma_wr_col_base),
            .ext_dma_wr_data(i_kernel_dma_wr_data),
            .ext_dma_wr_valid(i_kernel_dma_wr_valid),
        .weight_sending_done(weight_sending_done),
        .load_weight_done   (load_weight_done),
        .store_weight_req   (store_weight_req),
        .weight_out         (weight_out),
        .weight_data_valid  (weight_data_valid)
    );
        // 偏置加载器
        bias_loader #(
            .SIZE      (p_size),
            .DATA_WIDTH(32),
                .BUS_WIDTH (p_bus_width),
                .REG_WIDTH (p_reg_width),
                .COUNT_WIDTH(DIM_COUNT_WIDTH),
                .GROUP_BLOCKS_MAX(BIAS_GROUP_BLOCKS_MAX)
            ) u_bias_loader (
        .clk              (clk),
        .rst_n            (rst_n),
        .init_cfg         (init_cfg_bias),
        .load_bias_req    (o_load_bias_req),
            .load_bias_granted(i_load_bias_granted),
            .bias_base        (exec_bias_base),
            .k                (exec_k),
            .m                (exec_m),
            .bias_step_blocks (o_is_mode ? o_ia_reuse_num_eff : p_reg_width'(1)),
        .bias_switch      (bias_switch),
        .bias_sleep       (bias_load_sleep),
        .bias_last_loop   (bias_last_loop),
            .bias_valid       (bias_valid),
            .bias_group_valid (bias_group_valid),
            .load_bias_done   (load_bias_done),
            .is_mode          (o_is_mode),
            .group_read_idx   (is_bias_read_idx),
            .group_read_start (o_is_mode && send_ia_trigger && !bias_sleep),
            .data_out         (bias_data_out),
            .group_data_scalar(bias_group_scalar),
                .ext_dma_start    (o_bias_dma_start),
                .ext_dma_is_write (),
            .ext_dma_linear_read_mode(o_bias_dma_linear_read_mode),
            .ext_dma_base_addr(o_bias_dma_base_addr),
            .ext_dma_row_stride(o_bias_dma_row_stride),
            .ext_dma_rows_to_read(o_bias_dma_rows_to_read),
            .ext_dma_burst_len_m1(o_bias_dma_burst_len_m1),
            .ext_dma_slot_id  (o_bias_dma_slot_id),
            .ext_dma_use_16bits(o_bias_dma_use_16bits),
            .ext_dma_lhs_zp   (o_bias_dma_lhs_zp),
            .ext_dma_busy     (i_bias_dma_busy),
            .ext_dma_done     (i_bias_dma_done),
            .ext_dma_wr_slot  (i_bias_dma_wr_slot),
            .ext_dma_wr_row   (i_bias_dma_wr_row),
            .ext_dma_wr_col_base(i_bias_dma_wr_col_base),
            .ext_dma_wr_data  (i_bias_dma_wr_data),
            .ext_dma_wr_valid (i_bias_dma_wr_valid),
            .ext_dma_wr_use_16bits(i_bias_dma_wr_use_16bits)
        );
  // 脉动阵列计算核心
    assign capture_compute_bias = !o_is_mode && bias_base_nonzero &&
                              ia_tile_start && !(ws_final_bias ? bias_load_sleep : compute_bias_sleep);
    // 偏置来源和同步清零共用数据选择，两组寄存器分别保存自己的写入使能。
    for (genvar bias_lane = 0; bias_lane < p_size; bias_lane++) begin : g_bias_capture
        always_comb begin
            bias_capture_data[bias_lane] = bias_group_valid ?
                bias_data_out[bias_lane] : bias_data_hold[bias_lane];
            if (init_cfg_bias) bias_capture_data[bias_lane] = '0;
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                bias_data_hold[bias_lane] <= '0;
                compute_bias_latched[bias_lane] <= '0;
            end else begin
                if (init_cfg_bias || bias_group_valid)
                    bias_data_hold[bias_lane] <= bias_capture_data[bias_lane];
                if (init_cfg_bias || capture_compute_bias)
                    compute_bias_latched[bias_lane] <= bias_capture_data[bias_lane];
            end
        end
    end
  genvar cb_i;
  generate
    for (cb_i = 0; cb_i < p_size; cb_i = cb_i + 1) begin : gen_compute_bias_in
      assign compute_bias_in[cb_i] =
        (o_is_mode || ws_final_bias || !bias_base_nonzero) ? 32'sd0 : compute_bias_latched[cb_i];
    end
  endgenerate
    compute_core #(
        .SIZE          (p_size),
        .DATA_WIDTH    (p_ia_data_width),
        .WEIGHT_WIDTH  (p_kernel_data_width),
        .PS_FRAME_COUNT(p_ps_frame_count),
        .MAX_IA_REUSE  (IA_REUSE_NUM_MAX),
        .PS_STORAGE_ROWS(p_ps_storage_rows),
        .PS_EXTERNAL_RAM(int'(p_shared_ram_enabled)),
        .p_fixed_ps_channels(p_shared_ram_enabled && p_fixed_ps_channels),
        .PS_POOL_BYTES(p_shared_ram_enabled ? p_shared_total_bytes - p_shared_bank_bytes : `GEMMORA_PS_POOL_BYTES),
        .PS_BANK_BYTES(p_shared_bank_bytes),
        .PS_DIRECTORY_ROWS(p_shared_ram_enabled ? p_shared_ps_directory_rows : p_ps_frame_count * IA_REUSE_NUM_MAX * p_size),
        .PS_RAM_ADDR_BITS(p_shared_ps_addr_width)
    ) u_compute_core (
        .ps_store_cfg_valid(p_shared_ram_enabled && o_cfg_stage2_fire && !o_shared_allocation_invalid),
        .ps_pool_bank_words(active_ps_bank_depth),
        .ps_pool_bank_count(active_ps_bank_count),
        .ps_directory_stride(32'(ps_admission_rows)),
        .ps_ram_read_en(o_ps_ram_read_en), .ps_ram_read_addr(o_ps_ram_read_addr), .ps_ram_read_data(i_ps_ram_read_data),
        .ps_ram_write_en(o_ps_ram_write_en), .ps_ram_write_addr(o_ps_ram_write_addr), .ps_ram_write_data(o_ps_ram_write_data),
        .ps_capacity_fault(o_ps_capacity_fault),
        .ps_frame_request((o_frame_mode_q ? (frame_command_valid || (frame_command_active && !frame_ps_accepted)) : ia_data_valid) && !i_abort_pending),
        .ps_frame_id(o_frame_mode_q ? frame_command_id : p_ps_frame_id_w'(loader_frame_id)),
        .ps_frame_reserve_rows(o_frame_mode_q ? frame_command_reserve : 32'd0),
        .ps_frame_word_cap((o_frame_mode_q ? frame_command_final : ps_frame_final) ? 3'd4 : ps_word_cap_q),
        .ps_frame_pressure(ps_frame_pressure),
        .ps_frame_complete(ps_frame_complete),
        .ps_force_raw(ps_force_raw_q),
        .ps_frame_rows   (o_frame_mode_q ? frame_command_rows : ps_frame_rows),
        .ps_frame_init   (o_frame_mode_q ? frame_command_init : ps_frame_init),
        .ps_frame_final  (o_frame_mode_q ? frame_command_final : ps_frame_final),
        .ps_frame_ready  (ps_frame_ready),
        .clk             (clk),
        .rst_n           (rst_n),
        .store_weight_req(store_weight_req),
        .weight_commit(weight_commit),
        .weight_in       (weight_out),
        .ia_vec_in       (ia_out),
        .ia_row_valid    (ia_row_valid),
        .final_output_overlap(!o_is_mode && !use_per_channel_eff),
        .direct_final_stream(direct_final_stream),
        .active_columns  (($clog2(p_size)+1)'((stream_m > p_reg_width'(p_size)) ? p_reg_width'(p_size) : stream_m)),
        .ia_tile_start   (ia_tile_start),
        .ia_calc_done    (o_frame_mode_q ? frame_command_final : ia_calc_done),
        .ia_is_init_data (o_frame_mode_q ? frame_command_init : ia_is_init_data),
        .ia_l1_switch    (o_frame_mode_q ? ia_sending_done : ia_l1_switch),
        .ia_sending_done (ia_sending_done),
        .send_ia_trigger (send_ia_trigger),
        .bias_sleep      (compute_bias_sleep),
        .bias_in         (compute_bias_in),
        .acc_data_out    (acc_data_out),
        .acc_data_valid  (acc_data_valid),
        .partial_sum_calc_over(partial_sum_calc_over),
        .partial_sum_advance_ready(partial_sum_advance_ready),
        .tile_calc_over  (tile_calc_over)
    );
    npu_task_configuration #(
        .p_bus_width(p_bus_width),
        .p_data_width(p_data_width),
        .p_dim_count_width(DIM_COUNT_WIDTH),
        .p_enable_is_mode(p_enable_is_mode),
        .p_enable_per_channel(p_enable_per_channel),
        .p_frame_exec_enabled(p_frame_exec_enabled),
        .p_ia_cache_blocks(p_ia_cache_blocks),
        .p_ia_compact_enable(p_ia_compact_enable),
        .p_ia_data_width(p_ia_data_width),
        .p_ia_reuse_num_max(IA_REUSE_NUM_MAX),
        .p_ia_reuse_w(IA_REUSE_W),
        .p_is_bias_valid_w(IS_BIAS_VALID_W),
        .p_kernel_data_width(p_kernel_data_width),
        .p_oa_fifo_banks(OA_FIFO_BANKS),
        .p_oa_s16_fifo_banks(OA_S16_FIFO_BANKS),
        .p_ps_frame_count_width(PS_FRAME_COUNT_WIDTH),
        .p_ps_required_width(PS_REQUIRED_WIDTH),
        .p_ps_row_count_width(PS_ROW_COUNT_WIDTH),
        .p_ps_storage_rows(p_ps_storage_rows),
        .p_reg_width(p_reg_width),
        .p_shared_bank_bytes(p_shared_bank_bytes),
        .p_shared_physical_banks(p_shared_physical_banks),
        .p_shared_physical_banks_width(p_shared_physical_banks_width),
        .p_shared_ps_directory_rows(p_shared_ps_directory_rows),
        .p_shared_ram_enabled(p_shared_ram_enabled),
        .p_shared_total_bytes(p_shared_total_bytes),
        .p_size(p_size),
        .p_size_shift(p_size_shift),
        .p_vector_shared_ia_banks(p_vector_shared_ia_banks),
        .p_w_reuse_num_max(W_REUSE_NUM_MAX),
        .p_w_reuse_w(W_REUSE_W)
    ) u_task_configuration (
        .i_bias_base(i_bias_base),
        .i_cfg_16bits_ia(i_cfg_16bits_ia),
        .i_cfg_16x8(i_cfg_16x8),
        .i_cfg_col_groups(i_cfg_col_groups),
        .i_cfg_col_tail_tiles(i_cfg_col_tail_tiles),
        .i_cfg_conv(i_cfg_conv),
        .i_cfg_conv_enable(i_cfg_conv_enable),
        .i_cfg_dataflow_mode(i_cfg_dataflow_mode),
        .i_cfg_dataflow_mode_eff(i_cfg_dataflow_mode_eff),
        .i_cfg_ia_reuse_num(i_cfg_ia_reuse_num),
        .i_cfg_rhs_tile_packed(i_cfg_rhs_tile_packed),
        .i_cfg_row_groups(i_cfg_row_groups),
        .i_cfg_row_tail_tiles(i_cfg_row_tail_tiles),
        .i_cfg_shared_ia_banks(i_cfg_shared_ia_banks),
        .i_cfg_start_event(cfg_start_event),
        .i_cfg_w_reuse_num(i_cfg_w_reuse_num),
        .clk(clk),
        .i_conv_cfg_q(i_conv_cfg_q),
        .rst_n(rst_n),
        .i_ctrl_sa_ready(o_ctrl_sa_ready),
        .i_dst_base(i_dst_base),
        .i_dst_row_stride_b(i_dst_row_stride_b),
        .i_frame_mode_q(o_frame_mode_q),
        .i_frame_scheduler_ready(o_frame_scheduler_ready),
        .i_k(i_k),
        .i_lhs_base(i_lhs_base),
        .i_lhs_row_stride_b(i_lhs_row_stride_b),
        .i_lhs_zp(i_lhs_zp),
        .i_m(i_m),
        .i_n(i_n),
        .i_ps_control_q(i_ps_control_q),
        .i_q_mult_pt(i_q_mult_pt),
        .i_q_shift_pt(i_q_shift_pt),
        .i_rhs_base(i_rhs_base),
        .i_rhs_col_stride_b(i_rhs_col_stride_b),
        .i_rhs_zp(i_rhs_zp),
        .i_run_conv(i_run_conv),
        .i_run_lhs_tile_packed(i_run_lhs_tile_packed),
        .i_run_rhs_tile_packed(i_run_rhs_tile_packed),
        .i_use_per_channel(i_use_per_channel),
        .i_use_per_channel_eff(use_per_channel_eff),
        .i_vector_start_fire(i_vector_start_fire),
        .o_active_ia_cache_blocks(active_ia_cache_blocks),
        .o_active_ps_bank_count(active_ps_bank_count),
        .o_active_ps_bank_depth(active_ps_bank_depth),
        .o_cfg_16bits_ia_eff(cfg_16bits_ia_eff),
        .o_cfg_16x8_q(o_cfg_16x8_q),
        .o_cfg_ia_reuse_q(o_cfg_ia_reuse_q),
        .o_cfg_n_q(cfg_n_q),
        .o_cfg_stage2_fire(o_cfg_stage2_fire),
        .o_cfg_stream_k_q(o_cfg_stream_k_q),
        .o_cfg_stream_m_q(o_cfg_stream_m_q),
        .o_cfg_use16_q(o_cfg_use16_q),
        .o_cfg_valid_q(o_cfg_valid_q),
        .o_cfg_w_reuse_q(o_cfg_w_reuse_q),
        .o_conv_range_base(o_conv_range_base),
        .o_conv_range_end(o_conv_range_end),
        .o_direct_output_cfg(direct_output_cfg),
        .o_frame_config_error(frame_config_error),
        .o_frame_slice_tiles_s2(frame_slice_tiles_s2),
        .o_ia_reuse_num_eff(o_ia_reuse_num_eff),
        .o_is_bias_group_rows_target(is_bias_group_rows_target),
        .o_oa_chunk_cols_pre(oa_chunk_cols_pre),
        .o_oa_is_coalesce_pre(oa_is_coalesce_pre),
        .o_oa_ws_coalesce_pre(oa_ws_coalesce_pre),
        .o_output_reserve_banks(output_reserve_banks),
        .o_output_s16_ready_threshold(output_s16_ready_threshold),
        .o_output_s16_reserve_banks(output_s16_reserve_banks),
        .o_output_s8_ready_threshold(output_s8_ready_threshold),
        .o_ps_admission_rows(ps_admission_rows),
        .o_ps_force_raw_q(ps_force_raw_q),
        .o_ps_word_cap_q(ps_word_cap_q),
        .o_run_16x8(run_16x8),
        .o_run_compact(o_run_compact),
        .o_run_compact_offset(run_compact_offset),
        .o_run_is_mode(run_is_mode),
        .o_run_k(run_k),
        .o_run_m(run_m),
        .o_run_n(run_n),
        .o_run_use_16bits(run_use_16bits),
        .o_shared_allocation_invalid(o_shared_allocation_invalid),
        .o_shared_ia_banks_q(o_shared_ia_banks_q),
        .o_stream_k(stream_k),
        .o_stream_m(stream_m),
        .o_tiling_invalid(tiling_invalid),
        .o_use_frame_commands_s2(use_frame_commands_s2),
        .o_w_reuse_num_eff(w_reuse_num_eff)
    );
    npu_output_pipeline #(
        .p_bus_width(p_bus_width),
        .p_dim_count_width(DIM_COUNT_WIDTH),
        .p_dw_shared_quant_enable(p_dw_shared_quant_enable),
        .p_enable_is_mode(p_enable_is_mode),
        .p_enable_per_channel(p_enable_per_channel),
        .p_ia_reuse_num_max(IA_REUSE_NUM_MAX),
        .p_is_bias_row_w(IS_BIAS_ROW_W),
        .p_is_bias_valid_w(IS_BIAS_VALID_W),
        .p_oa_fifo_banks(OA_FIFO_BANKS),
        .p_oa_s16_fifo_banks(OA_S16_FIFO_BANKS),
        .p_reg_width(p_reg_width),
        .p_requant_max_ia_reuse(REQUANT_MAX_IA_REUSE),
        .p_size(p_size),
        .p_requant_compute_lanes(p_requant_compute_lanes),
        .p_s16_reserve_width(p_s16_reserve_width),
        .p_s8_reserve_width(p_s8_reserve_width)
    ) u_output_pipeline (
        .i_acc_data_out(acc_data_out),
        .i_acc_data_valid(acc_data_valid),
        .i_act_max(i_act_max),
        .i_act_min(i_act_min),
        .i_bias_base(i_bias_base),
        .i_bias_group_scalar(bias_group_scalar),
        .i_bias_sleep(bias_sleep),
        .i_bias_switch(bias_switch),
        .i_cfg_dataflow_mode_eff(i_cfg_dataflow_mode_eff),
        .clk(clk),
        .i_compute_bias_latched(compute_bias_latched),
        .rst_n(rst_n),
        .i_direct_output_cfg(direct_output_cfg),
        .i_dst_row_stride_b(i_dst_row_stride_b),
        .i_dst_zp(i_dst_zp),
        .i_dw_quant_accumulator(i_dw_quant_accumulator),
        .i_dw_quant_mask(i_dw_quant_mask),
        .i_dw_quant_maximum(i_dw_quant_maximum),
        .i_dw_quant_minimum(i_dw_quant_minimum),
        .i_dw_quant_multiplier(i_dw_quant_multiplier),
        .i_dw_quant_offset(i_dw_quant_offset),
        .i_dw_quant_req_tag(i_dw_quant_req_tag),
        .i_dw_quant_req_valid(i_dw_quant_req_valid),
        .i_dw_quant_right(i_dw_quant_right),
        .i_exec_dst_base(exec_dst_base),
        .i_exec_init_oa(exec_init_oa),
        .i_exec_init_requant(exec_init_requant),
        .i_exec_k(exec_k),
        .i_exec_m(exec_m),
        .i_exec_q_mult(exec_q_mult),
        .i_exec_q_shift(exec_q_shift),
        .i_exec_stream_k(exec_stream_k),
        .i_exec_stream_m(exec_stream_m),
        .i_frame_mode_q(o_frame_mode_q),
        .i_ia_reuse_num_eff(o_ia_reuse_num_eff),
        .i_init_cfg_ia(init_cfg_ia),
        .i_init_cfg_oa(init_cfg_oa),
        .i_is_bias_group_rows_target(is_bias_group_rows_target),
        .i_is_mode(o_is_mode),
        .i_load_quant_granted(i_load_quant_granted),
        .i_oa_chunk_cols_pre(oa_chunk_cols_pre),
        .i_oa_dma_busy(i_oa_dma_busy),
        .i_oa_dma_done(i_oa_dma_done),
        .i_oa_dma_src_wready(i_oa_dma_src_wready),
        .i_oa_is_coalesce_pre(oa_is_coalesce_pre),
        .i_oa_ws_coalesce_pre(oa_ws_coalesce_pre),
        .i_output_reserve_banks(output_reserve_banks),
        .i_output_s16_ready_threshold(output_s16_ready_threshold),
        .i_output_s16_reserve_banks(output_s16_reserve_banks),
        .i_output_s8_ready_threshold(output_s8_ready_threshold),
        .i_ps_capacity_fault(o_ps_capacity_fault),
        .i_quant_dma_raw_data(i_quant_dma_raw_data),
        .i_quant_dma_raw_valid(i_quant_dma_raw_valid),
        .i_requant_group_rows(requant_group_rows),
        .i_requant_group_start(requant_group_start),
        .i_run_16x8(run_16x8),
        .i_run_vector(i_run_vector),
        .i_send_ia_trigger(send_ia_trigger),
        .i_tile_calc_over(tile_calc_over),
        .i_use_per_channel_eff(use_per_channel_eff),
        .i_write_oa_granted(i_write_oa_granted),
        .i_ws_final_bias(ws_final_bias),
        .o_direct_final_stream(direct_final_stream),
        .o_dw_quant_req_ready(o_dw_quant_req_ready),
        .o_dw_quant_rsp_tag(o_dw_quant_rsp_tag),
        .o_dw_quant_rsp_valid(o_dw_quant_rsp_valid),
        .o_fifo_full_flag(fifo_full_flag),
        .o_is_bias_read_idx(is_bias_read_idx),
        .o_load_quant_req(o_load_quant_req),
        .o_oa_calc_over(oa_calc_over),
        .o_oa_dma_base_addr(o_oa_dma_base_addr),
        .o_oa_dma_burst_len_m1(o_oa_dma_burst_len_m1),
        .o_oa_dma_row_stride(o_oa_dma_row_stride),
        .o_oa_dma_rows_to_read(o_oa_dma_rows_to_read),
        .o_oa_dma_src_wdata(o_oa_dma_src_wdata),
        .o_oa_dma_src_wmask(o_oa_dma_src_wmask),
        .o_oa_dma_src_wvalid(o_oa_dma_src_wvalid),
        .o_oa_dma_start(o_oa_dma_start),
        .o_quant_dma_base_addr(o_quant_dma_base_addr),
        .o_quant_dma_burst_len_m1(o_quant_dma_burst_len_m1),
        .o_quant_dma_lhs_zp(o_quant_dma_lhs_zp),
        .o_quant_dma_linear_read_mode(o_quant_dma_linear_read_mode),
        .o_quant_dma_row_stride(o_quant_dma_row_stride),
        .o_quant_dma_rows_to_read(o_quant_dma_rows_to_read),
        .o_quant_dma_slot_id(o_quant_dma_slot_id),
        .o_quant_dma_start(o_quant_dma_start),
        .o_quant_dma_use_16bits(o_quant_dma_use_16bits),
        .o_quant_params_valid(quant_params_valid),
        .o_requant_group_ready(requant_group_ready),
        .o_requant_out(o_requant_out),
        .o_write_oa_req(o_write_oa_req)
    );

endmodule

`default_nettype wire
