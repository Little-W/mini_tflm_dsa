`ifndef TEST_COMPUTE_TASKS_SVH
`define TEST_COMPUTE_TASKS_SVH

// Weight Loader 独立循环执行（16次：4 tile × 4 partial_sum）
task automatic simulate_weight_loader();
    int load_count;
    load_count = 0;

    $display("%s  === Weight loader started ===%s", COLOR_BOLD_BLUE, COLOR_RESET);

    while (load_count < 16) begin
        // 发起加载请求
        @(weight_if.cb);
        weight_if.cb.load_weight_req <= 1'b1;
        $display("  [%0t] Weight loader: requesting load (count=%0d)", $time, load_count);

        // 等待授权
        wait (weight_if.load_weight_granted);
        $display("  [%0t] Weight loader: granted", $time);

        // 清除请求并清除之前的 done 信号
        @(weight_if.cb);
        weight_if.cb.weight_sending_done <= 1'b0;
        weight_if.cb.load_weight_req     <= 1'b0;

        // 模拟数据加载延迟
        repeat (4) @(weight_if.cb);
        weight_if.cb.weight_data_valid <= 1'b1;
        $display("  [%0t] Weight data valid (count=%0d)", $time, load_count);

        // 等待发送触发
        wait (weight_if.send_weight_trigger);
        $display("  [%0t] Weight send triggered (count=%0d)", $time, load_count);

        // 立即清除 valid 信号
        @(weight_if.cb);
        weight_if.cb.weight_data_valid <= 1'b0;

        // 模拟发送延迟
        repeat (5) @(weight_if.cb);
        weight_if.cb.weight_sending_done <= 1'b1;
        $display("  [%0t] Weight sending done (count=%0d)", $time, load_count);

        load_count++;

        // 如果还有分块未完成，在发送完成后等待一个周期，准备下一次请求
        if (load_count < 16) begin
            @(weight_if.cb);
            @(posedge clk);
            weight_if.cb.weight_sending_done <= 1'b0;
        end
    end

    $display("%s  === Weight loader finished (total=%0d) ===%s", COLOR_BOLD_BLUE, load_count,
             COLOR_RESET);
endtask

// IA Loader 独立循环执行（16次）
task automatic simulate_ia_loader();
    int load_count;
    load_count = 0;

    $display("%s  === IA loader started ===%s", COLOR_BOLD_BLUE, COLOR_RESET);

    while (load_count < 16) begin
        // 发起加载请求
        @(ia_if.cb);
        ia_if.cb.load_ia_req <= 1'b1;
        $display("  [%0t] IA loader: requesting load (count=%0d)", $time, load_count);

        // 等待授权
        wait (ia_if.load_ia_granted);
        $display("  [%0t] IA loader: granted", $time);

        // 清除请求并清除之前的 done 信号
        @(ia_if.cb);
        ia_if.cb.ia_sending_done <= 1'b0;
        ia_if.cb.load_ia_req     <= 1'b0;

        // 模拟数据加载延迟
        repeat (4) @(ia_if.cb);
        ia_if.cb.ia_data_valid <= 1'b1;
        $display("  [%0t] IA data valid (count=%0d)", $time, load_count);

        // 等待发送触发
        wait (ia_if.send_ia_trigger);
        $display("  [%0t] IA send triggered (count=%0d)", $time, load_count);

        // 立即清除 valid 信号
        @(ia_if.cb);
        ia_if.cb.ia_data_valid <= 1'b0;

        // 模拟发送延迟
        repeat (5) @(ia_if.cb);
        ia_if.cb.ia_sending_done <= 1'b1;
        $display("  [%0t] IA sending done (count=%0d)", $time, load_count);

        load_count++;

        // 如果还有分块未完成，在发送完成后等待一个周期，准备下一次请求
        if (load_count < 16) begin
            @(ia_if.cb);
            @(posedge clk);
            ia_if.cb.ia_sending_done <= 1'b0;
        end
    end

    $display("%s  === IA loader finished (total=%0d) ===%s", COLOR_BOLD_BLUE, load_count,
             COLOR_RESET);
endtask

// Bias Loader 独立循环执行（4次：每个 tile 一次）
task automatic simulate_bias_loader();
    int load_count;
    load_count = 0;

    $display("%s  === Bias loader started ===%s", COLOR_BOLD_BLUE, COLOR_RESET);

    while (load_count < 4) begin
        // 发起加载请求
        @(bias_if.cb);
        bias_if.cb.load_bias_req <= 1'b1;
        $display("  [%0t] Bias loader: requesting load (tile=%0d)", $time, load_count);

        // 等待授权
        wait (bias_if.load_bias_granted);
        $display("  [%0t] Bias loader: granted (tile=%0d)", $time, load_count);

        @(bias_if.cb);
        bias_if.cb.load_bias_req <= 1'b0;

        // 模拟加载延迟后使偏置数据有效
        repeat (4) @(bias_if.cb);
        bias_if.cb.bias_valid <= 1'b1;
        $display("  [%0t] Bias data valid (tile=%0d)", $time, load_count);

        // 等待该 tile 完成（通过 tile_calc_over）
        wait (comp_if.tile_calc_over);
        $display("  [%0t] Bias loader: tile done, clearing valid (tile=%0d)", $time, load_count);

        @(bias_if.cb);
        bias_if.cb.bias_valid <= 1'b0;

        load_count++;
    end

    $display("%s  === Bias loader finished (total=%0d tiles) ===%s", COLOR_BOLD_BLUE, load_count,
             COLOR_RESET);
endtask

// Quant Loader 独立循环执行（4次：每个 tile 一次）
task automatic simulate_quant_loader();
    int load_count;
    load_count = 0;

    $display("%s  === Quant loader started ===%s", COLOR_BOLD_BLUE, COLOR_RESET);

    while (load_count < 4) begin
        // 发起加载请求
        @(quant_if.cb);
        quant_if.cb.load_quant_req <= 1'b1;
        $display("  [%0t] Quant loader: requesting load (tile=%0d)", $time, load_count);

        // 等待授权
        wait (quant_if.load_quant_granted);
        $display("  [%0t] Quant loader: granted (tile=%0d)", $time, load_count);

        @(quant_if.cb);
        quant_if.cb.load_quant_req <= 1'b0;

        // 模拟加载延迟后使量化参数有效
        repeat (4) @(quant_if.cb);
        quant_if.cb.quant_params_valid <= 1'b1;
        $display("  [%0t] Quant params valid (tile=%0d)", $time, load_count);

        // 等待该 tile 完成（通过 tile_calc_over）
        wait (comp_if.tile_calc_over);
        $display("  [%0t] Quant loader: tile done, clearing valid (tile=%0d)", $time, load_count);

        @(quant_if.cb);
        quant_if.cb.quant_params_valid <= 1'b0;

        load_count++;
    end

    $display("%s  === Quant loader finished (total=%0d tiles) ===%s", COLOR_BOLD_BLUE, load_count,
             COLOR_RESET);
endtask

// OA Writer 任务保持不变（已经是独立循环）
task automatic simulate_oa_writer();
    int write_count;
    write_count = 0;
    $display("%s  === OA writer started ===%s", COLOR_BOLD_BLUE, COLOR_RESET);
    forever begin
        // 等待某个 tile 的最后一个部分和完成（由 compute core 发出）
        wait (comp_if.tile_calc_over);
        $display("%s  [%0t] OA writer: detected tile_calc_over, requesting write (count=%0d)%s",
                 COLOR_MAGENTA, $time, write_count, COLOR_RESET);

        // 请求写回
        @(oa_if.cb);
        oa_if.cb.write_oa_req <= 1'b1;

        // 等待授权
        wait (oa_if.write_oa_granted);
        $display("%s  [%0t] OA writer: write granted%s", COLOR_MAGENTA, $time, COLOR_RESET);

        // 发送完请求后立即清除请求信号（在下一个 cb 周期）
        @(oa_if.cb);
        oa_if.cb.write_oa_req <= 1'b0;

        // 模拟写回延迟
        repeat (10) @(oa_if.cb);
        oa_if.cb.write_done <= 1'b1;
        $display("%s  [%0t] OA writer: write_done asserted%s", COLOR_MAGENTA, $time, COLOR_RESET);

        // 在一个时钟沿后清除 write_done
        @(oa_if.cb);
        @(posedge clk);
        oa_if.cb.write_done <= 1'b0;

        write_count++;

        // 如果所有 4 个 tile 都写回完毕（tile_idx = 0..3 -> count == 4），设置 oa_calc_over 并退出
        if (write_count == 4) begin
            @(oa_if.cb);
            oa_if.cb.oa_calc_over <= 1'b1;
            $display("%s  [%0t] OA writer: all tiles written, oa_calc_over asserted%s",
                     COLOR_BOLD_MAGENTA, $time, COLOR_RESET);
            @(oa_if.cb);
            @(posedge clk);
            oa_if.cb.oa_calc_over <= 1'b0;
            $display("%s  === OA writer finished ===%s", COLOR_BOLD_BLUE, COLOR_RESET);
            return;
        end
    end
endtask

// Compute Core 模拟任务（模拟 16 次部分和计算和 4 次 tile 完成）
task automatic simulate_compute_core();
    int partial_sum_count, tile_idx;
    partial_sum_count = 0;
    tile_idx          = 0;

    $display("%s  === Compute core simulator started ===%s", COLOR_BOLD_WHITE, COLOR_RESET);

    while (partial_sum_count < 16) begin
        // 等待 weight 和 ia 数据都准备好（通过 sending_done 信号）
        wait (ia_if.ia_sending_done);

        $display("%s  [%0t] Compute: starting partial sum %0d (tile %0d, round %0d/4)%s",
                 COLOR_WHITE, $time, partial_sum_count, tile_idx, (partial_sum_count % 4) + 1,
                 COLOR_RESET);

        // 模拟部分和计算延迟
        repeat (10) @(comp_if.cb);

        // 断言 partial_sum_calc_over
        comp_if.cb.partial_sum_calc_over <= 1'b1;
        $display("%s  [%0t] Compute: partial_sum_calc_over asserted (count=%0d)%s", COLOR_WHITE,
                 $time, partial_sum_count, COLOR_RESET);

        // 检查是否是 tile 的最后一个部分和
        if ((partial_sum_count % 4) == 3) begin
            comp_if.cb.tile_calc_over <= 1'b1;
            $display("%s  [%0t] Compute: tile_calc_over asserted (tile %0d completed)%s",
                     COLOR_WHITE, $time, tile_idx, COLOR_RESET);
            tile_idx++;
        end

        @(comp_if.cb);
        @(posedge clk);
        comp_if.cb.partial_sum_calc_over <= 1'b0;
        comp_if.cb.tile_calc_over        <= 1'b0;

        partial_sum_count++;
    end

    $display("%s  === Compute core simulator finished (total=%0d partial sums, %0d tiles) ===%s",
             COLOR_BOLD_WHITE, partial_sum_count, tile_idx, COLOR_RESET);
endtask

// 主计算任务 - 启动所有独立任务并等待完成
task automatic simulate_block_computation(input bit cfg16);
    $display("\n%s  === Starting block computation (cfg16=%0b) ===%s", COLOR_BOLD_BLUE, cfg16,
             COLOR_RESET);

    // 配置位与启动
    @(ctrl_if.cb);
    ctrl_if.cb.cfg_16bits_ia <= cfg16;
    ctrl_if.cb.calc_start    <= 1'b1;
    @(ctrl_if.cb);
    @(posedge clk);
    ctrl_if.cb.calc_start <= 1'b0;

    // 等待初始化完成
    wait (ctrl_if.init_cfg_ia && ctrl_if.init_cfg_weight);
    $display("%s  [%0t] Initialization completed (cfg16=%0b)%s", COLOR_BLUE, $time, cfg16,
             COLOR_RESET);

    // 并发启动所有独立任务
    fork
        simulate_weight_loader();
        simulate_ia_loader();
        simulate_bias_loader();
        simulate_quant_loader();
        simulate_oa_writer();
        simulate_compute_core();
    join

    // 所有任务完成后，等待 oa_calc_over 信号
    $display("%s  [%0t] All simulation tasks completed, waiting for oa_calc_over%s", COLOR_BLUE,
             $time, COLOR_RESET);
    wait (oa_if.oa_calc_over);
    $display("%s  [%0t] OA calculation done (detected oa_calc_over)%s", COLOR_BLUE, $time,
             COLOR_RESET);

    // 等待控制器返回 IDLE 并就绪
    wait (ctrl_if.sa_ready);
    $display("%s  [%0t] Controller ready after block computation (cfg16=%0b)%s", COLOR_BLUE, $time,
             cfg16, COLOR_RESET);
    $display("%s  === Block computation completed (cfg16=%0b) ===%s\n", COLOR_BOLD_BLUE, cfg16,
             COLOR_RESET);
endtask

`endif  // TEST_COMPUTE_TASKS_SVH
