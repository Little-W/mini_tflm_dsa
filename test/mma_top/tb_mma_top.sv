`timescale 1ns / 1ps
`include "icb_types.svh"
`include "icb_ext_if.sv"
`include "mma_top_if.sv"

module tb_mma_top;
    // 时钟复位
    logic clk = 0;
    always #5 clk = ~clk;  // 100MHz
    logic rst_n = 0;
    initial begin
        rst_n = 0;
        repeat (5) @(posedge clk);
        rst_n = 1;
    end

    localparam int unsigned SIZE = 4;
    localparam int unsigned REGW = 32;
    localparam int unsigned LK = 4;   // K 维度
    localparam int unsigned LN = 16;  // N 维度
    localparam int unsigned LM = 16;  // M 维度

    // 布局
    localparam logic [31:0] LHS_BASE = 32'h0000_0000;
    localparam logic [31:0] RHS_BASE = 32'h0000_0400;
    localparam logic [31:0] BIAS_BASE = 32'h0000_0800;
    localparam logic [31:0] DST_BASE = 32'h0000_0C00;

    localparam logic [31:0] LHS_ROW_STRIDE_B = LN * 2;  // K×N, 16-bit, 每行 N 个元素
    localparam logic [31:0] RHS_ROW_STRIDE_B = LM * 1;  // N×M, 8-bit, 每行 M 个元素
    localparam logic [31:0] DST_ROW_STRIDE_B = LM * 1;  // K×M, 8-bit, 每行 M 个元素

    localparam logic signed [31:0] LHS_ZP = 32'sd0;
    localparam logic signed [31:0] RHS_ZP = 32'sd0;
    localparam logic signed [31:0] DST_ZP = 32'sd0;
    localparam logic signed [31:0] QMUL = 32'sd1;
    localparam logic signed [31:0] QSHIFT = 32'sd0;
    localparam logic signed [31:0] ACT_MIN = -128;
    localparam logic signed [31:0] ACT_MAX = 127;

    // Interface 实例化
    mma_top_if #(
        .REG_WIDTH(REGW)
    ) mma_cfg_if (
        .clk  (clk),
        .rst_n(rst_n)
    );
    icb_ext_if #(
        .ADDR_W(19),
        .WIDTH (32),
        .LEN_W (3)
    ) icb_bus (
        .clk  (clk),
        .rst_n(rst_n)
    );

    // DUT 实例
    mma_top #(
        .SIZE(SIZE)
    ) u_dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .calc_start   (mma_cfg_if.calc_start),
        .cfg_16bits_ia(mma_cfg_if.cfg_16bits_ia),
        .sa_ready     (mma_cfg_if.sa_ready),

        .lhs_base (mma_cfg_if.lhs_base),
        .rhs_base (mma_cfg_if.rhs_base),
        .dst_base (mma_cfg_if.dst_base),
        .bias_base(mma_cfg_if.bias_base),

        .lhs_zp         (mma_cfg_if.lhs_zp),
        .rhs_zp         (mma_cfg_if.rhs_zp),
        .dst_zp         (mma_cfg_if.dst_zp),
        .q_mult_pt      (mma_cfg_if.q_mult_pt),
        .q_shift_pt     (mma_cfg_if.q_shift_pt),
        .use_per_channel(mma_cfg_if.use_per_channel),

        .k(mma_cfg_if.k),
        .n(mma_cfg_if.n),
        .m(mma_cfg_if.m),

        .lhs_row_stride_b(mma_cfg_if.lhs_row_stride_b),
        .dst_row_stride_b(mma_cfg_if.dst_row_stride_b),
        .rhs_row_stride_b(mma_cfg_if.rhs_row_stride_b),

        .act_min(mma_cfg_if.act_min),
        .act_max(mma_cfg_if.act_max),

        .sa_icb_cmd      (icb_bus.cmd_m),
        .sa_icb_wr       (icb_bus.wr_m),
        .sa_icb_cmd_ready(icb_bus.cmd_s),
        .sa_icb_w_ready  (icb_bus.wr_s),
        .sa_icb_rsp      (icb_bus.rsp_s),
        .sa_icb_rsp_ready(icb_bus.rsp_m)
    );

    // 扁平信号用于连接 bridge
    wire        icb_cmd_valid;
    wire        icb_cmd_ready;
    wire [18:0] icb_cmd_addr;
    wire        icb_cmd_read;
    wire [ 2:0] icb_cmd_len;
    wire [31:0] icb_cmd_wdata;
    wire [ 3:0] icb_cmd_wmask;
    wire        icb_w_valid;
    wire        icb_w_ready;
    wire        icb_rsp_valid;
    wire        icb_rsp_ready;
    wire [31:0] icb_rsp_rdata;
    wire        icb_rsp_err;

    // Interface -> 扁平端口适配
    icb_ext_flat_adapter #(
        .WIDTH (32),
        .ADDR_W(19),
        .LEN_W (3)
    ) u_if2bridge (
        .clk  (clk),
        .rst_n(rst_n),

        // 打包信号输入（直接连接 interface 的信号）
        .icb_cmd_m(icb_bus.cmd_m),
        .icb_wr_m (icb_bus.wr_m),
        .icb_cmd_s(icb_bus.cmd_s),
        .icb_wr_s (icb_bus.wr_s),
        .icb_rsp_s(icb_bus.rsp_s),
        .icb_rsp_m(icb_bus.rsp_m),

        .sa_icb_cmd_valid(icb_cmd_valid),
        .sa_icb_cmd_ready(icb_cmd_ready),
        .sa_icb_cmd_addr (icb_cmd_addr),
        .sa_icb_cmd_read (icb_cmd_read),
        .sa_icb_cmd_len  (icb_cmd_len),
        .sa_icb_cmd_wdata(icb_cmd_wdata),
        .sa_icb_cmd_wmask(icb_cmd_wmask),
        .sa_icb_w_valid  (icb_w_valid),
        .sa_icb_w_ready  (icb_w_ready),
        .sa_icb_rsp_valid(icb_rsp_valid),
        .sa_icb_rsp_ready(icb_rsp_ready),
        .sa_icb_rsp_rdata(icb_rsp_rdata),
        .sa_icb_rsp_err  (icb_rsp_err)
    );

    // Bridge 实例（SRAM）
    top_sram_icb_bridge #(
        .WIDTH       (32),
        .ADDR_W      (19),
        .AW_LSB      (2),
        .MW          (4),
        .USR_W       (1),
        .DP          (131072),
        .FORCE_X2ZERO(0)
    ) u_mem (
        .clk       (clk),
        .rst_n     (rst_n),
        .tcm_cgstop(1'b0),
        .test_mode (1'b0),

        .sa_icb_cmd_valid(icb_cmd_valid),
        .sa_icb_cmd_ready(icb_cmd_ready),
        .sa_icb_cmd_addr (icb_cmd_addr),
        .sa_icb_cmd_read (icb_cmd_read),
        .sa_icb_cmd_len  (icb_cmd_len),
        .sa_icb_cmd_wdata(icb_cmd_wdata),
        .sa_icb_cmd_wmask(icb_cmd_wmask),
        .sa_icb_w_valid  (icb_w_valid),
        .sa_icb_w_ready  (icb_w_ready),
        .sa_icb_rsp_valid(icb_rsp_valid),
        .sa_icb_rsp_ready(icb_rsp_ready),
        .sa_icb_rsp_rdata(icb_rsp_rdata),
        .sa_icb_rsp_err  (icb_rsp_err)
    );

    // 使用 clocking block 初始化配置
    initial begin
        @(posedge rst_n);
        @(mma_cfg_if.cb_cfg);
        mma_cfg_if.cb_cfg.cfg_16bits_ia    <= 1'b1;
        mma_cfg_if.cb_cfg.lhs_base         <= LHS_BASE;
        mma_cfg_if.cb_cfg.rhs_base         <= RHS_BASE;
        mma_cfg_if.cb_cfg.dst_base         <= DST_BASE;
        mma_cfg_if.cb_cfg.bias_base        <= BIAS_BASE;
        mma_cfg_if.cb_cfg.lhs_zp           <= LHS_ZP;
        mma_cfg_if.cb_cfg.rhs_zp           <= RHS_ZP;
        mma_cfg_if.cb_cfg.dst_zp           <= DST_ZP;
        mma_cfg_if.cb_cfg.q_mult_pt        <= QMUL;
        mma_cfg_if.cb_cfg.q_shift_pt       <= QSHIFT;
        mma_cfg_if.cb_cfg.use_per_channel  <= 1'b0;
        mma_cfg_if.cb_cfg.k                <= LK;
        mma_cfg_if.cb_cfg.n                <= LN;
        mma_cfg_if.cb_cfg.m                <= LM;
        mma_cfg_if.cb_cfg.lhs_row_stride_b <= LHS_ROW_STRIDE_B;
        mma_cfg_if.cb_cfg.dst_row_stride_b <= DST_ROW_STRIDE_B;
        mma_cfg_if.cb_cfg.rhs_row_stride_b <= RHS_ROW_STRIDE_B;
        mma_cfg_if.cb_cfg.act_min          <= ACT_MIN;
        mma_cfg_if.cb_cfg.act_max          <= ACT_MAX;
        mma_cfg_if.cb_cfg.calc_start       <= 1'b0;
    end

    // 使用 clocking block 驱动 rsp_ready
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) icb_bus.rsp_m.rsp_ready <= 1'b0;
        else icb_bus.rsp_m.rsp_ready <= 1'b1;
    end

    // 层级引用加载内存
    string init_mem_path, golden_mem_path;
    localparam int MEMW = 32;
    localparam int MEMDP = 131072;
    reg [MEMW-1:0] golden_mem[0:MEMDP-1];

    initial begin
        if (!$value$plusargs("INIT_MEM=%s", init_mem_path)) init_mem_path = "out/init.mem";
        if (!$value$plusargs("GOLDEN_MEM=%s", golden_mem_path)) golden_mem_path = "out/golden.mem";
        $display("[TB] INIT_MEM=%s", init_mem_path);
        $display("[TB] GOLDEN_MEM=%s", golden_mem_path);

        $dumpfile("wave.vcd");
        $dumpvars(0, tb_mma_top);

        $readmemh(init_mem_path, u_mem.u_sram_icb.u_sram.mem_r);
        $readmemh(golden_mem_path, golden_mem);
    end

    // 使用 clocking block 触发计算
    initial begin
        wait (rst_n);
        repeat (5) @(mma_cfg_if.cb_cfg);
        mma_cfg_if.cb_cfg.calc_start <= 1'b1;
        @(mma_cfg_if.cb_cfg);
        mma_cfg_if.cb_cfg.calc_start <= 1'b0;
    end

    // 校验
    initial begin
        @(posedge rst_n);

        // 等待 calc_start 被触发
        @(posedge mma_cfg_if.calc_start);
        $display("[TB] calc_start triggered at time %0t", $time);

        // 等待 sa_ready 变为 0（计算开始）
        wait (mma_cfg_if.sa_ready == 1'b0);
        $display("[TB] Computation started (sa_ready=0) at time %0t", $time);

        // 等待 sa_ready 恢复为 1（计算完成）
        wait (mma_cfg_if.sa_ready == 1'b1);
        $display("[TB] Computation done (sa_ready=1) at time %0t", $time);

        // 额外等待几个周期确保结果写入完成
        repeat (10) @(posedge clk);

        int err = 0;
        for (int i = 0; i < 4096; i++) begin
            if (u_mem.u_sram_icb.u_sram.mem_r[i] !== golden_mem[i]) begin
                $display("[TB][MISMATCH] word %0d: got=%08x exp=%08x", i,
                         u_mem.u_sram_icb.u_sram.mem_r[i], golden_mem[i]);
                err++;
            end
        end
        if (err == 0) $display("[TB] PASS");
        else $display("[TB] FAIL, err=%0d", err);
        $finish;
    end

endmodule
