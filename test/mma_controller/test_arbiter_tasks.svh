`ifndef TEST_ARBITER_TASKS_SVH
`define TEST_ARBITER_TASKS_SVH

// 测试任务：简单仲裁
task automatic simple_arbiter_test();
    $display("\n%s[Test 2] Simple ICB arbiter test%s", COLOR_BOLD_CYAN, COLOR_RESET);

    // 等待一点空闲
    repeat (10) @(posedge clk);

    // 同时发起多个请求
    @(weight_if.cb);
    weight_if.cb.load_weight_req <= 1'b1;
    @(ia_if.cb);
    ia_if.cb.load_ia_req <= 1'b1;
    @(oa_if.cb);
    oa_if.cb.write_oa_req <= 1'b1;
    @(bias_if.cb);
    bias_if.cb.load_bias_req <= 1'b1;

    // 检查优先级：OA Writer应该获得授权
    repeat (2) @(posedge clk);
    if (oa_if.write_oa_granted && ctrl_if.icb_sel == 3'd4) begin
        $display("%s  [%0t] OA Writer granted (highest priority)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [WARN] OA Writer not granted as expected (icb_sel=%0d, oa_grant=%0b)%s",
                 COLOR_YELLOW, $time, ctrl_if.icb_sel, oa_if.write_oa_granted, COLOR_RESET);
    end

    @(oa_if.cb);
    oa_if.cb.write_oa_req <= 1'b0;
    repeat (3) @(oa_if.cb);
    oa_if.cb.write_done <= 1'b1;
    @(oa_if.cb);
    oa_if.cb.write_done <= 1'b0;

    // Kernel Loader应该获得授权
    repeat (2) @(posedge clk);
    if (weight_if.load_weight_granted && ctrl_if.icb_sel == 3'd1) begin
        $display("%s  [%0t] Kernel Loader granted (second priority)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display(
            "%s  [%0t] [WARN] Kernel Loader not granted as expected (icb_sel=%0d, w_grant=%0b)%s",
            COLOR_YELLOW, $time, ctrl_if.icb_sel, weight_if.load_weight_granted, COLOR_RESET);
    end

    @(weight_if.cb);
    weight_if.cb.load_weight_req <= 1'b0;
    repeat (3) @(weight_if.cb);
    weight_if.cb.weight_data_valid <= 1'b1;
    @(weight_if.cb);
    weight_if.cb.weight_data_valid <= 1'b0;

    // IA Loader应该获得授权
    repeat (2) @(posedge clk);
    if (ia_if.load_ia_granted && ctrl_if.icb_sel == 3'd0) begin
        $display("%s  [%0t] IA Loader granted (third priority)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [WARN] IA Loader not granted as expected (icb_sel=%0d, ia_grant=%0b)%s",
                 COLOR_YELLOW, $time, ctrl_if.icb_sel, ia_if.load_ia_granted, COLOR_RESET);
    end

    @(ia_if.cb);
    ia_if.cb.load_ia_req <= 1'b0;
    repeat (3) @(ia_if.cb);
    ia_if.cb.ia_data_valid <= 1'b1;
    @(ia_if.cb);
    ia_if.cb.ia_data_valid <= 1'b0;

    // Bias Loader应该获得授权
    repeat (2) @(posedge clk);
    if (bias_if.load_bias_granted && ctrl_if.icb_sel == 3'd2) begin
        $display("%s  [%0t] Bias Loader granted (fourth priority)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [INFO] Bias Loader grant state (icb_sel=%0d, bias_grant=%0b)%s", 
                 COLOR_CYAN, $time, ctrl_if.icb_sel, bias_if.load_bias_granted, COLOR_RESET);
    end

    @(bias_if.cb);
    bias_if.cb.load_bias_req <= 1'b0;
    repeat (3) @(bias_if.cb);
    bias_if.cb.bias_valid <= 1'b1;
    @(bias_if.cb);
    bias_if.cb.bias_valid <= 1'b0;

    repeat (10) @(posedge clk);
endtask

// 测试任务：复杂仲裁场景
task automatic test_complex_arbitration();
    $display("\n%s[Test 3] Complex arbitration scenarios%s", COLOR_BOLD_CYAN, COLOR_RESET);

    // 场景1：所有模块同时请求
    $display("\n%s  Scenario 1: All modules request simultaneously%s", COLOR_MAGENTA, COLOR_RESET);
    @(ia_if.cb);
    ia_if.cb.load_ia_req <= 1'b1;
    @(weight_if.cb);
    weight_if.cb.load_weight_req <= 1'b1;
    @(bias_if.cb);
    bias_if.cb.load_bias_req <= 1'b1;
    @(quant_if.cb);
    quant_if.cb.load_quant_req <= 1'b1;
    @(oa_if.cb);
    oa_if.cb.write_oa_req <= 1'b1;

    repeat (2) @(posedge clk);

    // 验证OA Writer获得最高优先级
    if (oa_if.write_oa_granted) begin
        $display("%s  [%0t] [PASS] OA Writer granted (Priority 1)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [FAIL] OA Writer should be granted first!%s", 
                 COLOR_RED, $time, COLOR_RESET);
    end

    // OA Writer完成
    @(oa_if.cb);
    oa_if.cb.write_oa_req <= 1'b0;
    repeat (2) @(oa_if.cb);
    oa_if.cb.write_done <= 1'b1;
    @(oa_if.cb);
    oa_if.cb.write_done <= 1'b0;

    repeat (2) @(posedge clk);

    // 验证Kernel Loader获得第二优先级
    if (weight_if.load_weight_granted) begin
        $display("%s  [%0t] [PASS] Kernel Loader granted (Priority 2)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [FAIL] Kernel Loader should be granted second!%s", 
                 COLOR_RED, $time, COLOR_RESET);
    end

    // Kernel Loader完成
    @(weight_if.cb);
    weight_if.cb.load_weight_req <= 1'b0;
    repeat (2) @(weight_if.cb);
    weight_if.cb.weight_data_valid <= 1'b1;
    @(weight_if.cb);
    weight_if.cb.weight_data_valid <= 1'b0;

    repeat (2) @(posedge clk);

    // 验证IA Loader获得第三优先级
    if (ia_if.load_ia_granted) begin
        $display("%s  [%0t] [PASS] IA Loader granted (Priority 3)%s", 
                 COLOR_GREEN, $time, COLOR_RESET);
    end else begin
        $display("%s  [%0t] [FAIL] IA Loader should be granted third!%s", 
                 COLOR_RED, $time, COLOR_RESET);
    end

    // IA Loader完成
    @(ia_if.cb);
    ia_if.cb.load_ia_req <= 1'b0;
    repeat (2) @(ia_if.cb);
    ia_if.cb.ia_data_valid <= 1'b1;
    @(ia_if.cb);
    ia_if.cb.ia_data_valid <= 1'b0;

    repeat (2) @(posedge clk);

    // Bias和Quant的相对优先级
    if (bias_if.load_bias_granted || quant_if.load_quant_granted) begin
        $display("%s  [%0t] [INFO] Lower priority module granted (icb_sel=%0d)%s",
                 COLOR_CYAN, $time, ctrl_if.icb_sel, COLOR_RESET);
    end

    // 清理剩余请求
    @(bias_if.cb);
    bias_if.cb.load_bias_req <= 1'b0;
    @(quant_if.cb);
    quant_if.cb.load_quant_req <= 1'b0;
    if (bias_if.load_bias_granted) begin
        repeat (2) @(bias_if.cb);
        bias_if.cb.bias_valid <= 1'b1;
        @(bias_if.cb);
        bias_if.cb.bias_valid <= 1'b0;
    end
    if (quant_if.load_quant_granted) begin
        repeat (2) @(quant_if.cb);
        quant_if.cb.quant_params_valid <= 1'b1;
        @(quant_if.cb);
        quant_if.cb.quant_params_valid <= 1'b0;
    end

    repeat (5) @(posedge clk);

    // 场景2：高优先级模块抢占测试
    $display("\n%s  Scenario 2: High priority preemption test%s", COLOR_MAGENTA, COLOR_RESET);

    // 先让低优先级模块获得授权
    @(bias_if.cb);
    bias_if.cb.load_bias_req <= 1'b1;
    repeat (2) @(posedge clk);

    if (bias_if.load_bias_granted) begin
        $display("%s  [%0t] [INFO] Bias Loader granted%s", 
                 COLOR_CYAN, $time, COLOR_RESET);

        // 此时高优先级模块请求
        @(oa_if.cb);
        oa_if.cb.write_oa_req <= 1'b1;

        // 高优先级应该等待当前事务完成
        repeat (3) @(posedge clk);
        if (!oa_if.write_oa_granted) begin
            $display("%s  [%0t] [PASS] OA Writer correctly waiting for current transaction%s",
                     COLOR_GREEN, $time, COLOR_RESET);
        end

        // 完成当前事务
        @(bias_if.cb);
        bias_if.cb.load_bias_req <= 1'b0;
        bias_if.cb.bias_valid <= 1'b1;
        @(bias_if.cb);
        bias_if.cb.bias_valid <= 1'b0;

        repeat (2) @(posedge clk);

        // 高优先级现在应该获得授权
        if (oa_if.write_oa_granted) begin
            $display("%s  [%0t] [PASS] OA Writer granted after lower priority completed%s", 
                     COLOR_GREEN, $time, COLOR_RESET);
        end

        @(oa_if.cb);
        oa_if.cb.write_oa_req <= 1'b0;
        repeat (2) @(oa_if.cb);
        oa_if.cb.write_done <= 1'b1;
        @(oa_if.cb);
        oa_if.cb.write_done <= 1'b0;
    end

    repeat (5) @(posedge clk);

    // 场景3：快速连续请求
    $display("\n%s  Scenario 3: Rapid sequential requests%s", COLOR_MAGENTA, COLOR_RESET);

    for (int i = 0; i < 3; i++) begin
        @(weight_if.cb);
        weight_if.cb.load_weight_req <= 1'b1;
        repeat (2) @(weight_if.cb);
        weight_if.cb.load_weight_req <= 1'b0;
        weight_if.cb.weight_data_valid <= 1'b1;
        @(weight_if.cb);
        weight_if.cb.weight_data_valid <= 1'b0;
        $display("%s  [%0t] [INFO] Weight request cycle %0d completed%s", 
                 COLOR_CYAN, $time, i + 1, COLOR_RESET);
        repeat (2) @(posedge clk);
    end

    repeat (5) @(posedge clk);

    // 场景4：交错请求
    $display("\n%s  Scenario 4: Interleaved requests%s", COLOR_MAGENTA, COLOR_RESET);

    fork
        begin
            @(ia_if.cb);
            ia_if.cb.load_ia_req <= 1'b1;
            wait (ia_if.load_ia_granted);
            $display("%s  [%0t] [INFO] IA Loader granted in interleaved test%s", 
                     COLOR_CYAN, $time, COLOR_RESET);
            @(ia_if.cb);
            ia_if.cb.load_ia_req <= 1'b0;
            repeat (3) @(ia_if.cb);
            ia_if.cb.ia_data_valid <= 1'b1;
            @(ia_if.cb);
            ia_if.cb.ia_data_valid <= 1'b0;
        end
        begin
            repeat (2) @(weight_if.cb);
            weight_if.cb.load_weight_req <= 1'b1;
            wait (weight_if.load_weight_granted);
            $display("%s  [%0t] [INFO] Weight Loader granted in interleaved test%s", 
                     COLOR_CYAN, $time, COLOR_RESET);
            @(weight_if.cb);
            weight_if.cb.load_weight_req <= 1'b0;
            repeat (3) @(weight_if.cb);
            weight_if.cb.weight_data_valid <= 1'b1;
            @(weight_if.cb);
            weight_if.cb.weight_data_valid <= 1'b0;
        end
        begin
            repeat (4) @(oa_if.cb);
            oa_if.cb.write_oa_req <= 1'b1;
            wait (oa_if.write_oa_granted);
            $display("%s  [%0t] [INFO] OA Writer granted in interleaved test (should preempt)%s",
                     COLOR_CYAN, $time, COLOR_RESET);
            @(oa_if.cb);
            oa_if.cb.write_oa_req <= 1'b0;
            repeat (2) @(oa_if.cb);
            oa_if.cb.write_done <= 1'b1;
            @(oa_if.cb);
            oa_if.cb.write_done <= 1'b0;
        end
    join

    repeat (10) @(posedge clk);

    $display("\n%s  [%0t] Complex arbitration test completed%s", 
             COLOR_BLUE, $time, COLOR_RESET);
endtask

`endif // TEST_ARBITER_TASKS_SVH
