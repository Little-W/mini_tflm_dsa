// ================================================================
// tb_scoreboard.sv — golden 数据与比对
// ================================================================

  function automatic logic signed [DATA_WIDTH-1:0] f_expected_word(input int unsigned block_idx,
                                                                   input int unsigned elem_idx);
    automatic int unsigned flat_idx;
    flat_idx = block_idx * SIZE + elem_idx;
    if (flat_idx < TC_M) begin
      f_expected_word = DATA_WIDTH'($signed(flat_idx + 1));
    end else begin
      f_expected_word = '0;
    end
  endfunction

  function automatic int unsigned f_block_elems(input int unsigned block_idx);
    if (block_idx + 1 < TC_NUM_BLOCKS) begin
      f_block_elems = SIZE;
    end else begin
      f_block_elems = TC_LAST_BLOCK_ELEMS;
    end
  endfunction

  int error_count  = 0;
  int total_checks = 0;

  task automatic check_block(input int unsigned block_idx);
    automatic int unsigned elems = f_block_elems(block_idx);
    for (int i = 0; i < SIZE; i++) begin
      automatic logic signed [DATA_WIDTH-1:0] expected;
      expected = (i < elems) ? f_expected_word(block_idx, i) : '0;
      total_checks++;
      if (data_out[i] !== expected) begin
        if (error_count < 20) begin
          $display("[SCB] ERROR block=%0d idx=%0d got=%0d exp=%0d", block_idx, i,
                   data_out[i], expected);
        end
        error_count++;
      end
    end
  endtask

  function automatic bit f_block_matches(input int unsigned block_idx);
    automatic int unsigned elems = f_block_elems(block_idx);
    f_block_matches = 1'b1;
    for (int i = 0; i < SIZE; i++) begin
      automatic logic signed [DATA_WIDTH-1:0] expected;
      expected = (i < elems) ? f_expected_word(block_idx, i) : '0;
      if (data_out[i] !== expected) begin
        f_block_matches = 1'b0;
      end
    end
  endfunction

