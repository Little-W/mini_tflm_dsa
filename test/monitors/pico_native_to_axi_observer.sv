// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module pico_native_to_axi_observer;

    bit trace_en;
    bit stats_en;
    longint unsigned stat_read_reqs;
    longint unsigned stat_write_reqs;
    longint unsigned stat_read_wait_cycles;
    longint unsigned stat_write_wait_cycles;
    longint unsigned stat_instr_reqs;
    longint unsigned stat_data_reqs;
    longint unsigned stat_icache_hits;
    longint unsigned stat_icache_misses;
    longint unsigned stat_icache_fill_beats;

    initial begin
        trace_en = $test$plusargs("SOC_CPU_AXI_TRACE");
        stats_en = $test$plusargs("SOC_CPU_AXI_STATS");
    end

    always @(posedge pico_native_to_axi.clk) begin
        if (trace_en && pico_native_to_axi.rst_n) begin
            if (pico_native_to_axi.mem_valid || pico_native_to_axi.mem_ready || pico_native_to_axi.m_axi_arvalid || pico_native_to_axi.m_axi_rvalid ||
                pico_native_to_axi.m_axi_awvalid || pico_native_to_axi.m_axi_wvalid || pico_native_to_axi.m_axi_bvalid) begin
                $display("[SOC_CPU_AXI] t=%0t mem_v=%0b mem_rdy=%0b instr=%0b addr=%08h wstrb=%b rdata=%08h ar=%0b/%0b r=%0b/%0b aw=%0b/%0b w=%0b/%0b b=%0b/%0b",
                         $time, pico_native_to_axi.mem_valid, pico_native_to_axi.mem_ready, pico_native_to_axi.mem_instr, pico_native_to_axi.mem_addr,
                         pico_native_to_axi.mem_wstrb, pico_native_to_axi.mem_rdata,
                         pico_native_to_axi.m_axi_arvalid, pico_native_to_axi.m_axi_arready,
                         pico_native_to_axi.m_axi_rvalid, pico_native_to_axi.m_axi_rready,
                         pico_native_to_axi.m_axi_awvalid, pico_native_to_axi.m_axi_awready,
                         pico_native_to_axi.m_axi_wvalid, pico_native_to_axi.m_axi_wready,
                         pico_native_to_axi.m_axi_bvalid, pico_native_to_axi.m_axi_bready);
            end
        end
    end

    always_ff @(posedge pico_native_to_axi.clk) begin
        if (!pico_native_to_axi.rst_n) begin
            stat_read_reqs         <= 0;
            stat_write_reqs        <= 0;
            stat_read_wait_cycles  <= 0;
            stat_write_wait_cycles <= 0;
            stat_instr_reqs        <= 0;
            stat_data_reqs         <= 0;
            stat_icache_hits       <= 0;
            stat_icache_misses     <= 0;
            stat_icache_fill_beats <= 0;
        end else if (stats_en) begin
            if (pico_native_to_axi.new_read_req) begin
                stat_read_reqs <= stat_read_reqs + 1;
                if (pico_native_to_axi.mem_instr) stat_instr_reqs <= stat_instr_reqs + 1;
                else stat_data_reqs <= stat_data_reqs + 1;
            end
            if (pico_native_to_axi.icache_hit) stat_icache_hits <= stat_icache_hits + 1;
            if (pico_native_to_axi.icache_miss) stat_icache_misses <= stat_icache_misses + 1;
            if (pico_native_to_axi.new_write_req) begin
                stat_write_reqs <= stat_write_reqs + 1;
                stat_data_reqs <= stat_data_reqs + 1;
            end
            if (pico_native_to_axi.r_fire && pico_native_to_axi.ic_fill_q) begin
                stat_icache_fill_beats <= stat_icache_fill_beats + 1;
            end
            if ((pico_native_to_axi.read_busy_q && !pico_native_to_axi.r_fire) || pico_native_to_axi.ic_req_q) begin
                stat_read_wait_cycles <= stat_read_wait_cycles + 1;
            end
            if (pico_native_to_axi.write_busy_q && !pico_native_to_axi.b_fire) begin
                stat_write_wait_cycles <= stat_write_wait_cycles + 1;
            end
        end
    end

    final begin
        if (stats_en) begin
            $display("[SOC_CPU_AXI_STATS] read_req=%0d write_req=%0d instr_req=%0d data_req=%0d read_wait=%0d write_wait=%0d ic_hit=%0d ic_miss=%0d ic_fill_beats=%0d",
                     stat_read_reqs, stat_write_reqs,
                     stat_instr_reqs, stat_data_reqs,
                     stat_read_wait_cycles, stat_write_wait_cycles,
                     stat_icache_hits, stat_icache_misses,
                     stat_icache_fill_beats);
        end
    end

endmodule
bind pico_native_to_axi pico_native_to_axi_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
