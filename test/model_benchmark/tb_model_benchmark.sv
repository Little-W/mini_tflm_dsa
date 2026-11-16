// SPDX-License-Identifier: Apache-2.0
// Observes firmware executing on the production CPU, interconnect, NPU and RAM.
`ifndef SOC_NETWORK_RAM_WORDS
`define SOC_NETWORK_RAM_WORDS 524288
`endif
`ifndef SOC_NETWORK_ICACHE
`define SOC_NETWORK_ICACHE 0
`endif
`ifndef SOC_NETWORK_PE_COUNT
`define SOC_NETWORK_PE_COUNT 8
`endif
`ifndef SOC_NETWORK_IA_CACHE_BLOCKS
`define SOC_NETWORK_IA_CACHE_BLOCKS 8
`endif
`ifndef SOC_NETWORK_PS_STORAGE_ROWS
`define SOC_NETWORK_PS_STORAGE_ROWS 799
`endif
`ifndef SOC_NETWORK_S16_OUTPUT_BANKS
`define SOC_NETWORK_S16_OUTPUT_BANKS 4
`endif
module tb_model_benchmark(input logic clk, rst_n, output logic finished,
                      output logic [31:0] progress, pc);
    localparam int RAM_WORDS = `SOC_NETWORK_RAM_WORDS;
    localparam int RAM_INDEX_BITS = $clog2(RAM_WORDS);
    wire npu_busy, npu_irq, uart_tx, soc_finish, cpu_trap;
    wire [31:0] soc_status;
    soc_top #(
        .SIZE(16), .DATA_WIDTH(16), .WEIGHT_WIDTH(16), .BUS_WIDTH(32),
        .IA_CACHE_BLOCKS(`SOC_NETWORK_IA_CACHE_BLOCKS), .PS_FRAME_COUNT(16),
        .PS_STORAGE_ROWS(`SOC_NETWORK_PS_STORAGE_ROWS),
        .OA_S16_FIFO_BANKS_MAX(`SOC_NETWORK_S16_OUTPUT_BANKS),
        .ENABLE_VECTOR_ENGINE(1), .VECTOR_PE_COUNT(`SOC_NETWORK_PE_COUNT), .DW_MAX_TAPS(49), .POOL_MAX_TAPS(256),
        .CPU_MEM_DP(RAM_WORDS), .CPU_MEM_PATH(""), .CPU_MEM_INIT_EN(1),
        .CPU_ENABLE_ICACHE(`SOC_NETWORK_ICACHE),
        .AXI_READ_OUTSTANDING(4), .AXI_WRITE_OUTSTANDING(4),
        .NPU_ENABLE_IS_MODE(1), .NPU_ENABLE_PER_CHANNEL(1),
        .NPU_ENABLE_CLOCK_GATING(1), .BYPASS_RAM_PINGPONG(1),
        .RAM_WRITE_TIMING_BUFFER(1)
    ) dut (
        .clk, .rst_n, .mem_reload_req(1'b0), .npu_busy, .npu_irq,
        .uart_tx, .uart_rx(1'b1), .soc_finish, .soc_status, .cpu_trap
    );
    assign progress = dut.soc_progress;
    assign pc = dut.u_picorv32.reg_pc;
    assign finished = soc_finish;

    typedef struct packed {
        logic [63:0] cycles, npu_busy_cycles, cpu_instruction_reads, cpu_data_reads;
        logic [63:0] cpu_data_write_bytes, cpu_mmio_reads, cpu_mmio_write_bytes;
        logic [63:0] npu_read_bytes, npu_write_bytes, npu_read_bursts, npu_write_bursts;
        logic [63:0] jobs, conv_jobs, dw_jobs, pool_jobs, vector_jobs, gemm_jobs, add_jobs;
        logic [63:0] conv_done, dw_done, pool_done, vector_done, gemm_done, add_done, npu_errors;
        logic [63:0] done_jobs, axi_errors, ia_windows, kernel_windows, dw_windows;
        logic [63:0] array_jobs_busy_cycles, array_ia_valid_cycles, array_weight_commits;
        logic [63:0] array_controller_cycles, array_wait_weight_tail, array_wait_weight_data;
        logic [63:0] array_wait_ia_data, array_wait_bias, array_wait_quant;
        logic [63:0] array_wait_output, array_wait_ia_done, window_cache_hits;
        logic [63:0] window_cache_misses, window_cache_read_bytes, vector_compute_cycles;
        logic [63:0] vector_dma_wait_cycles, softmax_jobs, softmax_done;
    } counters_t;
    counters_t total, network_start, layer_start;
    logic [31:0] progress_seen, network_begin_marker, network_end_marker, tensor_marker;
    bit network_open, network_complete, layer_open, job_inflight;
    int unsigned layer_index, layer_count;
    typedef enum logic [2:0] {JOB_GEMM, JOB_CONV, JOB_DW, JOB_POOL, JOB_VECTOR, JOB_ADD, JOB_SOFTMAX} job_kind_t;
    job_kind_t job_kind;
    int outstanding_reads, outstanding_writes;
    longint unsigned window_requested_elements, window_response_elements;
    longint unsigned window_first_response_cycle, window_last_response_cycle;
    logic [31:0] read_address[32], read_current[32], write_address[32];
    logic [7:0] read_length[32], write_length[32];
    logic [2:0] read_size[32], write_size[32];
    logic [1:0] read_burst[32];
    int read_head,read_tail,write_head,write_tail;
    int read_beats[32],write_beats[32],write_data_head,outstanding_write_data;
    bit write_data_done[32];
    longint unsigned timeout_cycles;
    int unsigned result_addr, result_words, output_addr, output_bytes;
    int unsigned model_addr, model_bytes, input_addr, input_bytes;
    int output_addr_word, output_bytes_word;
    int unsigned trace_addr, trace_words, trace_address_word, trace_bytes_word, trace_count;
    int unsigned expected_status;
    string result_path, output_path, trace_dir, trace_path, model_path, input_path;
    int trace_file;

    function automatic counters_t difference(input counters_t a, b);
        counters_t c;
        c.cycles=a.cycles-b.cycles;
        c.npu_busy_cycles=a.npu_busy_cycles-b.npu_busy_cycles;
        c.cpu_instruction_reads=a.cpu_instruction_reads-b.cpu_instruction_reads;
        c.cpu_data_reads=a.cpu_data_reads-b.cpu_data_reads;
        c.cpu_data_write_bytes=a.cpu_data_write_bytes-b.cpu_data_write_bytes;
        c.cpu_mmio_reads=a.cpu_mmio_reads-b.cpu_mmio_reads;
        c.cpu_mmio_write_bytes=a.cpu_mmio_write_bytes-b.cpu_mmio_write_bytes;
        c.npu_read_bytes=a.npu_read_bytes-b.npu_read_bytes;
        c.npu_write_bytes=a.npu_write_bytes-b.npu_write_bytes;
        c.npu_read_bursts=a.npu_read_bursts-b.npu_read_bursts;
        c.npu_write_bursts=a.npu_write_bursts-b.npu_write_bursts;
        c.jobs=a.jobs-b.jobs;
        c.conv_jobs=a.conv_jobs-b.conv_jobs;
        c.dw_jobs=a.dw_jobs-b.dw_jobs;
        c.pool_jobs=a.pool_jobs-b.pool_jobs;
        c.vector_jobs=a.vector_jobs-b.vector_jobs;
        c.gemm_jobs=a.gemm_jobs-b.gemm_jobs;
        c.add_jobs=a.add_jobs-b.add_jobs;
        c.conv_done=a.conv_done-b.conv_done;
        c.dw_done=a.dw_done-b.dw_done;
        c.pool_done=a.pool_done-b.pool_done;
        c.vector_done=a.vector_done-b.vector_done;
        c.gemm_done=a.gemm_done-b.gemm_done;
        c.add_done=a.add_done-b.add_done;
        c.npu_errors=a.npu_errors-b.npu_errors;
        c.done_jobs=a.done_jobs-b.done_jobs;
        c.axi_errors=a.axi_errors-b.axi_errors;
        c.ia_windows=a.ia_windows-b.ia_windows;
        c.kernel_windows=a.kernel_windows-b.kernel_windows;
        c.dw_windows=a.dw_windows-b.dw_windows;
        c.array_jobs_busy_cycles=a.array_jobs_busy_cycles-b.array_jobs_busy_cycles;
        c.array_ia_valid_cycles=a.array_ia_valid_cycles-b.array_ia_valid_cycles;
        c.array_weight_commits=a.array_weight_commits-b.array_weight_commits;
        c.array_controller_cycles=a.array_controller_cycles-b.array_controller_cycles;
        c.array_wait_weight_tail=a.array_wait_weight_tail-b.array_wait_weight_tail;
        c.array_wait_weight_data=a.array_wait_weight_data-b.array_wait_weight_data;
        c.array_wait_ia_data=a.array_wait_ia_data-b.array_wait_ia_data;
        c.array_wait_bias=a.array_wait_bias-b.array_wait_bias;
        c.array_wait_quant=a.array_wait_quant-b.array_wait_quant;
        c.array_wait_output=a.array_wait_output-b.array_wait_output;
        c.array_wait_ia_done=a.array_wait_ia_done-b.array_wait_ia_done;
        c.window_cache_hits=a.window_cache_hits-b.window_cache_hits;
        c.window_cache_misses=a.window_cache_misses-b.window_cache_misses;
        c.window_cache_read_bytes=a.window_cache_read_bytes-b.window_cache_read_bytes;
        c.vector_compute_cycles=a.vector_compute_cycles-b.vector_compute_cycles;
        c.vector_dma_wait_cycles=a.vector_dma_wait_cycles-b.vector_dma_wait_cycles;
        c.softmax_jobs=a.softmax_jobs-b.softmax_jobs;
        c.softmax_done=a.softmax_done-b.softmax_done;
        return c;
    endfunction

    function automatic logic [31:0] ram_word(input int unsigned addr);
        assert(addr < RAM_WORDS*4 && addr[1:0]==0) else $fatal(1,"invalid observed word address");
        return dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr>>2)];
    endfunction
    function automatic logic [7:0] ram_byte(input int unsigned addr);
        return 8'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr>>2)] >> (8*(addr&3)));
    endfunction
    function automatic longint unsigned read_bytes(
        input logic [31:0] addr, input logic [7:0] len,
        input logic [2:0] size, input logic [1:0] burst);
        longint unsigned step, lane;
        step=64'd1<<size; lane=64'(addr)&(step-1);
        return burst==0 ? (64'(len)+1)*(step-lane) : (64'(len)+1)*step-lane;
    endfunction

    task automatic dump_bytes(input string path, input int unsigned addr, bytes_count);
        int handle;
        assert(64'(addr)+64'(bytes_count)<=64'(RAM_WORDS)*4) else $fatal(1,"dump outside RAM");
        handle=$fopen(path,"wb");
        assert(handle!=0) else $fatal(1,"cannot open RAM dump %s",path);
        for(int unsigned i=0;i<bytes_count;i++) $fwrite(handle,"%c",ram_byte(addr+i));
        $fclose(handle);
    endtask
    task automatic report(input string scope, input int unsigned index, input counters_t c);
        $display("SOC_NETWORK_COUNTER scope=%s index=%0d cycles=%0d npu_busy_cycles=%0d cpu_instruction_reads=%0d cpu_data_reads=%0d cpu_data_write_bytes=%0d cpu_mmio_reads=%0d cpu_mmio_write_bytes=%0d npu_read_bytes=%0d npu_write_bytes=%0d npu_read_bursts=%0d npu_write_bursts=%0d jobs=%0d conv_jobs=%0d dw_jobs=%0d pool_jobs=%0d vector_jobs=%0d gemm_jobs=%0d add_jobs=%0d conv_done=%0d dw_done=%0d pool_done=%0d vector_done=%0d gemm_done=%0d add_done=%0d npu_errors=%0d done_jobs=%0d axi_errors=%0d ia_windows=%0d kernel_windows=%0d dw_windows=%0d array_jobs_busy_cycles=%0d array_ia_valid_cycles=%0d array_weight_commits=%0d array_controller_cycles=%0d array_wait_weight_tail=%0d array_wait_weight_data=%0d array_wait_ia_data=%0d array_wait_bias=%0d array_wait_quant=%0d array_wait_output=%0d array_wait_ia_done=%0d window_cache_hits=%0d window_cache_misses=%0d window_cache_read_bytes=%0d vector_compute_cycles=%0d vector_dma_wait_cycles=%0d softmax_jobs=%0d softmax_done=%0d",
            scope,index,c.cycles,c.npu_busy_cycles,c.cpu_instruction_reads,c.cpu_data_reads,
            c.cpu_data_write_bytes,c.cpu_mmio_reads,c.cpu_mmio_write_bytes,c.npu_read_bytes,
            c.npu_write_bytes,c.npu_read_bursts,c.npu_write_bursts,c.jobs,c.conv_jobs,c.dw_jobs,
            c.pool_jobs,c.vector_jobs,c.gemm_jobs,c.add_jobs,c.conv_done,c.dw_done,c.pool_done,
            c.vector_done,c.gemm_done,c.add_done,c.npu_errors,c.done_jobs,c.axi_errors,
            c.ia_windows,c.kernel_windows,c.dw_windows,
            c.array_jobs_busy_cycles,c.array_ia_valid_cycles,c.array_weight_commits,
            c.array_controller_cycles,c.array_wait_weight_tail,c.array_wait_weight_data,
            c.array_wait_ia_data,c.array_wait_bias,c.array_wait_quant,
            c.array_wait_output,c.array_wait_ia_done,c.window_cache_hits,
            c.window_cache_misses,c.window_cache_read_bytes,c.vector_compute_cycles,
            c.vector_dma_wait_cycles,c.softmax_jobs,c.softmax_done);
    endtask

    initial begin
        timeout_cycles=64'd4000000000;
        result_addr=0;result_words=0;output_addr=0;output_bytes=0;
        model_addr=0;model_bytes=0;input_addr=0;input_bytes=0;model_path="";input_path="";
        result_path="";output_path="";output_addr_word=-1;output_bytes_word=-1;
        trace_addr=0;trace_words=9;trace_address_word=6;trace_bytes_word=7;
        trace_count=0;trace_file=0;trace_dir="";trace_path="";
        expected_status=0;
        network_begin_marker=32'hc0f10001;network_end_marker=32'hc0f10002;tensor_marker=32'hc0f20000;
        void'($value$plusargs("TIMEOUT_CYCLES=%d",timeout_cycles));
        void'($value$plusargs("RESULT_ADDR=%h",result_addr));
        void'($value$plusargs("RESULT_WORDS=%d",result_words));
        void'($value$plusargs("RESULT_FILE=%s",result_path));
        void'($value$plusargs("OUTPUT_ADDR=%h",output_addr));
        void'($value$plusargs("OUTPUT_BYTES=%d",output_bytes));
        void'($value$plusargs("OUTPUT_ADDR_WORD=%d",output_addr_word));
        void'($value$plusargs("OUTPUT_BYTES_WORD=%d",output_bytes_word));
        void'($value$plusargs("OUTPUT_FILE=%s",output_path));
        void'($value$plusargs("MODEL_ADDR=%h",model_addr));
        void'($value$plusargs("MODEL_BYTES=%d",model_bytes));
        void'($value$plusargs("MODEL_FILE=%s",model_path));
        void'($value$plusargs("INPUT_ADDR=%h",input_addr));
        void'($value$plusargs("INPUT_BYTES=%d",input_bytes));
        void'($value$plusargs("INPUT_FILE=%s",input_path));
        void'($value$plusargs("TRACE_ADDR=%h",trace_addr));
        void'($value$plusargs("TRACE_WORDS=%d",trace_words));
        void'($value$plusargs("TRACE_ADDRESS_WORD=%d",trace_address_word));
        void'($value$plusargs("TRACE_BYTES_WORD=%d",trace_bytes_word));
        void'($value$plusargs("TRACE_DIR=%s",trace_dir));
        void'($value$plusargs("TRACE_FILE=%s",trace_path));
        void'($value$plusargs("NETWORK_BEGIN=%h",network_begin_marker));
        void'($value$plusargs("NETWORK_END=%h",network_end_marker));
        void'($value$plusargs("TENSOR_MARKER=%h",tensor_marker));
        void'($value$plusargs("EXPECTED_STATUS=%d",expected_status));
        if(trace_path!="") begin
            trace_file=$fopen(trace_path,"w");
            assert(trace_file!=0) else $fatal(1,"cannot open trace record");
        end
    end

    // One observation process updates counters before taking marker snapshots.
    always @(posedge clk) begin : observe
        int unsigned tensor_addr,tensor_bytes;
        if(!rst_n) begin
            total='0;network_start='0;layer_start='0;
            progress_seen=0;network_open=0;network_complete=0;layer_open=0;
            layer_index=0;layer_count=0;job_inflight=0;job_kind=JOB_GEMM;
            outstanding_reads=0;outstanding_writes=0;
            window_requested_elements=0;window_response_elements=0;
            window_first_response_cycle=0;window_last_response_cycle=0;
            read_head=0;read_tail=0;write_head=0;write_tail=0;
            write_data_head=0;outstanding_write_data=0;
        end else begin
            total.cycles++;
            if(npu_busy) total.npu_busy_cycles++;
            // IA-valid counts rows injected into the WS array. It excludes
            // the fill and drain periods and is independent of shape padding.
            if(job_inflight && (job_kind==JOB_CONV || job_kind==JOB_GEMM)) begin
                if(npu_busy) total.array_jobs_busy_cycles++;
                if(dut.u_npu_axil_top.npu_clk_gate_en) begin
                    if(dut.u_npu_axil_top.u_npu_top.ia_row_valid)
                        total.array_ia_valid_cycles++;
                    if(dut.u_npu_axil_top.u_npu_top.weight_commit)
                        total.array_weight_commits++;
                end
            end
            if(dut.pico_mem_valid && dut.pico_mem_ready) begin
                if(dut.pico_mem_wstrb==0) begin
                    if(dut.pico_mem_instr) total.cpu_instruction_reads++;
                    else if(dut.pico_mem_addr<RAM_WORDS*4) total.cpu_data_reads++;
                    else total.cpu_mmio_reads++;
                end else if(dut.pico_mem_addr<RAM_WORDS*4)
                    total.cpu_data_write_bytes+=64'($countones(dut.pico_mem_wstrb));
                else total.cpu_mmio_write_bytes+=64'($countones(dut.pico_mem_wstrb));
            end
            if(dut.npu_axi_arvalid && dut.npu_axi_arready) begin
                assert(outstanding_reads<32) else $fatal(1,"read observer capacity exceeded");
                assert(dut.npu_axi_arburst==1 && dut.npu_axi_arsize<=2)
                    else $fatal(1,"unsupported NPU read command");
                assert((64'(dut.npu_axi_araddr)&4095)+((64'(dut.npu_axi_arlen)+1)<<dut.npu_axi_arsize)<=4096)
                    else $fatal(1,"NPU read crosses 4 KiB");
                read_address[read_tail]=dut.npu_axi_araddr;read_current[read_tail]=dut.npu_axi_araddr;
                read_beats[read_tail]=0;
                read_length[read_tail]=dut.npu_axi_arlen;read_size[read_tail]=dut.npu_axi_arsize;
                read_burst[read_tail]=dut.npu_axi_arburst;read_tail=(read_tail+1)%32;
                total.npu_read_bursts++;outstanding_reads++;
                total.npu_read_bytes+=read_bytes(dut.npu_axi_araddr,dut.npu_axi_arlen,dut.npu_axi_arsize,dut.npu_axi_arburst);
            end
            if(dut.npu_axi_rvalid && dut.npu_axi_rready) begin
                assert(outstanding_reads>0) else $fatal(1,"read response without request");
                assert(dut.npu_axi_rlast==(read_beats[read_head]==int'(read_length[read_head])))
                    else $fatal(1,"NPU read RLAST does not match ARLEN");
                read_beats[read_head]++;
                if(dut.npu_axi_rresp!=0) begin
                    total.axi_errors++;
                    $display("SOC_NETWORK_AXI_ERROR channel=R cycles=%0d start=%08x address=%08x len=%0d size=%0d burst=%0d resp=%0d last=%0d conv=%0d dw=%0d op=%0d",
                        total.cycles,read_address[read_head],read_current[read_head],read_length[read_head],
                        read_size[read_head],read_burst[read_head],dut.npu_axi_rresp,dut.npu_axi_rlast,
                        dut.u_npu_axil_top.cfg_conv_enable_reg,dut.u_npu_axil_top.cfg_vector_enable_reg,dut.u_npu_axil_top.cfg_vector_op_reg);
                end
                if(read_burst[read_head]!=0)
                    read_current[read_head]=(read_current[read_head]&~((32'd1<<read_size[read_head])-1))+(32'd1<<read_size[read_head]);
                if(dut.npu_axi_rlast) begin outstanding_reads--;read_head=(read_head+1)%32;end
            end
            if(dut.npu_axi_awvalid && dut.npu_axi_awready) begin
                assert(outstanding_writes<32) else $fatal(1,"write observer capacity exceeded");
                assert(dut.npu_axi_awburst==1 && dut.npu_axi_awsize==2 && dut.npu_axi_awaddr[1:0]==0)
                    else $fatal(1,"unsupported NPU write command");
                assert((64'(dut.npu_axi_awaddr)&4095)+((64'(dut.npu_axi_awlen)+1)<<dut.npu_axi_awsize)<=4096)
                    else $fatal(1,"NPU write crosses 4 KiB");
                write_address[write_tail]=dut.npu_axi_awaddr;write_length[write_tail]=dut.npu_axi_awlen;
                write_beats[write_tail]=0;write_data_done[write_tail]=0;outstanding_write_data++;
                write_size[write_tail]=dut.npu_axi_awsize;write_tail=(write_tail+1)%32;
                total.npu_write_bursts++;outstanding_writes++;
            end
            if(dut.npu_axi_wvalid && dut.npu_axi_wready) begin
                assert(outstanding_write_data>0) else $fatal(1,"NPU write data without AW");
                assert(dut.npu_axi_wlast==(write_beats[write_data_head]==int'(write_length[write_data_head])))
                    else $fatal(1,"NPU write WLAST does not match AWLEN");
                write_beats[write_data_head]++;
                total.npu_write_bytes+=64'($countones(dut.npu_axi_wstrb));
                if(dut.npu_axi_wlast) begin
                    write_data_done[write_data_head]=1;write_data_head=(write_data_head+1)%32;
                    outstanding_write_data--;
                end
            end
            if(dut.npu_axi_bvalid && dut.npu_axi_bready) begin
                assert(outstanding_writes>0) else $fatal(1,"write response without request");
                assert(write_data_done[write_head]) else $fatal(1,"NPU B response before WLAST");
                if(dut.npu_axi_bresp!=0) begin
                    total.axi_errors++;
                    $display("SOC_NETWORK_AXI_ERROR channel=B cycles=%0d address=%08x len=%0d size=%0d resp=%0d conv=%0d dw=%0d op=%0d",
                        total.cycles,write_address[write_head],write_length[write_head],write_size[write_head],dut.npu_axi_bresp,
                        dut.u_npu_axil_top.cfg_conv_enable_reg,dut.u_npu_axil_top.cfg_vector_enable_reg,dut.u_npu_axil_top.cfg_vector_op_reg);
                end
                outstanding_writes--;
                write_head=(write_head+1)%32;
            end
            if(dut.u_npu_axil_top.npu_clk_gate_en) begin
                if(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.cfg_fire) begin
                    window_requested_elements=0;window_response_elements=0;
                    window_first_response_cycle=0;window_last_response_cycle=0;
                end
                if(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_req_valid &&
                   dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_req_ready) begin
                    total.dw_windows++;
                    window_requested_elements+=64'(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_req_cols);
                end
                if(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_rsp_valid &&
                   dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_rsp_ready &&
                   !dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_rsp_error) begin
                    if(window_response_elements==0) window_first_response_cycle=total.cycles;
                    window_last_response_cycle=total.cycles;
                    window_response_elements+=64'($countones(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_rsp_mask));
                end
            end
            if(dut.u_npu_axil_top.npu_core_calc_start && dut.u_npu_axil_top.npu_sa_ready) begin
                assert(!job_inflight) else $fatal(1,"NPU command already active");
                job_inflight=1;total.jobs++;
                if(dut.u_npu_axil_top.cfg_vector_enable_reg) begin
                    case(dut.u_npu_axil_top.cfg_vector_op_reg)
                        4'd0:begin total.dw_jobs++;job_kind=JOB_DW;end
                        4'd1,4'd2,4'd3:begin total.pool_jobs++;job_kind=JOB_POOL;end
                        4'd9:begin total.add_jobs++;job_kind=JOB_ADD;end
                        4'd10:begin total.softmax_jobs++;job_kind=JOB_SOFTMAX;end
                        default:begin total.vector_jobs++;job_kind=JOB_VECTOR;end
                    endcase
                end else if(dut.u_npu_axil_top.cfg_conv_enable_reg) begin total.conv_jobs++;job_kind=JOB_CONV;end
                else begin total.gemm_jobs++;job_kind=JOB_GEMM;end
            end
            if(dut.u_npu_axil_top.npu_done_fire) begin
                assert(job_inflight) else $fatal(1,"NPU completion without command");
                total.done_jobs++;job_inflight=0;
                if(dut.u_npu_axil_top.npu_err_code!=0) total.npu_errors++;
                // The controller counters are stable when the wrapper
                // reports completion. Wait reasons within each issue state
                // are mutually exclusive; IA-valid is an independent measure.
                if(job_kind==JOB_CONV || job_kind==JOB_GEMM) begin
                    total.array_controller_cycles+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_active_cycles;
                    total.array_wait_weight_tail+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_weight_tail_cycles;
                    total.array_wait_weight_data+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_weight_data_cycles;
                    total.array_wait_ia_data+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_ia_data_cycles;
                    total.array_wait_bias+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_bias_cycles;
                    total.array_wait_quant+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_quant_cycles;
                    total.array_wait_output+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_fifo_cycles;
                    total.array_wait_ia_done+=dut.u_npu_axil_top.u_npu_top.u_npu_controller.util_stall_ia_done_cycles;
                end else begin
                    total.vector_compute_cycles+=64'(dut.u_npu_axil_top.u_npu_top.vector_stat_compute);
                    total.vector_dma_wait_cycles+=64'(dut.u_npu_axil_top.u_npu_top.vector_stat_dma_wait);
                end
                if(job_kind==JOB_CONV || job_kind==JOB_DW || job_kind==JOB_POOL) begin
                    total.window_cache_hits+=64'(dut.u_npu_axil_top.u_npu_top.conv_stat_hits);
                    total.window_cache_misses+=64'(dut.u_npu_axil_top.u_npu_top.conv_stat_misses);
                    total.window_cache_read_bytes+=64'(dut.u_npu_axil_top.u_npu_top.conv_stat_read_bytes);
                end
                if(job_kind==JOB_DW || job_kind==JOB_POOL) begin
                    assert(!dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_busy)
                        else $fatal(1,"window requests remain at job completion");
                    assert(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_requests==
                           dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_completions)
                        else $fatal(1,"window completion count differs from accepted requests");
                    if(dut.u_npu_axil_top.npu_err_code==0)
                        assert(window_requested_elements==window_response_elements)
                            else $fatal(1,"window response elements differ from requested elements");
                    $display("SOC_NETWORK_WINDOW_JOB job=%0d layer=%0d operation=%0d requests=%0d completions=%0d peak_outstanding=%0d response_beats=%0d consecutive_responses=%0d request_response_overlap=%0d requested_elements=%0d response_elements=%0d return_span_cycles=%0d",
                        total.jobs-1,layer_open ? int'(layer_index) : -1,int'(job_kind),
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_requests,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_completions,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_peak_outstanding,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_response_beats,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_consecutive_responses,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.win_stat_request_response_overlap,
                        window_requested_elements,window_response_elements,
                        window_response_elements==0 ? 64'd0 : window_last_response_cycle-window_first_response_cycle+1);
                end
                case(job_kind)
                    JOB_GEMM:total.gemm_done++;
                    JOB_CONV:total.conv_done++;
                    JOB_DW:total.dw_done++;
                    JOB_POOL:total.pool_done++;
                    JOB_VECTOR:total.vector_done++;
                    JOB_ADD:total.add_done++;
                    JOB_SOFTMAX:total.softmax_done++;
                    default:$fatal(1,"invalid completed operation");
                endcase
            end
            if(dut.u_npu_axil_top.npu_clk_gate_en &&
               dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_dma_start &&
               dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_dma_im2col) begin
                case(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.rd_command_client)
                    3'd0:total.ia_windows++;
                    3'd1:total.kernel_windows++;
                    3'd4:total.dw_windows++;
                    default:$fatal(1,"invalid im2col client");
                endcase
            end
            if(progress!=progress_seen) begin
                progress_seen=progress;
                $display("SOC_NETWORK_PROGRESS cycles=%0d value=%08x",total.cycles,progress);
                if(progress==network_begin_marker) begin
                    assert(!network_open && !network_complete) else $fatal(1,"duplicate network start");
                    network_start=total;network_open=1;
                end else if(progress==network_end_marker) begin
                    assert(network_open && !layer_open) else $fatal(1,"unmatched network end");
                    report("network",0,difference(total,network_start));
                    network_open=0;network_complete=1;
                end else if(progress[31:16]==16'hd100) begin
                    assert(network_open && !layer_open) else $fatal(1,"unmatched layer start");
                    layer_index=32'(progress[15:0]);layer_start=total;layer_open=1;
                end else if(progress[31:16]==16'hd200) begin
                    assert(layer_open && layer_index==32'(progress[15:0])) else $fatal(1,"unmatched layer end");
                    report("layer",layer_index,difference(total,layer_start));
                    layer_open=0;layer_count++;
                end else if(progress[31:16]==tensor_marker[31:16] && trace_addr!=0) begin
                    tensor_addr=ram_word(trace_addr+4*trace_address_word);
                    tensor_bytes=ram_word(trace_addr+4*trace_bytes_word);
                    if(trace_file!=0) begin
                        for(int unsigned i=0;i<trace_words;i++) $fwrite(trace_file,"%08x ",ram_word(trace_addr+4*i));
                        $fwrite(trace_file,"\n");$fflush(trace_file);
                    end
                    if(trace_dir!="") dump_bytes($sformatf("%s/tensor_%0d.bin",trace_dir,trace_count),tensor_addr,tensor_bytes);
                    trace_count++;
                end
                $fflush();
            end
            if(cpu_trap) $fatal(1,"CPU trap cycles=%0d pc=%08x",total.cycles,pc);
            if(total.cycles>=timeout_cycles) $fatal(1,"CPU timeout cycles=%0d pc=%08x progress=%08x",total.cycles,pc,progress);
            if(soc_finish) begin
                report("boot",0,total);
                if(result_path!="") dump_bytes(result_path,result_addr,result_words*4);
                if(output_addr_word>=0) output_addr=ram_word(result_addr+4*32'(output_addr_word));
                if(output_bytes_word>=0) output_bytes=ram_word(result_addr+4*32'(output_bytes_word));
                if(output_path!="" && output_bytes!=0) dump_bytes(output_path,output_addr,output_bytes);
                if(model_path!="" && model_bytes!=0) dump_bytes(model_path,model_addr,model_bytes);
                if(input_path!="" && input_bytes!=0) dump_bytes(input_path,input_addr,input_bytes);
                if(trace_file!=0) $fclose(trace_file);
                assert(soc_status==expected_status && total.axi_errors==0 && total.npu_errors==0)
                    else $fatal(1,"firmware status=%08x axi_errors=%0d npu_errors=%0d",soc_status,total.axi_errors,total.npu_errors);
                assert(total.jobs==total.done_jobs) else $fatal(1,"NPU command/completion count mismatch");
                assert(outstanding_reads==0 && outstanding_writes==0 && !npu_busy && !job_inflight)
                    else $fatal(1,"unfinished accelerator operation");
                assert(network_complete && !network_open && !layer_open) else $fatal(1,"missing completed network interval");
                $display("SOC_NETWORK_PASS status=%0d cycles=%0d layers=%0d tensors=%0d output_bytes=%0d",
                         soc_status,total.cycles,layer_count,trace_count,output_bytes);
                $finish;
            end
        end
    end
endmodule
