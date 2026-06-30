// ================================================================
// tb_test_seq.sv — 测试序列与辅助 task（`include 到 tb_ia_loader 内）
// ================================================================

  // ── 辅助 task ──
  task automatic wait_clks(input int n_cyc);
    repeat(n_cyc) @(posedge clk);
  endtask

  task automatic wait_data_valid(input int timeout_cycles);
    int cnt = 0;
    while (!ia_data_valid && cnt < timeout_cycles) begin
      @(posedge clk);
      cnt++;
    end
    if (cnt >= timeout_cycles) begin
      $display("[SEQ] TIMEOUT waiting for ia_data_valid after %0d cycles!", timeout_cycles);
      $finish;
    end
  endtask

  // bias_sleep / bias_switch 监视：
  // 1) 当前 L1 组属于 init group 时，bias_sleep 必须保持低电平
  // 2) 非 init group 时，bias_sleep 必须保持高电平
  // 3) bias_switch 必须按新版列复用边界发出
  // 4) bias_last_loop 必须只在最后一个 L2 group 时拉高
  logic bias_monitor_pending;
  logic bias_monitor_active;
  logic expected_bias_switch_by_col;

  assign expected_bias_switch_by_col =
      u_dut.u_ctrl.cache_l1_done &&
      (u_dut.u_ctrl.ia_idx == u_dut.u_ctrl.r_cur - 1) &&
      (u_dut.u_ctrl.output_col_tile_num > 1) &&
      (((u_dut.u_ctrl.l1_idx == '0) && (u_dut.u_ctrl.w_cnt < u_dut.u_ctrl.w_cur - 1)) ||
       (u_dut.u_ctrl.cache_l1_calc_done && (u_dut.u_ctrl.w_cnt == u_dut.u_ctrl.w_cur - 1))) &&
      !u_dut.u_ctrl.last_send;

  logic send_ia_trigger_d1;
  logic trigger_latency_active;
  int trigger_latency_cnt;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      bias_monitor_pending <= 1'b0;
      bias_monitor_active <= 1'b0;
      send_ia_trigger_d1 <= 1'b0;
      trigger_latency_active <= 1'b0;
      trigger_latency_cnt <= 0;
    end else begin
      send_ia_trigger_d1 <= send_ia_trigger;

      if (init_cfg)
        bias_monitor_pending <= 1'b1;

      if (bias_monitor_pending) begin
        bias_monitor_active  <= 1'b1;
        bias_monitor_pending <= 1'b0;
      end

      if (bias_monitor_active) begin
        if ((u_dut.state != 2'b00) && u_dut.u_ctrl.cache_l1_is_init) begin
          if (bias_sleep !== 1'b0) begin
            $display("[SEQ] ERROR: bias_sleep must stay low during init groups!");
            $finish;
          end
        end else if (bias_sleep !== 1'b1) begin
          $display("[SEQ] ERROR: bias_sleep must stay high during non-init groups!");
          $finish;
        end

        if (bias_switch !== expected_bias_switch_by_col) begin
          $display("[SEQ] ERROR: bias_switch mismatch: got=%0b exp=%0b",
                   bias_switch, expected_bias_switch_by_col);
          $finish;
        end

        if (bias_last_loop !== ((u_dut.state != 2'b00) && (u_dut.u_ctrl.l2_idx == TC_G2 - 1))) begin
          $display("[SEQ] ERROR: bias_last_loop must match the last L2 group!");
          $finish;
        end
      end

      if (send_ia_trigger && !send_ia_trigger_d1) begin
        trigger_latency_active <= 1'b1;
        trigger_latency_cnt <= 0;
      end else if (trigger_latency_active) begin
        if (ia_out[0] !== '0) begin
          if ((trigger_latency_cnt + 1) != 2) begin
            $display("[SEQ] ERROR: first ia_out[0] latency after send_ia_trigger is %0d cycles, expected 2!", trigger_latency_cnt + 1);
            $finish;
          end
          trigger_latency_active <= 1'b0;
        end else begin
          trigger_latency_cnt <= trigger_latency_cnt + 1;
        end
      end
    end
  end

  // 等待整个 L1 组的 ia_sending_done，并按对角化有效窗口捕获数据
  //
  // 对角化输出下，各列数据相互错开：col j 比 col 0 滞后 j 拍。
  // s8 随机数据可能合法为 0，因此不能再用 ia_out[j] != 0 作为有效条件。
  // 整个 L1 组在同一缓冲中积累，不在 tile 边界重置。
  task automatic wait_l1_done_and_capture(input int ti_start, input int r_cur, input int timeout_cycles);
    int active_age   [CACHE_BLOCKS];
    int active_base  [CACHE_BLOCKS];
    int active_vrows [CACHE_BLOCKS];
    bit active_valid [CACHE_BLOCKS];
    int next_tile = 0;
    int row_offset = 0;
    int cnt = 0;
    for (int t = 0; t < CACHE_BLOCKS; t++) begin
      active_age[t]   = 0;
      active_base[t]  = 0;
      active_vrows[t] = 0;
      active_valid[t] = 1'b0;
    end
    for (int r = 0; r < TC_K; r++)
      for (int j = 0; j < SIZE; j++)
        captured_l1[r][j] = '0;

    // The first tile_start can occur on the trigger-accept cycle just before
    // this task starts, so arm the first tile window immediately.
    if (r_cur > 0) begin
      automatic int vrows = int'(send_queue[ti_start].vrows);
      active_age[0]   = 0;
      active_base[0]  = row_offset;
      active_vrows[0] = vrows;
      active_valid[0] = 1'b1;
      row_offset += vrows;
      next_tile = 1;
    end

    forever begin
      @(posedge clk);
      cnt++;
      for (int t = 0; t < CACHE_BLOCKS; t++) begin
        if (active_valid[t]) begin
          active_age[t]++;
          for (int j = 0; j < SIZE; j++) begin
            automatic int rel_row = active_age[t] - 1 - j;
            if (rel_row >= 0 && rel_row < active_vrows[t]) begin
              captured_l1[active_base[t] + rel_row][j] = ia_out[j];
            end
          end
          if (active_age[t] > active_vrows[t] + SIZE)
            active_valid[t] = 1'b0;
        end
      end

      if (ia_tile_start && next_tile < r_cur) begin
        automatic int vrows = int'(send_queue[ti_start + next_tile].vrows);
        active_age[next_tile]   = -1;
        active_base[next_tile]  = row_offset;
        active_vrows[next_tile] = vrows;
        active_valid[next_tile] = 1'b1;
        row_offset += vrows;
        next_tile++;
      end

      if (ia_sending_done) break;
      if (cnt >= timeout_cycles) begin
        $display("[SEQ] TIMEOUT waiting for ia_sending_done after %0d cycles!", timeout_cycles);
        $finish;
      end
    end
  endtask

  // granted 驱动：
  // 1) 当 req 拉高后，按配置插入反压延迟
  // 2) 一旦授权，保持 granted=1 直到 req 拉低
  logic grant_pending;
  int unsigned grant_wait_cnt;
  int grant_bp_hits;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      load_ia_granted <= 1'b0;
      grant_pending   <= 1'b0;
      grant_wait_cnt  <= '0;
      grant_bp_hits   <= 0;
    end else begin
      if (load_ia_granted) begin
        if (!load_ia_req)
          load_ia_granted <= 1'b0;
      end else if (grant_pending) begin
        if (!load_ia_req) begin
          grant_pending  <= 1'b0;
          grant_wait_cnt <= '0;
        end else if (grant_wait_cnt == 0) begin
          load_ia_granted <= 1'b1;
          grant_pending   <= 1'b0;
        end else begin
          grant_wait_cnt <= grant_wait_cnt - 1;
        end
      end else if (load_ia_req) begin
        if ((TC_GRANT_BP_EN != 0) && (TC_GRANT_BP_CYCLES > 0)) begin
          grant_pending  <= 1'b1;
          grant_wait_cnt <= TC_GRANT_BP_CYCLES;
          grant_bp_hits  <= grant_bp_hits + 1;
        end else begin
          load_ia_granted <= 1'b1;
        end
      end
    end
  end

  // 协议检查：没有 req&&granted 握手，不允许启动 tile_loader
  property p_tl_start_requires_handshake;
    @(posedge clk) disable iff (!rst_n)
      u_dut.u_ctrl.tl_start |-> (load_ia_req && load_ia_granted);
  endproperty

  assert property (p_tl_start_requires_handshake)
    else begin
      $display("[SEQ] PROTOCOL ERROR: tl_start without req&&granted handshake!");
      $finish;
    end

  // ── 主测试序列 ──
  initial begin
    // 初始信号
    init_cfg         = 0;
    send_ia_trigger  = 0;
    k_in             = TC_K;
    n_in             = TC_N;
    m_in             = TC_M;
    lhs_base         = TC_BASE_ADDR;
    lhs_row_stride_b = TC_ROW_STRIDE;
    lhs_zp           = TC_LHS_ZP;
    use_16bits       = TC_USE_16BITS;
    ia_reuse_num_in  = TC_R;
    w_reuse_num_in   = TC_W;

    // 复位
    rst_n = 0;
    repeat(10) @(posedge clk);
    rst_n = 1;
    repeat(5) @(posedge clk);

    $display("[SEQ] ========================================");
    $display("[SEQ] K=%0d N=%0d M=%0d SIZE=%0d R=%0d W=%0d",
             TC_K, TC_N, TC_M, SIZE, TC_R, TC_W);
    $display("[SEQ] HTN=%0d VTN=%0d G2=%0d G1=%0d R_ACT=%0d",
             TC_HTN, TC_VTN, TC_G2, TC_G1, TC_R_ACT);
    $display("[SEQ] Expected sends: %0d", send_queue_size);
    $display("[SEQ] ========================================");

    // init_cfg 脉冲
    @(posedge clk);
    init_cfg = 1;
    @(posedge clk);
    init_cfg = 0;

    // 主循环：以 L1 组为单位发送和验证
    // 每次循环：一次 send_ia_trigger → cache_mgr 自主完成 r_cur 个 tile 输出
    //           → ia_sending_done 拉高（L1 组完成）→ 逆对角化比对
    for (int ti = 0; ti < send_queue_size; ) begin
      automatic int l2_idx = int'(send_queue[ti].tile_r) / TC_R;
      automatic int r_cur  = (l2_idx == TC_G2 - 1) ? TC_R_ACT : TC_R;

      // 等 ia_data_valid 后发一次 trigger
      wait_data_valid(50000);
      @(posedge clk);
      send_ia_trigger = 1;
      @(posedge clk);
      send_ia_trigger = 0;

      // 等待 L1 组发送完成，同时逆对角化捕获数据
      wait_l1_done_and_capture(ti, r_cur, 50000);

      // 比对整个 L1 组
      check_l1_output(ti, r_cur);
      tile_send_count += r_cur;
      ti += r_cur;
    end

    // 结果汇总
    $display("[SEQ] ========================================");
    $display("[SEQ] Tiles sent: %0d / %0d", tile_send_count, send_queue_size);
    $display("[SEQ] Checks: %0d  Errors: %0d", total_checks, error_count);
    if (error_count == 0 && tile_send_count == send_queue_size)
      $display("[SEQ] *** PASS ***");
    else
      $display("[SEQ] *** FAIL ***");
    if (TC_GRANT_BP_EN != 0)
      $display("[SEQ] Grant backpressure events: %0d", grant_bp_hits);
    $display("[SEQ] ========================================");

    repeat(20) @(posedge clk);
    $finish;
  end

  // ── 全局超时 ──
  initial begin
    #5000000;
    $display("[SEQ] FATAL: Global timeout at 5ms!");
    $finish;
  end

  // ── 波形（文件名通过 +WAVE_FILE=<path> 传入，默认 wave.vcd）──
  initial begin
    string wave_file;
    if (!$value$plusargs("WAVE_FILE=%s", wave_file))
      wave_file = "wave.vcd";
    $dumpfile(wave_file);
    $dumpvars(0, tb_ia_loader);
  end
