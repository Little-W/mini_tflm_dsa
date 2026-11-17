// SPDX-License-Identifier: Apache-2.0
// Observes firmware executing on the production CPU, interconnect, NPU and RAM.
`ifndef SOC_NETWORK_RAM_WORDS
`define SOC_NETWORK_RAM_WORDS 524288
`endif
`ifndef SOC_NETWORK_ICACHE
`define SOC_NETWORK_ICACHE 1
`endif
`ifndef SOC_NETWORK_CPU_ENABLE_MUL
`define SOC_NETWORK_CPU_ENABLE_MUL 1
`endif
`ifndef SOC_NETWORK_CPU_ENABLE_FAST_MUL
`define SOC_NETWORK_CPU_ENABLE_FAST_MUL 1
`endif
`ifndef SOC_NETWORK_CPU_ENABLE_DIV
`define SOC_NETWORK_CPU_ENABLE_DIV 1
`endif
`ifndef SOC_NETWORK_CPU_ENABLE_REGS_DUALPORT
`define SOC_NETWORK_CPU_ENABLE_REGS_DUALPORT 1
`endif
`ifndef SOC_NETWORK_CPU_TWO_STAGE_SHIFT
`define SOC_NETWORK_CPU_TWO_STAGE_SHIFT 1
`endif
`ifndef SOC_NETWORK_CPU_BARREL_SHIFTER
`define SOC_NETWORK_CPU_BARREL_SHIFTER 1
`endif
`ifndef SOC_NETWORK_CPU_TWO_CYCLE_COMPARE
`define SOC_NETWORK_CPU_TWO_CYCLE_COMPARE 0
`endif
`ifndef SOC_NETWORK_CPU_TWO_CYCLE_ALU
`define SOC_NETWORK_CPU_TWO_CYCLE_ALU 0
`endif
`ifndef SOC_NETWORK_PE_COUNT
`define SOC_NETWORK_PE_COUNT 8
`endif
`ifndef SOC_NETWORK_READ_FIRST_LATENCY
`define SOC_NETWORK_READ_FIRST_LATENCY 8
`endif
`ifndef SOC_NETWORK_BUS_WIDTH
`define SOC_NETWORK_BUS_WIDTH 64
`endif
`ifndef SOC_NETWORK_SHARED_BANK_BYTES
`define SOC_NETWORK_SHARED_BANK_BYTES 2048
`endif
`ifndef SOC_NETWORK_SHARED_BANK_COUNT
`define SOC_NETWORK_SHARED_BANK_COUNT 7
`endif
`ifndef SOC_NETWORK_IM2COL_CACHE_BYTES
`define SOC_NETWORK_IM2COL_CACHE_BYTES 4096
`endif
`ifndef SOC_NETWORK_DMA_MAX_BYTES
`define SOC_NETWORK_DMA_MAX_BYTES (256 * (`SOC_NETWORK_BUS_WIDTH / 8))
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
`define PS_BENCH_AXIL dut.u_npu_axil_top
`define PS_BENCH_CORE dut.u_npu_axil_top.u_npu_top
module tb_model_benchmark(input logic clk, rst_n, output logic finished,
                      output logic [31:0] progress, pc);
    localparam int RAM_WORDS = `SOC_NETWORK_RAM_WORDS;
    localparam int BUS_BYTES = `SOC_NETWORK_BUS_WIDTH / 8;
    localparam int RAM_INDEX_BITS = $clog2(RAM_WORDS*4/BUS_BYTES);
    wire npu_busy, npu_irq, uart_tx, soc_finish, cpu_trap;
    wire [31:0] soc_status;
    soc_top #(
        .SIZE(16), .DATA_WIDTH(16), .WEIGHT_WIDTH(16), .BUS_WIDTH(`SOC_NETWORK_BUS_WIDTH),
        .SHARED_BANK_BYTES(`SOC_NETWORK_SHARED_BANK_BYTES),
        .SHARED_BANK_COUNT(`SOC_NETWORK_SHARED_BANK_COUNT),
        .IM2COL_CACHE_BYTES(`SOC_NETWORK_IM2COL_CACHE_BYTES),
        .CPU_MEM_WORD_WIDTH(`SOC_NETWORK_BUS_WIDTH),
        .IA_CACHE_BLOCKS(`SOC_NETWORK_IA_CACHE_BLOCKS), .PS_FRAME_COUNT(16),
        .PS_STORAGE_ROWS(`SOC_NETWORK_PS_STORAGE_ROWS),
        .OA_S16_FIFO_BANKS_MAX(`SOC_NETWORK_S16_OUTPUT_BANKS),
        .ENABLE_VECTOR_ENGINE(1), .VECTOR_PE_COUNT(`SOC_NETWORK_PE_COUNT), .DW_MAX_TAPS(49), .POOL_MAX_TAPS(256),
        .CPU_MEM_DP(RAM_WORDS), .CPU_MEM_PATH(""), .CPU_MEM_INIT_EN(1),
        .CPU_ENABLE_ICACHE(`SOC_NETWORK_ICACHE),
        .CPU_ENABLE_MUL(`SOC_NETWORK_CPU_ENABLE_MUL),
        .CPU_ENABLE_FAST_MUL(`SOC_NETWORK_CPU_ENABLE_FAST_MUL),
        .CPU_ENABLE_DIV(`SOC_NETWORK_CPU_ENABLE_DIV),
        .CPU_ENABLE_REGS_DUALPORT(`SOC_NETWORK_CPU_ENABLE_REGS_DUALPORT),
        .CPU_TWO_STAGE_SHIFT(`SOC_NETWORK_CPU_TWO_STAGE_SHIFT),
        .CPU_BARREL_SHIFTER(`SOC_NETWORK_CPU_BARREL_SHIFTER),
        .CPU_TWO_CYCLE_COMPARE(`SOC_NETWORK_CPU_TWO_CYCLE_COMPARE),
        .CPU_TWO_CYCLE_ALU(`SOC_NETWORK_CPU_TWO_CYCLE_ALU),
        .DMA_MAX_BYTES(`SOC_NETWORK_DMA_MAX_BYTES),
        .RAM_READ_FIRST_LATENCY(`SOC_NETWORK_READ_FIRST_LATENCY),
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

    initial begin
        assert(dut.u_axi_sim_ram.DW==`SOC_NETWORK_BUS_WIDTH &&
               dut.u_axi_sim_ram.DP*BUS_BYTES==RAM_WORDS*4 &&
               dut.u_pico_axi_bridge.DATA_WIDTH==32)
            else $fatal(1,"CPU or shared-memory data width differs from the profile");
        $display("SOC_NETWORK_CPU_PROFILE cpu_enable_mul=%0d cpu_enable_fast_mul=%0d cpu_enable_div=%0d cpu_enable_regs_dualport=%0d cpu_two_stage_shift=%0d cpu_barrel_shifter=%0d cpu_two_cycle_compare=%0d cpu_two_cycle_alu=%0d cpu_icache=%0d",
            dut.u_picorv32.ENABLE_MUL, dut.u_picorv32.ENABLE_FAST_MUL,
            dut.u_picorv32.ENABLE_DIV, dut.u_picorv32.ENABLE_REGS_DUALPORT,
            dut.u_picorv32.TWO_STAGE_SHIFT, dut.u_picorv32.BARREL_SHIFTER,
            dut.u_picorv32.TWO_CYCLE_COMPARE, dut.u_picorv32.TWO_CYCLE_ALU,
            dut.u_pico_axi_bridge.ENABLE_ICACHE);
    end

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
        logic [63:0] capacity_retries, conv_retries, gemm_retries;
    } counters_t;
    counters_t total, network_start, layer_start;
    typedef struct packed {
        logic [63:0] core_cycles, read_bytes, ia_read_bytes, weight_read_bytes;
        logic [63:0] ar, rbeats, write_bytes, ps_wait_cycles, array_rows;
        logic [63:0] ps_write_words, ps_read_words, ps_rows, ps_raw_rows;
    } job_counters_t;
    job_counters_t job_stats;
    logic [63:0] job_start_cycle;
    logic job_is_mode, job_vector;
    longint unsigned job_input_begin, job_input_end, job_weight_begin, job_weight_end;
    logic [31:0] progress_seen, network_begin_marker, network_end_marker, tensor_marker;
    bit network_open, network_complete, layer_open, job_inflight;
    int unsigned layer_index, layer_count;
    typedef enum logic [2:0] {JOB_GEMM, JOB_CONV, JOB_DW, JOB_POOL, JOB_VECTOR, JOB_ADD, JOB_SOFTMAX} job_kind_t;
    job_kind_t job_kind;
    int outstanding_reads, outstanding_writes;
    longint unsigned max_npu_read_burst_bytes, max_npu_write_burst_bytes;
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
        c.capacity_retries=a.capacity_retries-b.capacity_retries;
        c.conv_retries=a.conv_retries-b.conv_retries;
        c.gemm_retries=a.gemm_retries-b.gemm_retries;
        return c;
    endfunction

    function automatic logic [31:0] ram_word(input int unsigned addr);
        assert(addr < RAM_WORDS*4 && addr[1:0]==0) else $fatal(1,"invalid observed word address");
        return 32'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr/BUS_BYTES)] >> (8*(addr% BUS_BYTES)));
    endfunction
    function automatic logic [7:0] ram_byte(input int unsigned addr);
        return 8'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr/BUS_BYTES)] >> (8*(addr% BUS_BYTES)));
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
        $display("SOC_NETWORK_COUNTER scope=%s index=%0d cycles=%0d npu_busy_cycles=%0d cpu_instruction_reads=%0d cpu_data_reads=%0d cpu_data_write_bytes=%0d cpu_mmio_reads=%0d cpu_mmio_write_bytes=%0d npu_read_bytes=%0d npu_write_bytes=%0d npu_read_bursts=%0d npu_write_bursts=%0d jobs=%0d conv_jobs=%0d dw_jobs=%0d pool_jobs=%0d vector_jobs=%0d gemm_jobs=%0d add_jobs=%0d conv_done=%0d dw_done=%0d pool_done=%0d vector_done=%0d gemm_done=%0d add_done=%0d npu_errors=%0d done_jobs=%0d axi_errors=%0d ia_windows=%0d kernel_windows=%0d dw_windows=%0d array_jobs_busy_cycles=%0d array_ia_valid_cycles=%0d array_weight_commits=%0d array_controller_cycles=%0d array_wait_weight_tail=%0d array_wait_weight_data=%0d array_wait_ia_data=%0d array_wait_bias=%0d array_wait_quant=%0d array_wait_output=%0d array_wait_ia_done=%0d window_cache_hits=%0d window_cache_misses=%0d window_cache_read_bytes=%0d vector_compute_cycles=%0d vector_dma_wait_cycles=%0d softmax_jobs=%0d softmax_done=%0d capacity_retries=%0d conv_retries=%0d gemm_retries=%0d",
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
            c.vector_dma_wait_cycles,c.softmax_jobs,c.softmax_done,c.capacity_retries,c.conv_retries,c.gemm_retries);
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
            job_stats='0;job_start_cycle=0;job_is_mode=0;job_vector=0;
            progress_seen=0;network_open=0;network_complete=0;layer_open=0;
            layer_index=0;layer_count=0;job_inflight=0;job_kind=JOB_GEMM;
            outstanding_reads=0;outstanding_writes=0;
            max_npu_read_burst_bytes=0;max_npu_write_burst_bytes=0;
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
                assert(dut.npu_axi_arburst==1 && dut.npu_axi_arsize<=$clog2(BUS_BYTES))
                    else $fatal(1,"unsupported NPU read command");
                assert(((64'(dut.npu_axi_araddr)&4095)&~((64'd1<<dut.npu_axi_arsize)-1))+((64'(dut.npu_axi_arlen)+1)<<dut.npu_axi_arsize)<=4096)
                    else $fatal(1,"NPU read crosses 4 KiB");
                assert(((64'(dut.npu_axi_arlen)+1)<<dut.npu_axi_arsize)<=`SOC_NETWORK_DMA_MAX_BYTES)
                    else $fatal(1,"NPU read exceeds configured DMA transaction length");
                if(((64'(dut.npu_axi_arlen)+1)<<dut.npu_axi_arsize)>max_npu_read_burst_bytes)
                    max_npu_read_burst_bytes=(64'(dut.npu_axi_arlen)+1)<<dut.npu_axi_arsize;
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
                assert(dut.npu_axi_awburst==1 && dut.npu_axi_awsize==$clog2(BUS_BYTES) && (dut.npu_axi_awaddr&(BUS_BYTES-1))==0)
                    else $fatal(1,"unsupported NPU write command");
                assert(((64'(dut.npu_axi_awaddr)&4095)&~((64'd1<<dut.npu_axi_awsize)-1))+((64'(dut.npu_axi_awlen)+1)<<dut.npu_axi_awsize)<=4096)
                    else $fatal(1,"NPU write crosses 4 KiB");
                assert(((64'(dut.npu_axi_awlen)+1)<<dut.npu_axi_awsize)<=`SOC_NETWORK_DMA_MAX_BYTES)
                    else $fatal(1,"NPU write exceeds configured DMA transaction length");
                if(((64'(dut.npu_axi_awlen)+1)<<dut.npu_axi_awsize)>max_npu_write_burst_bytes)
                    max_npu_write_burst_bytes=(64'(dut.npu_axi_awlen)+1)<<dut.npu_axi_awsize;
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
            if (job_inflight) begin
                if (`PS_BENCH_AXIL.npu_clk_gate_en) begin
                    job_stats.core_cycles++;
                    if (!job_vector) begin
                        job_stats.ps_wait_cycles += `PS_BENCH_CORE.u_npu_controller.current_state == 3 &&
                            `PS_BENCH_CORE.ia_data_valid && `PS_BENCH_CORE.u_npu_controller.bias_ready_for_compute &&
                            `PS_BENCH_CORE.quant_params_valid &&
                            !(`PS_BENCH_CORE.fifo_full_flag && `PS_BENCH_CORE.ia_output_pending) &&
                            !`PS_BENCH_CORE.ia_sending_done && !`PS_BENCH_CORE.oa_calc_over && !`PS_BENCH_CORE.ps_frame_ready;
                        job_stats.array_rows += `PS_BENCH_CORE.u_compute_core.ia_row_valid;
`ifdef GEMPACT_PS_COMPRESS
                        job_stats.ps_write_words += $countones(`PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store.payload_ram_write_en);
                        job_stats.ps_read_words += $countones(`PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store.payload_ram_read_en);
                        job_stats.ps_rows += `PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store.encode_commit_valid;
                        job_stats.ps_raw_rows += `PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store.encode_commit_valid &&
                            `PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store.encode_commit_opcode == 3;
`endif
                    end
                end
                if (dut.npu_axi_arvalid && dut.npu_axi_arready) begin
                    job_stats.ar++;
                    job_stats.read_bytes += read_bytes(dut.npu_axi_araddr,dut.npu_axi_arlen,dut.npu_axi_arsize,dut.npu_axi_arburst);
                    if (!job_vector) begin
                        if (64'(dut.npu_axi_araddr) >= job_input_begin &&
                            64'(dut.npu_axi_araddr) < job_input_end)
                            job_stats.ia_read_bytes += read_bytes(dut.npu_axi_araddr,dut.npu_axi_arlen,dut.npu_axi_arsize,dut.npu_axi_arburst);
                        if (64'(dut.npu_axi_araddr) >= job_weight_begin &&
                            64'(dut.npu_axi_araddr) < job_weight_end)
                            job_stats.weight_read_bytes += read_bytes(dut.npu_axi_araddr,dut.npu_axi_arlen,dut.npu_axi_arsize,dut.npu_axi_arburst);
                    end
                end
                if (dut.npu_axi_rvalid && dut.npu_axi_rready) job_stats.rbeats++;
                if (dut.npu_axi_wvalid && dut.npu_axi_wready) job_stats.write_bytes += $countones(dut.npu_axi_wstrb);
            end
            if(dut.u_npu_axil_top.npu_core_calc_start && dut.u_npu_axil_top.npu_sa_ready) begin
                assert(!job_inflight) else $fatal(1,"NPU command already active");
                job_inflight=1;total.jobs++;
                job_stats='0;job_start_cycle=total.cycles;
                job_is_mode=`PS_BENCH_AXIL.cfg_dataflow_mode_reg;
                job_vector=`PS_BENCH_AXIL.cfg_vector_enable_reg;
                // Identify operands at the physical AR handshake, after the
                // registered AXI timing path and descriptor queue.
                job_input_begin = 64'(`PS_BENCH_AXIL.lhs_base_reg) & ~64'(BUS_BYTES-1);
                job_input_end = 64'(`PS_BENCH_AXIL.lhs_base_reg) +
                    (`PS_BENCH_AXIL.cfg_lhs_tile_packed_reg ?
                     ((64'(`PS_BENCH_AXIL.k_reg)+15)/16)*16 *
                     ((64'(`PS_BENCH_AXIL.n_reg)+15)/16)*16 *
                     (`PS_BENCH_AXIL.cfg_16bits_ia_reg ? 2 : 1) :
                     (64'(`PS_BENCH_AXIL.k_reg)-1)*64'(`PS_BENCH_AXIL.lhs_row_stride_b_reg) +
                     64'(`PS_BENCH_AXIL.n_reg)*(`PS_BENCH_AXIL.cfg_16bits_ia_reg ? 2 : 1));
                if (`PS_BENCH_AXIL.cfg_conv_enable_reg) begin
                    job_input_begin = 64'(`PS_BENCH_AXIL.cfg_conv_reg.input_base) & ~64'(BUS_BYTES-1);
                    job_input_end = 64'(`PS_BENCH_AXIL.cfg_conv_reg.input_base) +
                        64'(`PS_BENCH_AXIL.cfg_conv_reg.input_h) *
                        64'(`PS_BENCH_AXIL.cfg_conv_reg.input_w) *
                        64'(`PS_BENCH_AXIL.cfg_conv_reg.input_c);
                end
                job_weight_begin = 64'(`PS_BENCH_AXIL.rhs_base_reg) & ~64'(BUS_BYTES-1);
                job_weight_end = 64'(`PS_BENCH_AXIL.rhs_base_reg) +
                    (`PS_BENCH_AXIL.cfg_rhs_tile_packed_reg ?
                     ((64'(`PS_BENCH_AXIL.m_reg)+15)/16)*16 *
                     ((64'(`PS_BENCH_AXIL.n_reg)+15)/16)*16 :
                     (64'(`PS_BENCH_AXIL.m_reg)-1)*64'(`PS_BENCH_AXIL.rhs_col_stride_b_reg) +
                     64'(`PS_BENCH_AXIL.n_reg));
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
                $display("PS_JOB cycle=%0d job=%0d kind=%0d vector=%0d r=%0d w=%0d conv=%0d is=%0d k=%0d n=%0d m=%0d ps_control=%0d ia_banks=%0d ia_bytes=%0d ps_bytes=%0d",
                    total.cycles,total.jobs,job_kind,job_vector,
                    `PS_BENCH_AXIL.cfg_ia_reuse_num_reg,`PS_BENCH_AXIL.cfg_w_reuse_num_reg,
                    `PS_BENCH_AXIL.cfg_conv_enable_reg,`PS_BENCH_AXIL.cfg_dataflow_mode_reg,
                    `PS_BENCH_AXIL.k_reg,`PS_BENCH_AXIL.n_reg,`PS_BENCH_AXIL.m_reg,`PS_BENCH_AXIL.cfg_ps_control_reg,
                    `PS_BENCH_AXIL.cfg_shared_ia_banks_reg,
                    `PS_BENCH_AXIL.SHARED_CAPABLE ? `PS_BENCH_AXIL.cfg_shared_ia_banks_reg * `PS_BENCH_AXIL.SHARED_BANK_BYTES :
                        `PS_BENCH_AXIL.IA_CACHE_BLOCKS * 16 * 16 * 2,
                    `PS_BENCH_AXIL.SHARED_CAPABLE ? `PS_BENCH_AXIL.SHARED_TOTAL_BYTES -
                        `PS_BENCH_AXIL.cfg_shared_ia_banks_reg * `PS_BENCH_AXIL.SHARED_BANK_BYTES : `PS_BENCH_AXIL.PS_POOL_BYTES);
            end
            if(dut.u_npu_axil_top.npu_done_fire) begin
                assert(job_inflight) else $fatal(1,"NPU completion without command");
                $display("PS_JOB_END job=%0d end_cycle=%0d task_cycles=%0d core_cycles=%0d read_bytes=%0d ia_read_bytes=%0d weight_read_bytes=%0d ar=%0d rbeats=%0d write_bytes=%0d ps_wait_cycles=%0d array_rows=%0d ps_write_words=%0d ps_read_words=%0d ps_rows=%0d ps_raw_rows=%0d error=%0d frame_commands=%0d frame_pressure_events=%0d early_finish_frames=%0d",
                    total.jobs,total.cycles,total.cycles-job_start_cycle,job_stats.core_cycles,
                    job_stats.read_bytes,job_stats.ia_read_bytes,job_stats.weight_read_bytes,
                    job_stats.ar,job_stats.rbeats,job_stats.write_bytes,job_stats.ps_wait_cycles,
                    job_stats.array_rows,job_stats.ps_write_words,job_stats.ps_read_words,
                    job_stats.ps_rows,job_stats.ps_raw_rows,`PS_BENCH_AXIL.npu_err_code,
                    `PS_BENCH_CORE.tb_observer.ps_stat_commands,`PS_BENCH_CORE.tb_observer.ps_stat_pressure_events,
                    `PS_BENCH_CORE.tb_observer.ps_stat_early_finish_frames);
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
                    total.vector_compute_cycles+=64'(dut.u_npu_axil_top.u_npu_top.tb_observer.vector_stat_compute);
                    total.vector_dma_wait_cycles+=64'(dut.u_npu_axil_top.u_npu_top.tb_observer.vector_stat_dma_wait);
                end
                if(job_kind==JOB_CONV || job_kind==JOB_DW || job_kind==JOB_POOL) begin
                    total.window_cache_hits+=64'(dut.u_npu_axil_top.u_npu_top.tb_observer.conv_stat_hits);
                    total.window_cache_misses+=64'(dut.u_npu_axil_top.u_npu_top.tb_observer.conv_stat_misses);
                    total.window_cache_read_bytes+=64'(dut.u_npu_axil_top.u_npu_top.tb_observer.conv_stat_read_bytes);
                end
                if(job_kind==JOB_DW || job_kind==JOB_POOL) begin
                    assert(!dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.win_busy)
                        else $fatal(1,"window requests remain at job completion");
                    assert(dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_requests==
                           dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_completions)
                        else $fatal(1,"window completion count differs from accepted requests");
                    if(dut.u_npu_axil_top.npu_err_code==0)
                        assert(window_requested_elements==window_response_elements)
                            else $fatal(1,"window response elements differ from requested elements");
                    $display("SOC_NETWORK_WINDOW_JOB job=%0d layer=%0d operation=%0d requests=%0d completions=%0d peak_outstanding=%0d response_beats=%0d consecutive_responses=%0d request_response_overlap=%0d requested_elements=%0d response_elements=%0d return_span_cycles=%0d",
                        total.jobs-1,layer_open ? int'(layer_index) : -1,int'(job_kind),
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_requests,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_completions,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_peak_outstanding,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_response_beats,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_consecutive_responses,
                        dut.u_npu_axil_top.u_npu_top.u_block_dma_arbiter.u_dma.tb_observer.win_stat_request_response_overlap,
                        window_requested_elements,window_response_elements,
                        window_response_elements==0 ? 64'd0 : window_last_response_cycle-window_first_response_cycle+1);
                end
                if(dut.u_npu_axil_top.npu_err_code==2) begin
                    assert(job_kind==JOB_CONV || job_kind==JOB_GEMM)
                        else $fatal(1,"Capacity retry reported by a non-GEMM operation");
                    total.capacity_retries++;
                    if(job_kind==JOB_CONV)total.conv_retries++;
                    else total.gemm_retries++;
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
                $display("SOC_NETWORK_DMA_PROFILE read_first_latency=%0d observed_ram_first_min=%0d observed_ram_first_max=%0d ram_read_requests=%0d bus_width=%0d dma_max_bytes=%0d max_read_burst_bytes=%0d max_write_burst_bytes=%0d",
                         dut.u_axi_sim_ram.ram_read_first_latency,
                         dut.u_axi_sim_ram.read_first_latency_min,dut.u_axi_sim_ram.read_first_latency_max,
                         dut.u_axi_sim_ram.read_first_latency_samples,dut.BUS_WIDTH,dut.DMA_MAX_BYTES,max_npu_read_burst_bytes,max_npu_write_burst_bytes);
                $display("SOC_NETWORK_PASS status=%0d cycles=%0d layers=%0d tensors=%0d output_bytes=%0d",
                         soc_status,total.cycles,layer_count,trace_count,output_bytes);
                $finish;
            end
        end
    end
`ifdef GEMPACT_PS_COMPRESS
`define PS_BENCH_STORE `PS_BENCH_CORE.u_compute_core.u_ps_buffer.g_compressed.u_store
    localparam int PS_MONITOR_BANKS = `SOC_NETWORK_SHARED_BANK_COUNT - 1;
    localparam int PS_MONITOR_ROWS = 16 * (4 * `SOC_NETWORK_SHARED_BANK_BYTES / 512);
    initial begin
        assert(`PS_BENCH_CORE.SHARED_RAM_ENABLED &&
               `PS_BENCH_STORE.BANKS == PS_MONITOR_BANKS &&
               `PS_BENCH_CORE.IA_REUSE_NUM_MAX * 16 == PS_MONITOR_ROWS)
            else $fatal(1, "PS capture geometry differs from the shared RAM configuration");
    end
    logic [31:0] occupied_payload_bytes;
    always_comb begin
        occupied_payload_bytes = 0;
        for (int bank = 0; bank < PS_MONITOR_BANKS; bank++) begin
            if (bank < `PS_BENCH_STORE.pool_bank_count_q)
                occupied_payload_bytes += 16 * (32'(`PS_BENCH_STORE.pool_bank_words_q) -
                    32'(`PS_BENCH_STORE.bank_free_count[bank]));
        end
    end
    ps_stream_capture #(
        .MAX_FRAME_ROWS(PS_MONITOR_ROWS),
        .PAYLOAD_BANKS(PS_MONITOR_BANKS)
    ) u_ps_capture (
        .clk(`PS_BENCH_AXIL.npu_core_clk), .rst_n(`PS_BENCH_CORE.core_rst_n),
        .cycle(total.cycles), .job(total.jobs),
        .write_valid(`PS_BENCH_STORE.encoder_start), .write_data(`PS_BENCH_STORE.write_data),
        .frame_accept(`PS_BENCH_STORE.frame_accept), .frame_complete(`PS_BENCH_STORE.frame_complete),
        .frame_id(32'(`PS_BENCH_STORE.frame_id)), .frame_rows(`PS_BENCH_STORE.frame_rows),
        .frame_init(`PS_BENCH_STORE.frame_init), .frame_final(`PS_BENCH_STORE.frame_final),
        .replay_valid(`PS_BENCH_STORE.replay_valid), .replay_data(`PS_BENCH_STORE.replay_data),
        .payload_write_en(`PS_BENCH_STORE.payload_ram_write_en),
        .payload_read_en(`PS_BENCH_STORE.payload_ram_read_en),
        .decoded_write_en(`PS_BENCH_STORE.decoded_write_en),
        .decoded_read_en(`PS_BENCH_STORE.decoded_read_en), .replay_bypass(`PS_BENCH_STORE.replay_bypass),
        .occupied_payload_bytes(occupied_payload_bytes)
    );
`undef PS_BENCH_STORE
`endif

endmodule
`undef PS_BENCH_CORE
`undef PS_BENCH_AXIL
