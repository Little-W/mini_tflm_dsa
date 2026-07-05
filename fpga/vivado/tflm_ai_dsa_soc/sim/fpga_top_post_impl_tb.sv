`timescale 1ns / 1ps

module fpga_top_post_impl_tb #(
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
    parameter int unsigned NPU_ENABLE_CLOCK_GATING = 1,
    parameter int unsigned RESET_CYCLES = 20,
    parameter int unsigned FINISH_DRAIN_CYCLES = 100,
    parameter int unsigned MAX_SYS_CYCLES = 10_000_000
);
    logic       sys_clk = 1'b0;
    logic       sys_rst_n = 1'b0;
    logic       uart_rx = 1'b1;
    wire        uart_tx;
    wire [3:0]  user_led;

    fpga_top dut (
        .sys_clk(sys_clk),
        .sys_rst_n(sys_rst_n),
        .UART_0_rxd(uart_rx),
        .UART_0_txd(uart_tx),
        .user_led_tri_o(user_led)
    );

    always #10ns sys_clk = ~sys_clk;

    initial begin
        $display("[POST_IMPL_SMOKE] cfg SIZE=%0d IA_CACHE_BLOCKS=%0d WEIGHT_WIDTH=%0d DATA_WIDTH=%0d CPU_MEM_DP=%0d",
                 SIZE, IA_CACHE_BLOCKS, WEIGHT_WIDTH, DATA_WIDTH, CPU_MEM_DP);
        $display("[POST_IMPL_SMOKE] cfg CPU_MEM_PATH=%s", CPU_MEM_PATH);
        $display("[POST_IMPL_SMOKE] cfg NPU_ADDR_WIDTH=%0d IS=%0d PER_CHANNEL=%0d CLK_GATE=%0d MAX_SYS_CYCLES=%0d",
                 NPU_ADDR_WIDTH, NPU_ENABLE_IS_MODE, NPU_ENABLE_PER_CHANNEL,
                 NPU_ENABLE_CLOCK_GATING, MAX_SYS_CYCLES);
        repeat (RESET_CYCLES) @(posedge sys_clk);
        sys_rst_n = 1'b1;
    end

    initial begin : watchdog
        longint unsigned cycle_count;
        logic [3:0] last_led;
        logic       test_done;

        cycle_count = 0;
        last_led = 4'hx;
        test_done = 1'b0;
        forever begin
            @(posedge sys_clk);
            if (test_done) begin
                continue;
            end
            cycle_count++;

            if (user_led !== last_led) begin
                last_led = user_led;
                $display("[POST_IMPL_SMOKE] user_led=%b at sys_cycle=%0d",
                         user_led, cycle_count);
            end

            if (user_led[2] === 1'b1) begin
                $display("[POST_IMPL_SMOKE] FAIL: fail_led asserted at sys_cycle=%0d led=%b",
                         cycle_count, user_led);
                test_done = 1'b1;
                $finish;
            end

            if (user_led[1] === 1'b1) begin
                repeat (FINISH_DRAIN_CYCLES) @(posedge sys_clk);
                if (user_led[2] === 1'b1) begin
                    $display("[POST_IMPL_SMOKE] FAIL: cpu_trap asserted after finish");
                    test_done = 1'b1;
                    $finish;
                end
                $display("[POST_IMPL_SMOKE] PASS: soc_finish asserted at sys_cycle=%0d", cycle_count);
                test_done = 1'b1;
                $finish;
            end

            if (cycle_count >= MAX_SYS_CYCLES) begin
                $display("[POST_IMPL_SMOKE] TIMEOUT after %0d sys_clk cycles led=%b",
                         MAX_SYS_CYCLES, user_led);
                test_done = 1'b1;
                $finish;
            end
        end
    end
endmodule
