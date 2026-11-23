`timescale 1ns/1ps

`ifndef TB_SIZE
`define TB_SIZE 16
`endif
`ifndef TB_DATA_WIDTH
`define TB_DATA_WIDTH 16
`endif
`ifndef TB_WEIGHT_WIDTH
`define TB_WEIGHT_WIDTH 16
`endif
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 4
`endif
`ifndef TB_PS_FRAME_COUNT
`define TB_PS_FRAME_COUNT 16
`endif
`ifndef TB_AXI_READ_OUTSTANDING
`define TB_AXI_READ_OUTSTANDING 4
`endif
`ifndef TB_MEM_WORDS
`define TB_MEM_WORDS 131072
`endif

module tb_npu_top;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,calc_start=0;
    wire sa_ready,done_valid;
    wire [1:0] err_code;
    logic [31:0] cfg[0:31];
    logic [31:0] golden_mem[0:`TB_MEM_WORDS-1];
    string init_path,golden_path,case_path;

    wire m_axi_arvalid,m_axi_arready,m_axi_rvalid,m_axi_rready,m_axi_rlast;
    wire m_axi_awvalid,m_axi_awready,m_axi_wvalid,m_axi_wready,m_axi_wlast;
    wire m_axi_bvalid,m_axi_bready;
    wire [31:0] m_axi_araddr,m_axi_rdata,m_axi_awaddr,m_axi_wdata;
    wire [7:0] m_axi_arlen,m_axi_awlen;
    wire [2:0] m_axi_arsize,m_axi_awsize;
    wire [1:0] m_axi_arburst,m_axi_awburst,m_axi_rresp,m_axi_bresp;
    wire [3:0] m_axi_wstrb;

    npu_top #(
        .SIZE(`TB_SIZE),.DATA_WIDTH(`TB_DATA_WIDTH),.WEIGHT_WIDTH(`TB_WEIGHT_WIDTH),
        .IA_CACHE_BLOCKS(`TB_IA_CACHE_BLOCKS),.PS_FRAME_COUNT(`TB_PS_FRAME_COUNT),
        .SHARED_BANK_BYTES(8192),.SHARED_BANK_COUNT(7),
        .AXI_READ_OUTSTANDING(`TB_AXI_READ_OUTSTANDING)
    ) u_dut (
        .clk,.rst_n,.calc_start,.sa_ready,.done_valid,.done_ready(1'b1),.err_code,
        .cfg_operand_fetch64(1'b0),.cfg_16bits_ia(cfg[12][0]),.cfg_16x8(cfg[28][0]),
        .cfg_dataflow_mode(cfg[8][0]),.cfg_ia_reuse_num(cfg[6]),.cfg_w_reuse_num(cfg[7]),
        .cfg_shared_ia_banks(32'd2),.cfg_ps_control(32'd1),
        .cfg_row_groups({16'b0,cfg[30][15:0]}),.cfg_col_groups({16'b0,cfg[30][31:16]}),
        .cfg_row_tail_tiles({16'b0,cfg[31][15:0]}),.cfg_col_tail_tiles({16'b0,cfg[31][31:16]}),
        .lhs_base(cfg[14]),.rhs_base(cfg[15]),.bias_base(cfg[16]),.dst_base(cfg[17]),
        .lhs_zp(cfg[21]),.rhs_zp(cfg[22]),.dst_zp(cfg[23]),
        .q_mult_pt(cfg[24]),.q_shift_pt(cfg[25]),.use_per_channel(cfg[13][0]),
        .k(cfg[3]),.n(cfg[4]),.m(cfg[5]),
        .lhs_row_stride_b(cfg[18]),.rhs_col_stride_b(cfg[19]),.dst_row_stride_b(cfg[20]),
        .act_min(cfg[26]),.act_max(cfg[27]),
        .m_axi_arvalid,.m_axi_arready,.m_axi_araddr,.m_axi_arlen,.m_axi_arsize,.m_axi_arburst,
        .m_axi_rvalid,.m_axi_rready,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,
        .m_axi_awvalid,.m_axi_awready,.m_axi_awaddr,.m_axi_awlen,.m_axi_awsize,.m_axi_awburst,
        .m_axi_wvalid,.m_axi_wready,.m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,
        .m_axi_bvalid,.m_axi_bready,.m_axi_bresp
    );
    ddr_axi_mem_model #(.WIDTH(32),.ADDR_W(32),.MW(4),.DP(`TB_MEM_WORDS)) u_mem (
        .clk,.rst_n,
        .m_axi_arvalid,.m_axi_arready,.m_axi_araddr,.m_axi_arlen,.m_axi_arsize,.m_axi_arburst,
        .m_axi_rvalid,.m_axi_rready,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,
        .m_axi_awvalid,.m_axi_awready,.m_axi_awaddr,.m_axi_awlen,.m_axi_awsize,.m_axi_awburst,
        .m_axi_wvalid,.m_axi_wready,.m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,
        .m_axi_bvalid,.m_axi_bready,.m_axi_bresp
    );

`ifdef GEMPACT_PS_COMPRESS
    longint unsigned ps_rows=0;
    initial begin
        assert(u_dut.SHARED_RAM_ENABLED && u_dut.SHARED_TOTAL_BYTES==57344 &&
               u_dut.SHARED_BANK_BYTES==8192)
            else $fatal(1,"Shared IA/PS configuration differs");
    end
    always @(posedge clk) if(rst_n && u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.encode_commit_valid) begin
        ps_rows++;
    end
    final $display("[PS_STORAGE_METRICS] total_bytes=57344 bank_bytes=8192 ia_banks=2 rows=%0d",
                   ps_rows);
`endif

    logic ar_stalled=0,aw_stalled=0,w_stalled=0;
    logic [44:0] old_ar,old_aw;
    logic [36:0] old_w;
    always @(posedge clk) begin
        if(!rst_n) begin ar_stalled<=0;aw_stalled<=0;w_stalled<=0;end
        else begin
            if(ar_stalled)
                assert(m_axi_arvalid && {m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst}===old_ar)
                    else $fatal(1,"AXI AR changed during backpressure");
            if(aw_stalled)
                assert(m_axi_awvalid && {m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst}===old_aw)
                    else $fatal(1,"AXI AW changed during backpressure");
            if(w_stalled)
                assert(m_axi_wvalid && {m_axi_wdata,m_axi_wstrb,m_axi_wlast}===old_w)
                    else $fatal(1,"AXI W changed during backpressure");
            ar_stalled<=m_axi_arvalid && !m_axi_arready;
            aw_stalled<=m_axi_awvalid && !m_axi_awready;
            w_stalled<=m_axi_wvalid && !m_axi_wready;
            old_ar<={m_axi_araddr,m_axi_arlen,m_axi_arsize,m_axi_arburst};
            old_aw<={m_axi_awaddr,m_axi_awlen,m_axi_awsize,m_axi_awburst};
            old_w<={m_axi_wdata,m_axi_wstrb,m_axi_wlast};
            if(m_axi_arvalid && m_axi_arready)
                assert(32'(m_axi_araddr[11:0])+((32'(m_axi_arlen)+1)<<m_axi_arsize)<=4096)
                    else $fatal(1,"AXI read crosses a 4 KiB boundary");
            if(m_axi_awvalid && m_axi_awready) begin
                assert(32'(m_axi_awaddr[11:0])+((32'(m_axi_awlen)+1)<<m_axi_awsize)<=4096)
                    else $fatal(1,"AXI write crosses a 4 KiB boundary");
                assert(m_axi_awaddr>=cfg[17] && m_axi_awaddr<cfg[17]+cfg[3]*cfg[20])
                    else $fatal(1,"AXI write is outside the output tensor");
            end
        end
    end

    initial begin : run_case
        integer errors,words;
        assert($value$plusargs("INIT_MEM=%s",init_path)) else $fatal(1,"INIT_MEM is required");
        assert($value$plusargs("GOLDEN_MEM=%s",golden_path)) else $fatal(1,"GOLDEN_MEM is required");
        assert($value$plusargs("CASE_MEM=%s",case_path)) else $fatal(1,"CASE_MEM is required");
        foreach(cfg[i]) cfg[i]=0;
        $readmemh(case_path,cfg);
        assert(cfg[0]==32'h4e505531 && cfg[1]==`TB_SIZE && cfg[2]==`TB_IA_CACHE_BLOCKS &&
               cfg[9]<=`TB_PS_FRAME_COUNT && cfg[11]==`TB_MEM_WORDS && cfg[10]<=cfg[11])
            else $fatal(1,"Tensor descriptor differs from the compiled configuration");
        $readmemh(init_path,u_mem.mem_r);
        $readmemh(golden_path,golden_mem);
        repeat(5) @(negedge clk);
        rst_n=1;
        repeat(5) @(negedge clk);
        wait(sa_ready);
        calc_start=1;
        @(negedge clk);
        calc_start=0;
        wait(done_valid);
        assert(err_code==0) else $fatal(1,"NPU task error %0d",err_code);
        repeat(10) @(negedge clk);
        words=$test$plusargs("FULL_MEM_CHECK") ? int'(cfg[11]) : int'(cfg[10]);
        errors=0;
        for(int i=0;i<words;i++) if(u_mem.mem_r[i]!==golden_mem[i]) begin
            if(errors<32) $display("[TB][MISMATCH] word=%0d got=%08x expected=%08x",i,u_mem.mem_r[i],golden_mem[i]);
            errors++;
        end
        assert(errors==0) else $fatal(1,"Memory comparison failed for %0d words",errors);
`ifdef GEMPACT_PS_COMPRESS
        assert(ps_rows!=0 && u_dut.u_matrix_engine.ps_force_raw_q)
            else $fatal(1,"The shared storage cases must write raw partial sums");
`endif
        $display("[TB] PASS checked_words=%0d",words);
        $finish;
    end
    initial begin : timeout
        longint unsigned timeout_cycles;
        timeout_cycles=2000000;
        void'($value$plusargs("TB_TIMEOUT_CYCLES=%d",timeout_cycles));
        repeat(timeout_cycles) @(posedge clk);
        $fatal(1,"NPU timeout ready=%0d done=%0d error=%0d",sa_ready,done_valid,err_code);
    end
endmodule
