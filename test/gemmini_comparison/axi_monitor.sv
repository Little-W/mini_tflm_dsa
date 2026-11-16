`timescale 1ns/1ps
`ifndef TB_BUS_WIDTH
`define TB_BUS_WIDTH 32
`endif
`ifndef TB_DMA_MAX_BYTES
`define TB_DMA_MAX_BYTES (256*(`TB_BUS_WIDTH/8))
`endif

module common_gemm_axi_monitor #(
    parameter int unsigned DMA_MAX_BYTES = `TB_DMA_MAX_BYTES
) (
    input logic clk, rst_n, launch, done_valid,
    input logic arvalid, arready, rvalid, rready, rlast,
    input logic awvalid, awready, wvalid, wready, wlast, bvalid, bready,
    input logic [7:0] arlen, awlen,
    input logic [2:0] arsize, awsize
);
    longint unsigned tick, launch_tick;
    longint signed first_ar, first_r, last_r, first_aw, first_w, last_w, last_b;
    longint unsigned read_commands, read_completions, write_commands, write_completions;
    longint unsigned read_beats, write_beats, read_outstanding_max, write_outstanding_max;
    longint unsigned read_burst_bytes_max, write_burst_bytes_max;
    longint unsigned read_accept_tick [64];
    longint unsigned first_read_latency, read_latency_min, read_latency_max;
    bit active, read_first;

    always @(posedge clk) begin : observe
        longint unsigned read_outstanding, write_outstanding, bytes_in_burst, latency;
        if (!rst_n) begin
            tick = 0; launch_tick = 0; active = 0; read_first = 1;
            first_ar = -1; first_r = -1; last_r = -1;
            first_aw = -1; first_w = -1; last_w = -1; last_b = -1;
            read_commands = 0; read_completions = 0;
            write_commands = 0; write_completions = 0;
            read_beats = 0; write_beats = 0;
            read_outstanding_max = 0; write_outstanding_max = 0;
            read_burst_bytes_max = 0; write_burst_bytes_max = 0;
            first_read_latency = 0; read_latency_min = '1; read_latency_max = 0;
        end else begin
            if (launch) begin
                assert (!active) else $fatal(1, "Concurrent comparison jobs");
                active = 1;
                launch_tick = tick;
            end
            if (active) begin
                if (arvalid && arready) begin
                    if (first_ar < 0) first_ar = longint'(tick - launch_tick);
                    read_accept_tick[read_commands % 64] = tick;
                    read_commands++;
                    bytes_in_burst = (64'(arlen) + 1) << arsize;
                    assert (bytes_in_burst <= DMA_MAX_BYTES)
                        else $fatal(1, "AXI read exceeds the configured DMA limit");
                    if (bytes_in_burst > read_burst_bytes_max) read_burst_bytes_max = bytes_in_burst;
                end
                if (rvalid && rready) begin
                    assert (read_completions < read_commands) else $fatal(1, "Read response without command");
                    if (first_r < 0) first_r = longint'(tick - launch_tick);
                    last_r = longint'(tick - launch_tick);
                    read_beats++;
                    if (read_first) begin
                        latency = tick - read_accept_tick[read_completions % 64];
                        if (read_completions == 0) first_read_latency = latency;
                        if (latency < read_latency_min) read_latency_min = latency;
                        if (latency > read_latency_max) read_latency_max = latency;
                    end
                    read_first = rlast;
                    if (rlast) read_completions++;
                end
                if (awvalid && awready) begin
                    if (first_aw < 0) first_aw = longint'(tick - launch_tick);
                    write_commands++;
                    bytes_in_burst = (64'(awlen) + 1) << awsize;
                    assert (bytes_in_burst <= DMA_MAX_BYTES)
                        else $fatal(1, "AXI write exceeds the configured DMA limit");
                    if (bytes_in_burst > write_burst_bytes_max) write_burst_bytes_max = bytes_in_burst;
                end
                if (wvalid && wready) begin
                    if (first_w < 0) first_w = longint'(tick - launch_tick);
                    last_w = longint'(tick - launch_tick);
                    write_beats++;
                end
                if (bvalid && bready) begin
                    assert (write_completions < write_commands) else $fatal(1, "Write response without command");
                    last_b = longint'(tick - launch_tick);
                    write_completions++;
                end
                read_outstanding = read_commands - read_completions;
                write_outstanding = write_commands - write_completions;
                if (read_outstanding > read_outstanding_max) read_outstanding_max = read_outstanding;
                if (write_outstanding > write_outstanding_max) write_outstanding_max = write_outstanding;
                assert (read_outstanding <= 4 && write_outstanding <= 4)
                    else $fatal(1, "Comparison DMA outstanding limit exceeded");
                if (done_valid) begin
                    assert (read_outstanding == 0 && write_outstanding == 0)
                        else $fatal(1, "Completion before external memory responses drained");
                    $display("COMMON_TIMING first_ar=%0d first_r=%0d last_r=%0d first_aw=%0d first_w=%0d last_w=%0d last_b=%0d done=%0d first_read_latency=%0d read_latency_min=%0d read_latency_max=%0d read_commands=%0d write_commands=%0d read_beats=%0d write_beats=%0d read_outstanding_max=%0d write_outstanding_max=%0d read_burst_bytes_max=%0d write_burst_bytes_max=%0d",
                        first_ar, first_r, last_r, first_aw, first_w, last_w, last_b, tick - launch_tick,
                        first_read_latency, read_latency_min, read_latency_max, read_commands, write_commands,
                        read_beats, write_beats, read_outstanding_max, write_outstanding_max,
                        read_burst_bytes_max, write_burst_bytes_max);
                    active = 0;
                end
            end
            tick++;
        end
    end
endmodule

`ifndef COMMON_MONITOR_TOP
`define COMMON_MONITOR_TOP tb_conv_npu
`endif
bind `COMMON_MONITOR_TOP common_gemm_axi_monitor u_common_monitor (
    .clk(clk), .rst_n(rst_n), .launch(calc_start && sa_ready), .done_valid(done_valid),
    .arvalid(arvalid), .arready(arready), .arlen(arlen), .arsize(arsize),
    .rvalid(rvalid), .rready(rready), .rlast(rlast),
    .awvalid(awvalid), .awready(awready), .awlen(awlen), .awsize(awsize),
    .wvalid(wvalid), .wready(wready), .wlast(wlast), .bvalid(bvalid), .bready(bready)
);
