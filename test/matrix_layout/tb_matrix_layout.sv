// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 8
`endif
`ifndef TB_PS_STORAGE_ROWS
`define TB_PS_STORAGE_ROWS 799
`endif
`ifndef TB_S16_BANKS
`define TB_S16_BANKS 4
`endif
`ifndef TB_ENABLE_IS_MODE
`define TB_ENABLE_IS_MODE 1
`endif
// Complete AXI-Lite register interface, matrix core, and in-order AXI memory.
module tb_matrix_layout;
    localparam int SIZE=16, WORDS=131072, BYTES=WORDS*4;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,new_job=0;
    logic [31:0] cfg[64],golden[WORDS],initial_memory[WORDS];
    logic [1:0] access_kind[BYTES];
    longint unsigned cycle=0,job_start=0;
    always @(posedge clk)if(rst_n)cycle<=cycle+1;

    logic [15:0] la=0,lr=0;
    logic [31:0] ld=0;
    logic [3:0] ls=0;
    logic lav=0,ldv=0,lbr=0,lrv=0,lrr=0;
    wire lar,ldr,lbv,lrar,lrdv;
    wire [1:0] lbre,lrre;
    wire [31:0] lrd;
    wire busy,irq;
    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [31:0] araddr,rdata,awaddr,wdata;
    wire [7:0] arlen,awlen;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,rresp,awburst,bresp;
    wire [3:0] wstrb;
    wire injected,mem_awready,mem_wready;
    wire write_blocked=(cycle-job_start)<64'(cfg[54]);
    assign awready=mem_awready&&!write_blocked;
    assign wready=mem_wready&&!write_blocked;
    longint unsigned read_bytes,input_read_bytes,read_requests,write_bytes;
    wire [31:0] other_lo[4]='{default:0},other_hi[4]='{default:0};

    npu_axil_top #(.SIZE(SIZE),.IA_CACHE_BLOCKS(`TB_IA_CACHE_BLOCKS),.PS_FRAME_COUNT(16),
        .PS_STORAGE_ROWS(`TB_PS_STORAGE_ROWS),.OA_S16_FIFO_BANKS_MAX(`TB_S16_BANKS),
        .ENABLE_IS_MODE(`TB_ENABLE_IS_MODE),
        .AXI_READ_OUTSTANDING(4),.AXI_WRITE_OUTSTANDING(4),.ENABLE_CLOCK_GATING(1),
        .CONV_CACHE_SETS(128),.CONV_CACHE_WAYS(2),.CONV_CACHE_POLICY(3)) u_dut(
        .clk(clk),.rst_n(rst_n),
        .s_axil_awaddr(la),.s_axil_awprot(3'b0),.s_axil_awvalid(lav),.s_axil_awready(lar),
        .s_axil_wdata(ld),.s_axil_wstrb(ls),.s_axil_wvalid(ldv),.s_axil_wready(ldr),
        .s_axil_bresp(lbre),.s_axil_bvalid(lbv),.s_axil_bready(lbr),
        .s_axil_araddr(lr),.s_axil_arprot(3'b0),.s_axil_arvalid(lrv),.s_axil_arready(lrar),
        .s_axil_rdata(lrd),.s_axil_rresp(lrre),.s_axil_rvalid(lrdv),.s_axil_rready(lrr),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_arcache(),.m_axi_arprot(),.m_axi_arlock(),
        .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),
        .m_axi_awvalid(awvalid),.m_axi_awready(awready),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
        .m_axi_awcache(),.m_axi_awprot(),.m_axi_awlock(),
        .m_axi_wvalid(wvalid),.m_axi_wready(wready),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid),.m_axi_bready(bready),.m_axi_bresp(bresp),.irq(irq),.npu_busy(busy)
    );
    conv_test_axi_memory #(.WORDS(WORDS)) u_mem(
        .clk(clk),.rst_n(rst_n),.new_job(new_job),.protect_input(1'b0),
        .inject_error(cfg[53][0] && (cfg[59]==0 || araddr==cfg[59])),
        .inject_write_error(cfg[53][1]),.input_lo(32'b0),.input_hi(32'b0),.error_injected(injected),
        .other_lo(other_lo),.other_hi(other_hi),
        .read_bytes(read_bytes),.input_read_bytes(input_read_bytes),.read_requests(read_requests),.write_bytes(write_bytes),
        .arvalid(arvalid),.arready(arready),.araddr(araddr),.arlen(arlen),.arsize(arsize),.arburst(arburst),
        .rvalid(rvalid),.rready(rready),.rdata(rdata),.rresp(rresp),.rlast(rlast),
        .awvalid(awvalid&&!write_blocked),.awready(mem_awready),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
        .wvalid(wvalid&&!write_blocked),.wready(mem_wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),
        .bvalid(bvalid),.bready(bready),.bresp(bresp)
    );

    // A read may touch valid packed rows, including their reduction padding.
    // Unused rows in the final packed tile are excluded by the access bitmap.
    integer max_s16_used=0,max_s16_ready=0,s16_full_cycles=0,write_stall_cycles=0;
    integer ar_stall_cycles=0,r_wait_cycles=0,page_end_reads=0,page_end_writes=0;
    integer s16_tile_count=0;
    // 已完成存储块与当前写入中的存储块共同构成实际占用量。
    wire [31:0] s16_used_bank_count =
        32'(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.ready_bank_count_q) +
        32'(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.write_ptr != '0);
    bit old_aw_stall=0,old_w_stall=0;
    logic [44:0] old_aw;
    logic [36:0] old_w;
    always @(posedge clk) begin : monitor
        int unsigned byte_addr;
        if(!rst_n || new_job)begin
            max_s16_used=0;max_s16_ready=0;s16_full_cycles=0;write_stall_cycles=0;
            ar_stall_cycles=0;r_wait_cycles=0;page_end_reads=0;page_end_writes=0;s16_tile_count=0;
            old_aw_stall=0;old_w_stall=0;
        end else begin
            if(arvalid&&arready)begin
                for(int b=0;b<((int'(arlen)+1)<<arsize);b++)begin
                    assert(access_kind[araddr+32'(b)][0])
                        else $fatal(1,"read outside permitted allocation addr=%h",araddr+32'(b));
                end
                if((araddr&4095)+((32'(arlen)+1)<<arsize)==4096)page_end_reads++;
            end
            if(awvalid&&awready && (awaddr&4095)+((32'(awlen)+1)<<awsize)==4096)page_end_writes++;
            if(wvalid&&wready)begin
                for(int lane=0;lane<4;lane++)if(wstrb[lane])begin
                    byte_addr=(u_mem.wr_addr&32'hfffffffc)+32'(lane);
                    assert(access_kind[byte_addr][1])else $fatal(1,"write outside output addr=%h",byte_addr);
                end
            end
            if(arvalid&&!arready)ar_stall_cycles++;
            if(u_mem.rd_active&&!rvalid)r_wait_cycles++;
            if((awvalid&&!awready)||(wvalid&&!wready))write_stall_cycles++;
            if(old_aw_stall)assert(awvalid && {awaddr,awlen,awsize,awburst}===old_aw)
                else $fatal(1,"AW changed under write backpressure");
            if(old_w_stall)assert(wvalid && {wdata,wstrb,wlast}===old_w)
                else $fatal(1,"W changed under write backpressure");
            old_aw_stall=awvalid&&!awready;old_w_stall=wvalid&&!wready;
            old_aw={awaddr,awlen,awsize,awburst};old_w={wdata,wstrb,wlast};
            if(cfg[28][0])begin
                assert(s16_used_bank_count<=`TB_S16_BANKS)
                    else $fatal(1,"S16 FIFO capacity exceeded");
                assert(!(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.in_valid &&
                         u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.write_bank_blocked))
                    else $fatal(1,"S16 producer overwrote a ready bank");
                if(int'(s16_used_bank_count)>max_s16_used)
                    max_s16_used=int'(s16_used_bank_count);
                if(int'(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.ready_bank_count_q)>max_s16_ready)
                    max_s16_ready=int'(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.ready_bank_count_q);
                if(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.fifo_s16_full_flag)s16_full_cycles++;
                // FIFO 输入已包含输出模式选择，统计实际接收的 INT16 分块。
                if(u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.in_valid &&
                   u_dut.u_npu_top.u_matrix_engine.u_output_pipeline.u_vec_s16_to_fifo.in_tile_done)
                    s16_tile_count++;
            end
        end
    end

    // Separate AW and W issue times exercise both legal arrival orders.
    task automatic wr(input int unsigned address,input logic[31:0] data,
                      input logic[3:0] strobe=4'hf,input logic[1:0] response=0,input int order=0);
        int elapsed;
        bit a_done,d_done;
        @(negedge clk);la=16'(address);ld=data;ls=strobe;
        a_done=0;d_done=0;elapsed=0;
        lav=(order!=2);ldv=(order!=1);
        while(!a_done||!d_done)begin
            @(posedge clk);
            if(lav&&lar)a_done=1;
            if(ldv&&ldr)d_done=1;
            @(negedge clk);elapsed++;
            lav=!a_done && (order!=2||elapsed>=3);
            ldv=!d_done && (order!=1||elapsed>=3);
            assert(elapsed<100)else $fatal(1,"AXI-Lite write timeout");
        end
        while(!lbv)@(negedge clk);
        assert(lbre==response)else $fatal(1,"AXI-Lite response addr=%h got=%0d expected=%0d",address,lbre,response);
        repeat(2)begin @(negedge clk);assert(lbv&&lbre==response)else $fatal(1,"unstable B response");end
        lbr=1;@(negedge clk);lbr=0;
    endtask
    task automatic rd(input int unsigned address,output logic[31:0] value);
        @(negedge clk);lr=16'(address);lrv=1;
        do @(posedge clk);while(!lrar);
        @(negedge clk);lrv=0;
        while(!lrdv)@(negedge clk);
        value=lrd;assert(lrre==0)else $fatal(1,"AXI-Lite read response");
        repeat(2)begin @(negedge clk);assert(lrdv&&lrd==value)else $fatal(1,"unstable R response");end
        lrr=1;@(negedge clk);lrr=0;
    endtask
    task automatic expect_reg(input int unsigned address,input logic[31:0] expected);
        logic[31:0] value;
        rd(address,value);assert(value==expected)
            else $fatal(1,"register %h got=%h expected=%h",address,value,expected);
    endtask

    task automatic register_checks;
        expect_reg('he4,{8'd16,8'd16,8'(`TB_IA_CACHE_BLOCKS),8'(3|(`TB_ENABLE_IS_MODE ? 4:0))});
        expect_reg('he8,32'(`TB_PS_STORAGE_ROWS));
        expect_reg('hec,{16'(`TB_S16_BANKS),16'd32});
        foreach(cfg[i])cfg[i]=0;
        wr('h0,32'h600,4'h2,0,1);expect_reg('h0,32'h600);
        wr('h0,32'h00e,4'h1,0,2);expect_reg('h0,32'h60e);
        wr('h0,32'h201,4'h2);expect_reg('h0,32'h20e);
        assert(!busy)else $fatal(1,"masked START launched a job");
        wr('h0,32'hffffffff,4'hc);expect_reg('h0,32'h20e);
        wr('h0,32'hffffffff,4'h0);expect_reg('h0,32'h20e);
        wr('he4,0);wr('he8,0);wr('hec,0);
        expect_reg('he4,{8'd16,8'd16,8'(`TB_IA_CACHE_BLOCKS),8'(3|(`TB_ENABLE_IS_MODE ? 4:0))});
        expect_reg('he8,32'(`TB_PS_STORAGE_ROWS));
        expect_reg('hec,{16'(`TB_S16_BANKS),16'd32});
        wr('h0,0);$display("MATRIX_REGISTERS_PASS ia=%0d ps_rows=%0d s16_banks=%0d",`TB_IA_CACHE_BLOCKS,`TB_PS_STORAGE_ROWS,`TB_S16_BANKS);
    endtask

    task automatic configure;
        wr('h10,cfg[14]);wr('h14,cfg[15]);wr('h18,cfg[17]);wr('h1c,cfg[16]);
        wr('h20,cfg[3]);wr('h24,cfg[4]);wr('h28,cfg[5]);
        wr('h2c,cfg[18]);wr('h30,cfg[19]);wr('h34,cfg[20]);
        wr('h38,cfg[21]);wr('h3c,cfg[22]);wr('h40,cfg[23]);
        wr('h44,cfg[24]);wr('h48,cfg[25]);wr('h4c,cfg[26]);wr('h50,cfg[27]);
        wr('h54,cfg[6]);wr('h58,cfg[7]);
        wr('h60,{16'b0,cfg[30][15:0]});wr('h64,{16'b0,cfg[31][15:0]});
        wr('h68,{16'b0,cfg[30][31:16]});wr('h6c,{16'b0,cfg[31][31:16]});
        wr('h74,cfg[33]);wr('h78,{cfg[35][15:0],cfg[34][15:0]});
        wr('h7c,{cfg[37][15:0],cfg[36][15:0]});wr('h80,cfg[38]);
        wr('h84,{cfg[40][15:0],cfg[39][15:0]});wr('h88,{cfg[42][15:0],cfg[41][15:0]});
        wr('h8c,{cfg[44][15:0],cfg[43][15:0]});wr('h90,{cfg[46][15:0],cfg[45][15:0]});
        wr('h94,{cfg[48][15:0],cfg[47][15:0]});wr('h98,cfg[49]);
    endtask

    initial begin : run_suite
        string suite_path,cfg_path,init_path,golden_path,access_path;
        integer f,fields,task_number,errors;
        longint unsigned end_cycle;
        logic [31:0] status,ctrl;
        logic [7:0] observed,expected,original;
        task_number=0;
        foreach(cfg[i])cfg[i]=0;
        if(!$value$plusargs("SUITE=%s",suite_path))$fatal(1,"SUITE required");
        f=$fopen(suite_path,"r");assert(f!=0)else $fatal(1,"cannot open suite");
        repeat(5)@(negedge clk);rst_n=1;repeat(8)@(negedge clk);
        register_checks();
        while(!$feof(f))begin
            fields=$fscanf(f,"%s %s %s %s\n",cfg_path,init_path,golden_path,access_path);
            if(fields==4)begin
                assert(!busy)else $fatal(1,"busy before task %0d",task_number);
                $readmemh(cfg_path,cfg);
                assert(cfg[1]==SIZE && cfg[2]==`TB_IA_CACHE_BLOCKS)else $fatal(1,"profile mismatch");
                for(int i=0;i<WORDS;i++)begin u_mem.mem[i]=32'h5aa53cc3;golden[i]=32'h5aa53cc3;end
                for(int i=0;i<BYTES;i++)access_kind[i]=0;
                $readmemh(init_path,u_mem.mem);$readmemh(golden_path,golden);$readmemh(access_path,access_kind);
                for(int i=0;i<WORDS;i++)initial_memory[i]=u_mem.mem[i];
                configure();
                new_job=1;@(negedge clk);new_job=0;job_start=cycle;
                ctrl=(cfg[12]<<1)|(cfg[13]<<2)|(cfg[8]<<3)|(cfg[28]<<5)|(cfg[32]<<6)|(cfg[50]<<7)|(cfg[29]<<9);
                wr(0,ctrl|1);
                if(cfg[55]!=0)begin
                    wr(0,32'h600,4'h2,2'b10);expect_reg(0,ctrl);
                    wr('h10,32'h77777777,4'hf,2'b10);expect_reg('h10,cfg[14]);
                end
                status=0;
                while(!status[2] && cycle-job_start<2_000_000)begin
                    rd(4,status);
                    if(!status[2])repeat(5)@(negedge clk);
                end
                end_cycle=cycle;
                assert(status[2])else $fatal(1,"job timeout task=%0d state=%0d",task_number,u_dut.u_npu_top.u_matrix_engine.u_npu_controller.current_state);
                assert(status[4:3]==cfg[52][1:0])else $fatal(1,"error task=%0d got=%0d expected=%0d",task_number,status[4:3],cfg[52]);
                if(cfg[53]!=0)assert(injected)else $fatal(1,"requested bus error was not injected");
                assert(u_mem.count==0&&!u_mem.rd_active&&!rvalid&&!u_mem.wr_active&&!bvalid)
                    else $fatal(1,"job completed before AXI transactions drained");
                if(cfg[52]==1)assert(read_requests==0&&write_bytes==0)else $fatal(1,"invalid configuration accessed memory");
                errors=0;
                for(int addr=0;addr<BYTES;addr++)begin
                    observed=u_mem.mem[addr>>2][(addr&3)*8+:8];
                    expected=golden[addr>>2][(addr&3)*8+:8];
                    original=initial_memory[addr>>2][(addr&3)*8+:8];
                    if(cfg[53][1]&&access_kind[addr][1])begin
                        if(observed!=expected&&observed!=original)errors++;
                    end else if(observed!=expected)begin
                        if(errors<8)$display("MISMATCH task=%0d addr=%h got=%h expected=%h",task_number,addr,observed,expected);
                        errors++;
                    end
                end
                assert(errors==0)else $fatal(1,"memory comparison failed task=%0d bytes=%0d",task_number,errors);
                if(cfg[56]!=0)begin
                    assert(max_s16_used==`TB_S16_BANKS&&s16_full_cycles>0&&write_stall_cycles>100)
                        else $fatal(1,"S16 backpressure coverage used=%0d full_cycles=%0d stalls=%0d",max_s16_used,s16_full_cycles,write_stall_cycles);
                end
                if(cfg[57]!=0)assert(page_end_reads>0)else $fatal(1,"4 KiB read boundary not exercised");
                if(cfg[58]!=0)assert(page_end_writes>0)else $fatal(1,"4 KiB write boundary not exercised");
                if(cfg[52]==0)begin
                    assert(write_bytes==64'(cfg[3])*64'(cfg[5])*(cfg[28][0]?2:1))else $fatal(1,"output byte count mismatch");
                end
                $display("MATRIX_TASK_PASS task=%0d error=%0d cycles=%0d ar_bytes=%0d ar_requests=%0d write_bytes=%0d max_s16_used=%0d max_s16_ready=%0d s16_full_cycles=%0d s16_tiles=%0d write_stall_cycles=%0d ar_stall_cycles=%0d r_wait_cycles=%0d page_end_reads=%0d page_end_writes=%0d",task_number,status[4:3],end_cycle-job_start,read_bytes,read_requests,write_bytes,max_s16_used,max_s16_ready,s16_full_cycles,s16_tile_count,write_stall_cycles,ar_stall_cycles,r_wait_cycles,page_end_reads,page_end_writes);
                wr(4,4);rd(4,status);assert(!status[2]&&!busy)else $fatal(1,"completion status did not clear");
                repeat(8)@(negedge clk);task_number++;
            end else if(fields!=-1)$fatal(1,"malformed suite");
        end
        $fclose(f);assert(task_number>0)else $fatal(1,"empty suite");
        $display("MATRIX_LAYOUT_PASS tasks=%0d ia=%0d ps_rows=%0d s16_banks=%0d",task_number,`TB_IA_CACHE_BLOCKS,`TB_PS_STORAGE_ROWS,`TB_S16_BANKS);
        $finish;
    end
endmodule
