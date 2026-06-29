  task automatic wait_clks(input int n_cyc);
    repeat (n_cyc) @(posedge clk);
  endtask

  task automatic pulse_send_trigger();
    begin
      tb_if.send_weight_trigger <= 1'b1;
      wait_clks(1);
      tb_if.send_weight_trigger <= 1'b0;
    end
  endtask

  logic grant_pending;
  int unsigned grant_wait_cnt;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tb_if.load_weight_granted <= 1'b0;
      grant_pending       <= 1'b0;
      grant_wait_cnt      <= '0;
    end else begin
      if (tb_if.load_weight_granted) begin
        if (!tb_if.load_weight_req) begin
          tb_if.load_weight_granted <= 1'b0;
        end
      end else if (grant_pending) begin
        if (!tb_if.load_weight_req) begin
          grant_pending  <= 1'b0;
          grant_wait_cnt <= '0;
        end else if (grant_wait_cnt == 0) begin
          tb_if.load_weight_granted <= 1'b1;
          grant_pending       <= 1'b0;
        end else begin
          grant_wait_cnt <= grant_wait_cnt - 1;
        end
      end else if (tb_if.load_weight_req) begin
        if ((TC_GRANT_BP_EN != 0) && (TC_GRANT_BP_CYCLES > 0)) begin
          grant_pending  <= 1'b1;
          grant_wait_cnt <= TC_GRANT_BP_CYCLES;
        end else begin
          tb_if.load_weight_granted <= 1'b1;
        end
      end
    end
  end

  initial begin
    tb_if.init_cfg          = 1'b0;
    tb_if.send_weight_trigger = 1'b0;

    tb_if.k    = TC_K;
    tb_if.n    = TC_N;
    tb_if.m    = TC_M;
    tb_if.rhs_base = TC_BASE_ADDR;
    tb_if.rhs_row_stride_b = TC_ROW_STRIDE_B;
    tb_if.rhs_zp = TC_RHS_ZP;
    tb_if.ia_reuse_num = TC_IA_REUSE_NUM;
    tb_if.w_reuse_num  = TC_W_REUSE_NUM;

    rst_n = 1'b0;
    wait_clks(8);
    rst_n = 1'b1;
    wait_clks(4);

    @(posedge clk);
    tb_if.init_cfg <= 1'b1;
    @(posedge clk);
    tb_if.init_cfg <= 1'b0;

    for (int tile = 0; tile < TC_TOTAL_TILES; tile++) begin
      wait (tb_if.weight_data_valid == 1'b1);
      wait_clks(1);
      pulse_send_trigger();
      wait (tb_if.weight_sending_done == 1'b1);
      @(posedge clk);
    end

    wait_clks(10);
    print_summary();
    if (error_count == 0 && tile_send_count == TC_TOTAL_TILES) begin
      $display("[SEQ] PASS");
    end else begin
      $display("[SEQ] FAIL");
    end
    $finish;
  end

  initial begin
    #5000000;
    $display("[SEQ] FATAL: global timeout");
    $finish;
  end
