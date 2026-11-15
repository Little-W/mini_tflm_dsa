// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
`ifndef TB_SIZE
`define TB_SIZE 4
`endif
module tb_conv_dma;
    import conv_im2col_pkg::*;
    localparam int SIZE=`TB_SIZE;
    localparam int DMA_SIZE=(SIZE<16)?16:SIZE;
    localparam int CW=$clog2(SIZE);
    localparam int WORDS=131072;
    logic clk=0,rst_n=0,new_job=0;
    always #5 clk=~clk;
    logic conv_cfg_valid=0,conv_cfg_ready,conv_enable=1;
    conv_cfg_t conv_cfg, oracle_cfg;
    logic [31:0] ranges_base[4];
    logic [32:0] ranges_end[4];
    logic conv_error,conv_busy,idle,bus_error;
    logic [31:0] hits,misses,conv_bytes;
    logic ia_req=0,ia_start=0,ia_granted,ia_busy,ia_done;
    logic ia_im2col=0,ia_use_16bits=0;
    logic [31:0] ia_p0=0,ia_q0=0,ia_base_addr=0,ia_row_stride=0,ia_rows_to_read=0;
    logic [7:0] ia_burst_len_m1=0;
    logic [1:0] ia_slot_id=0,ia_wr_slot;
    logic signed [31:0] ia_lhs_zp=0;
    logic [CW-1:0] ia_wr_row,ia_wr_col_base;
    logic signed [15:0] ia_wr_data[4];
    logic ia_wr_valid[4],ia_wr_use_16bits;
    logic kernel_req=0,kernel_start=0,kernel_granted,kernel_busy,kernel_done;
    logic kernel_im2col=0,kernel_use_16bits=0,kernel_slot_id=0;
    logic [31:0] kernel_p0=0,kernel_q0=0,kernel_base_addr=0,kernel_row_stride=0,kernel_rows_to_read=0;
    logic [7:0] kernel_burst_len_m1=0;
    logic signed [31:0] kernel_lhs_zp=0;
    logic [CW-1:0] kernel_wr_row,kernel_wr_col_base;
    logic signed [15:0] kernel_wr_data[4];
    logic kernel_wr_valid[4];
    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [31:0] araddr,rdata,awaddr,wdata;
    wire [7:0] arlen,awlen;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,rresp,awburst,bresp;
    wire [3:0] wstrb;
    logic inject_error=0,error_injected;
    logic [31:0] other_lo[4],other_hi[4];
    longint unsigned read_bytes,input_read_bytes,read_requests,write_bytes;
    logic [31:0] input_hi;
    assign input_hi=oracle_cfg.input_base+32'(oracle_cfg.input_h)*32'(oracle_cfg.input_w)*32'(oracle_cfg.input_c);
    for(genvar g=0;g<4;g++)begin
        assign other_lo[g]=ranges_base[g];
        assign other_hi[g]=32'(ranges_end[g]);
    end
    axi_block_dma_arbiter #(.SIZE(SIZE),.DMA_SIZE(DMA_SIZE),.DATA_WIDTH(16),.KERNEL_WIDTH(16),
        .CACHE_BLOCKS(4),.CONV_CACHE_SETS(32),.CONV_CACHE_WAYS(2),.CONV_LINE_BYTES(16),.CONV_CACHE_POLICY(2)) u_arb(
        .clk,.rst_n,.conv_cfg_valid,.conv_cfg_ready,.conv_enable,.conv_cfg,
        .conv_sched_r(32'd0),.conv_sched_groups(32'd0),.conv_range_base(ranges_base),.conv_range_end(ranges_end),
        .conv_error,.conv_busy,.conv_stat_hits(hits),.conv_stat_misses(misses),.conv_stat_read_bytes(conv_bytes),
        .ia_req,.ia_granted,.ia_start,.ia_im2col,.ia_p0,.ia_q0,.ia_group(32'd0),.ia_linear_read_mode(1'b0),
        .ia_base_addr,.ia_row_stride,.ia_rows_to_read,.ia_burst_len_m1,.ia_slot_id,.ia_use_16bits,.ia_lhs_zp,
        .ia_busy,.ia_done,.ia_wr_slot,.ia_wr_row,.ia_wr_col_base,.ia_wr_data,.ia_wr_valid,.ia_wr_use_16bits,
        .kernel_req,.kernel_granted,.kernel_start,.kernel_im2col,.kernel_p0,.kernel_q0,.kernel_group(32'd0),
        .kernel_linear_read_mode(1'b0),.kernel_base_addr,.kernel_row_stride,.kernel_rows_to_read,
        .kernel_burst_len_m1,.kernel_slot_id,.kernel_use_16bits,.kernel_lhs_zp,
        .kernel_busy,.kernel_done,.kernel_wr_row,.kernel_wr_col_base,.kernel_wr_data,.kernel_wr_valid,
        .bias_req(1'b0),.bias_granted(),.bias_start(1'b0),.bias_linear_read_mode(1'b0),
        .bias_base_addr(32'd0),.bias_row_stride(32'd0),.bias_rows_to_read(32'd0),.bias_burst_len_m1(8'd0),
        .bias_slot_id(1'b0),.bias_use_16bits(1'b0),.bias_lhs_zp(32'sd0),.bias_busy(),.bias_done(),
        .bias_wr_slot(),.bias_wr_row(),.bias_wr_col_base(),.bias_wr_data(),.bias_wr_valid(),.bias_wr_use_16bits(),
        .quant_req(1'b0),.quant_granted(),.quant_start(1'b0),.quant_linear_read_mode(1'b0),
        .quant_base_addr(32'd0),.quant_row_stride(32'd0),.quant_rows_to_read(32'd0),.quant_burst_len_m1(8'd0),
        .quant_slot_id(1'b0),.quant_use_16bits(1'b0),.quant_lhs_zp(32'sd0),
        .quant_busy(),.quant_done(),.quant_raw_data(),.quant_raw_valid(),
        .oa_req(1'b0),.oa_granted(),.oa_start(1'b0),.oa_base_addr(32'd0),.oa_row_stride(32'd0),
        .oa_rows_to_read(32'd0),.oa_burst_len_m1(8'd0),.oa_src_wdata(32'd0),.oa_src_wmask(4'd0),
        .oa_src_wvalid(1'b0),.oa_src_wready(),.oa_busy(),.oa_done(),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),
        .m_axi_awvalid(awvalid),.m_axi_awready(awready),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
        .m_axi_wvalid(wvalid),.m_axi_wready(wready),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid),.m_axi_bready(bready),.m_axi_bresp(bresp),.idle,.bus_error
    );
    conv_test_axi_memory #(.WORDS(WORDS)) u_mem(
        .clk,.rst_n,.new_job,.protect_input(conv_enable),.inject_error,
        .input_lo(oracle_cfg.input_base),.input_hi,.other_lo,.other_hi,.error_injected,
        .read_bytes,.input_read_bytes,.read_requests,.write_bytes,
        .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,
        .awvalid,.awready,.awaddr,.awlen,.awsize,.awburst,.wvalid,.wready,.wdata,.wstrb,.wlast,.bvalid,.bready,.bresp
    );

    bit active[2],kind[2],seen[2][SIZE][SIZE],failed_completion[2];
    int score_p[2],score_q[2],score_rows[2],score_slot[2],returned[2],success_done[2];
    int descriptor_number=0,completed=0,trace_file,job_number=0;
    int unsigned normal_base=32'h20ffd;
    int ar_stalls=0,r_waits=0,total_elements=0,padding_elements=0,reduction_tail_elements=0;
    longint unsigned cycles=0;
    always @(posedge clk)if(rst_n)cycles<=cycles+1;
    function automatic int signed byte_at(input int unsigned address);
        int value;
        value=int'(u_mem.mem[address/4][(address%4)*8+:8]);
        return value>=128?value-256:value;
    endfunction
    function automatic int signed expected_value(input int owner,input int row,input int col);
        int p,q,oy,ox,tap,ch,ky,kx,iy,ix,address;
        if(!kind[owner])return byte_at(normal_base+32'(row*(SIZE+3)+col))-11;
        p=score_p[owner]+row;q=score_q[owner]+col;
        if(q>=int'(oracle_cfg.kernel_h)*int'(oracle_cfg.kernel_w)*int'(oracle_cfg.group_c))return 0;
        oy=p/int'(oracle_cfg.output_w);ox=p%int'(oracle_cfg.output_w);
        tap=q/int'(oracle_cfg.group_c);ch=q%int'(oracle_cfg.group_c);
        ky=tap/int'(oracle_cfg.kernel_w);kx=tap%int'(oracle_cfg.kernel_w);
        iy=oy*int'(oracle_cfg.stride_h)-int'(oracle_cfg.pad_top)+ky*int'(oracle_cfg.dilation_h);
        ix=ox*int'(oracle_cfg.stride_w)-int'(oracle_cfg.pad_left)+kx*int'(oracle_cfg.dilation_w);
        if(iy<0 || ix<0 || iy>=int'(oracle_cfg.input_h) || ix>=int'(oracle_cfg.input_w))return 0;
        address=int'(oracle_cfg.input_base)+(iy*int'(oracle_cfg.input_w)+ix)*int'(oracle_cfg.input_c)+int'(oracle_cfg.group_offset)+ch;
        return byte_at(32'(address))+int'($signed(oracle_cfg.input_offset));
    endfunction
    always @(posedge clk)if(rst_n)begin : check_returns
        int row,col,expected,observed;
        if(arvalid && !arready)ar_stalls++;
        if(u_mem.rd_active && !rvalid && u_mem.random_wait && !u_mem.random_state[5])r_waits++;
        if(u_arb.u_dma.fe_arvalid && u_arb.u_dma.fe_arready)
            assert(!u_arb.u_dma.g_im2col.u_frontend.pad_q)else $fatal(1,"padding performed an input read");
        for(int owner=0;owner<2;owner++)begin
            if((owner==0 && ia_done)||(owner==1 && kernel_done))success_done[owner]++;
            if(u_arb.u_dma.rd_done && u_arb.u_dma.rd_error && int'(u_arb.rd_response_client)==owner)
                failed_completion[owner]=1;
            for(int lane=0;lane<4;lane++)begin
                if((owner==0 && ia_wr_valid[lane])||(owner==1 && kernel_wr_valid[lane]))begin
                    assert(active[owner])else $fatal(1,"matrix data routed to inactive owner %0d",owner);
                    row=owner==0?int'(ia_wr_row):int'(kernel_wr_row);
                    col=(owner==0?int'(ia_wr_col_base):int'(kernel_wr_col_base))+lane;
                    observed=owner==0?int'($signed(ia_wr_data[lane])):int'($signed(kernel_wr_data[lane]));
                    assert(row<score_rows[owner] && col<SIZE)else $fatal(1,"matrix row/column outside descriptor");
                    assert(!seen[owner][row][col])else $fatal(1,"duplicate matrix element");
                    assert(int'(u_arb.u_dma.wr_slot)==score_slot[owner])else $fatal(1,"wrong matrix slot");
                    if(kind[owner])begin
                        assert(lane<2 && u_arb.u_dma.wr_use_16bits)else $fatal(1,"im2col return is not signed16");
                        if(score_q[owner]+col>=int'(oracle_cfg.kernel_h)*int'(oracle_cfg.kernel_w)*int'(oracle_cfg.group_c))reduction_tail_elements++;
                        if(u_arb.u_dma.g_im2col.u_frontend.pad_q)padding_elements++;
                    end
                    expected=expected_value(owner,row,col);
                    assert(observed==expected)else $fatal(1,"matrix mismatch job=%0d owner=%0d kind=%0d p=%0d q=%0d r=%0d c=%0d expected=%0d got=%0d",job_number,owner,kind[owner],score_p[owner],score_q[owner],row,col,expected,observed);
                    $fdisplay(trace_file,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",job_number,owner,kind[owner],score_p[owner],score_q[owner],row,col,expected,observed);
                    seen[owner][row][col]=1;returned[owner]++;total_elements++;
                end
            end
        end
    end

    task automatic configure(input bit enabled,input int seed,input bit bypass,input bit grouped,input int offset,input bit inject);
        int address,count,value;
        while(!conv_cfg_ready || !idle)@(negedge clk);
        assert(!active[0] && !active[1]);
        conv_cfg='0;conv_cfg.input_base=32'h10ffd;
        conv_cfg.input_h=grouped?16'd6:16'd5;conv_cfg.input_w=grouped?16'd7:16'd5;
        conv_cfg.input_c=grouped?16'd8:16'd3;conv_cfg.group_c=16'd3;conv_cfg.group_offset=grouped?16'd4:16'd0;
        conv_cfg.kernel_h=grouped?16'd2:16'd3;conv_cfg.kernel_w=16'd3;
        conv_cfg.output_h=grouped?16'd3:16'd5;conv_cfg.output_w=grouped?16'd7:16'd5;
        conv_cfg.stride_h=grouped?16'd2:16'd1;conv_cfg.stride_w=16'd1;
        conv_cfg.dilation_h=grouped?16'd2:16'd1;conv_cfg.dilation_w=grouped?16'd2:16'd1;
        conv_cfg.pad_top=16'd1;conv_cfg.pad_left=grouped?16'd2:16'd1;
        conv_cfg.input_offset=16'(offset);conv_cfg.bypass_cache=bypass;
        oracle_cfg=conv_cfg;conv_enable=enabled;inject_error=inject;
        // Conv repairs allocation/4-KiB tails inside DMA. The legacy GEMM
        // contract is unchanged, so its ordinary control command stays in-page.
        normal_base=enabled?32'h20ffd:32'h20f80;
        count=int'(conv_cfg.input_h)*int'(conv_cfg.input_w)*int'(conv_cfg.input_c);
        for(int i=0;i<count;i++)begin
            address=int'(conv_cfg.input_base)+i;value=(i*37+seed*17)%256;
            if(i==0)value=128;if(i==1)value=127;
            u_mem.mem[address/4][(address%4)*8+:8]=8'(value);
        end
        for(int i=0;i<3*(SIZE+3);i++)begin
            address=int'(normal_base)+i;u_mem.mem[address/4][(address%4)*8+:8]=8'(i*29+seed*13);
        end
        for(int i=0;i<4;i++)begin ranges_base[i]=0;ranges_end[i]=0;end
        ranges_base[0]=normal_base;ranges_end[0]=33'(normal_base)+33'(2*(SIZE+3)+SIZE);
        new_job=1;@(negedge clk);new_job=0;
        conv_cfg_valid=1;@(negedge clk);conv_cfg_valid=0;
        job_number++;
        assert(!conv_error)else $fatal(1,"new job failed to clear prior error");
    endtask

    task automatic request(input int owner,input bit im2col,input int p,input int q,input int rows,input int slot,input bit fail,input bit mutate,input bit no_input_reads);
        longint unsigned start_cycle,bytes_before;
        int id;
        id=descriptor_number;descriptor_number++;
        active[owner]=1;kind[owner]=im2col;score_p[owner]=p;score_q[owner]=q;
        score_rows[owner]=rows;score_slot[owner]=slot;returned[owner]=0;success_done[owner]=0;failed_completion[owner]=0;
        for(int r=0;r<SIZE;r++)for(int c=0;c<SIZE;c++)seen[owner][r][c]=0;
        bytes_before=input_read_bytes;start_cycle=cycles;
        if(owner==0)begin
            ia_im2col=im2col;ia_p0=32'(p);ia_q0=32'(q);ia_rows_to_read=32'(rows);ia_slot_id=2'(slot);
            ia_base_addr=normal_base;ia_row_stride=32'(SIZE+3);ia_burst_len_m1=8'(SIZE/4-1);ia_lhs_zp=-32'sd11;ia_use_16bits=im2col;
            ia_req=1;
            while(!ia_granted)@(negedge clk);
            ia_start=1;@(negedge clk);ia_start=0;ia_req=0;
            if(mutate)begin ia_p0=32'hffff;ia_q0=32'hffff;ia_slot_id=0;end
        end else begin
            kernel_im2col=im2col;kernel_p0=32'(p);kernel_q0=32'(q);kernel_rows_to_read=32'(rows);kernel_slot_id=1'(slot);
            kernel_base_addr=normal_base;kernel_row_stride=32'(SIZE+3);kernel_burst_len_m1=8'(SIZE/4-1);kernel_lhs_zp=-32'sd11;kernel_use_16bits=im2col;
            kernel_req=1;
            while(!kernel_granted)@(negedge clk);
            kernel_start=1;@(negedge clk);kernel_start=0;kernel_req=0;
            if(mutate)begin kernel_p0=32'hffff;kernel_q0=32'hffff;kernel_slot_id=0;end
        end
        if(mutate)begin conv_cfg.input_base=32'h1f000;conv_cfg.input_h=1;conv_cfg.input_offset=16'sd1;end
        while((fail?!failed_completion[owner]:success_done[owner]==0) && cycles-start_cycle<200000)@(negedge clk);
        assert(cycles-start_cycle<200000)else $fatal(1,"DMA descriptor timeout id=%0d owner=%0d im2col=%0d",id,owner,im2col);
        @(negedge clk);
        if(fail)begin
            assert(failed_completion[owner] && success_done[owner]==0 && conv_error)else $fatal(1,"failed matrix was published to client");
        end else begin
            assert(success_done[owner]==1 && !conv_error)else $fatal(1,"bad success completion");
            assert(returned[owner]==rows*SIZE)else $fatal(1,"missing matrix elements owner=%0d expected=%0d got=%0d",owner,rows*SIZE,returned[owner]);
        end
        if(no_input_reads)assert(input_read_bytes==bytes_before)else $fatal(1,"resident replay or invalid descriptor fetched input bytes");
        if(mutate)conv_cfg=oracle_cfg;
        active[owner]=0;completed++;
        $display("DMA_MATRIX_PASS case=%0d owner=%0d im2col=%0d error=%0d p=%0d q=%0d rows=%0d elements=%0d cycles=%0d job_input_bytes=%0d",id,owner,im2col,fail,p,q,rows,returned[owner],cycles-start_cycle,input_read_bytes);
    endtask

    logic concurrent_request = 0;
    logic concurrent_done = 0;
    initial begin : queued_producer
        forever begin
            @(posedge concurrent_request);
            concurrent_done = 0;
            while(!ia_busy) @(negedge clk);
            request(1,1,5,0,SIZE,1,0,0,1);
            concurrent_done = 1;
        end
    end

    initial begin : run
        string trace_path;
        int p_tail,q_tail;
        conv_cfg='0;oracle_cfg='0;
        for(int i=0;i<4;i++)begin ranges_base[i]=0;ranges_end[i]=0;end
        for(int o=0;o<2;o++)begin active[o]=0;failed_completion[o]=0;success_done[o]=0;end
        for(int i=0;i<WORDS;i++)u_mem.mem[i]=32'h5aa53cc3;
        if(!$value$plusargs("MATRIX_TRACE=%s",trace_path))trace_path="matrix_returns.csv";
        trace_file=$fopen(trace_path,"w");assert(trace_file!=0);
        $fdisplay(trace_file,"job,owner,im2col,p0,q0,row,col,expected,observed");
        repeat(5)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
        configure(1,11,0,0,128,0);
        request(0,1,5,0,SIZE,3,0,0,0);
        request(1,1,5,0,SIZE,1,0,0,1);
        p_tail=(24/SIZE)*SIZE;q_tail=(26/SIZE)*SIZE;
        request(1,1,p_tail,q_tail,25-p_tail,1,0,0,0);
        request(0,0,0,0,3,2,0,0,1);
        // Queue the next producer during an ordinary read. Its command can be
        // accepted on the old final-R edge; the old final data must retain IA.
        concurrent_request=1;
        request(0,0,0,0,3,2,0,0,1);
        while(!concurrent_done) @(negedge clk);
        concurrent_request=0;
        configure(1,12,0,0,-127,0);
        request(1,1,5,0,SIZE,1,0,1,0);
        configure(1,13,0,1,-127,0);
        request(1,1,(21-SIZE<7)?21-SIZE:7,0,SIZE,1,0,0,0);
        p_tail=(20/SIZE)*SIZE;q_tail=(17/SIZE)*SIZE;
        request(0,1,p_tail,q_tail,21-p_tail,3,0,0,0);
        configure(1,20,0,0,11,1);
        request(1,1,5,0,SIZE,1,1,0,0);
        assert(error_injected)else $fatal(1,"RRESP injection not reached");
        configure(1,21,0,0,11,0);
        request(0,1,5,0,SIZE,3,0,0,0);
        request(1,1,25,0,1,1,1,0,1);
        configure(0,22,0,0,11,0);
        request(0,0,0,0,3,2,0,0,1);
        configure(1,23,0,0,11,0);
        request(1,1,5,0,SIZE,1,0,0,0);
        while(!idle || !conv_cfg_ready)@(negedge clk);
        assert(completed==14 && descriptor_number==14);
        assert(total_elements>0 && padding_elements>0 && reduction_tail_elements>0);
        assert(ar_stalls>0 && r_waits>0)else $fatal(1,"random AXI wait coverage not exercised");
        assert(write_bytes==0)else $fatal(1,"read-only matrix DMA wrote memory");
        $fclose(trace_file);
        $display("CONV_DMA_PASS size=%0d descriptors=%0d jobs=%0d elements=%0d padding_elements=%0d tail_elements=%0d ar_stalls=%0d r_waits=%0d",SIZE,completed,job_number,total_elements,padding_elements,reduction_tail_elements,ar_stalls,r_waits);
        $finish;
    end
    initial begin #100000000;$fatal(1,"global DMA test timeout");end
endmodule
