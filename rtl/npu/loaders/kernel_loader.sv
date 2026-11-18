module kernel_loader #(
	    parameter int unsigned DATA_WIDTH   = 8,
	    parameter int unsigned SIZE         = 4,
	    parameter int unsigned BUS_WIDTH    = 32,
	    parameter int unsigned REG_WIDTH    = 32,
	    parameter int unsigned COUNT_WIDTH  = REG_WIDTH,
	    parameter int unsigned CACHE_BLOCKS = 1
	) (
    input  logic                        clk,
    input  logic                        rst_n,
    input  logic                        init_cfg,
    input  logic                        cfg_command_mode = 1'b0,
    input  logic                        cache_flush = 1'b0,
    input  logic                        prefetch_valid = 1'b0,
    input  logic [REG_WIDTH-1:0]        prefetch_base_addr = '0,
    input  logic [REG_WIDTH-1:0]        prefetch_p0 = '0,
    input  logic [REG_WIDTH-1:0]        prefetch_q0 = '0,
    input  logic [REG_WIDTH-1:0]        prefetch_rows = '0,
    input  logic [REG_WIDTH-1:0]        prefetch_valid_cols = '0,
    output logic                        prefetch_idle,
    // IS Conv uses this ordinary matrix loader for image-derived A blocks.
    input  logic                        cfg_im2col = 1'b0,
    input  logic                        cfg_tile_packed = 1'b0,
    input  logic [REG_WIDTH-1:0]        cfg_p0_base = '0,
    input  logic [REG_WIDTH-1:0]        cfg_q0_base = '0,
    output logic                        load_weight_req,
    input  logic                        load_weight_granted,
    input  logic                        send_weight_trigger,
    input  logic [REG_WIDTH-1:0]        k,
    input  logic [REG_WIDTH-1:0]        n,
    input  logic [REG_WIDTH-1:0]        m,
    input  logic [REG_WIDTH-1:0]        rhs_base,
    input  logic [REG_WIDTH-1:0]        rhs_row_stride_b,
    input  logic signed [REG_WIDTH-1:0] rhs_zp,
    input  logic                        use_16bits,
    input  logic [REG_WIDTH-1:0]        ia_reuse_num,
    input  logic [REG_WIDTH-1:0]        w_reuse_num,
    input logic [REG_WIDTH-1:0] row_groups,
    input logic [REG_WIDTH-1:0] row_tail_tiles,
    input logic [REG_WIDTH-1:0] col_groups,
    input logic [REG_WIDTH-1:0] col_tail_tiles,
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
	    input  logic                        ext_dma_busy,
	    input  logic                        ext_dma_done,
        input  logic                        ext_dma_wr_slot,
	    input  logic [$clog2(SIZE)-1:0]     ext_dma_wr_row,
	    input  logic [$clog2(SIZE)-1:0]     ext_dma_wr_col_base,
	    input  logic signed [DATA_WIDTH-1:0] ext_dma_wr_data [BUS_WIDTH/8],
	    input  logic                        ext_dma_wr_valid[BUS_WIDTH/8],
	    output logic                        weight_sending_done,
	    output logic                        load_weight_done,
	    output logic                        store_weight_req,
    output logic signed [DATA_WIDTH-1:0] weight_out [SIZE],
    output logic                        weight_data_valid
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
  logic command_mode_q, command_waiting, demand_confirmed, prefetch_window_open;
  logic transfer_active, transfer_prefetch, transfer_discard;
  logic managed_mode, descriptor_match, prefetch_capture;
  logic demand_issue, prefetch_issue, demand_dma_start, prefetch_dma_start;
  logic cache_hit_fire, cache_hit_done, discard_fire;
  logic [1:0] response_slots_active;
  logic response_accept;

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
  assign descriptor_match = ctrl_descriptor == prefetch_descriptor;
  assign ctrl_buf_load_ready = managed_mode ? !demand_confirmed : buf_load_ready;
  assign cache_hit_fire = managed_mode && ctrl_load_req && descriptor_match &&
      (prefetch_state == PF_CACHED || (prefetch_state == PF_LOADING && buf_load_commit)) &&
      !cache_flush && !init_cfg;
  assign discard_fire = managed_mode && ctrl_load_req && !descriptor_match &&
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
  assign dma_start = managed_mode ? load_weight_granted && (demand_issue || prefetch_issue) :
      ctrl_dma_start && !cache_flush;
  assign prefetch_dma_start = dma_start && managed_mode && prefetch_issue;
  assign demand_dma_start = dma_start && !prefetch_dma_start;
  assign buf_load_start = dma_start;
  assign response_accept = response_slots_active[ext_dma_wr_slot] && !cache_flush &&
      (!managed_mode || !transfer_discard);
  assign dma_done = cache_hit_done || (raw_dma_done && response_accept &&
      (!managed_mode || (transfer_active && !transfer_prefetch)));
  assign weight_data_valid = buf_weight_data_valid && !cache_flush &&
      (!managed_mode || (demand_confirmed && !init_cfg));
  assign prefetch_capture = command_mode_q && (prefetch_window_open || buf_send_start) &&
      prefetch_valid && prefetch_state == PF_EMPTY && !cache_flush && !init_cfg &&
      prefetch_rows != 0 && prefetch_rows <= REG_WIDTH'(SIZE) &&
      prefetch_valid_cols != 0 && prefetch_valid_cols <= REG_WIDTH'(SIZE) &&
      candidate_descriptor != ctrl_descriptor;
  assign prefetch_idle = prefetch_state != PF_PENDING && !transfer_active &&
      !prefetch_capture && !dma_start && !ext_dma_busy && response_slots_active == 0;

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
	  logic [REG_WIDTH-1:0] dma_beats_per_row;
	  logic [7:0]           dma_burst_len_m1;

	  always_comb begin
	    if (port_descriptor.tile_packed) begin
	      dma_beats_per_row = REG_WIDTH'(SIZE / ELEM_PER_BEAT_S8) << (port_descriptor.use16 ? 1 : 0);
	    end else if (port_descriptor.cols == 0) begin
	      dma_beats_per_row = REG_WIDTH'(1);
	    end else if (port_descriptor.use16) begin
	      dma_beats_per_row =
	        (port_descriptor.cols + REG_WIDTH'(ELEM_PER_BEAT_S16 - 1)) >> $clog2(ELEM_PER_BEAT_S16);
	    end else begin
	      dma_beats_per_row =
	        (port_descriptor.cols + REG_WIDTH'(ELEM_PER_BEAT_S8 - 1)) >> $clog2(ELEM_PER_BEAT_S8);
	    end
	    dma_burst_len_m1 = 8'(dma_beats_per_row - 1);
	  end

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

	  always_comb begin
	        beat_valid = 1'b0;
	        last_ext_beat = 1'b0;
	        for (int i = 0; i < BYTE_PER_BEAT; i++) begin
	          beat_valid |= ext_dma_wr_valid[i] && response_accept;
	          // Image-derived blocks may return a single lane at a tap or
	          // input-word boundary. Only an actually valid final element
	          // completes the row; nominal bus width can otherwise commit it
	          // early and discard the accumulated prefix on the next beat.
	          if (ext_dma_wr_valid[i] && response_accept &&
	              (REG_WIDTH'(ext_dma_wr_col_base) + REG_WIDTH'(i) + REG_WIDTH'(1)
	               >= ext_dma_valid_cols_r[ext_dma_wr_slot])) last_ext_beat = 1'b1;
	        end
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
	              if (!last_ext_beat) row_acc_n[col] =
                    REG_WIDTH'(col) < ext_dma_logical_cols_r[ext_dma_wr_slot] ? ext_dma_wr_data[i] : '0;
	            end
	          end
	          if (last_ext_beat) begin
	            for (int c = 0; c < SIZE; c++) begin
	              row_acc_n[c] = '0;
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
      assert (descriptor_match && !dma_start)
        else $fatal(1,"Kernel cache hit issued a DMA transaction");
    end
    if (managed_mode && weight_data_valid)
      assert (demand_confirmed) else $fatal(1,"Kernel tile became visible before descriptor confirmation");
  end
`endif

endmodule
