`timescale 1ns/1ps
`ifndef SOC_PERF_SIZE
`define SOC_PERF_SIZE 16
`endif
`ifndef SOC_PERF_RAM_WORDS
`define SOC_PERF_RAM_WORDS 524288
`endif
`ifndef SOC_PERF_ICACHE
`define SOC_PERF_ICACHE 0
`endif

// 运行实际 SoC 的 RISC-V 固件，核对 CPU 配置、NPU 计算和 AXI DMA 写回。
// 测试台负责存储初始化、时钟复位和传输统计，程序结束后检查结果及保护区。
module tb_conv_soc_perf;
    localparam int RAM_WORDS = `SOC_PERF_RAM_WORDS;
    localparam int RAM_INDEX_BITS = $clog2(RAM_WORDS);
    localparam int REGION_COUNT = 5;
    localparam logic [31:0] WINDOW_BEGIN = 32'hc0b10001;
    localparam logic [31:0] WINDOW_END = 32'hc0b10002;
    logic clk = 0;
    logic rst_n = 0;
    wire npu_busy, npu_irq, uart_tx, soc_finish, cpu_trap;
    wire [31:0] soc_status;
    always #5 clk = !clk;

    soc_top #(
        .SIZE(`SOC_PERF_SIZE), .DATA_WIDTH(16), .WEIGHT_WIDTH(16), .BUS_WIDTH(32),
        .IA_CACHE_BLOCKS(4), .PS_FRAME_COUNT(16),
        .SHARED_BANK_BYTES(8192), .SHARED_BANK_COUNT(7), .IM2COL_CACHE_BYTES(4096),
        .VECTOR_PE_COUNT(8),
        .CPU_MEM_DP(RAM_WORDS), .CPU_MEM_PATH(""), .CPU_MEM_INIT_EN(1),
        .CPU_ENABLE_ICACHE(`SOC_PERF_ICACHE),
        .AXI_READ_OUTSTANDING(4), .AXI_WRITE_OUTSTANDING(4),
        .NPU_ENABLE_IS_MODE(1), .NPU_ENABLE_PER_CHANNEL(1),
        .NPU_ENABLE_CLOCK_GATING(1), .BYPASS_RAM_PINGPONG(1),
        .RAM_WRITE_TIMING_BUFFER(1)
    ) dut (
        .clk, .rst_n, .mem_reload_req(1'b0), .npu_busy, .npu_irq,
        .uart_tx, .uart_rx(1'b1), .soc_finish, .soc_status, .cpu_trap
    );

    // 构建摘要使用以下固定参数，仿真开始时核对实际展开结果。
    initial begin
        assert(dut.BUS_WIDTH == 32 && dut.SHARED_BANK_BYTES == 8192 && dut.SHARED_BANK_COUNT == 7 &&
               dut.u_npu_axil_top.SHARED_CAPABLE && dut.u_npu_axil_top.u_npu_top.SHARED_RAM_ENABLED)
            else $fatal(1, "SoC shared storage parameters differ");
        assert(dut.u_npu_axil_top.CONV_CACHE_SETS == 16 && dut.u_npu_axil_top.CONV_CACHE_WAYS == 2 &&
               dut.u_npu_axil_top.CONV_LINE_BYTES == 128 && dut.u_npu_axil_top.CONV_CACHE_POLICY == 3)
            else $fatal(1, "SoC convolution cache parameters differ");
    end

    typedef struct packed {
        logic [63:0] cycles, npu_busy_cycles, npu_gate_cycles;
        logic [63:0] cpu_instruction_reads, cpu_ram_data_reads;
        logic [63:0] cpu_ram_write_bytes, cpu_mmio_reads, cpu_mmio_write_bytes;
        logic [63:0] npu_ar, npu_read_bytes, npu_rbeats;
        logic [63:0] npu_aw, npu_write_bytes, npu_bresponses;
        logic [63:0] npu_ar_stall, npu_r_stall, npu_aw_stall, npu_w_stall;
        logic [63:0] jobs, conv_jobs, is_jobs, done_jobs, axi_errors;
        logic [63:0] ia_im2col_blocks, kernel_im2col_blocks;
    } counters_t;
    counters_t total, begin_snapshot, measured;
    logic [63:0] cpu_read_region [REGION_COUNT];
    logic [63:0] cpu_write_region [REGION_COUNT];
    logic [63:0] npu_read_region [REGION_COUNT];
    logic [63:0] npu_write_region [REGION_COUNT];
    logic [63:0] cpu_read_begin [REGION_COUNT];
    logic [63:0] cpu_write_begin [REGION_COUNT];
    logic [63:0] npu_read_begin [REGION_COUNT];
    logic [63:0] npu_write_begin [REGION_COUNT];
    logic [63:0] region_base [REGION_COUNT], region_bytes [REGION_COUNT];
    string region_name [REGION_COUNT];
    logic [31:0] progress_seen;
    bit window_open, window_complete;
    longint unsigned timeout_cycles;
    longint unsigned golden_base;
    int unsigned result_addr, result_words;
    int unsigned expected_status;
    string result_path;
    int read_outstanding;
    bit job_inflight;
    // Monitor-only AW queue. Production interconnect permits multiple commands.
    logic [63:0] aw_address [32];
    logic [2:0] aw_size [32];
    logic [1:0] aw_burst [32];
    int aw_head, aw_tail, aw_count;

    function automatic longint unsigned overlap(
        input longint unsigned first, last, base, bytes_count
    );
        longint unsigned low, high;
        low = first > base ? first : base;
        high = last < base + bytes_count ? last : base + bytes_count;
        return high > low ? high - low : 0;
    endfunction

    function automatic longint unsigned read_bytes(
        input logic [31:0] address, input logic [7:0] length,
        input logic [2:0] size, input logic [1:0] burst
    );
        longint unsigned step, lane, count;
        step = 64'd1 << size;
        lane = 64'(address) & (step - 1);
        count = 64'(length) + 1;
        return burst == 0 ? count * (step - lane) : count * step - lane;
    endfunction

    function automatic longint unsigned region_read_bytes(
        input logic [31:0] address, input logic [7:0] length,
        input logic [2:0] size, input logic [1:0] burst,
        input longint unsigned base, bytes_count
    );
        longint unsigned step, first, last;
        step = 64'd1 << size;
        first = 64'(address);
        last = (first & ~(step - 1)) + step;
        if (burst == 0)
            return (64'(length) + 1) * overlap(first, last, base, bytes_count);
        last = (first & ~(step - 1)) + (64'(length) + 1) * step;
        return overlap(first, last, base, bytes_count);
    endfunction

    function automatic logic [7:0] ram_byte(input longint unsigned address);
        return 8'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(address >> 2)] >> (8 * (address & 3)));
    endfunction

    task automatic report_counters(input string scope, input counters_t c);
        $display("SOC_PERF_COUNTER scope=%s cycles=%0d npu_busy_cycles=%0d npu_gate_cycles=%0d cpu_instruction_reads=%0d cpu_ram_data_reads=%0d cpu_ram_write_bytes=%0d cpu_mmio_reads=%0d cpu_mmio_write_bytes=%0d npu_ar=%0d npu_read_bytes=%0d npu_rbeats=%0d npu_aw=%0d npu_write_bytes=%0d npu_bresponses=%0d npu_ar_stall=%0d npu_r_stall=%0d npu_aw_stall=%0d npu_w_stall=%0d jobs=%0d conv_jobs=%0d is_jobs=%0d done_jobs=%0d axi_errors=%0d",
            scope, c.cycles, c.npu_busy_cycles, c.npu_gate_cycles,
            c.cpu_instruction_reads, c.cpu_ram_data_reads, c.cpu_ram_write_bytes,
            c.cpu_mmio_reads, c.cpu_mmio_write_bytes, c.npu_ar, c.npu_read_bytes,
            c.npu_rbeats, c.npu_aw, c.npu_write_bytes, c.npu_bresponses,
            c.npu_ar_stall, c.npu_r_stall, c.npu_aw_stall, c.npu_w_stall,
            c.jobs, c.conv_jobs, c.is_jobs, c.done_jobs, c.axi_errors);
        $display("SOC_PERF_OWNER scope=%s ia_im2col_blocks=%0d kernel_im2col_blocks=%0d",
                 scope, c.ia_im2col_blocks, c.kernel_im2col_blocks);
    endtask

    task automatic report_window;
        // Packed-struct subtraction would borrow across fields. Subtract each
        // scalar explicitly so the printed counts retain their exact meaning.
        measured.cycles = total.cycles - begin_snapshot.cycles;
        measured.npu_busy_cycles = total.npu_busy_cycles - begin_snapshot.npu_busy_cycles;
        measured.npu_gate_cycles = total.npu_gate_cycles - begin_snapshot.npu_gate_cycles;
        measured.cpu_instruction_reads = total.cpu_instruction_reads - begin_snapshot.cpu_instruction_reads;
        measured.cpu_ram_data_reads = total.cpu_ram_data_reads - begin_snapshot.cpu_ram_data_reads;
        measured.cpu_ram_write_bytes = total.cpu_ram_write_bytes - begin_snapshot.cpu_ram_write_bytes;
        measured.cpu_mmio_reads = total.cpu_mmio_reads - begin_snapshot.cpu_mmio_reads;
        measured.cpu_mmio_write_bytes = total.cpu_mmio_write_bytes - begin_snapshot.cpu_mmio_write_bytes;
        measured.npu_ar = total.npu_ar - begin_snapshot.npu_ar;
        measured.npu_read_bytes = total.npu_read_bytes - begin_snapshot.npu_read_bytes;
        measured.npu_rbeats = total.npu_rbeats - begin_snapshot.npu_rbeats;
        measured.npu_aw = total.npu_aw - begin_snapshot.npu_aw;
        measured.npu_write_bytes = total.npu_write_bytes - begin_snapshot.npu_write_bytes;
        measured.npu_bresponses = total.npu_bresponses - begin_snapshot.npu_bresponses;
        measured.npu_ar_stall = total.npu_ar_stall - begin_snapshot.npu_ar_stall;
        measured.npu_r_stall = total.npu_r_stall - begin_snapshot.npu_r_stall;
        measured.npu_aw_stall = total.npu_aw_stall - begin_snapshot.npu_aw_stall;
        measured.npu_w_stall = total.npu_w_stall - begin_snapshot.npu_w_stall;
        measured.jobs = total.jobs - begin_snapshot.jobs;
        measured.conv_jobs = total.conv_jobs - begin_snapshot.conv_jobs;
        measured.is_jobs = total.is_jobs - begin_snapshot.is_jobs;
        measured.done_jobs = total.done_jobs - begin_snapshot.done_jobs;
        measured.axi_errors = total.axi_errors - begin_snapshot.axi_errors;
        measured.ia_im2col_blocks = total.ia_im2col_blocks - begin_snapshot.ia_im2col_blocks;
        measured.kernel_im2col_blocks = total.kernel_im2col_blocks - begin_snapshot.kernel_im2col_blocks;
        report_counters("call_window", measured);
        for (int r = 0; r < REGION_COUNT; r++)
            $display("SOC_PERF_REGION name=%s base=%0d length=%0d cpu_read_bus_bytes=%0d cpu_write_bytes=%0d npu_read_bytes=%0d npu_write_bytes=%0d",
                region_name[r], region_base[r], region_bytes[r],
                cpu_read_region[r] - cpu_read_begin[r], cpu_write_region[r] - cpu_write_begin[r],
                npu_read_region[r] - npu_read_begin[r], npu_write_region[r] - npu_write_begin[r]);
    endtask

    initial begin
        timeout_cycles = 100000000;
        result_addr = 0; result_words = 0; result_path = ""; golden_base = 0;
        expected_status = 0;
        region_name[0] = "input"; region_name[1] = "weight";
        region_name[2] = "scratch"; region_name[3] = "output";
        region_name[4] = "params";
        for (int r = 0; r < REGION_COUNT; r++) begin
            region_base[r] = 0; region_bytes[r] = 0;
            void'($value$plusargs({"PERF_", region_name[r], "_BASE=%h"}, region_base[r]));
            void'($value$plusargs({"PERF_", region_name[r], "_BYTES=%d"}, region_bytes[r]));
        end
        void'($value$plusargs("TIMEOUT_CYCLES=%d", timeout_cycles));
        void'($value$plusargs("RESULT_ADDR=%h", result_addr));
        void'($value$plusargs("RESULT_WORDS=%d", result_words));
        void'($value$plusargs("RESULT_FILE=%s", result_path));
        void'($value$plusargs("GOLDEN_BASE=%h", golden_base));
        void'($value$plusargs("EXPECTED_STATUS=%d", expected_status));
        repeat (8) @(negedge clk);
        rst_n = 1;
    end

    // Blocking assignments are intentional: this is one observation process,
    // with a single, deterministic snapshot after counting the current edge.
    always @(posedge clk) begin : monitor
        longint unsigned address, next_address;
        int result_file, mismatches;
        if (!rst_n) begin
            total = '0; begin_snapshot = '0; measured = '0;
            progress_seen = 0; window_open = 0; window_complete = 0;
            read_outstanding = 0; aw_head = 0; aw_tail = 0; aw_count = 0; job_inflight = 0;
            for (int r = 0; r < REGION_COUNT; r++) begin
                cpu_read_region[r] = 0; cpu_write_region[r] = 0;
                npu_read_region[r] = 0; npu_write_region[r] = 0;
                cpu_read_begin[r] = 0; cpu_write_begin[r] = 0;
                npu_read_begin[r] = 0; npu_write_begin[r] = 0;
            end
        end else begin
            total.cycles++;
            if (npu_busy) total.npu_busy_cycles++;
            if (dut.u_npu_axil_top.npu_clk_gate_en) total.npu_gate_cycles++;
            if (dut.pico_mem_valid && dut.pico_mem_ready) begin
                address = 64'(dut.pico_mem_addr) & ~64'd3;
                if (dut.pico_mem_wstrb == 0) begin
                    if (dut.pico_mem_instr) total.cpu_instruction_reads++;
                    else if (address < 64'(RAM_WORDS) * 4) begin
                        total.cpu_ram_data_reads++;
                        for (int r = 0; r < REGION_COUNT; r++)
                            cpu_read_region[r] += overlap(address, address + 4, region_base[r], region_bytes[r]);
                    end else total.cpu_mmio_reads++;
                end else begin
                    for (int lane = 0; lane < 4; lane++) begin
                        if (dut.pico_mem_wstrb[lane]) begin
                            if (address < 64'(RAM_WORDS) * 4) begin
                                total.cpu_ram_write_bytes++;
                                for (int r = 0; r < REGION_COUNT; r++)
                                    cpu_write_region[r] += overlap(address + 64'(lane), address + 64'(lane) + 1,
                                                                  region_base[r], region_bytes[r]);
                            end else total.cpu_mmio_write_bytes++;
                        end
                    end
                end
            end
            if (dut.npu_axi_arvalid && dut.npu_axi_arready) begin
                total.npu_ar++; read_outstanding++;
                total.npu_read_bytes += read_bytes(dut.npu_axi_araddr, dut.npu_axi_arlen,
                                                   dut.npu_axi_arsize, dut.npu_axi_arburst);
                for (int r = 0; r < REGION_COUNT; r++)
                    npu_read_region[r] += region_read_bytes(dut.npu_axi_araddr, dut.npu_axi_arlen,
                        dut.npu_axi_arsize, dut.npu_axi_arburst, region_base[r], region_bytes[r]);
            end
            if (dut.npu_axi_rvalid && dut.npu_axi_rready) begin
                total.npu_rbeats++;
                if (dut.npu_axi_rlast) read_outstanding--;
                if (dut.npu_axi_rresp != 0) total.axi_errors++;
            end
            if (dut.npu_axi_awvalid && dut.npu_axi_awready) begin
                assert(aw_count < 32) else $fatal(1, "monitor AW queue overflow");
                aw_address[aw_tail] = 64'(dut.npu_axi_awaddr);
                aw_size[aw_tail] = dut.npu_axi_awsize;
                aw_burst[aw_tail] = dut.npu_axi_awburst;
                aw_tail = (aw_tail + 1) % 32; aw_count++; total.npu_aw++;
            end
            if (dut.npu_axi_wvalid && dut.npu_axi_wready) begin
                assert(aw_count > 0) else $fatal(1, "NPU W beat without AW");
                address = aw_address[aw_head] & ~64'd3;
                for (int lane = 0; lane < 4; lane++) begin
                    if (dut.npu_axi_wstrb[lane]) begin
                        total.npu_write_bytes++;
                        for (int r = 0; r < REGION_COUNT; r++)
                            npu_write_region[r] += overlap(address + 64'(lane), address + 64'(lane) + 1,
                                                          region_base[r], region_bytes[r]);
                    end
                end
                next_address = (aw_address[aw_head] & ~((64'd1 << aw_size[aw_head]) - 1)) +
                               (64'd1 << aw_size[aw_head]);
                if (aw_burst[aw_head] != 0) aw_address[aw_head] = next_address;
                if (dut.npu_axi_wlast) begin aw_head = (aw_head + 1) % 32; aw_count--; end
            end
            if (dut.npu_axi_bvalid && dut.npu_axi_bready) begin
                total.npu_bresponses++;
                if (dut.npu_axi_bresp != 0) total.axi_errors++;
            end
            if (dut.npu_axi_arvalid && !dut.npu_axi_arready) total.npu_ar_stall++;
            if (dut.npu_axi_rvalid && !dut.npu_axi_rready) total.npu_r_stall++;
            if (dut.npu_axi_awvalid && !dut.npu_axi_awready) total.npu_aw_stall++;
            if (dut.npu_axi_wvalid && !dut.npu_axi_wready) total.npu_w_stall++;
            if (dut.u_npu_axil_top.npu_core_calc_start && dut.u_npu_axil_top.npu_sa_ready) begin
                assert(!job_inflight) else $fatal(1, "NPU start while prior command is active");
                job_inflight = 1;
                total.jobs++;
                if (dut.u_npu_axil_top.cfg_conv_enable_reg) total.conv_jobs++;
                if (dut.u_npu_axil_top.cfg_dataflow_mode_reg) total.is_jobs++;
                $display("SOC_PERF_JOB cycle=%0d conv=%0d is=%0d k=%0d n=%0d m=%0d",
                    total.cycles, dut.u_npu_axil_top.cfg_conv_enable_reg,
                    dut.u_npu_axil_top.cfg_dataflow_mode_reg,
                    dut.u_npu_axil_top.k_reg, dut.u_npu_axil_top.n_reg, dut.u_npu_axil_top.m_reg);
            end
            if (dut.u_npu_axil_top.npu_done_fire && job_inflight) begin
                total.done_jobs++; job_inflight = 0;
            end
            if (dut.u_npu_axil_top.npu_clk_gate_en &&
                dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_dma_start &&
                dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_dma_im2col) begin
                case (dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_command_client)
                    3'd0: total.ia_im2col_blocks++;
                    3'd1: total.kernel_im2col_blocks++;
                    default: $fatal(1, "im2col request from an invalid DMA client");
                endcase
            end
            if (dut.soc_progress != progress_seen) begin
                progress_seen = dut.soc_progress;
                $display("SOC_PERF_PROGRESS cycle=%0d value=%08x", total.cycles, progress_seen);
                if (progress_seen == WINDOW_BEGIN) begin
                    assert(!window_open && !window_complete) else $fatal(1, "duplicate call window");
                    begin_snapshot = total; window_open = 1;
                    for (int r = 0; r < REGION_COUNT; r++) begin
                        cpu_read_begin[r] = cpu_read_region[r]; cpu_write_begin[r] = cpu_write_region[r];
                        npu_read_begin[r] = npu_read_region[r]; npu_write_begin[r] = npu_write_region[r];
                    end
                end else if (progress_seen == WINDOW_END) begin
                    assert(window_open) else $fatal(1, "call window ended without begin");
                    report_window(); window_open = 0; window_complete = 1;
                end
            end
            if (cpu_trap) $fatal(1, "CPU trapped at cycle %0d pc=%08x", total.cycles, dut.u_picorv32.reg_pc);
            if (total.cycles >= timeout_cycles) $fatal(1, "CPU timeout cycle=%0d progress=%08x pc=%08x",
                                                       total.cycles, progress_seen, dut.u_picorv32.reg_pc);
            if (soc_finish) begin
                report_counters("boot_to_finish", total);
                result_file = 0;
                if (result_path != "") begin
                    result_file = $fopen(result_path, "w");
                    assert(result_file != 0) else $fatal(1, "cannot open result dump");
                end
                assert((64'(result_addr) + 4 * 64'(result_words)) <= 4 * 64'(RAM_WORDS))
                    else $fatal(1, "result range outside RAM");
                for (int unsigned i = 0; i < result_words; i++) begin
                    $display("SOC_PERF_RESULT index=%0d value=%08x", i, dut.u_axi_sim_ram.mem_r[(result_addr >> 2) + i]);
                    if (result_file != 0) $fdisplay(result_file, "%08x", dut.u_axi_sim_ram.mem_r[(result_addr >> 2) + i]);
                end
                if (result_file != 0) $fclose(result_file);
                mismatches = 0;
                if (golden_base != 0) begin
                    for (longint unsigned i = 0; i < region_bytes[3]; i++) begin
                        if (ram_byte(region_base[3] + i) != ram_byte(golden_base + i)) begin
                            if (mismatches < 8) $display("SOC_PERF_OUTPUT_MISMATCH offset=%0d actual=%02x expected=%02x",
                                i, ram_byte(region_base[3] + i), ram_byte(golden_base + i));
                            mismatches++;
                        end
                    end
                end
                assert(soc_status == expected_status && mismatches == 0 && total.axi_errors == 0)
                    else $fatal(1, "firmware failed status=%08x output_mismatches=%0d axi_errors=%0d",
                                soc_status, mismatches, total.axi_errors);
                assert(read_outstanding == 0 && aw_count == 0 && !npu_busy)
                    else $fatal(1, "firmware finished before NPU/AXI retirement");
                $display("SOC_PERF_PASS status=%0d cycles=%0d window_complete=%0d output_bytes=%0d",
                    soc_status, total.cycles, window_complete, region_bytes[3]);
                $finish;
            end
        end
    end
endmodule
