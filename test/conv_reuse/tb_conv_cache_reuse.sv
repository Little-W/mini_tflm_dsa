module tb_conv_cache_reuse;
    logic clk;
    initial begin clk=0;forever #5 clk=~clk;end
    logic rst_n=0,cfg_valid=0,cfg_ready,cfg_bypass=0;
    logic [31:0] cfg_base=32'h1003,cfg_bytes=106;
    logic req_valid=0,req_ready,rsp_valid,rsp_ready=0,rsp_error;
    logic [31:0] req_addr=0,rsp_data,stat_hits,stat_misses,stat_read_bytes;
    logic arvalid,arready,rvalid,rready,rlast;
    logic [31:0] araddr,rdata;
    logic [7:0] arlen;
    logic [2:0] arsize;
    logic [1:0] arburst,rresp;
    logic [31:0] epoch=1;
    logic block_ar=0,mem_active;
    longint unsigned read_bytes,ar_count;
    int requests=0;
    logic hint_pending,prefetch_ready;
    logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted,stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
    conv_read_cache #(.SETS(2),.WAYS(2),.LINE_BYTES(16),.CACHE_POLICY(0)) dut(
        .cfg_geometry(1'b0),.req_geometry(1'b0),.req_event_first(1'b0),
        .hint_valid(1'b0),.hint_next(32'hffffffff),.hint_pending,.cfg_windowed(1'b0),.cfg_prefetch_enable(1'b0),
        .req_window_index_valid(1'b0),.req_window_index(0),.req_window_epoch(0),
        .req_window_retire(32'hffffffff),.req_window_progress(0),.prefetch_valid(1'b0),
        .prefetch_addr(0),.prefetch_window_index_valid(1'b0),.prefetch_window_index(0),
        .prefetch_window_epoch(0),.prefetch_window_retire(32'hffffffff),.prefetch_next_fragment(1'b0),.*);
    assign stat_hits=dut.tb_observer.stat_hits;
    assign stat_misses=dut.tb_observer.stat_misses;
    assign stat_read_bytes=dut.tb_observer.stat_read_bytes;
    assign stat_prefetch_lines=dut.tb_observer.stat_prefetch_lines;
    assign stat_prefetch_used=dut.tb_observer.stat_prefetch_used;
    assign stat_prefetch_wasted=dut.tb_observer.stat_prefetch_wasted;
    assign stat_prefetch_unused=dut.tb_observer.stat_prefetch_unused;
    assign stat_prefetch_bytes=dut.tb_observer.stat_prefetch_bytes;
    assign stat_prefetch_late=dut.tb_observer.stat_prefetch_late;

    axi_counted_memory mem(.clk,.rst_n,.allocation_base(cfg_base),.allocation_bytes(cfg_bytes),.epoch,.block_ar,
        .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,
        .read_bytes,.ar_count,.active(mem_active));

    task automatic configure(input logic[31:0] new_epoch);
        @(negedge clk);epoch=new_epoch;cfg_valid=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;
        do @(posedge clk);while(!req_ready);
    endtask

    task automatic read_word(input logic[31:0] address,input int expected_bytes,input int expected_ars,
                             input string name,input bit force_stall=0);
        longint unsigned before_bytes,before_ars,held_bytes,held_ars;
        logic[31:0] held_data,word_base;
        @(negedge clk);before_bytes=read_bytes;before_ars=ar_count;
        block_ar=force_stall;rsp_ready=0;req_addr=address;req_valid=1;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;
        if(force_stall) begin
            while(!arvalid) @(negedge clk);
            repeat(7) @(negedge clk);
            if(ar_count!=before_ars) $fatal(1,"AR accepted while explicitly stalled");
            block_ar=0;
        end
        while(!rsp_valid) @(negedge clk);
        if(rsp_error) $fatal(1,"unexpected cache response error");
        word_base={address[31:2],2'b0};
        for(int b=0;b<4;b++) if(word_base+32'(b)>=cfg_base && word_base+32'(b)<cfg_base+cfg_bytes)
            if(rsp_data[b*8 +:8] != 8'(((word_base+32'(b))*32'd29)^((word_base+32'(b))>>4)^epoch))
                $fatal(1,"stale or incorrect cache data");
        held_bytes=read_bytes;held_ars=ar_count;held_data=rsp_data;
        repeat(9) begin
            @(negedge clk);
            if(!rsp_valid || rsp_data!=held_data || read_bytes!=held_bytes || ar_count!=held_ars)
                $fatal(1,"response backpressure caused new traffic or changed data");
        end
        rsp_ready=1;
        @(negedge clk);rsp_ready=0;
        if(read_bytes-before_bytes!=64'(expected_bytes) || ar_count-before_ars!=64'(expected_ars))
            $fatal(1,"unexpected traffic for %s bytes=%0d ars=%0d",name,read_bytes-before_bytes,ar_count-before_ars);
        $display("CACHE_REUSE_CASE name=%s bytes=%0d ars=%0d",name,read_bytes-before_bytes,ar_count-before_ars);
        requests=requests+1;
    endtask

    initial begin
        repeat(5) @(posedge clk);@(negedge clk);rst_n=1;
        configure(1);
        read_word(32'h1003,13,2,"cold_clipped_line",1);
        for(int i=0;i<106;i++)
            if(mem.byte_reads[i] != (i<13 ? 1 : 0)) $fatal(1,"cold line did not read each legal byte exactly once");
        $display("CACHE_COLD_LINE_BYTES unique=13 max_reads_per_byte=1 allocation_overread=0");
        read_word(32'h1003,0,0,"resident_same_word");
        read_word(32'h1004,0,0,"resident_next_word");
        read_word(32'h1008,0,0,"resident_word_2");
        read_word(32'h100c,0,0,"resident_word_3");
        read_word(32'h1024,16,1,"conflict_line_B");
        read_word(32'h1008,0,0,"A_most_recent");
        read_word(32'h1048,16,1,"C_evicts_B");
        read_word(32'h1004,0,0,"A_still_resident");
        read_word(32'h102c,16,1,"evicted_B_refill");
        read_word(32'h106c,13,2,"clipped_allocation_tail");
        configure(7);
        read_word(32'h1003,13,2,"same_address_new_task");
        for(int i=0;i<106;i++) begin
            int expected;
            logic[31:0] a;
            a=cfg_base+32'(i);expected=0;
            if(a<32'h1010 || (a>=32'h1020 && a<32'h1030)) expected=2;
            if((a>=32'h1040 && a<32'h1050) || (a>=32'h1060 && a<32'h106d)) expected=1;
            if(mem.byte_reads[i]!=32'(expected)) $fatal(1,"per-byte access mismatch addr=%h got=%0d exp=%0d",a,mem.byte_reads[i],expected);
            if(expected!=0) $display("CACHE_EXTERNAL_BYTE address=%h reads=%0d",a,mem.byte_reads[i]);
        end
        if(mem_active || rvalid || read_bytes!=87 || ar_count!=9) $fatal(1,"final byte accounting/drain");
        $display("CACHE_REUSE_PASS requests=%0d actual_read_bytes=%0d actual_ar_handshakes=%0d",requests,read_bytes,ar_count);
        $finish;
    end
    initial begin #1000000;$fatal(1,"cache reuse timeout");end
endmodule
