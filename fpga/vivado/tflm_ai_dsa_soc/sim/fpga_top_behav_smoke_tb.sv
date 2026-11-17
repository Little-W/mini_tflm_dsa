`timescale 1ns / 1ps

module fpga_top_behav_smoke_tb #(
    parameter int unsigned WEIGHT_WIDTH = 16,
    parameter int unsigned DATA_WIDTH = 16,
    parameter int unsigned SIZE = 16,
    parameter int unsigned BUS_WIDTH = 64,
    parameter int unsigned SHARED_BANK_BYTES = 8192,
    parameter int unsigned SHARED_BANK_COUNT = 7,
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
    parameter int unsigned MAX_SYS_CYCLES = 10_000_000,
    parameter bit          UART_MONITOR_ENABLE = 1'b1,
    parameter int unsigned UART_LINE_MAX = 256
);
    logic      sys_clk = 1'b0;
    logic      sys_rst_n = 1'b0;
    logic      uart_rx = 1'b1;
    wire       uart_tx;
    wire [3:0] user_led;
    logic      uart_fail_seen = 1'b0;
    string     uart_line = "";
    string     uart_fail_line = "";

    fpga_top #(
        .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .DATA_WIDTH(DATA_WIDTH),
        .SIZE(SIZE),
        .BUS_WIDTH(BUS_WIDTH),
        .SHARED_BANK_BYTES(SHARED_BANK_BYTES),
        .SHARED_BANK_COUNT(SHARED_BANK_COUNT),
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
        .NPU_ENABLE_PER_CHANNEL(NPU_ENABLE_PER_CHANNEL),
        .NPU_ENABLE_CLOCK_GATING(NPU_ENABLE_CLOCK_GATING)
    ) dut (
        .sys_clk(sys_clk),
        .sys_rst_n(sys_rst_n),
        .UART_0_rxd(uart_rx),
        .UART_0_txd(uart_tx),
        .user_led_tri_o(user_led)
    );

    always #10ns sys_clk = ~sys_clk;

    function automatic bit str_contains(input string text, input string needle);
        int text_len;
        int needle_len;
        int idx;

        text_len = text.len();
        needle_len = needle.len();
        if (needle_len == 0) begin
            return 1'b1;
        end
        if (text_len < needle_len) begin
            return 1'b0;
        end
        for (idx = 0; idx <= text_len - needle_len; idx++) begin
            if (text.substr(idx, idx + needle_len - 1) == needle) begin
                return 1'b1;
            end
        end
        return 1'b0;
    endfunction

    task automatic check_uart_line(input string line);
        if (line.len() == 0) begin
            return;
        end

        $display("[BEHAV_UART] %s", line);
        if (str_contains(line, "mismatch") ||
            str_contains(line, "FAIL") ||
            str_contains(line, "failed") ||
            str_contains(line, "Failed") ||
            str_contains(line, "error") ||
            str_contains(line, "Error")) begin
            uart_fail_seen = 1'b1;
            uart_fail_line = line;
            $display("[BEHAV_UART] FAIL: %s", line);
        end
    endtask

    task automatic record_uart_byte(input byte ch);
        if (ch == 8'h0d) begin
            return;
        end
        if (ch == 8'h0a) begin
            check_uart_line(uart_line);
            uart_line = "";
        end else if ((ch >= 8'h20) && (ch < 8'h7f)) begin
            if (uart_line.len() < UART_LINE_MAX) begin
                uart_line = {uart_line, ch};
            end
        end
    endtask

    initial begin : uart_monitor
        if (UART_MONITOR_ENABLE) begin
            wait (sys_rst_n === 1'b1);
            $display("[BEHAV_UART] monitor enabled on simpleuart accepted bytes");

            forever begin
                @(posedge dut.soc_clk);
                if (dut.u_soc_top.u_soc_uart.u_simpleuart.reg_dat_we &&
                    (dut.u_soc_top.u_soc_uart.u_simpleuart.send_bitcnt == 0)) begin
                    record_uart_byte(byte'(dut.u_soc_top.u_soc_uart.u_simpleuart.reg_dat_di[7:0]));
                end
            end
        end
    end

    initial begin
        if (CPU_MEM_PATH == "") begin
            $display("[BEHAV_SMOKE] FAIL: CPU_MEM_PATH is empty");
            $finish;
        end
        $display("[BEHAV_SMOKE] cfg SIZE=%0d IA_CACHE_BLOCKS=%0d WEIGHT_WIDTH=%0d DATA_WIDTH=%0d CPU_MEM_DP=%0d",
                 SIZE, IA_CACHE_BLOCKS, WEIGHT_WIDTH, DATA_WIDTH, CPU_MEM_DP);
        $display("[BEHAV_SMOKE] cfg CPU_MEM_PATH=%s", CPU_MEM_PATH);
        $display("[BEHAV_SMOKE] cfg NPU_ADDR_WIDTH=%0d IS=%0d PER_CHANNEL=%0d CLK_GATE=%0d MAX_SYS_CYCLES=%0d",
                 NPU_ADDR_WIDTH, NPU_ENABLE_IS_MODE, NPU_ENABLE_PER_CHANNEL,
                 NPU_ENABLE_CLOCK_GATING, MAX_SYS_CYCLES);
        repeat (RESET_CYCLES) @(posedge sys_clk);
        sys_rst_n = 1'b1;
    end

    initial begin : watchdog
        longint unsigned cycle_count;
        logic [3:0]  last_led;
        logic        test_done;

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
                $display("[BEHAV_SMOKE] user_led=%b at sys_cycle=%0d",
                         user_led, cycle_count);
            end

            if (user_led[2] === 1'b1) begin
                $display("[BEHAV_SMOKE] FAIL: fail_led asserted at sys_cycle=%0d led=%b",
                         cycle_count, user_led);
                if (uart_fail_line.len() != 0) begin
                    $display("[BEHAV_SMOKE] FAIL: UART line: %s", uart_fail_line);
                end
                test_done = 1'b1;
                $finish;
            end

            if (uart_fail_seen) begin
                $display("[BEHAV_SMOKE] FAIL: UART reported failure at sys_cycle=%0d line=\"%s\"",
                         cycle_count, uart_fail_line);
                test_done = 1'b1;
                $finish;
            end

            if (user_led[1] === 1'b1) begin
                repeat (FINISH_DRAIN_CYCLES) @(posedge sys_clk);
                if (user_led[2] === 1'b1) begin
                    $display("[BEHAV_SMOKE] FAIL: cpu_trap asserted after finish");
                    test_done = 1'b1;
                    $finish;
                end
                $display("[BEHAV_SMOKE] PASS: soc_finish at sys_cycle=%0d led=%b",
                         cycle_count, user_led);
                test_done = 1'b1;
                $finish;
            end

            if (cycle_count >= MAX_SYS_CYCLES) begin
                $display("[BEHAV_SMOKE] TIMEOUT after %0d sys_clk cycles led=%b trap=%0b",
                         MAX_SYS_CYCLES, user_led, user_led[2]);
                test_done = 1'b1;
                $finish;
            end
        end
    end
endmodule
