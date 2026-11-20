  logic proof_check_context, proof_config_success;
  logic proof_cache_active, proof_cache_clear;
  logic [5:0] proof_ranges_seen, proof_ranges_ok;
  logic [5:0] proof_range_prefix;
  logic [32:0] proof_saved_end[4];
  logic proof_current_range_ok;
  assign proof_range_prefix = (6'b000001 << u_config_check.range_index) - 6'd1;
  assign proof_current_range_ok = !u_config_check.range_enable_q ||
      (u_config_check.range_size_ok && !u_config_check.range_end_q[32] &&
       (u_config_check.range_index == 0 ||
        u_config_check.range_end_q <= {1'b0, c.output_base} ||
        u_config_check.output_end_q <= {1'b0, u_config_check.range_base_q}));

  // 独立从消费端的槽位优先级推导已完成范围的值。
  // 尚未检查和未启用的槽位均为零，输入范围优先于其余读取类型。
  always_comb begin
    for (int slot = 0; slot < 4; slot++) proof_saved_end[slot] = '0;
    if (global_pool) begin
      if (proof_ranges_seen[1])
        proof_saved_end[0] = {1'b0, c.input_base} + {1'b0, input_bytes[31:0]};
    end else if (depthwise) begin
      if (proof_ranges_seen[2])
        proof_saved_end[0] = {1'b0, c.rhs_base} + {1'b0, weight_bytes[31:0]};
      if (proof_ranges_seen[3] && c.bias_base != 0)
        proof_saved_end[1] = {1'b0, c.bias_base} + 33'(parameter_bytes);
      if (proof_ranges_seen[4])
        proof_saved_end[2] = {1'b0, c.multiplier_base} + 33'(parameter_bytes);
      if (proof_ranges_seen[5])
        proof_saved_end[3] = {1'b0, c.shift_base} + 33'(parameter_bytes);
    end else if (!spatial) begin
      if (proof_ranges_seen[1])
        proof_saved_end[0] = {1'b0, c.input_base} + {1'b0, input_bytes[31:0]};
      if (proof_ranges_seen[2] && (binary_vector || softmax_s8))
        proof_saved_end[1] = {1'b0, c.rhs_base} +
            (softmax_s8 ? 33'd1024 : {1'b0, input_bytes[31:0]});
    end
  end

  // 按实际同步清除条件观察保存寄存器，不约束复位前的任意初值。
  always_ff @(posedge clk) begin
    proof_cache_clear <= !rst_n ||
        (u_config_check.state == u_config_check.IDLE && state == CHECK) ||
        (u_config_check.state == u_config_check.COMPLETE && config_check_error);
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) proof_cache_active <= 1'b0;
    else if (state == IDLE && start) proof_cache_active <= 1'b0;
    else if (u_config_check.state == u_config_check.COMPLETE && config_check_error)
      proof_cache_active <= 1'b0;
    else if (state == CHECK && config_check_ready) proof_cache_active <= 1'b1;
  end

  // 检查所属配置由实际启动事件建立，新的配置与复位同时清除归属信息。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      proof_check_context <= 1'b0;
      proof_config_success <= 1'b0;
      proof_ranges_seen <= '0;
      proof_ranges_ok <= '0;
    end else if (state == IDLE && start) begin
      proof_check_context <= 1'b0;
      proof_config_success <= 1'b0;
      proof_ranges_seen <= '0;
      proof_ranges_ok <= '0;
    end else begin
      if (state == CHECK && config_check_ready) begin
        proof_check_context <= 1'b1;
        proof_ranges_seen <= '0;
        proof_ranges_ok <= '0;
      end
      if (proof_check_context && u_config_check.state == u_config_check.RANGE_COMPARE) begin
        proof_ranges_seen[u_config_check.range_index] <= 1'b1;
        proof_ranges_ok[u_config_check.range_index] <= proof_current_range_ok;
      end
      if (state == CHECK_WAIT && config_check_done && !config_check_error) begin
        proof_config_success <= proof_check_context && (&proof_ranges_seen) && (&proof_ranges_ok);
      end
    end
  end

  // 各项范围从保存到消费期间使用同一份描述符，长度高位仍由检查器验证。
  always_comb begin
    if (rst_n && proof_check_context) begin
      if (u_config_check.state == u_config_check.CALCULATE ||
          u_config_check.state == u_config_check.CAPTURE ||
          u_config_check.state == u_config_check.FIELDS) begin
        assert(proof_ranges_seen == 0);
        assert(proof_ranges_ok == 0);
      end
      if (u_config_check.state == u_config_check.RANGE_SELECT ||
          u_config_check.state == u_config_check.RANGE_ADD ||
          u_config_check.state == u_config_check.RANGE_COMPARE) begin
        assert(u_config_check.range_index <= 5);
        assert(proof_ranges_seen == proof_range_prefix);
        assert(proof_ranges_ok == proof_range_prefix);
      end
      if (u_config_check.state == u_config_check.RANGE_ADD ||
          u_config_check.state == u_config_check.RANGE_COMPARE) begin
        assert(u_config_check.range_base_q == u_config_check.selected_base);
        assert(u_config_check.range_bytes_q == u_config_check.selected_bytes);
        assert(u_config_check.range_enable_q == u_config_check.selected_enable);
      end
      if (u_config_check.state == u_config_check.RANGE_ADD) begin
        assert({u_config_check.range_end_carry, u_config_check.range_end_low} ==
            {1'b0, u_config_check.range_base_q[7:0]} +
            {1'b0, u_config_check.range_bytes_q[7:0]});
      end
      if (u_config_check.state == u_config_check.RANGE_COMPARE) begin
        assert(u_config_check.range_end_q == {1'b0, u_config_check.range_base_q} +
            {1'b0, u_config_check.range_bytes_q[31:0]});
        assert(u_config_check.range_size_ok ==
            (u_config_check.range_bytes_q != 0 && u_config_check.range_bytes_q[63:32] == 0));
      end
      if (config_check_done && !config_check_error) begin
        assert(u_config_check.range_index == 5);
        assert(&proof_ranges_seen);
        assert(&proof_ranges_ok);
      end
      if (proof_cache_active) begin
        for (int slot = 0; slot < 4; slot++)
          assert(checked_range_end[slot] == proof_saved_end[slot]);
      end
      if (proof_ranges_ok[1]) assert(input_bytes[63:32] == 0);
      if (proof_ranges_ok[2] && depthwise) assert(weight_bytes[63:32] == 0);
    end
    if (rst_n && proof_cache_clear) begin
      for (int slot = 0; slot < 4; slot++) assert(checked_range_end[slot] == 0);
    end
    if (rst_n && config_check_ready && config_check_error) begin
      for (int slot = 0; slot < 4; slot++) assert(checked_range_end[slot] == 0);
    end
    if (rst_n && state == CHECK_WAIT) begin
      assert(proof_check_context);
      assert(proof_cache_active);
    end
    if (rst_n && proof_cache_active) assert(proof_check_context);
    if (rst_n && proof_config_success) begin
      assert(proof_check_context && proof_cache_active);
      assert(config_check_ready && !config_check_error);
    end
    if (rst_n && state == CONFIGURE) begin
      assert(proof_check_context && proof_config_success);
      assert(&proof_ranges_seen);
      assert(&proof_ranges_ok);
      assert(input_range_mode == global_pool);
      assert(proof_cache_active);
      for (int range_idx = 0; range_idx < 4; range_idx++) begin
        assert(dma_range_base[range_idx] == proof_expected_base[range_idx]);
        assert(dma_range_end[range_idx] == proof_expected_end[range_idx]);
      end
    end
  end
