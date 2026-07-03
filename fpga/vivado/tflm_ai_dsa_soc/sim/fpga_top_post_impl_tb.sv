`timescale 1ns / 1ps

module fpga_top_post_impl_tb #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned ICB_LEN_W = 4,
    parameter int unsigned IA_CACHE_BLOCKS = 4,
    parameter int unsigned CPU_MEM_DP = 65536,
    parameter string       CPU_MEM_PATH = "",
    parameter int unsigned CPU_ENABLE_ICACHE = 1,
    parameter int unsigned CPU_AXI_WRITE_TIMING_BUFFER = 1,
    parameter int unsigned BYPASS_RAM_PINGPONG = 0,
    parameter int unsigned RAM_WRITE_TIMING_BUFFER = 1
);
    localparam int unsigned MAX_SYS_CYCLES = 2_000_000;

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
        repeat (20) @(posedge sys_clk);
        sys_rst_n = 1'b1;
    end

    initial begin : watchdog
        int unsigned cycle_count;

        cycle_count = 0;
        forever begin
            @(posedge sys_clk);
            cycle_count++;

            if (user_led[2] === 1'b1) begin
                $fatal(1, "[POST_IMPL_SMOKE] FAIL: cpu_trap asserted at sys_cycle=%0d", cycle_count);
            end

            if (user_led[1] === 1'b1) begin
                repeat (100) @(posedge sys_clk);
                if (user_led[2] === 1'b1) begin
                    $fatal(1, "[POST_IMPL_SMOKE] FAIL: cpu_trap asserted after finish");
                end
                $display("[POST_IMPL_SMOKE] PASS: soc_finish asserted at sys_cycle=%0d", cycle_count);
                $finish;
            end

            if (cycle_count >= MAX_SYS_CYCLES) begin
                $fatal(1, "[POST_IMPL_SMOKE] TIMEOUT after %0d sys_clk cycles", MAX_SYS_CYCLES);
            end
        end
    end
endmodule
