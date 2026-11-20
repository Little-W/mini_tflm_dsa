  logic proof_queue_enable, proof_queue_ready;
  logic [3:0] proof_opcode, proof_cfg_opcode;
  assign proof_opcode = c.op;
  assign proof_cfg_opcode = cfg.op;
  assign win_req_ready = proof_queue_ready && !dma_cfg_valid && !rd_start;
  conv_window_queue #(.DEPTH(4), .TAG_W(2), .COL_W(32), .p_max_cols(TILE)) proof_queue (
    .clk, .rst_n, .configure(dma_cfg_valid && dma_cfg_ready), .enable(proof_queue_enable),
    .req_valid(win_req_valid && !dma_cfg_valid && !rd_start), .req_ready(proof_queue_ready),
    .req_p0(win_req_p0), .req_q0(win_req_q0), .req_cols(win_req_cols), .req_tag(win_req_tag),
    .rsp_valid(win_rsp_valid), .rsp_ready(win_rsp_ready), .rsp_tag(win_rsp_tag),
    .rsp_col(win_rsp_col), .rsp_data(win_rsp_data), .rsp_mask(win_rsp_mask),
    .rsp_last(win_rsp_last), .rsp_error(win_rsp_error), .busy(win_busy),
    .frontend_ready(proof_frontend_ready), .frontend_rsp_valid(proof_frontend_valid),
    .frontend_rsp_col(proof_frontend_col), .frontend_rsp_data(proof_frontend_data),
    .frontend_rsp_mask(proof_frontend_mask), .frontend_rsp_last(proof_frontend_last),
    .frontend_error(proof_frontend_error)
  );
  assign proof_queue_enable = proof_enable;
  always_comb if (rst_n) begin
    assert(!global_pool || (spatial && !depthwise));
    assert(state != POOL_LOAD_WAIT || global_pool);
    assert(!(state == LOAD_WAIT && load_kind == LD_A) || !spatial);
    assert(!win_busy || (spatial && !global_pool));
    assert(pool_bank_valid == 0 || (spatial && global_pool));
    assert(!(state == LOAD_WAIT && load_kind == LD_A && window_response_fire));
    assert(!(state == LOAD_WAIT && load_kind == LD_A && pool_bank_valid != 0));
    assert(!(window_response_fire && pool_bank_valid != 0));
  end
