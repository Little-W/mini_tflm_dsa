`timescale 1ns / 1ps

module fpga_top_behav_smoke_tb #(
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned SIZE = 16,
    parameter int unsigned IA_CACHE_BLOCKS = 4,
    parameter int unsigned CPU_MEM_DP = 65536,
    parameter string       CPU_MEM_PATH = "",
    parameter int unsigned CPU_ENABLE_ICACHE = 1,
    parameter int unsigned CPU_AXI_WRITE_TIMING_BUFFER = 1,
    parameter int unsigned BYPASS_RAM_PINGPONG = 0,
    parameter int unsigned RAM_WRITE_TIMING_BUFFER = 1,
    parameter int unsigned NPU_ADDR_WIDTH = 32,
    parameter int unsigned NPU_ENABLE_IS_MODE = 1,
    parameter int unsigned NPU_ENABLE_PER_CHANNEL = 1,
    parameter int unsigned MAX_SYS_CYCLES = 2_000_000
);
    logic      sys_clk = 1'b0;
    logic      sys_rst_n = 1'b0;
    logic      uart_rx = 1'b1;
    wire       uart_tx;
    wire [3:0] user_led;

    fpga_top #(
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .SIZE(SIZE),
        .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS),
        .CPU_MEM_DP(CPU_MEM_DP),
        .CPU_MEM_PATH(CPU_MEM_PATH),
        .CPU_MEM_INIT_EN(1),
        .CPU_ENABLE_ICACHE(CPU_ENABLE_ICACHE),
        .CPU_AXI_WRITE_TIMING_BUFFER(CPU_AXI_WRITE_TIMING_BUFFER),
        .BYPASS_RAM_PINGPONG(BYPASS_RAM_PINGPONG),
        .RAM_WRITE_TIMING_BUFFER(RAM_WRITE_TIMING_BUFFER),
        .NPU_ADDR_WIDTH(NPU_ADDR_WIDTH),
        .NPU_ENABLE_IS_MODE(NPU_ENABLE_IS_MODE),
        .NPU_ENABLE_PER_CHANNEL(NPU_ENABLE_PER_CHANNEL)
    ) dut (
        .sys_clk(sys_clk),
        .sys_rst_n(sys_rst_n),
        .UART_0_rxd(uart_rx),
        .UART_0_txd(uart_tx),
        .user_led_tri_o(user_led)
    );

    always #10ns sys_clk = ~sys_clk;

    initial begin
        repeat (20) @(posedge sys_clk);
        sys_rst_n = 1'b1;
    end

    initial begin : watchdog
        int unsigned cycle_count;
        logic [31:0] last_progress;

        cycle_count = 0;
        last_progress = 32'hffff_ffff;
        forever begin
            @(posedge sys_clk);
            cycle_count++;

            if (dut.u_soc_top.soc_progress !== last_progress) begin
                last_progress = dut.u_soc_top.soc_progress;
                $display("[BEHAV_SMOKE] progress=0x%08x at sys_cycle=%0d",
                         last_progress, cycle_count);
            end

            if (user_led[2] === 1'b1) begin
                $fatal(1,
                       "[BEHAV_SMOKE] FAIL: cpu_trap at sys_cycle=%0d status=0x%08x progress=0x%08x",
                       cycle_count, dut.soc_status, dut.u_soc_top.soc_progress);
            end

            if (user_led[1] === 1'b1) begin
                repeat (100) @(posedge sys_clk);
                if (user_led[2] === 1'b1) begin
                    $fatal(1, "[BEHAV_SMOKE] FAIL: cpu_trap asserted after finish");
                end
                $display("[BEHAV_SMOKE] PASS: soc_finish at sys_cycle=%0d status=0x%08x progress=0x%08x",
                         cycle_count, dut.soc_status, dut.u_soc_top.soc_progress);
                $finish;
            end

            if (cycle_count >= MAX_SYS_CYCLES) begin
                $fatal(1,
                       "[BEHAV_SMOKE] TIMEOUT after %0d sys_clk cycles status=0x%08x progress=0x%08x trap=%0b",
                       MAX_SYS_CYCLES, dut.soc_status, dut.u_soc_top.soc_progress,
                       user_led[2]);
            end
        end
    end
endmodule
