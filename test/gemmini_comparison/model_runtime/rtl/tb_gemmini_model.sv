// SPDX-License-Identifier: Apache-2.0
// Observes Gemmini firmware on the same PicoRV32, interconnect and shared RAM.
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
module tb_model_benchmark(input logic clk, rst_n, output logic finished,
                      output logic [31:0] progress, pc);
    localparam int RAM_WORDS = `SOC_NETWORK_RAM_WORDS;
    localparam int BUS_BYTES = `SOC_NETWORK_BUS_WIDTH / 8;
    localparam int RAM_INDEX_BITS = $clog2(RAM_WORDS*4/BUS_BYTES);
    wire npu_busy, npu_irq, uart_tx, soc_finish, cpu_trap;
    wire [31:0] soc_status;
    gemmini_soc_top #(
        .NPU_AXIL_BASE(32'h50000000),
        .SIZE(16), .DATA_WIDTH(16), .WEIGHT_WIDTH(16), .BUS_WIDTH(`SOC_NETWORK_BUS_WIDTH),
        .IA_CACHE_BLOCKS(`SOC_NETWORK_IA_CACHE_BLOCKS), .PS_FRAME_COUNT(16),
        .PS_STORAGE_ROWS(`SOC_NETWORK_PS_STORAGE_ROWS),
        .OA_S16_FIFO_BANKS_MAX(`SOC_NETWORK_S16_OUTPUT_BANKS),
        .ENABLE_VECTOR_ENGINE(1), .VECTOR_PE_COUNT(`SOC_NETWORK_PE_COUNT), .DW_MAX_TAPS(49), .POOL_MAX_TAPS(256),
        .CPU_MEM_DP(RAM_WORDS), .CPU_MEM_PATH(""), .CPU_MEM_INIT_EN(1),
        .CPU_MEM_WORD_WIDTH(`SOC_NETWORK_BUS_WIDTH),
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
               dut.u_axi_sim_ram.MEM_WORD_WIDTH==`SOC_NETWORK_BUS_WIDTH &&
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
        logic [63:0] cycles;
        logic [63:0] npu_busy_cycles;
        logic [63:0] cpu_instruction_reads;
        logic [63:0] cpu_data_reads;
        logic [63:0] cpu_data_write_bytes;
        logic [63:0] cpu_mmio_reads;
        logic [63:0] cpu_mmio_write_bytes;
        logic [63:0] npu_read_bytes;
        logic [63:0] npu_write_bytes;
        logic [63:0] npu_read_bursts;
        logic [63:0] npu_write_bursts;
        logic [63:0] axi_errors;
        logic [63:0] npu_errors;
        logic [63:0] commands;
        logic [63:0] load_busy_cycles;
        logic [63:0] execute_busy_cycles;
        logic [63:0] store_busy_cycles;
        logic [63:0] dwconv_cycles;
        logic [63:0] loop_dwconv_cycles;
        logic [63:0] im2col_cycles;
        logic [63:0] im2col_requests;
        logic [63:0] im2col_responses;
    } counters_t;
    counters_t total, network_start, layer_start;
    logic [31:0] progress_seen, network_begin_marker, network_end_marker, tensor_marker;
    bit network_open, network_complete, layer_open;
    int unsigned layer_index, layer_count;
    int outstanding_reads, outstanding_writes;
    longint unsigned max_npu_read_burst_bytes, max_npu_write_burst_bytes;
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
    function automatic counters_t difference(input counters_t a,b);
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
        c.axi_errors=a.axi_errors-b.axi_errors;
        c.npu_errors=a.npu_errors-b.npu_errors;
        c.commands=a.commands-b.commands;
        c.load_busy_cycles=a.load_busy_cycles-b.load_busy_cycles;
        c.execute_busy_cycles=a.execute_busy_cycles-b.execute_busy_cycles;
        c.store_busy_cycles=a.store_busy_cycles-b.store_busy_cycles;
        c.dwconv_cycles=a.dwconv_cycles-b.dwconv_cycles;
        c.loop_dwconv_cycles=a.loop_dwconv_cycles-b.loop_dwconv_cycles;
        c.im2col_cycles=a.im2col_cycles-b.im2col_cycles;
        c.im2col_requests=a.im2col_requests-b.im2col_requests;
        c.im2col_responses=a.im2col_responses-b.im2col_responses;
        return c;
    endfunction
    function automatic logic [31:0] ram_word(input int unsigned addr);
        assert(addr < RAM_WORDS*4 && addr[1:0]==0) else $fatal(1,"invalid observed word address");
        return 32'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr/BUS_BYTES)] >> (8*(addr%BUS_BYTES)));
    endfunction
    function automatic logic [7:0] ram_byte(input int unsigned addr);
        return 8'(dut.u_axi_sim_ram.mem_r[RAM_INDEX_BITS'(addr/BUS_BYTES)] >> (8*(addr%BUS_BYTES)));
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
    task automatic report(input string scope,input int unsigned index,input counters_t c);
        $display("SOC_NETWORK_COUNTER scope=%s index=%0d cycles=%0d npu_busy_cycles=%0d cpu_instruction_reads=%0d cpu_data_reads=%0d cpu_data_write_bytes=%0d cpu_mmio_reads=%0d cpu_mmio_write_bytes=%0d npu_read_bytes=%0d npu_write_bytes=%0d npu_read_bursts=%0d npu_write_bursts=%0d axi_errors=%0d npu_errors=%0d commands=%0d load_busy_cycles=%0d execute_busy_cycles=%0d store_busy_cycles=%0d dwconv_cycles=%0d loop_dwconv_cycles=%0d im2col_cycles=%0d im2col_requests=%0d im2col_responses=%0d",
            scope,index,c.cycles,c.npu_busy_cycles,c.cpu_instruction_reads,c.cpu_data_reads,c.cpu_data_write_bytes,c.cpu_mmio_reads,c.cpu_mmio_write_bytes,c.npu_read_bytes,c.npu_write_bytes,c.npu_read_bursts,c.npu_write_bursts,c.axi_errors,c.npu_errors,c.commands,c.load_busy_cycles,c.execute_busy_cycles,c.store_busy_cycles,c.dwconv_cycles,c.loop_dwconv_cycles,c.im2col_cycles,c.im2col_requests,c.im2col_responses);
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

    always @(posedge clk) begin : observe
        int unsigned tensor_addr,tensor_bytes;
        if (!rst_n) begin
            total='0;network_start='0;layer_start='0;
            progress_seen=0;network_open=0;network_complete=0;layer_open=0;
            layer_index=0;layer_count=0;
            outstanding_reads=0;outstanding_writes=0;
            max_npu_read_burst_bytes=0;max_npu_write_burst_bytes=0;
            read_head=0;read_tail=0;write_head=0;write_tail=0;
            write_data_head=0;outstanding_write_data=0;
        end else begin
            total.cycles++;
            if (npu_busy) total.npu_busy_cycles++;
            if (dut.u_gemmini_mmio.command_valid && dut.u_gemmini_mmio.command_ready) total.commands++;
            if (dut.u_gemmini_mmio.load_busy) total.load_busy_cycles++;
            if (dut.u_gemmini_mmio.execute_busy) total.execute_busy_cycles++;
            if (dut.u_gemmini_mmio.store_busy) total.store_busy_cycles++;
            if (dut.u_gemmini_mmio.dwconv_active) total.dwconv_cycles++;
            if (dut.u_gemmini_mmio.loop_dwconv_busy) total.loop_dwconv_cycles++;
            if (dut.u_gemmini_mmio.im2col_active) total.im2col_cycles++;
            if (dut.u_gemmini_mmio.im2col_request_valid && dut.u_gemmini_mmio.im2col_request_ready)
                total.im2col_requests++;
            if (dut.u_gemmini_mmio.im2col_response_valid && dut.u_gemmini_mmio.im2col_response_ready)
                total.im2col_responses++;
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
                    $display("SOC_NETWORK_AXI_ERROR channel=R cycles=%0d start=%08x address=%08x len=%0d size=%0d burst=%0d resp=%0d last=%0d dw=%0d im2col=%0d execute=%0d",
                        total.cycles,read_address[read_head],read_current[read_head],read_length[read_head],
                        read_size[read_head],read_burst[read_head],dut.npu_axi_rresp,dut.npu_axi_rlast,
                        dut.u_gemmini_mmio.dwconv_active,dut.u_gemmini_mmio.im2col_active,dut.u_gemmini_mmio.execute_busy);
                end
                if(read_burst[read_head]!=0)
                    read_current[read_head]=(read_current[read_head]&~((32'd1<<read_size[read_head])-1))+(32'd1<<read_size[read_head]);
                if(dut.npu_axi_rlast) begin outstanding_reads--;read_head=(read_head+1)%32;end
            end
            if(dut.npu_axi_awvalid && dut.npu_axi_awready) begin
                assert(outstanding_writes<32) else $fatal(1,"write observer capacity exceeded");
                assert(dut.npu_axi_awburst==1 && dut.npu_axi_awsize<=$clog2(BUS_BYTES) && (dut.npu_axi_awaddr&((1<<dut.npu_axi_awsize)-1))==0)
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
                    $display("SOC_NETWORK_AXI_ERROR channel=B cycles=%0d address=%08x len=%0d size=%0d resp=%0d dw=%0d im2col=%0d execute=%0d",
                        total.cycles,write_address[write_head],write_length[write_head],write_size[write_head],dut.npu_axi_bresp,
                        dut.u_gemmini_mmio.dwconv_active,dut.u_gemmini_mmio.im2col_active,dut.u_gemmini_mmio.execute_busy);
                end
                outstanding_writes--;
                write_head=(write_head+1)%32;
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
                assert(outstanding_reads==0 && outstanding_writes==0 && !npu_busy)
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
endmodule
