// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
`ifndef TB_SIZE
`define TB_SIZE 4
`endif
`ifndef TB_CONV_CACHE_SETS
`define TB_CONV_CACHE_SETS 32
`endif
`ifndef TB_CONV_CACHE_POLICY
`define TB_CONV_CACHE_POLICY 2
`endif
module tb_conv_npu;
    import conv_im2col_pkg::*;
    localparam int SIZE=`TB_SIZE;
    localparam int WORDS=131072;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,calc_start=0,done_ready=0,new_job=0;
    wire sa_ready,done_valid;
    wire [1:0] err_code;
    logic [31:0] cfg[64], saved_cfg[64],golden[WORDS];
    conv_cfg_t conv_cfg;
    wire [31:0] hits,misses,conv_bytes,conv_cycles;
    longint unsigned cycle=0;
    always @(posedge clk)if(rst_n)cycle<=cycle+1;
    integer debug_events=0;
    integer padding_reads=0;
    integer ia_im2col_commands=0,kernel_im2col_commands=0;
    integer ar_stall_cycles=0,r_wait_cycles=0;
    always @(posedge clk)begin
        if(!rst_n || new_job)begin
            padding_reads=0;ia_im2col_commands=0;kernel_im2col_commands=0;
            ar_stall_cycles=0;r_wait_cycles=0;
        end else begin
            if(u_dut.u_block_dma_arbiter.u_dma.fe_arvalid &&
               u_dut.u_block_dma_arbiter.u_dma.fe_arready &&
               u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.pad_q)padding_reads++;
            if(u_dut.ia_dma_start && u_dut.ia_dma_im2col)begin
                assert(saved_cfg[32][0] && !saved_cfg[8][0])else $fatal(1,"IA im2col descriptor outside WS Conv");
                ia_im2col_commands++;
            end
            if(u_dut.kernel_dma_start && u_dut.kernel_dma_im2col)begin
                assert(saved_cfg[32][0] && saved_cfg[8][0])else $fatal(1,"kernel im2col descriptor outside IS Conv");
                kernel_im2col_commands++;
            end
            if(arvalid && !arready)ar_stall_cycles++;
            if(u_mem.rd_active && !rvalid && u_mem.random_wait && !u_mem.random_state[5])r_wait_cycles++;
        end
    end
    always @(posedge clk)if(rst_n && $test$plusargs("DEBUG_TILES") && debug_events<160)begin
        if(u_dut.u_ia_loader.tl_start || u_dut.u_ia_loader.tl_tile_done)begin
            $display("TILE cycle=%0d start=%0d done=%0d p=%0d q=%0d rows=%0d slot=%0d loaded=%0d cursor=%0d pf=%0d l2=%0d l1=%0d rd=%0d wr=%0d valid=%b",
                cycle,u_dut.u_ia_loader.tl_start,u_dut.u_ia_loader.tl_tile_done,
                u_dut.u_ia_loader.u_ctrl.tl_p0,u_dut.u_ia_loader.u_ctrl.tl_q0,
                u_dut.u_ia_loader.u_ctrl.tl_rows_to_read,u_dut.u_ia_loader.u_ctrl.tl_slot_id,
                u_dut.u_ia_loader.u_ctrl.load_tiles_done,u_dut.u_ia_loader.u_ctrl.load_ia_cursor,
                u_dut.u_ia_loader.u_ctrl.prefetch_active,u_dut.u_ia_loader.u_ctrl.l2_idx,u_dut.u_ia_loader.u_ctrl.l1_idx,
                u_dut.u_ia_loader.u_ctrl.rd_slot_base,u_dut.u_ia_loader.u_ctrl.wr_slot_ptr,u_dut.u_ia_loader.u_ctrl.cache_blk_valid);
            debug_events++;
        end
    end

    always_comb begin
        conv_cfg='0;
        conv_cfg.input_base=cfg[33];
        conv_cfg.input_h=cfg[34][15:0];conv_cfg.input_w=cfg[35][15:0];conv_cfg.input_c=cfg[36][15:0];
        conv_cfg.group_c=cfg[37][15:0];conv_cfg.group_offset=cfg[38][15:0];
        conv_cfg.kernel_h=cfg[39][15:0];conv_cfg.kernel_w=cfg[40][15:0];
        conv_cfg.output_h=cfg[41][15:0];conv_cfg.output_w=cfg[42][15:0];
        conv_cfg.stride_h=cfg[43][15:0];conv_cfg.stride_w=cfg[44][15:0];
        conv_cfg.dilation_h=cfg[45][15:0];conv_cfg.dilation_w=cfg[46][15:0];
        conv_cfg.pad_top=cfg[47][15:0];conv_cfg.pad_left=cfg[48][15:0];
        conv_cfg.input_offset=$signed(cfg[49][15:0]);
        conv_cfg.bypass_cache=cfg[50][0];conv_cfg.input_s16=cfg[51][0];
    end
    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [31:0] araddr,rdata,awaddr,wdata;
    wire [7:0] arlen,awlen;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,rresp,awburst,bresp;
    wire [3:0] wstrb;
    wire injected;
    wire [31:0] tensor_bytes=saved_cfg[34]*saved_cfg[35]*saved_cfg[36]*(saved_cfg[51][0]?32'd2:32'd1);
    wire [31:0] other_lo[4],other_hi[4];
    assign other_lo[0]=saved_cfg[15];assign other_hi[0]=saved_cfg[15]+saved_cfg[4]*saved_cfg[5];
    assign other_lo[1]=saved_cfg[16];assign other_hi[1]=saved_cfg[16]+4*saved_cfg[5];
    assign other_lo[2]=saved_cfg[13][0]?saved_cfg[24]:0;assign other_hi[2]=saved_cfg[24]+4*saved_cfg[5];
    assign other_lo[3]=saved_cfg[13][0]?saved_cfg[25]:0;assign other_hi[3]=saved_cfg[25]+4*saved_cfg[5];
    longint unsigned read_bytes,input_read_bytes,read_requests,write_bytes;

    npu_top #(.SIZE(SIZE),.DATA_WIDTH(16),.WEIGHT_WIDTH(16),.IA_CACHE_BLOCKS(4),.PS_FRAME_COUNT(16),.AXI_READ_OUTSTANDING(4),
        .CONV_CACHE_SETS(`TB_CONV_CACHE_SETS),.CONV_CACHE_WAYS(2),.CONV_LINE_BYTES(16),
        .CONV_CACHE_POLICY(`TB_CONV_CACHE_POLICY)) u_dut(
        .clk(clk),.rst_n(rst_n),.calc_start(calc_start),.sa_ready(sa_ready),.done_valid(done_valid),.done_ready(done_ready),.err_code(err_code),
        .cfg_operand_fetch64(1'b0),.cfg_16bits_ia(cfg[12][0]),.cfg_16x8(cfg[28][0]),.cfg_dataflow_mode(cfg[8][0]),
        .cfg_ia_reuse_num(cfg[6]),.cfg_w_reuse_num(cfg[7]),
        .cfg_row_groups({16'b0,cfg[30][15:0]}),.cfg_col_groups({16'b0,cfg[30][31:16]}),
        .cfg_row_tail_tiles({16'b0,cfg[31][15:0]}),.cfg_col_tail_tiles({16'b0,cfg[31][31:16]}),
        .cfg_conv_enable(cfg[32][0]),.cfg_conv(conv_cfg),
        .conv_stat_hits(hits),.conv_stat_misses(misses),.conv_stat_read_bytes(conv_bytes),.conv_stat_cycles(conv_cycles),
        .lhs_base(cfg[14]),.rhs_base(cfg[15]),.bias_base(cfg[16]),.dst_base(cfg[17]),
        .lhs_row_stride_b(cfg[18]),.rhs_col_stride_b(cfg[19]),.dst_row_stride_b(cfg[20]),
        .lhs_zp(cfg[21]),.rhs_zp(cfg[22]),.dst_zp(cfg[23]),.q_mult_pt(cfg[24]),.q_shift_pt(cfg[25]),
        .use_per_channel(cfg[13][0]),.act_min(cfg[26]),.act_max(cfg[27]),.k(cfg[3]),.n(cfg[4]),.m(cfg[5]),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),
        .m_axi_awvalid(awvalid),.m_axi_awready(awready),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
        .m_axi_wvalid(wvalid),.m_axi_wready(wready),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid),.m_axi_bready(bready),.m_axi_bresp(bresp)
    );
    conv_test_axi_memory #(.WORDS(WORDS)) u_mem(
        .clk(clk),.rst_n(rst_n),.new_job(new_job),.protect_input(saved_cfg[32][0]),.inject_error(saved_cfg[53][0]),
        .input_lo(saved_cfg[33]),.input_hi(saved_cfg[33]+tensor_bytes),.error_injected(injected),
        .other_lo(other_lo),.other_hi(other_hi),
        .read_bytes(read_bytes),.input_read_bytes(input_read_bytes),.read_requests(read_requests),.write_bytes(write_bytes),
        .arvalid(arvalid),.arready(arready),.araddr(araddr),.arlen(arlen),.arsize(arsize),.arburst(arburst),
        .rvalid(rvalid),.rready(rready),.rdata(rdata),.rresp(rresp),.rlast(rlast),
        .awvalid(awvalid),.awready(awready),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
        .wvalid(wvalid),.wready(wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bresp(bresp)
    );

    initial begin : run_suite
        string suite_path,cfg_path,init_path,golden_path,required_path,histogram_path;
        integer f,fields,task_number,errors,histogram_file;
        integer unique_input,max_input_reads,required_input,unused_unique_input,covered_input;
        longint unsigned histogram_total;
        longint unsigned start_cycle,end_cycle;
        logic [1:0] observed_error;
        task_number=0;
        for(int i=0;i<64;i++)begin cfg[i]=0;saved_cfg[i]=0;end
        if(!$value$plusargs("SUITE=%s",suite_path))$fatal(1,"SUITE required");
        f=$fopen(suite_path,"r");if(f==0)$fatal(1,"cannot open suite");
        repeat(5)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
        while(!$feof(f))begin
            fields=$fscanf(f,"%s %s %s %s\n",cfg_path,init_path,golden_path,required_path);
            if(fields==4)begin
                assert(sa_ready)else $fatal(1,"NPU not ready before task %0d",task_number);
                $readmemh(cfg_path,cfg);
                for(int i=0;i<64;i++)saved_cfg[i]=cfg[i];
                assert(cfg[1]==SIZE)else $fatal(1,"wrong array size");
                for(int i=0;i<WORDS;i++)begin u_mem.mem[i]=32'h5aa53cc3;golden[i]=32'h5aa53cc3;end
                $readmemh(init_path,u_mem.mem);$readmemh(golden_path,golden);
                for(int i=0;i<65536;i++)u_mem.input_required[i]=0;
                $readmemh(required_path,u_mem.input_required);
                new_job=1;@(negedge clk);new_job=0;
                start_cycle=cycle;calc_start=1;@(negedge clk);calc_start=0;
                if(saved_cfg[56]!=0)begin
                    repeat(3)@(negedge clk);
                    cfg[33]=32'h1f000;cfg[34]=1;cfg[35]=1;
                end
                while(!done_valid && cycle-start_cycle<2_000_000)@(negedge clk);
                if(!done_valid)begin
                    $display("TIMEOUT state=%0d ia_state=%0d fe_state=%0d conv_enable=%0d ready=%0d busy=%0d err=%0d abort=%0d",
                        u_dut.u_npu_controller.current_state,u_dut.u_ia_loader.u_ctrl.state,
                        u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.state,u_dut.run_conv,
                        u_dut.u_block_dma_arbiter.u_dma.fe_tile_ready,u_dut.conv_busy,u_dut.conv_error,u_dut.abort_state);
                    $display("TIMEOUT AXI count=%0d active=%0d ar=%0d/%0d r=%0d/%0d reads=%0d inputbytes=%0d kernelbusy=%0d biasbusy=%0d quantbusy=%0d tlstart=%0d tlbusy=%0d",
                        u_mem.count,u_mem.rd_active,arvalid,arready,rvalid,rready,read_bytes,input_read_bytes,
                        u_dut.kernel_dma_busy,u_dut.bias_dma_busy,u_dut.quant_dma_busy,
                        u_dut.u_ia_loader.tl_start,u_dut.u_ia_loader.tl_busy);
                    $display("TIMEOUT IA loaded=%0d cursor=%0d target=%0d pf=%0d l2=%0d l1=%0d rd=%0d wr=%0d valid=%b canload=%0d req=%0d grant=%0d readygroup=%0d output=%0d wvalid=%0d biasvalid=%0d quantvalid=%0d",
                        u_dut.u_ia_loader.u_ctrl.load_tiles_done,u_dut.u_ia_loader.u_ctrl.load_ia_cursor,
                        u_dut.u_ia_loader.u_ctrl.load_r_target,u_dut.u_ia_loader.u_ctrl.prefetch_active,
                        u_dut.u_ia_loader.u_ctrl.l2_idx,u_dut.u_ia_loader.u_ctrl.l1_idx,
                        u_dut.u_ia_loader.u_ctrl.rd_slot_base,u_dut.u_ia_loader.u_ctrl.wr_slot_ptr,
                        u_dut.u_ia_loader.u_ctrl.cache_blk_valid,u_dut.u_ia_loader.u_ctrl.can_start_load,
                        u_dut.load_ia_req,u_dut.load_ia_granted,u_dut.u_ia_loader.u_ctrl.send_group_ready_r,
                        u_dut.u_ia_loader.u_ctrl.in_l1_output,u_dut.weight_data_valid,u_dut.bias_valid,u_dut.quant_params_valid);
                    $fatal(1,"task timeout id=%0d",task_number);
                end
                observed_error=err_code;
                end_cycle=cycle;
                assert(err_code==saved_cfg[52][1:0])else $fatal(1,"task id=%0d expected error=%0d got=%0d",task_number,saved_cfg[52],err_code);
                if(saved_cfg[53][0])assert(injected)else $fatal(1,"requested RRESP was never injected");
                repeat(3)begin
                    @(negedge clk);
                    assert(done_valid && err_code==observed_error)else $fatal(1,"unstable completion under backpressure");
                end
                errors=0;
                for(int i=0;i<WORDS;i++)begin
                    if(u_mem.mem[i]!==golden[i])begin
                        if(errors<12)$display("MISMATCH task=%0d word=%h got=%h expected=%h",task_number,i,u_mem.mem[i],golden[i]);
                        errors++;
                    end
                end
                assert(errors==0)else $fatal(1,"memory mismatch count=%0d",errors);
                if(saved_cfg[32][0] && saved_cfg[52]==0)
                    assert(64'(conv_bytes)==input_read_bytes)else $fatal(1,"read-byte counter mismatch RTL=%0d AXI=%0d",conv_bytes,input_read_bytes);
                if(saved_cfg[32][0] && saved_cfg[52]==0)begin
                    if(saved_cfg[8][0])assert(kernel_im2col_commands>0 && ia_im2col_commands==0)
                        else $fatal(1,"IS did not use the kernel DMA im2col path");
                    else assert(ia_im2col_commands>0 && kernel_im2col_commands==0)
                        else $fatal(1,"WS did not use the IA DMA im2col path");
                end
                if(saved_cfg[32][0] && saved_cfg[52]==1)
                    assert(read_requests==0 && write_bytes==0 && ia_im2col_commands==0 && kernel_im2col_commands==0)
                        else $fatal(1,"invalid Conv issued memory or im2col commands");
                unique_input=0;max_input_reads=0;required_input=0;unused_unique_input=0;covered_input=0;histogram_total=0;
                histogram_path={suite_path,$sformatf(".task%0d.input_reads.csv",task_number)};
                histogram_file=$fopen(histogram_path,"w");
                assert(histogram_file!=0)else $fatal(1,"cannot create input histogram");
                $fdisplay(histogram_file,"byte_address,allocation_offset,required_by_window,axi_read_count");
                for(int i=0;i<65536;i++)begin
                    histogram_total+=64'(u_mem.input_hist[i]);
                    if(u_mem.input_hist[i]>0)unique_input++;
                    if(u_mem.input_hist[i]>max_input_reads)max_input_reads=int'(u_mem.input_hist[i]);
                    if(u_mem.input_required[i])begin
                        required_input++;
                        if(u_mem.input_hist[i]>0)covered_input++;
                    end else if(u_mem.input_hist[i]>0)unused_unique_input++;
                    if(saved_cfg[32][0] && 32'(i)+32'h10000>=saved_cfg[33] &&
                       32'(i)+32'h10000<saved_cfg[33]+tensor_bytes)begin
                        $fdisplay(histogram_file,"0x%08h,%0d,%0d,%0d",32'(i)+32'h10000,
                            32'(i)+32'h10000-saved_cfg[33],u_mem.input_required[i],u_mem.input_hist[i]);
                        if(saved_cfg[58]!=0)assert(u_mem.input_hist[i]==1)
                            else $fatal(1,"resident input byte %h read %0d times, expected exactly once",32'(i)+32'h10000,u_mem.input_hist[i]);
                    end
                end
                $fclose(histogram_file);
                assert(histogram_total==input_read_bytes)else $fatal(1,"input histogram byte sum mismatch");
                assert(padding_reads==0)else $fatal(1,"padding caused an external input read");
                if(saved_cfg[32][0] && observed_error==0)
                    assert(covered_input==required_input)else $fatal(1,"required input bytes were not fetched");
                $display("CONV_TASK_PASS task=%0d conv=%0d dataflow=%0d bypass=%0d error=%0d cycles=%0d hits=%0d misses=%0d input_bytes=%0d input_unique=%0d input_duplicate=%0d input_max_reads=%0d input_required=%0d input_prefetched_unused=%0d padding_reads=%0d ar_bytes=%0d ar_requests=%0d write_bytes=%0d device_cycles=%0d ia_im2col_commands=%0d kernel_im2col_commands=%0d ar_stall_cycles=%0d r_wait_cycles=%0d",task_number,saved_cfg[32],saved_cfg[8],saved_cfg[50],observed_error,end_cycle-start_cycle,hits,misses,input_read_bytes,unique_input,input_read_bytes-64'(unique_input),max_input_reads,required_input,unused_unique_input,padding_reads,read_bytes,read_requests,write_bytes,conv_cycles,ia_im2col_commands,kernel_im2col_commands,ar_stall_cycles,r_wait_cycles);
                done_ready=1;@(negedge clk);done_ready=0;
                repeat(8)@(negedge clk);
                task_number++;
            end else if(fields!=-1)$fatal(1,"malformed suite entry fields=%0d",fields);
        end
        $fclose(f);
        assert(task_number>0)else $fatal(1,"empty test suite");
        $display("CONV_NPU_PASS tasks=%0d size=%0d",task_number,SIZE);
        $finish;
    end
endmodule
