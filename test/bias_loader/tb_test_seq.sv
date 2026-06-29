// ================================================================
// tb_test_seq.sv — 测试序列与辅助 task
// ================================================================

  task automatic wait_clks(input int n_cyc);
    repeat (n_cyc) @(posedge clk);
  endtask

  task automatic wait_bias_valid(input int timeout_cycles);
    int cnt = 0;
    while (!bias_valid && cnt < timeout_cycles) begin
      @(posedge clk);
      cnt++;
      if ((cnt % 1000) == 0) begin
        $display("[SEQ] wait_bias_valid cnt=%0d req=%0b grant=%0b dma_start=%0b dma_busy=%0b dma_done=%0b bias_valid=%0b",
                 cnt, load_bias_req, load_bias_granted, u_dut.ctrl_dma_start,
                 u_dut.dma_busy, u_dut.dma_done, bias_valid);
      end
    end
    if (cnt >= timeout_cycles) begin
      $display("[SEQ] TIMEOUT waiting for bias_valid after %0d cycles!", timeout_cycles);
      $finish;
    end
  endtask

  task automatic wait_block_match(input int unsigned block_idx, input int timeout_cycles);
    int cnt = 0;
    while ((!(bias_valid && f_block_matches(block_idx))) && cnt < timeout_cycles) begin
      @(posedge clk);
      cnt++;
      if ((cnt % 1000) == 0) begin
        $display("[SEQ] wait_block_match block=%0d cnt=%0d req=%0b grant=%0b dma_start=%0b dma_busy=%0b dma_done=%0b bias_valid=%0b",
                 block_idx, cnt, load_bias_req, load_bias_granted, u_dut.ctrl_dma_start,
                 u_dut.dma_busy, u_dut.dma_done, bias_valid);
      end
    end
    if (cnt >= timeout_cycles) begin
      $display("[SEQ] TIMEOUT waiting for block %0d after %0d cycles!", block_idx, timeout_cycles);
      $finish;
    end
  endtask

  task automatic pulse_bias_switch();
    @(posedge clk);
    bias_switch = 1'b1;
    @(posedge clk);
    bias_switch = 1'b0;
  endtask

  task automatic wait_backpressured_reload_and_check_bias_valid_low(input int timeout_cycles);
    int cnt = 0;
    bit saw_pending = 1'b0;
    bit saw_drop = 1'b0;

    while (cnt < timeout_cycles) begin
      @(posedge clk);
      cnt++;

      if (load_bias_req && !load_bias_granted) begin
        saw_pending = 1'b1;
        if (!saw_drop) begin
          if (bias_valid === 1'b0) begin
            saw_drop = 1'b1;
          end
        end else if (bias_valid !== 1'b0) begin
          $display("[SEQ] ERROR: bias_valid must stay low while new block load is backpressured!");
          $finish;
        end
      end

      if (saw_pending && saw_drop && load_bias_granted) begin
        return;
      end
    end

    if (!saw_pending) begin
      $display("[SEQ] TIMEOUT: did not observe a backpressured reload request!");
    end else if (!saw_drop) begin
      $display("[SEQ] TIMEOUT: bias_valid never dropped while reload stayed backpressured!");
    end else begin
      $display("[SEQ] TIMEOUT: backpressured reload did not complete within %0d cycles!", timeout_cycles);
    end
    $finish;
  endtask

  logic grant_pending;
  int unsigned grant_wait_cnt;
  int grant_bp_hits;
  int unsigned grant_req_count;
  logic load_bias_req_d;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      load_bias_granted <= 1'b0;
      grant_pending     <= 1'b0;
      grant_wait_cnt    <= '0;
      grant_bp_hits     <= 0;
      grant_req_count   <= '0;
      load_bias_req_d   <= 1'b0;
    end else begin
      load_bias_req_d <= load_bias_req;

      if (load_bias_granted) begin
        if (!load_bias_req) begin
          load_bias_granted <= 1'b0;
        end
      end else if (grant_pending) begin
        if (!load_bias_req) begin
          grant_pending  <= 1'b0;
          grant_wait_cnt <= '0;
        end else if (grant_wait_cnt == 0) begin
          load_bias_granted <= 1'b1;
          grant_pending     <= 1'b0;
        end else begin
          grant_wait_cnt <= grant_wait_cnt - 1;
        end
      end else if (load_bias_req && !load_bias_req_d) begin
        grant_req_count <= grant_req_count + 1;

        if ((TC_GRANT_BP_EN != 0) && (TC_GRANT_BP_CYCLES > 0)) begin
          grant_pending  <= 1'b1;
          grant_wait_cnt <= TC_GRANT_BP_CYCLES;
          grant_bp_hits  <= grant_bp_hits + 1;
        end else if ((TC_BP_TARGET_REQ_IDX != 0)
                  && ((grant_req_count + 1) == TC_BP_TARGET_REQ_IDX)
                  && (TC_BP_TARGET_REQ_CYCLES > 0)) begin
          grant_pending  <= 1'b1;
          grant_wait_cnt <= TC_BP_TARGET_REQ_CYCLES;
          grant_bp_hits  <= grant_bp_hits + 1;
        end else begin
          load_bias_granted <= 1'b1;
        end
      end
    end
  end

  task automatic compare_active_block(input int unsigned block_idx, input int active_cycles);
    wait_block_match(block_idx, 10000);
    check_block(block_idx);
    repeat (active_cycles) begin
      @(posedge clk);
      if (bias_sleep == 1'b0) begin
        check_block(block_idx);
      end else begin
        for (int i = 0; i < SIZE; i++) begin
          total_checks++;
          if (data_out[i] !== '0) begin
            if (error_count < 20) begin
              $display("[SCB] ERROR bias_sleep gate idx=%0d got=%0d", i, data_out[i]);
            end
            error_count++;
          end
        end
      end
    end
  endtask

  initial begin
    init_cfg       = 1'b0;
    bias_switch    = 1'b0;
    bias_sleep     = 1'b0;
    bias_last_loop = TC_LAST_LOOP;

    bias_base = TC_BASE_ADDR;
    k_in      = TC_K;
    m_in      = TC_M;

    rst_n = 1'b0;
    repeat (10) @(posedge clk);
    rst_n = 1'b1;
    repeat (5) @(posedge clk);

    $display("[SEQ] ========================================");
    $display("[SEQ] M=%0d SIZE=%0d NUM_BLOCKS=%0d LAST_ELEMS=%0d LAST_LOOP=%0b",
             TC_M, SIZE, TC_NUM_BLOCKS, TC_LAST_BLOCK_ELEMS, TC_LAST_LOOP);
    $display("[SEQ] Grant backpressure: en=%0d cycles=%0d", TC_GRANT_BP_EN,
             TC_GRANT_BP_CYCLES);
    $display("[SEQ] Targeted backpressure request idx=%0d cycles=%0d",
         TC_BP_TARGET_REQ_IDX, TC_BP_TARGET_REQ_CYCLES);
    $display("[SEQ] Check valid drop during backpressure: en=%0d", TC_CHECK_VALID_DROP);
    $display("[SEQ] ========================================");

    @(posedge clk);
    init_cfg = 1'b1;
    @(posedge clk);
    init_cfg = 1'b0;

    wait_bias_valid(10000);

    for (int seq = 0; seq < TC_SEQ_LEN; seq++) begin
      automatic int unsigned block_idx;
      if (seq < TC_NUM_BLOCKS) begin
        block_idx = seq;
      end else begin
        block_idx = 0;
      end

      compare_active_block(block_idx, 2);

      if (u_dut.dma_busy) begin
        wait (u_dut.dma_busy == 1'b0);
      end

      if (seq == TC_SEQ_LEN - 1) begin
        bias_sleep = 1'b1;
      end

      pulse_bias_switch();

      if ((TC_CHECK_VALID_DROP != 0)
          && (TC_BP_TARGET_REQ_IDX != 0)
          && ((seq + 2) == TC_BP_TARGET_REQ_IDX)) begin
        wait_backpressured_reload_and_check_bias_valid_low(10000);
      end

      wait_clks(1);
    end

    if (TC_LAST_LOOP != 0) begin
      wait_clks(4);
      if (load_bias_req !== 1'b0) begin
        $display("[SEQ] ERROR: load_bias_req should be low after the final loop!");
        $finish;
      end
    end

    $display("[SEQ] ========================================");
    $display("[SEQ] Checks: %0d  Errors: %0d", total_checks, error_count);
    if (TC_GRANT_BP_EN != 0)
      $display("[SEQ] Grant backpressure events: %0d", grant_bp_hits);
    if (error_count == 0)
      $display("[SEQ] *** PASS ***");
    else
      $display("[SEQ] *** FAIL ***");
    $display("[SEQ] ========================================");

    repeat (20) @(posedge clk);
    $finish;
  end

  initial begin
    #2000000;
    $display("[SEQ] FATAL: Global timeout!");
    $finish;
  end

  initial begin
    string wave_file;
    if (!$value$plusargs("WAVE_FILE=%s", wave_file)) begin
      wave_file = "wave.vcd";
    end
    $dumpfile(wave_file);
    $dumpvars(0, tb_bias_loader);
  end
