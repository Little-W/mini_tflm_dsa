
`default_nettype none
// 调度矩阵分块的 DMA 读取与后台预取，按阵列顺序发送已装载数据。
module kernel_loader #(
	    parameter int unsigned DATA_WIDTH   = 8,
	    parameter int unsigned SIZE         = 4,
	    parameter int unsigned BUS_WIDTH    = 32,
        parameter int unsigned DMA_LANES    = BUS_WIDTH / 8,
	    parameter int unsigned REG_WIDTH    = 32,
	    parameter int unsigned COUNT_WIDTH  = REG_WIDTH,
	    parameter int unsigned CACHE_BLOCKS = 1
	) (
    input  wire logic                        clk, // 权重装载、预取和发送控制的工作时钟。
    input  wire logic                        rst_n, // 低有效异步复位。
    input  wire logic                        init_cfg, // 接收新任务配置并初始化当前装载请求。
    input  wire logic                        cfg_command_mode = 1'b0, // 启用按命令确认需求和后台预取的管理方式。
    input  wire logic                        cache_flush = 1'b0, // 清空缓存槽位并撤销当前预取和传输上下文。
    input  wire logic                        prefetch_valid = 1'b0, // 待检查的预取分块描述符有效。
    input  wire logic [REG_WIDTH-1:0]        prefetch_base_addr = '0, // 预取分块的外部存储起始字节地址。
    input  wire logic [REG_WIDTH-1:0]        prefetch_p0 = '0, // 预取分块的列位置或图像输出位置起点。
    input  wire logic [REG_WIDTH-1:0]        prefetch_q0 = '0, // 预取分块的归约位置起点。
    input  wire logic [REG_WIDTH-1:0]        prefetch_rows = '0, // 预取 DMA 需要读取的行数。
    input  wire logic [REG_WIDTH-1:0]        prefetch_valid_cols = '0, // 预取 DMA 每行的有效归约元素数。
    output logic                        prefetch_idle, // 后台处理空闲且本周期没有接受装载授予。
    // 输入驻留卷积通过同一矩阵装载器读取图像展开得到的输入分块。
    input  wire logic                        cfg_im2col = 1'b0, // 当前矩阵装载通过图像展开前端产生输入数据。
    input  wire logic                        cfg_tile_packed = 1'b0, // 外部矩阵按完整分块连续存放。
    input  wire logic [REG_WIDTH-1:0]        cfg_p0_base = '0, // 图像展开输出位置的全局起点。
    input  wire logic [REG_WIDTH-1:0]        cfg_q0_base = '0, // 图像展开归约位置的全局起点。
    output logic                        load_weight_req, // 请求取得权重或图像展开数据的装载资源。
    input  wire logic                        load_weight_granted, // 当前装载请求取得资源授予。
    input  wire logic                        send_weight_trigger, // 请求将已准备分块发送到计算阵列。
    input  wire logic [REG_WIDTH-1:0]        k, // 流式维度长度，WS 对应输出行数，IS 对应输出列数。
    input  wire logic [REG_WIDTH-1:0]        n, // 当前装载矩阵的归约维度长度。
    input  wire logic [REG_WIDTH-1:0]        m, // 驻留维度长度，WS 对应输出列数，IS 对应输出行数。
    input  wire logic [REG_WIDTH-1:0]        rhs_base, // 当前装载矩阵的外部存储首地址。
    input  wire logic [REG_WIDTH-1:0]        rhs_row_stride_b, // 相邻 DMA 行起点之间的字节跨度。
    input  wire logic signed [REG_WIDTH-1:0] rhs_zp, // 装载数据需要扣除的有符号量化零点。
    input  wire logic                        use_16bits, // DMA 按十六位元素读取矩阵。
    input  wire logic [REG_WIDTH-1:0]        ia_reuse_num, // 一个流式操作数复用组包含的分块数。
    input  wire logic [REG_WIDTH-1:0]        w_reuse_num, // 一个驻留操作数复用组包含的分块数。
    input wire logic [REG_WIDTH-1:0] row_groups, // 流式维度的分块组数，WS 对应输出行，IS 对应输出列。
    input wire logic [REG_WIDTH-1:0] row_tail_tiles, // 最后一个流式维度分组的有效分块数。
    input wire logic [REG_WIDTH-1:0] col_groups, // 驻留维度的分块组数，WS 对应输出列，IS 对应输出行。
    input wire logic [REG_WIDTH-1:0] col_tail_tiles, // 最后一个驻留维度分组的有效分块数。
	    output logic                        ext_dma_start, // 启动已取得授予的外部读取传输。
	    output logic                        ext_dma_is_write, // DMA 方向标志，本模块固定为读取。
	    output logic                        ext_dma_linear_read_mode, // DMA 连续线性读取标志，本模块使用逐行读取。
    output logic                        ext_dma_im2col, // 当前 DMA 请求采用图像展开读取。
    output logic [REG_WIDTH-1:0]        ext_dma_p0, // 当前 DMA 分块的列位置或图像输出位置起点。
    output logic [REG_WIDTH-1:0]        ext_dma_q0, // 当前 DMA 分块的归约位置起点。
    output logic [REG_WIDTH-1:0]        ext_dma_group, // 当前 DMA 分块所属的流式维度复用组编号。
	    output logic [REG_WIDTH-1:0]        ext_dma_base_addr, // 当前 DMA 读取的起始字节地址。
	    output logic [REG_WIDTH-1:0]        ext_dma_row_stride, // 当前 DMA 相邻行起点之间的字节跨度。
	    output logic [REG_WIDTH-1:0]        ext_dma_rows_to_read, // 当前 DMA 需要读取的行数。
	    output logic [7:0]                  ext_dma_burst_len_m1, // 当前 DMA 每行传输的总线拍数减一。
	    output logic                        ext_dma_slot_id, // 当前 DMA 返回数据应写入的逻辑槽号。
	    output logic                        ext_dma_use_16bits, // 当前 DMA 读取十六位元素。
	    output logic signed [REG_WIDTH-1:0] ext_dma_lhs_zp, // 当前 DMA 数据需要扣除的有符号零点。
	    input  wire logic                        ext_dma_busy, // 外部 DMA 仍在执行传输。
	    input  wire logic                        ext_dma_done, // 外部 DMA 当前读取传输完成。
        input  wire logic                        ext_dma_wr_slot, // DMA 返回数据对应的逻辑槽号。
	    input  wire logic [$clog2(SIZE)-1:0]     ext_dma_wr_row, // DMA 返回数据的分块内行索引。
	    input  wire logic [$clog2(SIZE)-1:0]     ext_dma_wr_col_base, // DMA 返回数据在当前行内的起始元素索引。
	    input  wire logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [DMA_LANES], // DMA 返回各通道的有符号矩阵元素。
	    input  wire logic                        ext_dma_wr_valid[DMA_LANES], // DMA 返回各通道的数据有效标志。
	    output logic                        weight_sending_done, // 当前分块向计算阵列发送完成。
	    output logic                        load_weight_done, // 当前需求分块通过 DMA 返回或缓存命中完成装载。
	    output logic                        store_weight_req, // 当前权重向量需要写入计算阵列。
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE], // 按计算阵列输入顺序排列的权重向量。
    output logic                        weight_data_valid, // 队首需求分块已准备好，可接受发送触发。
    // 后台状态独立于当前授予，供顶层在末级合并同周期中止。
    output logic                        o_prefetch_quiescent, // 后台预取、传输及返回槽位均已空闲。
    // 供任务接收在后台空闲条件下判断当前需求请求。
    output logic                        o_admission_request // 用于任务接收判断的当前需求装载请求。
);

  typedef enum logic [1:0] {TOP_IDLE, TOP_INIT, TOP_RUN} top_state_t;

  (* fsm_encoding = "sequential" *) top_state_t top_state;

  logic [REG_WIDTH-1:0] cfg_k, cfg_n, cfg_m;
  logic [REG_WIDTH-1:0] cfg_rhs_base, cfg_rhs_row_stride_b;
  logic signed [REG_WIDTH-1:0] cfg_rhs_zp;
  logic cfg_use_16bits;
  logic im2col_q;
  logic tile_packed_q;
  logic [REG_WIDTH-1:0] p0_base_q, q0_base_q;
  logic [REG_WIDTH-1:0] cfg_ia_reuse_num, cfg_w_reuse_num;

  logic cfg_valid;
  logic ctrl_all_done;

  logic                        dma_start;
  logic                        ctrl_dma_start, ctrl_load_req, ctrl_load_granted;
  logic ctrl_o_request_pending;
  (* keep = "true" *) logic ctrl_i_request_accept;
  logic managed_demand_available, unmanaged_demand_available;
  logic prefetch_available;
  // 需求接收独立完成，控制器状态更新只使用该接收结果。
  (* keep = "true" *) logic managed_demand_granted;
  logic                        ctrl_buf_load_start, ctrl_i_request_open;
  logic [REG_WIDTH-1:0]        dma_p0, dma_q0, dma_group;
  logic [REG_WIDTH-1:0]        dma_tile_base_addr;
  logic [REG_WIDTH-1:0] ctrl_o_column_group_base;
  logic [REG_WIDTH-1:0] ctrl_o_column_group_offset;
  logic [REG_WIDTH-1:0] ctrl_o_address_group_base;
  logic [REG_WIDTH-1:0] ctrl_o_address_row_offset;
  logic [REG_WIDTH-1:0] ctrl_o_address_column_offset;
  logic ctrl_o_descriptor_update;
  logic [REG_WIDTH-1:0]        dma_rows_to_read;
  logic [REG_WIDTH-1:0]        dma_row_stride_b;
  logic [REG_WIDTH-1:0]        dma_valid_cols;
  logic signed [REG_WIDTH-1:0] dma_rhs_zp;
  logic                        buf_load_start;
  logic                        buf_send_start;
  logic                        buf_load_ready;
  logic                        buf_load_slot;
  logic                        buf_load_commit, buf_load_commit_slot, buf_discard_ready, buf_discard_head;
  logic                        buf_weight_data_valid;
  logic                        buf_weight_sending_done;
  logic                        buf_store_weight_req;
  logic signed [DATA_WIDTH-1:0] buf_weight_out [SIZE];
  logic                        dma_busy;
	  logic                        dma_done, raw_dma_done;
	  assign load_weight_done = dma_done;

  typedef struct packed {
    logic im2col;
    logic use16;
    logic tile_packed;
    logic [REG_WIDTH-1:0] base_addr, row_stride, p0, q0, group, rows, cols;
    logic signed [REG_WIDTH-1:0] zp;
  } descriptor_t;
  typedef enum logic [1:0] {PF_EMPTY, PF_PENDING, PF_LOADING, PF_CACHED} prefetch_state_t;
  prefetch_state_t prefetch_state;
  descriptor_t ctrl_descriptor, candidate_descriptor, issue_descriptor, port_descriptor;
  logic port_use_active;
  descriptor_t prefetch_descriptor, active_descriptor;
  descriptor_t comparison_descriptor;
  logic command_mode_q, command_waiting, demand_confirmed, prefetch_window_open;
  logic transfer_active, transfer_prefetch, transfer_discard;
  logic managed_mode, prefetch_capture;
  logic comparison_equal;
  logic comparison_match_q, comparison_valid_q, comparison_ready;
  logic comparison_stored_ready;
  logic comparison_from_candidate_q;
  logic prefetch_candidate_valid, prefetch_check_pending;
  logic [5*REG_WIDTH-1:0] candidate_fields, candidate_fields_q;
  logic [5*REG_WIDTH-1:0] candidate_equal_i_current, candidate_equal_i_saved;
  logic candidate_equal_o_equal;
  logic comparison_metadata_equal;
  // 各项比较独立完成，尾部尺寸的选择结果在最终汇合处参与判断。
  (* keep = "true" *) logic comparison_fixed_equal;
  (* keep = "true" *) logic comparison_rows_equal, comparison_columns_equal;
  logic [3*REG_WIDTH+2:0] metadata_equal_i_current, metadata_equal_i_saved;
  logic [REG_WIDTH-1:0] column_equal_i_a, column_equal_i_b, column_equal_i_c;
  logic [REG_WIDTH-1:0] column_equal_i_target;
  (* keep = "true" *) logic column_equal_o_equal;
  logic [REG_WIDTH-1:0] row_equal_i_a, row_equal_i_b, row_equal_i_target;
  logic row_equal_i_carry_in;
  (* keep = "true" *) logic row_equal_o_equal;
  logic [REG_WIDTH-1:0] address_equal_i_a, address_equal_i_b, address_equal_i_c;
  logic [REG_WIDTH-1:0] address_equal_i_target;
  (* keep = "true" *) logic address_equal_o_equal;
  logic address_equal_four_state;
  logic column_equal_four_state, column_equal_fast;
  localparam int p_count_width = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  localparam int p_size_shift = $clog2(SIZE);
  localparam int p_dimension_width = (SIZE < 1) ? 1 : $clog2(SIZE+1);
  logic demand_issue, prefetch_issue, demand_dma_start, prefetch_dma_start;
  logic cache_data_available, demand_data_available;
  (* keep = "true" *) logic managed_request_available, selected_request_available;
  logic managed_prefetch_available;
  (* keep = "true" *) logic selected_prefetch;
  logic request_permitted;
  logic managed_grant_ready, unmanaged_grant_ready;
  logic cache_hit_fire, cache_hit_done, discard_fire;
  logic [1:0] response_slots_active;
  logic response_accept;
  logic load_idle_i_request, load_idle_i_granted, load_idle_i_quiescent;
  logic load_idle_o_start, load_idle_o_idle;
  logic admission_o_request;
  logic [1:0][REG_WIDTH-1:0] position_i_a, position_i_b, position_fast, position_sum;
  logic [1:0] unused_position_carry;

  assign position_i_a[0] = dma_p0;
  assign position_i_a[1] = dma_q0;
  assign position_i_b[0] = p0_base_q;
  assign position_i_b[1] = q0_base_q;
  // 块坐标与配置偏移独立求和，最终描述符选择完整结果。
  for (genvar dimension = 0; dimension < 2; dimension++) begin : g_descriptor_position
    parallel_prefix_add #(.p_width(REG_WIDTH), .p_dsp_split_width(REG_WIDTH/2),
        .p_preserve_groups(1'b1), .p_parallel_high_prefix(1'b1)) u_position (
        .i_a(position_i_a[dimension]), .i_b(position_i_b[dimension]), .i_carry(1'b0),
        .o_sum(position_fast[dimension]), .o_carry(unused_position_carry[dimension])
    );
    always_comb begin
      case (^{position_i_a[dimension], position_i_b[dimension]})
        1'b0, 1'b1: position_sum[dimension] = position_fast[dimension];
        default: position_sum[dimension] = position_i_a[dimension] + position_i_b[dimension];
      endcase
    end
  end

  always_comb begin
    ctrl_descriptor = '0;
    ctrl_descriptor.im2col = im2col_q;
    ctrl_descriptor.use16 = cfg_use_16bits;
    ctrl_descriptor.tile_packed = tile_packed_q;
    ctrl_descriptor.base_addr = dma_tile_base_addr;
    ctrl_descriptor.row_stride = dma_row_stride_b;
    ctrl_descriptor.p0 = position_sum[0];
    ctrl_descriptor.q0 = position_sum[1];
    ctrl_descriptor.group = dma_group;
    ctrl_descriptor.rows = dma_rows_to_read;
    ctrl_descriptor.cols = dma_valid_cols;
    ctrl_descriptor.zp = dma_rhs_zp;
    candidate_descriptor = ctrl_descriptor;
    candidate_descriptor.base_addr = prefetch_base_addr;
    candidate_descriptor.p0 = prefetch_p0;
    candidate_descriptor.q0 = prefetch_q0;
    candidate_descriptor.group = '0;
    candidate_descriptor.rows = prefetch_rows;
    candidate_descriptor.cols = prefetch_valid_cols;
    issue_descriptor = prefetch_issue ? prefetch_descriptor : ctrl_descriptor;
    // 请求期间先选好待发描述符，授予只控制接收边沿。
    port_descriptor = port_use_active ? active_descriptor : issue_descriptor;
  end

  assign managed_mode = command_mode_q || prefetch_state != PF_EMPTY ||
      (transfer_active && transfer_prefetch);

  // 空闲状态比较新候选，已保存状态比较预取项；两个消费条件使用同一比较器。
  assign comparison_descriptor = (prefetch_state == PF_EMPTY) ?
      candidate_descriptor : prefetch_descriptor;
  assign metadata_equal_i_current =
      {ctrl_descriptor.im2col, ctrl_descriptor.use16, ctrl_descriptor.tile_packed,
       ctrl_descriptor.row_stride, ctrl_descriptor.group, ctrl_descriptor.zp};
  assign metadata_equal_i_saved =
      {comparison_descriptor.im2col, comparison_descriptor.use16, comparison_descriptor.tile_packed,
       comparison_descriptor.row_stride, comparison_descriptor.group, comparison_descriptor.zp};
  // 描述符元数据按三位比较，再以六路平衡树合并各组结果。
  kernel_candidate_equal #(.p_width(3*REG_WIDTH+3)) u_metadata_equal (
      .i_current(metadata_equal_i_current), .i_saved(metadata_equal_i_saved),
      .o_equal(comparison_fixed_equal)
  );
  // 行列尾项独立比较，晚到的尾项选择不经过其他元数据的归并树。
  assign comparison_rows_equal = ctrl_descriptor.rows == comparison_descriptor.rows;
  assign comparison_columns_equal = ctrl_descriptor.cols == comparison_descriptor.cols;
  assign comparison_metadata_equal = comparison_fixed_equal && comparison_rows_equal && comparison_columns_equal;
  assign comparison_equal = comparison_metadata_equal && column_equal_o_equal &&
      row_equal_o_equal && address_equal_o_equal;

  // 比较结果与候选字段同拍保存，候选变化时等待新结果。
  assign candidate_fields = {prefetch_base_addr, prefetch_p0, prefetch_q0,
      prefetch_rows, prefetch_valid_cols};
  always_ff @(posedge clk) begin
    candidate_fields_q <= candidate_fields;
    comparison_match_q <= comparison_equal;
    comparison_from_candidate_q <= prefetch_state == PF_EMPTY;
  end
  // 控制器输出和已保存描述符的改变均使上一周期比较结果失效。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) comparison_valid_q <= 1'b0;
    else comparison_valid_q <= !cache_flush && !init_cfg &&
        top_state != TOP_INIT && !ctrl_o_descriptor_update &&
        !prefetch_capture && !discard_fire && !cache_hit_fire;
  end
  assign comparison_ready = comparison_valid_q &&
      ((prefetch_state == PF_EMPTY) == comparison_from_candidate_q) &&
      (prefetch_state != PF_EMPTY || candidate_equal_o_equal);
  // 缓存与在途预取使用已保存描述符，接收资格直接选择其比较结果。
  always_comb begin
    case (^prefetch_state)
      1'b0, 1'b1: comparison_stored_ready = comparison_valid_q && !comparison_from_candidate_q;
      default: comparison_stored_ready = comparison_ready;
    endcase
  end
  assign candidate_equal_i_current = candidate_fields;
  assign candidate_equal_i_saved = candidate_fields_q;

  kernel_candidate_equal #(.p_width(5*REG_WIDTH)) u_candidate_equal (
      .i_current(candidate_equal_i_current), .i_saved(candidate_equal_i_saved),
      .o_equal(candidate_equal_o_equal)
  );

  // 列号截断位置高于地址有效位时，可直接比较三个独立的模加法操作数。
  if ((p_count_width + p_size_shift) >= REG_WIDTH) begin : g_column_operands
    assign column_equal_i_a = ctrl_o_column_group_base;
    assign column_equal_i_b = ctrl_o_column_group_offset;
    assign column_equal_i_c = p0_base_q;
  end else begin : g_column_truncated
    assign column_equal_i_a = dma_p0;
    assign column_equal_i_b = p0_base_q;
    assign column_equal_i_c = '0;
  end
  assign column_equal_i_target = comparison_descriptor.p0;
  assign row_equal_i_a = dma_q0;
  assign row_equal_i_b = q0_base_q;
  assign row_equal_i_target = comparison_descriptor.q0;
  assign row_equal_i_carry_in = 1'b0;
  assign address_equal_i_a = ctrl_o_address_group_base;
  assign address_equal_i_b = ctrl_o_address_row_offset;
  assign address_equal_i_c = ctrl_o_address_column_offset;
  assign address_equal_i_target = comparison_descriptor.base_addr;

  if (p_count_width + p_size_shift < REG_WIDTH) begin : g_truncated_column_equal
    localparam int unsigned p_low_width = p_count_width + p_size_shift;
    localparam int unsigned p_high_width = REG_WIDTH - p_low_width;
    logic low_equal, high_equal, high_increment_equal, low_carry, unused_low_equal;
    logic legacy_equal, fast_equal;
    add3_equal #(.p_width(p_low_width)) u_low_equal (
        .i_a(ctrl_o_column_group_base[p_low_width-1:0]),
        .i_b(ctrl_o_column_group_offset[p_low_width-1:0]),
        .i_c(p0_base_q[p_low_width-1:0]),
        .i_target(column_equal_i_target[p_low_width-1:0]), .o_equal(low_equal)
    );
    unsigned_compare #(.p_width(p_low_width)) u_low_carry (
        .i_a(column_equal_i_target[p_low_width-1:0]), .i_b(p0_base_q[p_low_width-1:0]),
        .o_less(low_carry), .o_equal(unused_low_equal)
    );
    assign high_equal = p0_base_q[REG_WIDTH-1:p_low_width] == column_equal_i_target[REG_WIDTH-1:p_low_width];
    add_equal #(.p_width(p_high_width)) u_high_increment_equal (
        .i_a(p0_base_q[REG_WIDTH-1:p_low_width]), .i_b(p_high_width'(1)), .i_carry_in(1'b0),
        .i_target(column_equal_i_target[REG_WIDTH-1:p_low_width]), .o_equal(high_increment_equal)
    );
    assign fast_equal = low_equal && (low_carry ? high_increment_equal : high_equal);
    add3_equal #(.p_width(REG_WIDTH)) u_legacy_equal (
        .i_a(column_equal_i_a), .i_b(column_equal_i_b), .i_c(column_equal_i_c),
        .i_target(column_equal_i_target), .o_equal(legacy_equal)
    );
    always_comb begin
      case (^{column_equal_i_a, column_equal_i_b, column_equal_i_c, column_equal_i_target})
        1'b0, 1'b1: column_equal_four_state = fast_equal;
        default: column_equal_four_state = legacy_equal;
      endcase
    end
  end else begin : g_complete_column_equal
    add3_equal #(.p_width(REG_WIDTH)) u_column_equal (
        .i_a(column_equal_i_a), .i_b(column_equal_i_b), .i_c(column_equal_i_c),
        .i_target(column_equal_i_target), .o_equal(column_equal_four_state)
    );
  end
  // 控制器保存定宽列位置，列坐标比较只需两个操作数的逐位进位关系。
  add_equal #(.p_width(REG_WIDTH), .p_preserve_bits(1'b1)) u_saved_column_equal (
      .i_a(dma_p0), .i_b(p0_base_q), .i_target(column_equal_i_target),
      .i_carry_in(1'b0), .o_equal(column_equal_fast)
  );
  always_comb begin
    case (^{column_equal_i_a, column_equal_i_b, column_equal_i_c, column_equal_i_target})
      1'b0, 1'b1: column_equal_o_equal = column_equal_fast;
      default: column_equal_o_equal = column_equal_four_state;
    endcase
  end
  add_equal #(.p_width(REG_WIDTH), .p_preserve_bits(1'b1)) u_row_equal (
      .i_a(row_equal_i_a), .i_b(row_equal_i_b), .i_target(row_equal_i_target),
      .i_carry_in(row_equal_i_carry_in), .o_equal(row_equal_o_equal)
  );
  add3_equal #(.p_width(REG_WIDTH)) u_address_equal (
      .i_a(address_equal_i_a), .i_b(address_equal_i_b), .i_c(address_equal_i_c),
      .i_target(address_equal_i_target), .o_equal(address_equal_four_state)
  );
  // 已保存的完整 DMA 地址直接参与描述符比较，未知输入保留逐位进位比较语义。
  always_comb begin
    case (^{address_equal_i_a, address_equal_i_b, address_equal_i_c, address_equal_i_target})
      1'b0, 1'b1: address_equal_o_equal = dma_tile_base_addr == address_equal_i_target;
      default: address_equal_o_equal = address_equal_four_state;
    endcase
  end
  // 控制器提供未发起的需求，槽位与模式资格在加载器接收处独立合并。
  assign ctrl_i_request_open = 1'b1;
  assign ctrl_load_req = ctrl_o_request_pending &&
      (managed_mode ? !demand_confirmed : buf_load_ready);
  assign managed_demand_available = ctrl_o_request_pending && !demand_confirmed;
  assign unmanaged_demand_available = ctrl_o_request_pending && buf_load_ready;
  assign cache_hit_fire = managed_mode && ctrl_load_req && comparison_stored_ready && comparison_match_q &&
      (prefetch_state == PF_CACHED || (prefetch_state == PF_LOADING && buf_load_commit)) &&
      !cache_flush && !init_cfg;
  assign discard_fire = managed_mode && ctrl_load_req && comparison_stored_ready && !comparison_match_q &&
      prefetch_state == PF_CACHED && buf_discard_ready && !transfer_active && !cache_flush;
  assign buf_discard_head = discard_fire;
  assign demand_issue = managed_mode && ctrl_load_req && !transfer_active && !ext_dma_busy &&
      buf_load_ready && (prefetch_state == PF_EMPTY || prefetch_state == PF_PENDING) &&
      !cache_flush && !init_cfg;
  // 预取窗口与需求接收分别检查，需求更新不经过预取选择的归并。
  assign prefetch_available = prefetch_state == PF_PENDING && !command_waiting &&
      !managed_demand_available && !transfer_active && !ext_dma_busy && buf_load_ready;
  assign managed_prefetch_available = prefetch_state == PF_PENDING && !command_waiting &&
      !ctrl_load_req && !transfer_active && !ext_dma_busy && buf_load_ready;
  // 槽位可写状态在末端参与请求资格，需求和预取状态独立准备。
  (* keep = "true" *) logic managed_request_eligible;
  assign managed_request_eligible = !transfer_active && !ext_dma_busy &&
      ((managed_demand_available && (prefetch_state == PF_EMPTY || prefetch_state == PF_PENDING)) ||
       (prefetch_state == PF_PENDING && !command_waiting && !managed_demand_available));
  assign managed_request_available = managed_request_eligible && buf_load_ready;
  // 受管传输活动期间不接受新请求，端口描述符可直接由活动状态选择。
  // 普通加载仍检查原请求资格，未知输入使用完整请求表达式。
  always_comb begin
    port_use_active = !load_weight_req && transfer_active;
    case (^{transfer_active, managed_mode, cache_flush, unmanaged_demand_available})
      1'b0, 1'b1: port_use_active = transfer_active &&
          (managed_mode || cache_flush || !unmanaged_demand_available);
      default: ;
    endcase
  end
  always_comb begin
    case (managed_mode)
      1'b0: begin
        selected_request_available = unmanaged_demand_available;
      end
      1'b1: begin
        selected_request_available = managed_request_available;
      end
      default: begin
        selected_request_available = managed_mode ?
            ((ctrl_load_req && demand_data_available) || managed_prefetch_available) : ctrl_load_req;
      end
    endcase
  end
  // 待发预取状态已包含管理模式资格，选择不再经过需求请求的模式选择。
  always_comb begin
    case (^prefetch_state)
      1'b0, 1'b1: begin
        selected_prefetch = prefetch_available;
        prefetch_issue = prefetch_available && !cache_flush && !init_cfg;
      end
      default: begin
        selected_prefetch = managed_mode && managed_prefetch_available;
        prefetch_issue = managed_mode && prefetch_state == PF_PENDING && !command_waiting &&
            !ctrl_load_req && !transfer_active && !ext_dma_busy && buf_load_ready && !cache_flush && !init_cfg;
      end
    endcase
  end
  assign request_permitted = !cache_flush && (!managed_mode || !init_cfg);
  always_comb begin
    load_weight_req = selected_request_available && request_permitted;
`ifndef SYNTHESIS
    // 未知模式继续使用接口选择的四态语义。
    if ((^managed_mode) === 1'bx) begin
      load_weight_req = !cache_flush &&
          (managed_mode ? (demand_issue || prefetch_issue) : ctrl_load_req);
    end
`endif
  end
  // 缓存命中和实际 DMA 授予先合并资格，配置与清除只参与末级接收选择。
  assign cache_data_available = comparison_stored_ready && comparison_match_q &&
      (prefetch_state == PF_CACHED || (prefetch_state == PF_LOADING && buf_load_commit));
  assign demand_data_available = !transfer_active && !ext_dma_busy && buf_load_ready &&
      (prefetch_state == PF_EMPTY || prefetch_state == PF_PENDING);
  assign managed_grant_ready = managed_mode && ctrl_load_req &&
      (cache_data_available || (load_weight_granted && demand_data_available));
  assign unmanaged_grant_ready = load_weight_granted && !managed_mode;
  assign ctrl_load_granted = !cache_flush &&
      (unmanaged_grant_ready || (managed_grant_ready && !init_cfg));
  assign managed_demand_granted = managed_demand_available &&
      (cache_data_available || (load_weight_granted && demand_data_available));
  // 已完成需求资格的接收事件直接驱动控制器，控制器仍保留原有配置和清除优先级。
  always_comb begin
    case (managed_mode)
      1'b0: ctrl_i_request_accept = !cache_flush && unmanaged_demand_available && load_weight_granted;
      1'b1: ctrl_i_request_accept = !cache_flush && !init_cfg && managed_demand_granted;
      default: ctrl_i_request_accept = ctrl_load_req && ctrl_load_granted;
    endcase
  end
  assign dma_start = load_idle_o_start;
  always_comb begin
    prefetch_dma_start = dma_start && selected_prefetch;
    demand_dma_start = dma_start && !selected_prefetch;
`ifndef SYNTHESIS
    // 控制输入含未知位时按逐级接收表达式传播四态结果。
    if ((^{dma_start, managed_mode, cache_flush, init_cfg}) === 1'bx) begin
      prefetch_dma_start = dma_start && managed_mode && prefetch_issue;
      demand_dma_start = dma_start && !prefetch_dma_start;
    end
`endif
  end
  assign buf_load_start = dma_start;
  assign response_accept = response_slots_active[ext_dma_wr_slot] && !cache_flush &&
      (!managed_mode || !transfer_discard);
  assign dma_done = cache_hit_done || (raw_dma_done && response_accept &&
      (!managed_mode || (transfer_active && !transfer_prefetch)));
  assign weight_data_valid = buf_weight_data_valid && !cache_flush &&
      (!managed_mode || (demand_confirmed && !init_cfg));
  assign prefetch_candidate_valid = command_mode_q && (prefetch_window_open || buf_send_start) &&
      prefetch_valid && prefetch_state == PF_EMPTY && !cache_flush && !init_cfg &&
      prefetch_rows != 0 && prefetch_rows <= REG_WIDTH'(SIZE) &&
      prefetch_valid_cols != 0 && prefetch_valid_cols <= REG_WIDTH'(SIZE);
  assign prefetch_capture = prefetch_candidate_valid && comparison_ready && !comparison_match_q;
  // 新候选等待比较时占用预取窗口，调度器只在处理结束后观察空闲。
  // 有效候选已确定为空状态，稳定检查直接合并已保存的比较条件。
  assign prefetch_check_pending = prefetch_candidate_valid &&
      !(comparison_valid_q && comparison_from_candidate_q &&
        candidate_equal_o_equal && comparison_match_q);
  // 请求和后台空闲条件提前并行准备，授予信号只参与最后一级接收与空闲选择。
  assign load_idle_i_request = load_weight_req;
  assign load_idle_i_granted = load_weight_granted;
  assign load_idle_i_quiescent = prefetch_state != PF_PENDING && !transfer_active &&
      !prefetch_check_pending && !ext_dma_busy && response_slots_active == 0;
  assign prefetch_idle = load_idle_o_idle;
  assign o_prefetch_quiescent = load_idle_i_quiescent;
  // 后台空闲已排除待发预取和在途传输；仅空状态的控制请求可能占用当前授予。
  // 待发状态由同一空闲条件屏蔽，因此请求选择只需检查预取状态的高位。
  assign admission_o_request = !prefetch_state[1] && !cache_flush && ctrl_load_req &&
    (!command_mode_q || (buf_load_ready && !init_cfg));
  assign o_admission_request = admission_o_request;

  kernel_request_idle u_load_idle (
      .i_request(load_idle_i_request), .i_granted(load_idle_i_granted),
      .i_quiescent(load_idle_i_quiescent),
      .o_start(load_idle_o_start), .o_idle(load_idle_o_idle)
  );

  // Linear descriptors may overlap while their ordered responses target
  // separate buffer slots. Command prefetch still owns one transfer at a time.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      response_slots_active <= '0;
      cache_hit_done <= 1'b0;
    end else if (cache_flush) begin
      response_slots_active <= '0;
      cache_hit_done <= 1'b0;
    end else begin
      cache_hit_done <= cache_hit_fire;
      if (buf_load_commit) response_slots_active[buf_load_commit_slot] <= 1'b0;
      if (dma_start) response_slots_active[buf_load_slot] <= 1'b1;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prefetch_state <= PF_EMPTY;
      prefetch_descriptor <= '0;
      active_descriptor <= '0;
      command_mode_q <= 1'b0;
      command_waiting <= 1'b0;
      demand_confirmed <= 1'b0;
      prefetch_window_open <= 1'b0;
      transfer_active <= 1'b0;
      transfer_prefetch <= 1'b0;
      transfer_discard <= 1'b0;
    end else begin
      if (cache_flush) begin
        prefetch_state <= PF_EMPTY;
        command_mode_q <= 1'b0;
        command_waiting <= 1'b0;
        demand_confirmed <= 1'b0;
        prefetch_window_open <= 1'b0;
        transfer_discard <= transfer_active;
      end else begin
        if (buf_send_start) begin
          demand_confirmed <= 1'b0;
          prefetch_window_open <= 1'b1;
        end
        if (prefetch_capture) begin
          prefetch_descriptor <= candidate_descriptor;
          // 候选行列数在 1..SIZE 范围内，保存块内有效位并扩展至公开接口。
          prefetch_descriptor.rows <= REG_WIDTH'(p_dimension_width'(candidate_descriptor.rows));
          prefetch_descriptor.cols <= REG_WIDTH'(p_dimension_width'(candidate_descriptor.cols));
          prefetch_state <= PF_PENDING;
          prefetch_window_open <= 1'b0;
        end
        if (prefetch_dma_start) prefetch_state <= PF_LOADING;
        if (buf_load_commit && transfer_active && transfer_prefetch)
          prefetch_state <= PF_CACHED;
        if (discard_fire) prefetch_state <= PF_EMPTY;
        if (demand_dma_start || cache_hit_fire) begin
          demand_confirmed <= 1'b1;
          command_waiting <= 1'b0;
          if (cache_hit_fire || prefetch_state == PF_PENDING) prefetch_state <= PF_EMPTY;
        end
        if (init_cfg) begin
          command_mode_q <= cfg_command_mode;
          command_waiting <= 1'b1;
          demand_confirmed <= 1'b0;
          prefetch_window_open <= 1'b0;
        end
      end
      if (dma_start && managed_mode) begin
        active_descriptor <= issue_descriptor;
        transfer_active <= 1'b1;
        transfer_prefetch <= prefetch_dma_start;
        transfer_discard <= 1'b0;
      end else if (transfer_active && (buf_load_commit ||
                   ((transfer_discard || cache_flush) && raw_dma_done))) begin
        transfer_active <= 1'b0;
        transfer_discard <= 1'b0;
      end
    end
  end

	  logic                        dma_row_valid;
	  logic [$clog2(SIZE)-1:0]     dma_row_idx;
	  logic signed [DATA_WIDTH-1:0] dma_row_data [SIZE];
	  localparam int BYTE_PER_BEAT = BUS_WIDTH / 8;
	  localparam int ELEM_PER_BEAT_S8 = BYTE_PER_BEAT;
	  localparam int ELEM_PER_BEAT_S16 = BYTE_PER_BEAT / 2;
	  logic [7:0]           dma_burst_len_m1;
  logic [7:0] descriptor_burst [3];

  // 各描述符先独立编码突发长度，传输选择只选择八位编码结果。
  for (genvar descriptor = 0; descriptor < 3; descriptor++) begin : g_burst_encoding
    logic [REG_WIDTH-1:0] burst_i_columns;
    logic burst_i_use16, burst_i_tile_packed;
    logic [7:0] burst_o_length_m1;

    if (descriptor == 0) begin : g_controller
      assign burst_i_columns = ctrl_descriptor.cols;
      assign burst_i_use16 = ctrl_descriptor.use16;
      assign burst_i_tile_packed = ctrl_descriptor.tile_packed;
    end else if (descriptor == 1) begin : g_prefetch
      assign burst_i_columns = prefetch_descriptor.cols;
      assign burst_i_use16 = prefetch_descriptor.use16;
      assign burst_i_tile_packed = prefetch_descriptor.tile_packed;
    end else begin : g_active
      assign burst_i_columns = active_descriptor.cols;
      assign burst_i_use16 = active_descriptor.use16;
      assign burst_i_tile_packed = active_descriptor.tile_packed;
    end
    kernel_burst_encode #(
        .p_width(REG_WIDTH), .p_size(SIZE), .p_bus_width(BUS_WIDTH)
    ) u_encode (
        .i_columns(burst_i_columns), .i_use16(burst_i_use16),
        .i_tile_packed(burst_i_tile_packed), .o_length_m1(burst_o_length_m1)
    );
    assign descriptor_burst[descriptor] = burst_o_length_m1;
  end
  assign dma_burst_len_m1 = port_use_active ? descriptor_burst[2] :
      (prefetch_issue ? descriptor_burst[1] : descriptor_burst[0]);

	  assign ext_dma_start            = dma_start;
	  assign ext_dma_is_write         = 1'b0;
	  assign ext_dma_linear_read_mode = 1'b0;
  assign ext_dma_im2col           = port_descriptor.im2col;
  assign ext_dma_p0               = port_descriptor.p0;
  assign ext_dma_q0               = port_descriptor.q0;
  assign ext_dma_group            = port_descriptor.group;
	  assign ext_dma_base_addr        = port_descriptor.base_addr;
	  assign ext_dma_row_stride       = port_descriptor.row_stride;
	  assign ext_dma_rows_to_read     = port_descriptor.rows;
	  assign ext_dma_burst_len_m1     = dma_burst_len_m1;
	  assign ext_dma_slot_id          = buf_load_slot;
	  assign ext_dma_use_16bits       = port_descriptor.use16;
	  assign ext_dma_lhs_zp           = port_descriptor.zp;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      im2col_q <= 1'b0; p0_base_q <= '0; q0_base_q <= '0;
    end else if (init_cfg && !cache_flush) begin
      im2col_q <= cfg_im2col; p0_base_q <= cfg_p0_base; q0_base_q <= cfg_q0_base;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      top_state          <= TOP_IDLE;
      cfg_valid          <= 1'b0;
      cfg_k              <= '0;
      cfg_n              <= '0;
      cfg_m              <= '0;
      cfg_rhs_base       <= '0;
      cfg_rhs_row_stride_b <= '0;
      cfg_rhs_zp         <= '0;
      cfg_use_16bits     <= 1'b0;
      tile_packed_q      <= 1'b0;
      cfg_ia_reuse_num   <= '0;
      cfg_w_reuse_num    <= '0;
    end else if (cache_flush) begin
      top_state <= TOP_IDLE;
      cfg_valid <= 1'b0;
    end else begin
      case (top_state)
        TOP_IDLE: begin
          cfg_valid <= 1'b0;
          if (init_cfg) begin
            top_state <= TOP_INIT;
          end
        end

        TOP_INIT: begin
          cfg_k               <= k;
          cfg_n               <= n;
          cfg_m               <= m;
          cfg_rhs_base        <= rhs_base;
          cfg_rhs_row_stride_b<= rhs_row_stride_b;
          cfg_rhs_zp          <= rhs_zp;
          cfg_use_16bits      <= use_16bits;
          tile_packed_q       <= cfg_tile_packed;
          cfg_ia_reuse_num    <= ia_reuse_num;
          cfg_w_reuse_num     <= w_reuse_num;
          cfg_valid           <= 1'b1;
          top_state           <= TOP_RUN;
        end

	        TOP_RUN: begin
	          if (ctrl_all_done) begin
	            cfg_valid  <= 1'b0;
	            top_state  <= TOP_IDLE;
	          end
	        end
	        default: begin
	          cfg_valid <= 1'b0;
	          top_state <= TOP_IDLE;
	        end
	      endcase
    end
  end

  kernel_loader_ctrl #(
    .SIZE      (SIZE),
    .REG_WIDTH (REG_WIDTH),
    .COUNT_WIDTH(COUNT_WIDTH)
  ) u_ctrl (
    .clk                   (clk),
    .rst_n                 (rst_n),
    .clear                 (cache_flush),
    .cfg_valid             (cfg_valid),
    .cfg_k                 (cfg_k),
    .cfg_n                 (cfg_n),
    .cfg_m                 (cfg_m),
    .cfg_rhs_base          (cfg_rhs_base),
    .cfg_rhs_row_stride_b  (cfg_rhs_row_stride_b),
    .cfg_rhs_zp            (cfg_rhs_zp),
    .cfg_use_16bits        (cfg_use_16bits),
    .cfg_tile_packed       (tile_packed_q),
    .cfg_ia_reuse_num      (cfg_ia_reuse_num),
    .cfg_w_reuse_num       (cfg_w_reuse_num),
    .cfg_row_groups (row_groups),
    .cfg_row_tail_tiles (row_tail_tiles),
    .cfg_col_groups (col_groups),
    .cfg_col_tail_tiles (col_tail_tiles),
    .load_weight_granted   (ctrl_i_request_accept),
    .send_weight_trigger    (send_weight_trigger),
    .buf_weight_data_valid  (weight_data_valid),
    .buf_weight_sending_done(weight_sending_done),
    .buf_load_ready          (ctrl_i_request_open),
    .load_done               (dma_done),
    .load_weight_req       (ctrl_o_request_pending),
    .dma_start             (ctrl_dma_start),
    .dma_p0                (dma_p0),
    .dma_q0                (dma_q0),
    .dma_group             (dma_group),
    .dma_tile_base_addr    (dma_tile_base_addr),
    .o_column_group_base   (ctrl_o_column_group_base),
    .o_column_group_offset (ctrl_o_column_group_offset),
    .o_address_group_base  (ctrl_o_address_group_base),
    .o_address_row_offset  (ctrl_o_address_row_offset),
    .o_address_column_offset(ctrl_o_address_column_offset),
    .o_descriptor_update(ctrl_o_descriptor_update),
    .dma_rows_to_read      (dma_rows_to_read),
    .dma_row_stride_b      (dma_row_stride_b),
    .dma_valid_cols        (dma_valid_cols),
    .dma_rhs_zp            (dma_rhs_zp),
    .buf_load_start        (ctrl_buf_load_start),
    .buf_send_start        (buf_send_start),
    .ctrl_all_done         (ctrl_all_done),
    .tile_row_dbg          (),
    .tile_col_dbg          (),
    .repeat_dbg            ()
  );

  logic signed [DATA_WIDTH-1:0] row_acc [SIZE];
  logic signed [DATA_WIDTH-1:0] row_acc_data [SIZE];
  logic row_finish_q;
  logic signed [DATA_WIDTH-1:0] row_emit_n [SIZE];
  logic beat_valid;
  logic last_ext_beat;
  logic [REG_WIDTH-1:0] ext_dma_valid_cols_r[2];
  logic [REG_WIDTH-1:0] ext_dma_logical_cols_r[2];

      // The buffer registers each assembled row before writing its RAM.
      // Completion uses the same register stage as the final row.
      assign dma_row_valid = last_ext_beat;
      assign dma_row_idx = ext_dma_wr_row;
      assign raw_dma_done = ext_dma_done;
      always_comb begin
        for (int c = 0; c < SIZE; c++) dma_row_data[c] = row_emit_n[c];
      end

  // 有效传输的最后一个元素决定整行完成，支持不连续的有效通道。
  always_comb begin
    beat_valid = 1'b0;
    last_ext_beat = 1'b0;
    for (int lane = 0; lane < DMA_LANES; lane++) begin
      beat_valid |= ext_dma_wr_valid[lane] && response_accept;
      if (ext_dma_wr_valid[lane] && response_accept &&
          (REG_WIDTH'(ext_dma_wr_col_base) + REG_WIDTH'(lane) + REG_WIDTH'(1) >=
           ext_dma_valid_cols_r[ext_dma_wr_slot])) begin
        last_ext_beat = 1'b1;
      end
    end
  end

  if (DMA_LANES > 1 && (DMA_LANES & (DMA_LANES-1)) == 0) begin : g_rotated_rows
    localparam int p_lane_bits = $clog2(DMA_LANES);
    logic signed [DATA_WIDTH-1:0] rotated_data [DMA_LANES];
    logic rotated_valid [DMA_LANES];
    logic row_clear;
    // 相隔一个总线通道组的列使用同一输入数据，只计算一组循环选择结果。
    assign row_clear = cache_flush || (managed_mode && transfer_discard);
    for (genvar lane = 0; lane < DMA_LANES; lane++) begin : g_rotate
      logic [p_lane_bits-1:0] source_lane;
      assign source_lane = p_lane_bits'(lane) - p_lane_bits'(ext_dma_wr_col_base);
      assign rotated_data[lane] = ext_dma_wr_data[source_lane];
      assign rotated_valid[lane] = ext_dma_wr_valid[source_lane];
    end
    for (genvar column = 0; column < SIZE; column++) begin : g_column
      logic column_in_beat, column_update, column_logical;
      if (column < DMA_LANES) begin : g_first_group
        assign column_in_beat = int'(ext_dma_wr_col_base) <= column;
      end else begin : g_later_group
        assign column_in_beat = int'(ext_dma_wr_col_base) <= column &&
          int'(ext_dma_wr_col_base) > column-DMA_LANES;
      end
      // 每列只检查对应通道，返回资格与列范围并行形成。
      always_comb begin
        case (^ext_dma_wr_col_base)
          1'b0, 1'b1: column_update = response_accept && column_in_beat &&
              rotated_valid[column % DMA_LANES] &&
              REG_WIDTH'(column) < ext_dma_valid_cols_r[ext_dma_wr_slot];
          default: column_update = beat_valid && column_in_beat &&
              rotated_valid[column % DMA_LANES] &&
              REG_WIDTH'(column) < ext_dma_valid_cols_r[ext_dma_wr_slot];
        endcase
      end
      assign column_logical = REG_WIDTH'(column) < ext_dma_logical_cols_r[ext_dma_wr_slot];
      // 每列独立选择接收、填零或保留；最后一次传输清空累积状态。
      assign row_emit_n[column] = column_update ?
        (column_logical ? rotated_data[column % DMA_LANES] : '0) :
        (row_clear ? '0 : row_acc[column]);
    end
  end else begin : g_general_rows
    // 通道数为其他整数时，逐项更新对应列并保留相同的覆盖顺序。
    always_comb begin
      for (int c = 0; c < SIZE; c++) begin
        row_emit_n[c] = row_acc[c];
      end
      if (cache_flush || (managed_mode && transfer_discard)) begin
        for (int c = 0; c < SIZE; c++) begin
          row_emit_n[c] = '0;
        end
      end
      if (beat_valid) begin
        for (int i = 0; i < DMA_LANES; i++) begin
          automatic int col;
          col = int'(ext_dma_wr_col_base) + i;
          if (ext_dma_wr_valid[i] && col < SIZE && REG_WIDTH'(col) < ext_dma_valid_cols_r[ext_dma_wr_slot]) begin
            row_emit_n[col] = REG_WIDTH'(col) < ext_dma_logical_cols_r[ext_dma_wr_slot] ? ext_dma_wr_data[i] : '0;
          end
        end
      end
    end
  end

  // 完整行与结束标志同拍保存，零反馈与下一周期的列更新共同选择。
  for (genvar column = 0; column < SIZE; column++) begin : g_row_feedback
    assign row_acc[column] = row_finish_q ? '0 : row_acc_data[column];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dma_busy <= 1'b0;
      row_finish_q <= 1'b0;
      for (int bank = 0; bank < 2; bank++) begin
        ext_dma_valid_cols_r[bank] <= REG_WIDTH'(SIZE);
        ext_dma_logical_cols_r[bank] <= REG_WIDTH'(SIZE);
      end
      for (int column = 0; column < SIZE; column++) begin
        row_acc_data[column] <= '0;
      end
    end else begin
      dma_busy <= ext_dma_busy;
      row_finish_q <= last_ext_beat;
      if (dma_start) begin
        // 图像块保留完整行长度，归约尾部由零元素填充。
        ext_dma_valid_cols_r[buf_load_slot] <=
            (port_descriptor.im2col || port_descriptor.tile_packed) ? REG_WIDTH'(SIZE) : port_descriptor.cols;
        ext_dma_logical_cols_r[buf_load_slot] <=
            port_descriptor.im2col ? REG_WIDTH'(SIZE) : port_descriptor.cols;
      end
      for (int column = 0; column < SIZE; column++) begin
        row_acc_data[column] <= row_emit_n[column];
      end
    end
  end

  kernel_loader_buffer #(
    .DATA_WIDTH (DATA_WIDTH),
    .SIZE       (SIZE)
  ) u_buf (
    .clk                 (clk),
    .rst_n               (rst_n),
    .cache_flush         (cache_flush),
    .discard_head        (buf_discard_head),
    .load_start          (buf_load_start),
    .load_slot_id        (buf_load_slot),
    .row_slot            (ext_dma_wr_slot),
    .done_slot           (ext_dma_wr_slot),
    .row_valid           (dma_row_valid),
    .row_idx             (dma_row_idx),
    .row_data            (dma_row_data),
    .load_done           (raw_dma_done && response_accept),
    .send_start          (buf_send_start),
    .load_ready          (buf_load_ready),
    .load_commit         (buf_load_commit),
    .load_commit_slot    (buf_load_commit_slot),
    .discard_ready       (buf_discard_ready),
    .weight_data_valid   (buf_weight_data_valid),
    .weight_sending_done (buf_weight_sending_done),
    .store_weight_req    (buf_store_weight_req),
    .weight_out          (buf_weight_out)
  );

  // Keep the kernel RAM local to the loader.  The controller observes the
  // delayed done together with the delayed store request, so IA launch remains
  // ordered after the final weight-load beat.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      weight_sending_done <= 1'b0;
      store_weight_req    <= 1'b0;
      for (int c = 0; c < SIZE; c++) begin
        weight_out[c] <= '0;
      end
    end else if (cache_flush) begin
      weight_sending_done <= 1'b0;
      store_weight_req <= 1'b0;
      for (int c = 0; c < SIZE; c++) weight_out[c] <= '0;
    end else begin
      weight_sending_done <= buf_weight_sending_done;
      store_weight_req    <= buf_store_weight_req;
      for (int c = 0; c < SIZE; c++) begin
        weight_out[c] <= buf_weight_out[c];
      end
    end
  end

`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n && !cache_flush) begin
    if (dma_start) begin
      assert ((!managed_mode || !transfer_active || buf_load_commit) && buf_load_ready &&
              (!response_slots_active[buf_load_slot] ||
               (buf_load_commit && buf_load_commit_slot == buf_load_slot)))
        else $fatal(1,"Kernel DMA starts before its destination is available");
    end
    if (cache_hit_fire) begin
      assert (comparison_equal && !dma_start)
        else $fatal(1,"Kernel cache hit issued a DMA transaction");
    end
    if (managed_mode && weight_data_valid)
      assert (demand_confirmed) else $fatal(1,"Kernel tile became visible before descriptor confirmation");
  end
`endif

endmodule

`default_nettype wire
