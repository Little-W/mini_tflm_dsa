`timescale 1ns/1ps
`ifndef TB_BUS_WIDTH
`define TB_BUS_WIDTH 32
`endif
`ifndef TB_READ_BEAT_CYCLES
`define TB_READ_BEAT_CYCLES 1
`endif
`ifndef TB_READ_FIRST_LATENCY
`define TB_READ_FIRST_LATENCY 8
`endif
`ifndef TB_PIPELINED_READ
`define TB_PIPELINED_READ 1
`endif
`ifndef TB_DMA_MAX_BYTES
`define TB_DMA_MAX_BYTES (256*(`TB_BUS_WIDTH/8))
`endif
`ifndef TB_CONV_CACHE_SETS
`define TB_CONV_CACHE_SETS 128
`endif
`ifndef TB_CONV_CACHE_POLICY
`define TB_CONV_CACHE_POLICY 3
`endif
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 8
`endif
`ifndef TB_PS_FRAME_COUNT
`define TB_PS_FRAME_COUNT 16
`endif
`ifndef TB_PS_STORAGE_ROWS
`define TB_PS_STORAGE_ROWS 799
`endif
`ifndef TB_OA_S16_FIFO_BANKS_MAX
`define TB_OA_S16_FIFO_BANKS_MAX 4
`endif

module tb_common_conv;
    import conv_im2col_pkg::*;
    import vector_engine_pkg::*;
    localparam int WORDS = 131072;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, calc_start = 0, done_ready = 0, new_job = 0;
    logic [31:0] cfg[64], golden[WORDS];
    logic sa_ready, done_valid;
    logic [1:0] err_code;
    conv_cfg_t conv_cfg;
    vector_engine_cfg_t vector_cfg;
    logic [31:0] hits, misses, conv_bytes, conv_cycles;
    logic [31:0] vector_cycles, vector_compute, vector_dma_wait;
    logic arvalid, arready, rvalid, rready, rlast, awvalid, awready, wvalid, wready, wlast, bvalid, bready;
    logic [31:0] araddr, awaddr;
    logic [`TB_BUS_WIDTH-1:0] rdata, wdata;
    logic [7:0] arlen, awlen;
    logic [2:0] arsize, awsize;
    logic [1:0] arburst, rresp, awburst, bresp;
    logic [`TB_BUS_WIDTH/8-1:0] wstrb;
    logic [31:0] other_lo[4], other_hi[4];
    logic error_injected;
    longint unsigned read_bytes, input_read_bytes, read_requests, write_bytes;
    longint unsigned cycle = 0;
    always @(posedge clk) if (rst_n) cycle <= cycle + 1;

    always_comb begin
        conv_cfg = '0;
        conv_cfg.input_base = cfg[33];
        conv_cfg.input_h = cfg[34][15:0]; conv_cfg.input_w = cfg[35][15:0]; conv_cfg.input_c = cfg[36][15:0];
        conv_cfg.group_c = cfg[37][15:0]; conv_cfg.group_offset = cfg[38][15:0];
        conv_cfg.kernel_h = cfg[39][15:0]; conv_cfg.kernel_w = cfg[40][15:0];
        conv_cfg.output_h = cfg[41][15:0]; conv_cfg.output_w = cfg[42][15:0];
        conv_cfg.stride_h = cfg[43][15:0]; conv_cfg.stride_w = cfg[44][15:0];
        conv_cfg.dilation_h = cfg[45][15:0]; conv_cfg.dilation_w = cfg[46][15:0];
        conv_cfg.pad_top = cfg[47][15:0]; conv_cfg.pad_left = cfg[48][15:0];
        conv_cfg.input_offset = 0; conv_cfg.bypass_cache = 0; conv_cfg.input_s16 = 0;
`ifdef COMMON_WINDOWED_INPUT
        conv_cfg.windowed = 1;
`endif
`ifdef COMMON_PREFETCH_INPUT
        conv_cfg.prefetch_enable = 1;
`endif
        vector_cfg = '0;
        vector_cfg.op = DW_S8;
        vector_cfg.input_base = cfg[33]; vector_cfg.rhs_base = cfg[15]; vector_cfg.output_base = cfg[17];
        vector_cfg.bias_base = cfg[16]; vector_cfg.multiplier_base = cfg[24]; vector_cfg.shift_base = cfg[25];
        vector_cfg.output_offset = 0; vector_cfg.activation_min = -128; vector_cfg.activation_max = 127;
        vector_cfg.image = conv_cfg;
        other_lo[0] = cfg[15];
        other_hi[0] = cfg[15] + (cfg[29][1] ?
            ((cfg[4]+15)/16)*((cfg[5]+15)/16)*256 : cfg[4]*cfg[5]);
        other_lo[1] = cfg[16]; other_hi[1] = cfg[16] + 4 * cfg[5];
        other_lo[2] = cfg[59][0] ? cfg[24] : 0; other_hi[2] = cfg[24] + 4 * cfg[5];
        other_lo[3] = cfg[59][0] ? cfg[25] : 0; other_hi[3] = cfg[25] + 4 * cfg[5];
    end

    npu_top #(.BUS_WIDTH(`TB_BUS_WIDTH),.SIZE(16), .DATA_WIDTH(16), .WEIGHT_WIDTH(16), .IA_CACHE_BLOCKS(`TB_IA_CACHE_BLOCKS),
              .DMA_MAX_BYTES(`TB_DMA_MAX_BYTES),
              .PS_FRAME_COUNT(`TB_PS_FRAME_COUNT), .PS_STORAGE_ROWS(`TB_PS_STORAGE_ROWS),
              .OA_S16_FIFO_BANKS_MAX(`TB_OA_S16_FIFO_BANKS_MAX),
              .AXI_READ_OUTSTANDING(4), .CONV_CACHE_SETS(`TB_CONV_CACHE_SETS),
              .CONV_CACHE_WAYS(2), .CONV_LINE_BYTES(16), .CONV_CACHE_POLICY(`TB_CONV_CACHE_POLICY)) u_dut (
        .clk, .rst_n, .calc_start, .sa_ready, .done_valid, .done_ready, .err_code,
        .cfg_operand_fetch64(1'b0), .cfg_16bits_ia(cfg[12][0]), .cfg_16x8(1'b0), .cfg_dataflow_mode(cfg[8][0]),
        .cfg_lhs_tile_packed(1'b0), .cfg_rhs_tile_packed(cfg[29][1]),
        .cfg_ia_reuse_num(cfg[6]), .cfg_w_reuse_num(cfg[7]),
        .cfg_row_groups({16'b0, cfg[30][15:0]}), .cfg_col_groups({16'b0, cfg[30][31:16]}),
        .cfg_row_tail_tiles({16'b0, cfg[31][15:0]}), .cfg_col_tail_tiles({16'b0, cfg[31][31:16]}),
        .cfg_conv_enable(cfg[32][0]), .cfg_conv(conv_cfg),
        .cfg_vector_enable(cfg[59][0]), .cfg_vector(vector_cfg),
        .lhs_base(cfg[14]), .rhs_base(cfg[15]), .bias_base(cfg[16]), .dst_base(cfg[17]),
        .lhs_row_stride_b(cfg[18]), .rhs_col_stride_b(cfg[19]), .dst_row_stride_b(cfg[20]),
        .lhs_zp(32'd0), .rhs_zp(32'd0), .dst_zp(32'd0), .q_mult_pt(cfg[24]), .q_shift_pt(cfg[25]),
        .use_per_channel(1'b0), .act_min(-32'sd128), .act_max(32'sd127), .k(cfg[3]), .n(cfg[4]), .m(cfg[5]),
        .m_axi_arvalid(arvalid), .m_axi_arready(arready), .m_axi_araddr(araddr), .m_axi_arlen(arlen),
        .m_axi_arsize(arsize), .m_axi_arburst(arburst), .m_axi_rvalid(rvalid), .m_axi_rready(rready),
        .m_axi_rdata(rdata), .m_axi_rresp(rresp), .m_axi_rlast(rlast),
        .m_axi_awvalid(awvalid), .m_axi_awready(awready), .m_axi_awaddr(awaddr), .m_axi_awlen(awlen),
        .m_axi_awsize(awsize), .m_axi_awburst(awburst), .m_axi_wvalid(wvalid), .m_axi_wready(wready),
        .m_axi_wdata(wdata), .m_axi_wstrb(wstrb), .m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid), .m_axi_bready(bready), .m_axi_bresp(bresp)
    );
    assign hits=u_dut.tb_observer.conv_stat_hits;
    assign misses=u_dut.tb_observer.conv_stat_misses;
    assign conv_bytes=u_dut.tb_observer.conv_stat_read_bytes;
    assign conv_cycles=u_dut.tb_observer.conv_stat_cycles;
    assign vector_cycles=u_dut.tb_observer.vector_stat_cycles;
    assign vector_compute=u_dut.tb_observer.vector_stat_compute;
    assign vector_dma_wait=u_dut.tb_observer.vector_stat_dma_wait;

    conv_test_axi_memory #(.WORDS(WORDS),.BUS_WIDTH(`TB_BUS_WIDTH),
        .READ_BEAT_CYCLES(`TB_READ_BEAT_CYCLES),
        .READ_FIRST_LATENCY(`TB_READ_FIRST_LATENCY),.PIPELINED_READ(`TB_PIPELINED_READ)) u_mem (
        .clk, .rst_n, .new_job, .protect_input(1'b1), .inject_error(1'b0), .error_injected,
        .input_lo(cfg[33]), .input_hi(cfg[33] + cfg[34] * cfg[35] * cfg[36]), .other_lo, .other_hi,
        .read_bytes, .input_read_bytes, .read_requests, .write_bytes,
        .arvalid, .arready, .araddr, .arlen, .arsize, .arburst, .rvalid, .rready, .rdata, .rresp, .rlast,
        .awvalid, .awready, .awaddr, .awlen, .awsize, .awburst, .wvalid, .wready, .wdata, .wstrb, .wlast,
        .bvalid, .bready, .bresp
    );

    initial begin : run_case
        string config_path, init_path, golden_path;
        longint unsigned start_cycle, finish_cycle;
        int errors;
        if (!$value$plusargs("CONFIG=%s", config_path) || !$value$plusargs("INIT=%s", init_path) ||
            !$value$plusargs("GOLDEN=%s", golden_path)) $fatal(1, "Comparison input files are required");
        for (int i = 0; i < 64; i++) cfg[i] = 0;
        for (int i = 0; i < WORDS; i++) begin
            u_mem.mem[i] = 32'h5aa53cc3;
            golden[i] = 32'h5aa53cc3;
        end
        $readmemh(config_path, cfg); $readmemh(init_path, u_mem.mem); $readmemh(golden_path, golden);
        repeat (5) @(negedge clk);
        rst_n = 1;
        repeat (3) @(negedge clk);
        assert (sa_ready) else $fatal(1, "NPU not ready after reset");
        new_job = 1; @(negedge clk); new_job = 0;
        start_cycle = cycle; calc_start = 1; @(negedge clk); calc_start = 0;
        while (!done_valid && cycle - start_cycle < 10000000) @(negedge clk);
        assert (done_valid && err_code == 0) else $fatal(1, "Conv comparison failed or timed out");
        finish_cycle = cycle;
        repeat (3) @(negedge clk);
        errors = 0;
        for (int i = 0; i < WORDS; i++) begin
            if (u_mem.mem[i] !== golden[i]) begin
                if (errors < 8) $display("COMMON_MISMATCH word=%h observed=%h expected=%h", i, u_mem.mem[i], golden[i]);
                errors++;
            end
        end
        assert (errors == 0) else $fatal(1, "Conv output or memory preservation mismatch");
        $display("COMMON_CONV_PASS depthwise=%0d cycles=%0d hits=%0d misses=%0d input_bytes=%0d ar_bytes=%0d ar_requests=%0d write_bytes=%0d frontend_cycles=%0d vector_cycles=%0d vector_compute=%0d vector_dma_wait=%0d",
            cfg[59][0], finish_cycle - start_cycle, hits, misses, input_read_bytes, read_bytes,
            read_requests, write_bytes, conv_cycles, vector_cycles, vector_compute, vector_dma_wait);
        done_ready = 1; @(negedge clk); done_ready = 0;
        repeat (3) @(negedge clk);
        $finish;
    end
endmodule
