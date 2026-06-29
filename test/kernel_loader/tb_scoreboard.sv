  logic signed [DATA_WIDTH-1:0] golden [TC_K][TC_N];

  int queue_tile_row [TC_TOTAL_TILES];
  int queue_tile_col [TC_TOTAL_TILES];
  int queue_idx;
  int send_tile_idx;
  int row_in_tile;
  int total_row_checks;
  int tile_send_count;
  int error_count;

  initial begin
    for (int r = 0; r < TC_K; r++) begin
      for (int c = 0; c < TC_N; c++) begin
        golden[r][c] = DATA_WIDTH'(r * TC_N + c + 1);
      end
    end

    queue_idx = 0;
    for (int rep = 0; rep < TC_IA_REUSE_NUM; rep++) begin
      for (int l2 = 0; l2 < TC_L2_GROUPS; l2++) begin
        int base_col = l2 * TC_W_REUSE_NUM;
        int group_width = (l2 == TC_L2_GROUPS - 1)
                        ? (TC_TILE_COLS - base_col)
                        : TC_W_REUSE_NUM;
        if (group_width <= 0) group_width = TC_W_REUSE_NUM;
        for (int tr = 0; tr < TC_TILE_ROWS; tr++) begin
          for (int tc = 0; tc < group_width; tc++) begin
            queue_tile_row[queue_idx] = tr;
            queue_tile_col[queue_idx] = base_col + tc;
            queue_idx++;
          end
        end
      end
    end

    $display("[SCB] Built queue: %0d tiles", queue_idx);
  end

  task automatic check_current_row();
    int tr;
    int tc;
    int mat_r;
    int mat_c;
    logic signed [DATA_WIDTH-1:0] expected;
    begin
      if (send_tile_idx >= TC_TOTAL_TILES) begin
        error_count++;
        $display("[SCB] ERROR: row capture beyond expected queue");
        return;
      end

      tr = queue_tile_row[send_tile_idx];
      tc = queue_tile_col[send_tile_idx];
      mat_r = tr * SIZE + (SIZE - 1 - row_in_tile);

      for (int c = 0; c < SIZE; c++) begin
        mat_c = tc * SIZE + c;
        if (mat_r < TC_K && mat_c < TC_N) begin
          expected = golden[mat_r][mat_c];
          expected = expected + DATA_WIDTH'(TC_RHS_ZP);
        end else begin
          expected = '0;
        end

        if (tb_if.weight_out[c] !== expected) begin
          if (error_count < 20) begin
            $display("[SCB] ERROR tile(%0d,%0d) row=%0d col=%0d got=%0d exp=%0d",
                     tr, tc, row_in_tile, c, tb_if.weight_out[c], expected);
          end
          error_count++;
        end
      end

      total_row_checks++;
      row_in_tile++;
    end
  endtask

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      row_in_tile       <= 0;
      send_tile_idx     <= 0;
      total_row_checks  <= 0;
      tile_send_count   <= 0;
      error_count       <= 0;
    end else begin
      if (tb_if.store_weight_req) begin
        check_current_row();
      end

      if (tb_if.weight_sending_done) begin
        if (row_in_tile != SIZE) begin
          $display("[SCB] ERROR: tile %0d finished with row_in_tile=%0d", send_tile_idx, row_in_tile);
          error_count++;
        end
        row_in_tile    <= 0;
        send_tile_idx  <= send_tile_idx + 1;
        tile_send_count<= tile_send_count + 1;
      end
    end
  end

  task automatic print_summary();
    begin
      $display("[SCB] ========================================");
      $display("[SCB] Tiles sent: %0d / %0d", tile_send_count, TC_TOTAL_TILES);
      $display("[SCB] Row checks : %0d", total_row_checks);
      $display("[SCB] Errors     : %0d", error_count);
      if (error_count == 0 && tile_send_count == TC_TOTAL_TILES) begin
        $display("[SCB] PASS");
      end else begin
        $display("[SCB] FAIL");
      end
      $display("[SCB] ========================================");
    end
  endtask
