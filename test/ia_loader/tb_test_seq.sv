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
  // 3) bias_switch 必须与 ia_sending_done 同拍，且只在 bias_sleep=0 时发出
  // 4) bias_last_loop 必须只在最后一个 L2 group 时拉高
  logic bias_monitor_pending;
  logic bias_monitor_active;

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

        if (bias_switch !== (ia_sending_done && !bias_sleep)) begin
          $display("[SEQ] ERROR: bias_switch must align with ia_sending_done and be gated by bias_sleep=0!");
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

  // 等待整个 L1 组的 ia_sending_done，并按列独立计数捕获数据
  //
  // 对角化输出下，各列数据相互错开：col j 比 col 0 滞后 j 拍。
  // 用 per-column 计数器 col_cnt[j] 记录该列已接收的行数，
  // 数据有效判断：ia_out[j] !== '0（测试数据保证有效行 ≥ 1）。
  // 整个 L1 组在同一缓冲中积累，不在 tile 边界重置。
  task automatic wait_l1_done_and_capture(input int total_l1_rows, input int timeout_cycles);
    int col_cnt [SIZE];
    int cnt = 0;
    for (int j = 0; j < SIZE; j++) col_cnt[j] = 0;
    for (int r = 0; r < TC_K; r++)
      for (int j = 0; j < SIZE; j++)
        captured_l1[r][j] = '0;

    forever begin
      @(posedge clk);
      cnt++;
      for (int j = 0; j < SIZE; j++) begin
        if (ia_out[j] !== '0 && col_cnt[j] < total_l1_rows) begin
          captured_l1[col_cnt[j]][j] = ia_out[j];
          col_cnt[j]++;
        end
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

      // 计算本 L1 组的总有效行数（各 tile vrows 之和）
      automatic int total_l1_rows = 0;
      for (int t = 0; t < r_cur; t++)
        total_l1_rows += int'(send_queue[ti + t].vrows);

      // 等 ia_data_valid 后发一次 trigger
      wait_data_valid(50000);
      @(posedge clk);
      send_ia_trigger = 1;
      @(posedge clk);
      send_ia_trigger = 0;

      // 等待 L1 组发送完成，同时逆对角化捕获数据
      wait_l1_done_and_capture(total_l1_rows, 50000);

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
