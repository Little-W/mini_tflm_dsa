// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module soc_axi_interconnect_observer;

    bit axi_stats_en;
    longint unsigned cpu_ram_ar_wait_cycles;
    longint unsigned npu_ram_ar_wait_cycles;
    longint unsigned cpu_ram_aw_wait_cycles;
    longint unsigned npu_ram_aw_wait_cycles;
    longint unsigned rd_yield_cycles;
    longint unsigned wr_yield_cycles;
    longint unsigned npu_lock_cycles;
    longint unsigned cpu_lock_ar_block_cycles;
    longint unsigned cpu_lock_aw_block_cycles;
    longint unsigned cpu_lock_w_block_cycles;

    initial begin
        axi_stats_en = $test$plusargs("SOC_AXI_STATS");
    end

    always_ff @(posedge soc_axi_interconnect.clk or negedge soc_axi_interconnect.rst_n) begin
        if (!soc_axi_interconnect.rst_n) begin
            cpu_ram_ar_wait_cycles <= 0;
            npu_ram_ar_wait_cycles <= 0;
            cpu_ram_aw_wait_cycles <= 0;
            npu_ram_aw_wait_cycles <= 0;
            rd_yield_cycles        <= 0;
            wr_yield_cycles        <= 0;
            npu_lock_cycles        <= 0;
            cpu_lock_ar_block_cycles <= 0;
            cpu_lock_aw_block_cycles <= 0;
            cpu_lock_w_block_cycles  <= 0;
        end else if (axi_stats_en) begin
            if (soc_axi_interconnect.cpu_ram_ar_req && !soc_axi_interconnect.cpu_ram_ar_hs) begin
                cpu_ram_ar_wait_cycles <= cpu_ram_ar_wait_cycles + 1;
            end
            if (soc_axi_interconnect.npu_ram_ar_req && !soc_axi_interconnect.s1_axi_arready) begin
                npu_ram_ar_wait_cycles <= npu_ram_ar_wait_cycles + 1;
            end
            if (soc_axi_interconnect.cpu_ram_aw_req && !soc_axi_interconnect.s0_axi_awready) begin
                cpu_ram_aw_wait_cycles <= cpu_ram_aw_wait_cycles + 1;
            end
            if (soc_axi_interconnect.npu_ram_aw_req && !soc_axi_interconnect.s1_axi_awready) begin
                npu_ram_aw_wait_cycles <= npu_ram_aw_wait_cycles + 1;
            end
            if (soc_axi_interconnect.ram_rd_yield) begin
                rd_yield_cycles <= rd_yield_cycles + 1;
            end
            if (soc_axi_interconnect.ram_wr_yield) begin
                wr_yield_cycles <= wr_yield_cycles + 1;
            end
            if (soc_axi_interconnect.npu_bus_lock) begin
                npu_lock_cycles <= npu_lock_cycles + 1;
            end
            if (soc_axi_interconnect.npu_bus_lock && soc_axi_interconnect.s0_axi_arvalid && !soc_axi_interconnect.s0_axi_arready) begin
                cpu_lock_ar_block_cycles <= cpu_lock_ar_block_cycles + 1;
            end
            if (soc_axi_interconnect.npu_bus_lock && soc_axi_interconnect.s0_axi_awvalid && !soc_axi_interconnect.s0_axi_awready) begin
                cpu_lock_aw_block_cycles <= cpu_lock_aw_block_cycles + 1;
            end
            if (soc_axi_interconnect.npu_bus_lock && soc_axi_interconnect.s0_axi_wvalid && !soc_axi_interconnect.s0_axi_wready) begin
                cpu_lock_w_block_cycles <= cpu_lock_w_block_cycles + 1;
            end
        end
    end

    always_ff @(posedge soc_axi_interconnect.clk) begin
        if (soc_axi_interconnect.rst_n && soc_axi_interconnect.npu_bus_lock) begin
            if (soc_axi_interconnect.s0_axi_arvalid && soc_axi_interconnect.s0_axi_arready) begin
                $error("CPU AR accepted while NPU bus lock is active");
            end
            if (soc_axi_interconnect.s0_axi_awvalid && soc_axi_interconnect.s0_axi_awready) begin
                $error("CPU AW accepted while NPU bus lock is active");
            end
        end
    end

    final begin
        if (axi_stats_en) begin
            $display("[SOC_AXI_STATS] cpu_ar_wait=%0d npu_ar_wait=%0d cpu_aw_wait=%0d npu_aw_wait=%0d rd_yield=%0d wr_yield=%0d npu_lock=%0d cpu_lock_ar_block=%0d cpu_lock_aw_block=%0d cpu_lock_w_block=%0d",
                     cpu_ram_ar_wait_cycles, npu_ram_ar_wait_cycles,
                     cpu_ram_aw_wait_cycles, npu_ram_aw_wait_cycles,
                     rd_yield_cycles, wr_yield_cycles, npu_lock_cycles,
                     cpu_lock_ar_block_cycles, cpu_lock_aw_block_cycles,
                     cpu_lock_w_block_cycles);
        end
    end

endmodule
bind soc_axi_interconnect soc_axi_interconnect_observer tb_observer();
`endif
