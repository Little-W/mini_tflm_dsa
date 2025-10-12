`timescale 1ns / 1ps

module tb_mma_controller;

    // 参数定义
    parameter int unsigned WEIGHT_WIDTH = 8;
    parameter int unsigned DATA_WIDTH = 16;
    parameter int unsigned SIZE = 16;
    parameter int unsigned BUS_WIDTH = 32;
    parameter int unsigned REG_WIDTH = 32;
    parameter int unsigned CLK_PERIOD = 10;

    // ANSI颜色代码定义
    localparam string COLOR_RESET = "\033[0m";
    localparam string COLOR_RED = "\033[31m";
    localparam string COLOR_GREEN = "\033[32m";
    localparam string COLOR_YELLOW = "\033[33m";
    localparam string COLOR_BLUE = "\033[34m";
    localparam string COLOR_MAGENTA = "\033[35m";
    localparam string COLOR_CYAN = "\033[36m";
    localparam string COLOR_WHITE = "\033[37m";
    localparam string COLOR_GRAY  = "\033[90m"; // 新增灰色
    localparam string COLOR_BOLD = "\033[1m";

    // 组合颜色代码
    localparam string COLOR_BOLD_CYAN = "\033[1;36m";
    localparam string COLOR_BOLD_BLUE = "\033[1;34m";
    localparam string COLOR_BOLD_WHITE = "\033[1;37m";
    localparam string COLOR_BOLD_MAGENTA = "\033[1;35m";

    // 时钟和复位
    logic clk;
    logic rst_n;

    // 实例化接口
    control_if #(.REG_WIDTH(REG_WIDTH)) ctrl_if (clk);
    ia_loader_if ia_if (clk);
    weight_loader_if weight_if (clk);
    bias_loader_if bias_if (clk);
    requant_if quant_if (clk);
    oa_writer_if oa_if (clk);
    compute_core_if comp_if (clk);

    // 实例化DUT
    mma_controller #(
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .SIZE        (SIZE),
        .BUS_WIDTH   (BUS_WIDTH),
        .REG_WIDTH   (REG_WIDTH)
    ) dut (
        .clk                  (clk),
        .rst_n                (rst_n),
        .calc_start           (ctrl_if.calc_start),
        .cfg_16bits_ia        (ctrl_if.cfg_16bits_ia),
        .sa_ready             (ctrl_if.sa_ready),
        .icb_sel              (ctrl_if.icb_sel),
        .init_cfg_ia          (ctrl_if.init_cfg_ia),
        .init_cfg_weight      (ctrl_if.init_cfg_weight),
        .init_cfg_bias        (ctrl_if.init_cfg_bias),
        .init_cfg_requant     (ctrl_if.init_cfg_requant),
        .init_cfg_oa          (ctrl_if.init_cfg_oa),
        .use_16bits           (ctrl_if.use_16bits),
        .tile_count           (ctrl_if.tile_count),
        .partial_sum_calc_over(comp_if.partial_sum_calc_over),
        .load_ia_req          (ia_if.load_ia_req),
        .load_ia_granted      (ia_if.load_ia_granted),
        .send_ia_trigger      (ia_if.send_ia_trigger),
        .ia_sending_done      (ia_if.ia_sending_done),
        .ia_data_valid        (ia_if.ia_data_valid),
        .load_weight_req      (weight_if.load_weight_req),
        .load_weight_granted  (weight_if.load_weight_granted),
        .send_weight_trigger  (weight_if.send_weight_trigger),
        .weight_sending_done  (weight_if.weight_sending_done),
        .weight_data_valid    (weight_if.weight_data_valid),
        .load_bias_req        (bias_if.load_bias_req),
        .load_bias_granted    (bias_if.load_bias_granted),
        .bias_valid           (bias_if.bias_valid),
        .load_quant_req       (quant_if.load_quant_req),
        .load_quant_granted   (quant_if.load_quant_granted),
        .quant_params_valid   (quant_if.quant_params_valid),
        .fifo_full_flag       (ctrl_if.fifo_full_flag),
        .write_oa_req         (oa_if.write_oa_req),
        .write_oa_granted     (oa_if.write_oa_granted),
        .write_done           (oa_if.write_done),
        .oa_calc_over         (oa_if.oa_calc_over)
    );

    // 时钟生成
    initial begin
        clk = 0;
        forever #(CLK_PERIOD / 2) clk = ~clk;
    end

    // 波形dump
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_mma_controller);
    end

    // 包含所有测试任务文件
    `include "test_monitor_tasks.svh"
    `include "test_compute_tasks.svh"
    `include "test_arbiter_tasks.svh"

    // 主测试流程
    initial begin
        // 初始化信号 - 使用clocking block
        rst_n = 1'b0;

        // 等待一个时钟周期后使用clocking block初始化
        @(posedge clk);
        @(ctrl_if.cb);
        ctrl_if.cb.calc_start     <= 1'b0;
        ctrl_if.cb.cfg_16bits_ia  <= 1'b0;
        ctrl_if.cb.fifo_full_flag <= 1'b0;

        @(comp_if.cb);
        comp_if.cb.partial_sum_calc_over <= 1'b0;
        comp_if.cb.tile_calc_over        <= 1'b0;

        @(ia_if.cb);
        ia_if.cb.load_ia_req     <= 1'b0;
        ia_if.cb.ia_sending_done <= 1'b0;
        ia_if.cb.ia_calc_done    <= 1'b0;
        ia_if.cb.ia_data_valid   <= 1'b0;

        @(weight_if.cb);
        weight_if.cb.load_weight_req     <= 1'b0;
        weight_if.cb.weight_sending_done <= 1'b0;
        weight_if.cb.weight_data_valid   <= 1'b0;

        @(bias_if.cb);
        bias_if.cb.load_bias_req <= 1'b0;
        bias_if.cb.bias_valid    <= 1'b0;

        @(quant_if.cb);
        quant_if.cb.load_quant_req     <= 1'b0;
        quant_if.cb.quant_params_valid <= 1'b0;

        @(oa_if.cb);
        oa_if.cb.write_oa_req <= 1'b0;
        oa_if.cb.write_done   <= 1'b0;
        oa_if.cb.oa_calc_over <= 1'b0;

        // 复位
        repeat (5) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        $display("%s========== Test Start ==========%s", COLOR_BOLD_WHITE, COLOR_RESET);

        // 测试1：基本计算流程（封装为 task）
        $display("\n%s[Test 1] Basic computation flow (8-bit mode) - task%s", COLOR_BOLD_CYAN,
                 COLOR_RESET);
        simulate_block_computation(1'b0);  // 8-bit 模式

        // 可以再次以 16-bit 模式调用： simulate_block_computation(1'b1);
        // repeat (20) @(posedge clk);
        // // 调用封装好的简单仲裁测试 task
        // simple_arbiter_test();

        // 测试3：复杂仲裁场景
        // test_complex_arbitration();

        repeat (20) @(posedge clk);

        $display("\n%s========== Test Completed ==========%s", COLOR_BOLD_WHITE, COLOR_RESET);
        $finish;
    end

    // 启动监控任务
    initial begin
        fork
            monitor_arbitration();
        join_none
    end

    // 超时保护
    initial begin
        #100000;
        $display("\n%sERROR: Simulation timeout!%s", COLOR_RED, COLOR_RESET);
        $finish;
    end

endmodule
