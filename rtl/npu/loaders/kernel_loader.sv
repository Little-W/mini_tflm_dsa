`default_nettype none

module kernel_loader #(
	    parameter int unsigned DATA_WIDTH   = 8,
	    parameter int unsigned SIZE         = 4,
	    parameter int unsigned BUS_WIDTH    = 32,
	    parameter int unsigned REG_WIDTH    = 32,
	    parameter int unsigned COUNT_WIDTH  = REG_WIDTH,
	    parameter int unsigned CACHE_BLOCKS = 1
	) (
    input  wire logic                        clk,
    input  wire logic                        rst_n,
    input  wire logic                        init_cfg,
    input  wire logic                        cfg_command_mode = 1'b0,
    input  wire logic                        cache_flush = 1'b0,
    input  wire logic                        prefetch_valid = 1'b0,
    input  wire logic [REG_WIDTH-1:0]        prefetch_base_addr = '0,
    input  wire logic [REG_WIDTH-1:0]        prefetch_p0 = '0,
    input  wire logic [REG_WIDTH-1:0]        prefetch_q0 = '0,
    input  wire logic [REG_WIDTH-1:0]        prefetch_rows = '0,
    input  wire logic [REG_WIDTH-1:0]        prefetch_valid_cols = '0,
    output logic                        prefetch_idle,
    // IS Conv uses this ordinary matrix loader for image-derived A blocks.
    input  wire logic                        cfg_im2col = 1'b0,
    input  wire logic                        cfg_tile_packed = 1'b0,
    input  wire logic [REG_WIDTH-1:0]        cfg_p0_base = '0,
    input  wire logic [REG_WIDTH-1:0]        cfg_q0_base = '0,
    output logic                        load_weight_req,
    input  wire logic                        load_weight_granted,
    input  wire logic                        send_weight_trigger,
    input  wire logic [REG_WIDTH-1:0]        k,
    input  wire logic [REG_WIDTH-1:0]        n,
    input  wire logic [REG_WIDTH-1:0]        m,
    input  wire logic [REG_WIDTH-1:0]        rhs_base,
    input  wire logic [REG_WIDTH-1:0]        rhs_row_stride_b,
    input  wire logic signed [REG_WIDTH-1:0] rhs_zp,
    input  wire logic                        use_16bits,
    input  wire logic [REG_WIDTH-1:0]        ia_reuse_num,
    input  wire logic [REG_WIDTH-1:0]        w_reuse_num,
    input wire logic [REG_WIDTH-1:0] row_groups,
    input wire logic [REG_WIDTH-1:0] row_tail_tiles,
    input wire logic [REG_WIDTH-1:0] col_groups,
    input wire logic [REG_WIDTH-1:0] col_tail_tiles,
	    output logic                        ext_dma_start,
	    output logic                        ext_dma_is_write,
	    output logic                        ext_dma_linear_read_mode,
    output logic                        ext_dma_im2col,
    output logic [REG_WIDTH-1:0]        ext_dma_p0,
    output logic [REG_WIDTH-1:0]        ext_dma_q0,
    output logic [REG_WIDTH-1:0]        ext_dma_group,
	    output logic [REG_WIDTH-1:0]        ext_dma_base_addr,
	    output logic [REG_WIDTH-1:0]        ext_dma_row_stride,
	    output logic [REG_WIDTH-1:0]        ext_dma_rows_to_read,
	    output logic [7:0]                  ext_dma_burst_len_m1,
	    output logic                        ext_dma_slot_id,
	    output logic                        ext_dma_use_16bits,
	    output logic signed [REG_WIDTH-1:0] ext_dma_lhs_zp,
	    input  wire logic                        ext_dma_busy,
	    input  wire logic                        ext_dma_done,
        input  wire logic                        ext_dma_wr_slot,
	    input  wire logic [$clog2(SIZE)-1:0]     ext_dma_wr_row,
	    input  wire logic [$clog2(SIZE)-1:0]     ext_dma_wr_col_base,
	    input  wire logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [BUS_WIDTH/8],
	    input  wire logic                        ext_dma_wr_valid[BUS_WIDTH/8],
	    output logic                        weight_sending_done,
	    output logic                        load_weight_done,
	    output logic                        store_weight_req,
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE],
    output logic                        weight_data_valid,
    // 后台状态独立于当前授予，供顶层在末级合并同周期中止。
    output logic                        o_prefetch_quiescent
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
  logic                        ctrl_buf_load_start, ctrl_buf_load_ready;
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
  descriptor_t prefetch_descriptor, active_descriptor;
  descriptor_t comparison_descriptor;
  logic command_mode_q, command_waiting, demand_confirmed, prefetch_window_open;
  logic transfer_active, transfer_prefetch, transfer_discard;
  logic managed_mode, prefetch_capture;
  logic comparison_equal;
  logic comparison_match_q, comparison_valid_q, comparison_ready;
  logic comparison_from_candidate_q;
  logic prefetch_candidate_valid, prefetch_check_pending;
  logic [5*REG_WIDTH-1:0] candidate_fields, candidate_fields_q;
  logic [5*REG_WIDTH-1:0] candidate_equal_i_current, candidate_equal_i_saved;
  logic candidate_equal_o_equal;
  logic comparison_metadata_equal;
  logic [REG_WIDTH-1:0] column_equal_i_a, column_equal_i_b, column_equal_i_c;
  logic [REG_WIDTH-1:0] column_equal_i_target;
  logic column_equal_o_equal;
  logic [REG_WIDTH-1:0] row_equal_i_a, row_equal_i_b, row_equal_i_target;
  logic row_equal_i_carry_in;
  logic row_equal_o_equal;
  logic [REG_WIDTH-1:0] address_equal_i_a, address_equal_i_b, address_equal_i_c;
  logic [REG_WIDTH-1:0] address_equal_i_target;
  logic address_equal_o_equal;
  localparam int p_count_width = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
  localparam int p_size_shift = $clog2(SIZE);
  logic demand_issue, prefetch_issue, demand_dma_start, prefetch_dma_start;
  logic cache_hit_fire, cache_hit_done, discard_fire;
  logic [1:0] response_slots_active;
  logic response_accept;
  logic load_idle_i_request, load_idle_i_granted, load_idle_i_quiescent;
  logic load_idle_o_start, load_idle_o_idle;

  always_comb begin
    ctrl_descriptor = '0;
    ctrl_descriptor.im2col = im2col_q;
    ctrl_descriptor.use16 = cfg_use_16bits;
    ctrl_descriptor.tile_packed = tile_packed_q;
    ctrl_descriptor.base_addr = dma_tile_base_addr;
    ctrl_descriptor.row_stride = dma_row_stride_b;
    ctrl_descriptor.p0 = dma_p0 + p0_base_q;
    ctrl_descriptor.q0 = dma_q0 + q0_base_q;
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
    port_descriptor = dma_start ? issue_descriptor :
        transfer_active ? active_descriptor : issue_descriptor;
  end

  assign managed_mode = command_mode_q || prefetch_state != PF_EMPTY ||
      (transfer_active && transfer_prefetch);

  // 空闲状态比较新候选，已保存状态比较预取项；两个消费条件使用同一比较器。
  assign comparison_descriptor = (prefetch_state == PF_EMPTY) ?
      candidate_descriptor : prefetch_descriptor;
  assign comparison_metadata_equal =
      {ctrl_descriptor.im2col, ctrl_descriptor.use16, ctrl_descriptor.tile_packed,
       ctrl_descriptor.row_stride, ctrl_descriptor.group, ctrl_descriptor.rows,
       ctrl_descriptor.cols, ctrl_descriptor.zp} ==
      {comparison_descriptor.im2col, comparison_descriptor.use16, comparison_descriptor.tile_packed,
       comparison_descriptor.row_stride, comparison_descriptor.group, comparison_descriptor.rows,
       comparison_descriptor.cols, comparison_descriptor.zp};
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

  add3_equal #(.p_width(REG_WIDTH)) u_column_equal (
      .i_a(column_equal_i_a), .i_b(column_equal_i_b), .i_c(column_equal_i_c),
      .i_target(column_equal_i_target), .o_equal(column_equal_o_equal)
  );
  add_equal #(.p_width(REG_WIDTH)) u_row_equal (
      .i_a(row_equal_i_a), .i_b(row_equal_i_b), .i_target(row_equal_i_target),
      .i_carry_in(row_equal_i_carry_in), .o_equal(row_equal_o_equal)
  );
  add3_equal #(.p_width(REG_WIDTH)) u_address_equal (
      .i_a(address_equal_i_a), .i_b(address_equal_i_b), .i_c(address_equal_i_c),
      .i_target(address_equal_i_target), .o_equal(address_equal_o_equal)
  );
  assign ctrl_buf_load_ready = managed_mode ? !demand_confirmed : buf_load_ready;
  assign cache_hit_fire = managed_mode && ctrl_load_req && comparison_ready && comparison_match_q &&
      (prefetch_state == PF_CACHED || (prefetch_state == PF_LOADING && buf_load_commit)) &&
      !cache_flush && !init_cfg;
  assign discard_fire = managed_mode && ctrl_load_req && comparison_ready && !comparison_match_q &&
      prefetch_state == PF_CACHED && buf_discard_ready && !transfer_active && !cache_flush;
  assign buf_discard_head = discard_fire;
  assign demand_issue = managed_mode && ctrl_load_req && !transfer_active && !ext_dma_busy &&
      buf_load_ready && (prefetch_state == PF_EMPTY || prefetch_state == PF_PENDING) &&
      !cache_flush && !init_cfg;
  assign prefetch_issue = managed_mode && prefetch_state == PF_PENDING && !command_waiting &&
      !ctrl_load_req && !transfer_active && !ext_dma_busy && buf_load_ready && !cache_flush && !init_cfg;
  assign load_weight_req = !cache_flush &&
      (managed_mode ? (demand_issue || prefetch_issue) : ctrl_load_req);
  assign ctrl_load_granted = cache_hit_fire ||
      (load_weight_granted && !cache_flush && (!managed_mode || demand_issue));
  assign dma_start = load_idle_o_start;
  assign prefetch_dma_start = dma_start && managed_mode && prefetch_issue;
  assign demand_dma_start = dma_start && !prefetch_dma_start;
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
  assign prefetch_check_pending = prefetch_candidate_valid &&
      (!comparison_ready || !comparison_match_q);
  // 请求和后台空闲条件提前并行准备，授予信号只参与最后一级接收与空闲选择。
  assign load_idle_i_request = load_weight_req;
  assign load_idle_i_granted = load_weight_granted;
  assign load_idle_i_quiescent = prefetch_state != PF_PENDING && !transfer_active &&
      !prefetch_check_pending && !ext_dma_busy && response_slots_active == 0;
  assign prefetch_idle = load_idle_o_idle;
  assign o_prefetch_quiescent = load_idle_i_quiescent;

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
  assign dma_burst_len_m1 = (!dma_start && transfer_active) ? descriptor_burst[2] :
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
    .load_weight_granted   (ctrl_load_granted),
    .send_weight_trigger    (send_weight_trigger),
    .buf_weight_data_valid  (weight_data_valid),
    .buf_weight_sending_done(weight_sending_done),
    .buf_load_ready          (ctrl_buf_load_ready),
    .load_done               (dma_done),
    .load_weight_req       (ctrl_load_req),
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
	  logic signed [DATA_WIDTH-1:0] row_acc_n [SIZE];
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
    for (int lane = 0; lane < BYTE_PER_BEAT; lane++) begin
      beat_valid |= ext_dma_wr_valid[lane] && response_accept;
      if (ext_dma_wr_valid[lane] && response_accept &&
          (REG_WIDTH'(ext_dma_wr_col_base) + REG_WIDTH'(lane) + REG_WIDTH'(1) >=
           ext_dma_valid_cols_r[ext_dma_wr_slot])) begin
        last_ext_beat = 1'b1;
      end
    end
  end

  if (BYTE_PER_BEAT > 1 && (BYTE_PER_BEAT & (BYTE_PER_BEAT-1)) == 0) begin : g_rotated_rows
    localparam int p_lane_bits = $clog2(BYTE_PER_BEAT);
    logic signed [DATA_WIDTH-1:0] rotated_data [BYTE_PER_BEAT];
    logic rotated_valid [BYTE_PER_BEAT];
    logic row_clear, row_finish;
`ifdef SYNTHESIS
`ifndef ASIC_SYNTHESIS
    localparam bit p_fpga_row_pair = 1'b1;
`else
    localparam bit p_fpga_row_pair = 1'b0;
`endif
`else
    localparam bit p_fpga_row_pair = 1'b0;
`endif

    // 相隔一个总线通道组的列使用同一输入数据，只计算一组循环选择结果。
    assign row_clear = cache_flush || (managed_mode && transfer_discard);
    assign row_finish = beat_valid && last_ext_beat;
    for (genvar lane = 0; lane < BYTE_PER_BEAT; lane++) begin : g_rotate
      logic [p_lane_bits-1:0] source_lane;
      assign source_lane = p_lane_bits'(lane) - p_lane_bits'(ext_dma_wr_col_base);
      assign rotated_data[lane] = ext_dma_wr_data[source_lane];
      assign rotated_valid[lane] = ext_dma_wr_valid[source_lane];
    end
    for (genvar column = 0; column < SIZE; column++) begin : g_column
      logic column_in_beat, column_update, column_logical;
      if (column < BYTE_PER_BEAT) begin : g_first_group
        assign column_in_beat = int'(ext_dma_wr_col_base) <= column;
      end else begin : g_later_group
        assign column_in_beat = int'(ext_dma_wr_col_base) <= column &&
          int'(ext_dma_wr_col_base) > column-BYTE_PER_BEAT;
      end
      assign column_update = beat_valid && column_in_beat && rotated_valid[column % BYTE_PER_BEAT] &&
        REG_WIDTH'(column) < ext_dma_valid_cols_r[ext_dma_wr_slot];
      assign column_logical = REG_WIDTH'(column) < ext_dma_logical_cols_r[ext_dma_wr_slot];
      if (p_fpga_row_pair) begin : g_paired_output
        // 两个结果共用一次数据选择，完成条件只影响累积结果。
        for (genvar bit_index = 0; bit_index < DATA_WIDTH; bit_index++) begin : g_bit
          logic [5:0] pair_i_bits;
          logic pair_o_emit, pair_o_accumulate;
          assign pair_i_bits = {row_finish, row_clear, column_logical, column_update,
            rotated_data[column % BYTE_PER_BEAT][bit_index], row_acc[column][bit_index]};
          assign row_emit_n[column][bit_index] = pair_o_emit;
          assign row_acc_n[column][bit_index] = pair_o_accumulate;
          LUT6_2 #(.INIT(64'h00000000c000ca0a)) u_pair (
            .I0(pair_i_bits[0]), .I1(pair_i_bits[1]), .I2(pair_i_bits[2]),
            .I3(pair_i_bits[3]), .I4(pair_i_bits[4]), .I5(pair_i_bits[5]),
            .O5(pair_o_emit), .O6(pair_o_accumulate)
          );
        end
      end else begin : g_generic_output
        // 每列独立决定接收、填零或保留；最后一次传输同时清空累积状态。
        assign row_emit_n[column] = column_update ?
          (column_logical ? rotated_data[column % BYTE_PER_BEAT] : '0) :
          (row_clear ? '0 : row_acc[column]);
        assign row_acc_n[column] = row_finish ? '0 : row_emit_n[column];
      end
    end
  end else begin : g_general_rows
    // 通道数为其他整数时，逐项更新对应列并保留相同的覆盖顺序。
    always_comb begin
      for (int c = 0; c < SIZE; c++) begin
        row_acc_n[c] = row_acc[c];
        row_emit_n[c] = row_acc[c];
      end
      if (cache_flush || (managed_mode && transfer_discard)) begin
        for (int c = 0; c < SIZE; c++) begin
          row_acc_n[c] = '0;
          row_emit_n[c] = '0;
        end
      end
      if (beat_valid) begin
        for (int i = 0; i < BYTE_PER_BEAT; i++) begin
          automatic int col;
          col = int'(ext_dma_wr_col_base) + i;
          if (ext_dma_wr_valid[i] && col < SIZE && REG_WIDTH'(col) < ext_dma_valid_cols_r[ext_dma_wr_slot]) begin
            row_emit_n[col] = REG_WIDTH'(col) < ext_dma_logical_cols_r[ext_dma_wr_slot] ? ext_dma_wr_data[i] : '0;
            if (!last_ext_beat) begin
              row_acc_n[col] = REG_WIDTH'(col) < ext_dma_logical_cols_r[ext_dma_wr_slot] ? ext_dma_wr_data[i] : '0;
            end
          end
        end
        if (last_ext_beat) begin
          for (int c = 0; c < SIZE; c++) begin
            row_acc_n[c] = '0;
          end
        end
      end
    end
  end

	  always_ff @(posedge clk or negedge rst_n) begin
	        if (!rst_n) begin
	          dma_busy <= 1'b0;
              for(int bank=0;bank<2;bank++)begin
                ext_dma_valid_cols_r[bank] <= REG_WIDTH'(SIZE);
                ext_dma_logical_cols_r[bank] <= REG_WIDTH'(SIZE);
              end
	          for (int c = 0; c < SIZE; c++) begin
	            row_acc[c] <= '0;
	          end
	        end else begin
	          dma_busy <= ext_dma_busy;
	          if (dma_start) begin
                // The image block is returned as a complete SIZE-column row,
                // including explicit zero reduction-tail elements. Commit it
                // once at SIZE, rather than re-emitting after each padded beat.
	            ext_dma_valid_cols_r[buf_load_slot] <= (port_descriptor.im2col || port_descriptor.tile_packed) ? REG_WIDTH'(SIZE) : port_descriptor.cols;
	            ext_dma_logical_cols_r[buf_load_slot] <= port_descriptor.im2col ? REG_WIDTH'(SIZE) : port_descriptor.cols;
	          end
	          for (int c = 0; c < SIZE; c++) begin
	            row_acc[c] <= row_acc_n[c];
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

// 同周期请求占用空闲状态，两个输出共用一个双输出 LUT。
module kernel_request_idle #(
    parameter bit p_use_lut =
`ifdef ASIC_SYNTHESIS
        1'b0
`elsif XILINX_FPGA
        1'b1
`elsif SYNTHESIS
        1'b1
`else
        1'b0
`endif
) (
    input  wire logic i_request,
    input  wire logic i_granted,
    input  wire logic i_quiescent,
    output logic o_start,
    output logic o_idle
);
    if (p_use_lut) begin : g_fpga
        LUT6_2 #(.INIT(64'h7070_7070_8888_8888)) u_select (
            .I0(i_request), .I1(i_granted), .I2(i_quiescent),
            .I3(1'b0), .I4(1'b0), .I5(1'b1),
            .O5(o_start), .O6(o_idle)
        );
    end else begin : g_generic
        assign o_start = i_request && i_granted;
        assign o_idle = i_quiescent && !(i_request && i_granted);
    end
endmodule

// 三位相等比较以六路组合树归并，完整候选字段使用四级 LUT。
module kernel_candidate_equal #(
    parameter int p_width = 160,
    parameter bit p_use_lut =
`ifdef ASIC_SYNTHESIS
        1'b0
`elsif XILINX_FPGA
        1'b1
`elsif SYNTHESIS
        1'b1
`else
        1'b0
`endif
) (
    input  wire logic [p_width-1:0] i_current,
    input  wire logic [p_width-1:0] i_saved,
    output logic o_equal
);
    localparam int p_groups = (p_width + 2) / 3;
    localparam int p_levels = (p_groups <= 1) ? 0 : $clog2(p_groups);
    logic [p_groups-1:0] level_equal [0:p_levels];

    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_leaf
        logic [2:0] current_bits, saved_bits;
        logic leaf_o_equal;

        assign current_bits = 3'(i_current >> (3*group_index));
        assign saved_bits = 3'(i_saved >> (3*group_index));
        if (p_use_lut) begin : g_fpga
            LUT6 #(.INIT(64'h9009_0000_0000_9009)) u_equal (
                .I0(current_bits[0]), .I1(saved_bits[0]),
                .I2(current_bits[1]), .I3(saved_bits[1]),
                .I4(current_bits[2]), .I5(saved_bits[2]),
                .O(leaf_o_equal)
            );
        end else begin : g_generic
            assign leaf_o_equal = current_bits == saved_bits;
        end
        assign level_equal[0][group_index] = leaf_o_equal;
    end

    for (genvar level = 1; level <= p_levels; level++) begin : g_level
        localparam int p_previous_span = 6 ** (level-1);
        localparam int p_current_span = 6 ** level;
        localparam int p_previous_nodes = (p_groups+p_previous_span-1) / p_previous_span;
        localparam int p_current_nodes = (p_groups+p_current_span-1) / p_current_span;

        for (genvar node = 0; node < p_groups; node++) begin : g_node
            if (node < p_current_nodes) begin : g_present
                localparam int p_children = (p_previous_nodes-6*node >= 6) ?
                    6 : p_previous_nodes-6*node;
                logic [5:0] merge_i_equal;
                logic merge_o_equal;

                for (genvar child = 0; child < 6; child++) begin : g_child
                    if (child < p_children) begin : g_present
                        assign merge_i_equal[child] = level_equal[level-1][6*node+child];
                    end else begin : g_padding
                        assign merge_i_equal[child] = 1'b1;
                    end
                end
                if (p_children == 1) begin : g_forward
                    assign merge_o_equal = merge_i_equal[0];
                end else if (p_use_lut) begin : g_fpga
                    LUT6 #(.INIT(64'h8000_0000_0000_0000)) u_merge (
                        .I0(merge_i_equal[0]), .I1(merge_i_equal[1]),
                        .I2(merge_i_equal[2]), .I3(merge_i_equal[3]),
                        .I4(merge_i_equal[4]), .I5(merge_i_equal[5]),
                        .O(merge_o_equal)
                    );
                end else begin : g_generic
                    assign merge_o_equal = &merge_i_equal;
                end
                assign level_equal[level][node] = merge_o_equal;
            end else begin : g_padding
                assign level_equal[level][node] = 1'b1;
            end
        end
    end
    assign o_equal = level_equal[p_levels][0];
endmodule

// 输出 AXI 突发长度的低八位，独立完成列数与数据宽度的组合编码。
module kernel_burst_encode #(
    parameter int p_width = 32,
    parameter int p_size = 16,
    parameter int p_bus_width = 64
) (
    input  wire logic [p_width-1:0] i_columns,
    input  wire logic i_use16,
    input  wire logic i_tile_packed,
    output logic [7:0] o_length_m1
);
    localparam int p_elements_s8 = p_bus_width / 8;
    localparam int p_elements_s16 = p_bus_width / 16;
    localparam int p_shift_s8 = $clog2(p_elements_s8);
    localparam int p_shift_s16 = $clog2(p_elements_s16);
    logic [p_width-1:0] packed_beats;
    logic [7:0] column_length_m1;

    assign packed_beats = p_width'(p_size/p_elements_s8) << (i_use16 ? 1 : 0);
    if (p_width >= 8+p_shift_s8 && p_elements_s8 > 0 && p_elements_s16 > 0 &&
        (p_elements_s8 & (p_elements_s8-1)) == 0 &&
        (p_elements_s16 & (p_elements_s16-1)) == 0) begin : g_count_encoding
        logic [p_width-1:0] columns_m1;
        assign columns_m1 = i_columns - 1'b1;
        assign column_length_m1 = i_use16 ?
            8'(columns_m1 >> p_shift_s16) : 8'(columns_m1 >> p_shift_s8);
    end else begin : g_narrow_width
        logic [p_width-1:0] beats;
        assign beats = i_use16 ?
            ((i_columns+p_width'(p_elements_s16-1)) >> p_shift_s16) :
            ((i_columns+p_width'(p_elements_s8-1)) >> p_shift_s8);
        assign column_length_m1 = 8'(beats-1);
    end
    assign o_length_m1 = i_tile_packed ? 8'(packed_beats-1) :
        ((i_columns == '0) ? 8'd0 : column_length_m1);
endmodule

`default_nettype wire
