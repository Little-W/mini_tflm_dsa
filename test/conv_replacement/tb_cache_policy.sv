// Directed checks for future-use admission, independent of the predictor.
module tb_cache_policy;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,cfg_valid=0,cfg_ready,cfg_bypass=0,cfg_geometry=1;
    logic [31:0] cfg_base=32'h1000,cfg_bytes=256;
    logic req_valid=0,req_ready,rsp_valid,rsp_ready=0,rsp_error;
    logic req_geometry=1,req_event_first=0,hint_valid=0,hint_pending;
    logic [31:0] req_addr=0,hint_next=32'hffffffff,rsp_data;
    logic [31:0] stat_hits,stat_misses,stat_read_bytes;
    logic prefetch_ready;
    logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted,stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
    logic arvalid,arready,rvalid,rready,rlast;
    logic [31:0] araddr,rdata;
    logic [7:0] arlen;
    logic [2:0] arsize;
    logic [1:0] arburst,rresp,mem_rresp;
    logic [31:0] epoch=1;
    logic block_ar=0,mem_active,fail_reads=0;
    longint unsigned read_bytes,ar_count,job_start_bytes;
    int requests=0;
    assign rresp=fail_reads ? 2'b10 : mem_rresp;

    conv_read_cache #(.SETS(2),.WAYS(2),.LINE_BYTES(16),.CACHE_POLICY(2)) dut(.cfg_windowed(1'b0),.cfg_prefetch_enable(1'b0),
        .preview_valid(1'b0),.preview_addr(32'd0),.preview_index_valid(1'b0),.preview_index(32'd0),
        .rsp_success(),.rsp_failure(),
        .req_window_index_valid(1'b0),.req_window_index(0),.req_window_epoch(0),
        .req_window_retire(32'hffffffff),.req_window_progress(0),.prefetch_valid(1'b0),
        .prefetch_addr(0),.prefetch_next_fragment(1'b0),.prefetch_window_index_valid(1'b0),.prefetch_window_index(0),
        .prefetch_window_epoch(0),.prefetch_window_retire(32'hffffffff),
        .prefetch_ref_valid(1'b0),.prefetch_ref_addr(0),.prefetch_ref_index_valid(1'b0),
        .prefetch_ref_index(0),.prefetch_ref_epoch(0),.*);
    assign stat_hits=dut.tb_observer.stat_hits;
    assign stat_misses=dut.tb_observer.stat_misses;
    assign stat_read_bytes=dut.tb_observer.stat_read_bytes;
    assign stat_prefetch_lines=dut.tb_observer.stat_prefetch_lines;
    assign stat_prefetch_used=dut.tb_observer.stat_prefetch_used;
    assign stat_prefetch_wasted=dut.tb_observer.stat_prefetch_wasted;
    assign stat_prefetch_unused=dut.tb_observer.stat_prefetch_unused;
    assign stat_prefetch_bytes=dut.tb_observer.stat_prefetch_bytes;
    assign stat_prefetch_late=dut.tb_observer.stat_prefetch_late;

    axi_counted_memory #(.TRACK_BASE(32'h1000),.TRACK_BYTES(8192)) mem(
        .clk,.rst_n,.allocation_base(cfg_base),.allocation_bytes(cfg_bytes),.epoch,.block_ar,
        .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,
        .rresp(mem_rresp),.rlast,.read_bytes,.ar_count,.active(mem_active));

    task automatic configure(input logic [31:0] new_base,input logic [31:0] new_bytes,
                             input bit geometry,input bit bypass,input logic [31:0] new_epoch);
        @(negedge clk);
        cfg_base=new_base;cfg_bytes=new_bytes;cfg_geometry=geometry;cfg_bypass=bypass;
        epoch=new_epoch;hint_valid=0;req_event_first=0;cfg_valid=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;
        do @(posedge clk);while(!req_ready);
        job_start_bytes=read_bytes;
    endtask

    task automatic read_word(input logic [31:0] address,input logic [31:0] next_use,
                             input bit first_event,input int hint_delay,
                             input int expected_bytes,input int expected_ars,
                             input string name,input bit expected_error=0,input bit force_stall=0);
        longint unsigned before_bytes,before_ars,held_bytes,held_ars;
        logic [31:0] held_data,word_base;
        logic held_error;
        @(negedge clk);
        before_bytes=read_bytes;before_ars=ar_count;block_ar=force_stall;
        rsp_ready=0;req_addr=address;req_valid=1;req_geometry=cfg_geometry;
        req_event_first=first_event;hint_next=next_use;
        hint_valid=first_event && hint_delay==0;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;
        repeat(hint_delay) @(negedge clk);
        hint_valid=first_event;
        if(force_stall) begin
            while(!arvalid) @(negedge clk);
            repeat(7) @(negedge clk);
            if(ar_count!=before_ars) $fatal(1,"AR accepted during explicit stall");
            block_ar=0;
        end
        while(!rsp_valid) @(negedge clk);
        if(rsp_error!=expected_error) $fatal(1,"wrong response error in %s",name);
        word_base={address[31:2],2'b0};
        if(!expected_error) for(int b=0;b<4;b++)
            if(word_base+32'(b)>=cfg_base && word_base+32'(b)<cfg_base+cfg_bytes)
                if(rsp_data[b*8 +:8] != 8'(((word_base+32'(b))*32'd29)^((word_base+32'(b))>>4)^epoch))
                    $fatal(1,"data mismatch or resident corruption in %s",name);
        held_bytes=read_bytes;held_ars=ar_count;held_data=rsp_data;held_error=rsp_error;
        repeat(9) begin
            @(negedge clk);
            if(!rsp_valid || rsp_data!=held_data || rsp_error!=held_error ||
               read_bytes!=held_bytes || ar_count!=held_ars)
                $fatal(1,"response changed or duplicate read under backpressure in %s",name);
        end
        rsp_ready=1;
        @(negedge clk);rsp_ready=0;hint_valid=0;req_event_first=0;
        if(read_bytes-before_bytes!=64'(expected_bytes) || ar_count-before_ars!=64'(expected_ars))
            $fatal(1,"wrong traffic %s bytes=%0d expected=%0d ars=%0d expected=%0d",
                   name,read_bytes-before_bytes,expected_bytes,ar_count-before_ars,expected_ars);
        if(hint_pending) $fatal(1,"hint not committed after response in %s",name);
        if(64'(stat_read_bytes)!=read_bytes-job_start_bytes)
            $fatal(1,"cache stat differs from external accepted bytes in %s",name);
        $display("CACHE_POLICY_CASE name=%s bytes=%0d ars=%0d error=%0d",
                 name,read_bytes-before_bytes,ar_count-before_ars,rsp_error);
        requests++;
    endtask

    initial begin
        repeat(5) @(posedge clk);@(negedge clk);rst_n=1;
        configure(32'h1000,256,1,0,1);
        // With two sets, 1000/1030/1040/1070 all have XOR set index zero.
        read_word(32'h1000,10,1,0,16,1,"cold_A",0,1);
        read_word(32'h1030,50,1,60,16,1,"cold_B_late_hint");
        read_word(32'h1004,10,1,12,0,0,"A_hit_background_hint");
        read_word(32'h1034,50,1,0,0,0,"B_is_MRU_but_far_future");
        read_word(32'h1040,20,1,30,16,1,"C_evicts_far_B_not_LRU_A");
        read_word(32'h1008,10,1,0,0,0,"A_retained");
        read_word(32'h1030,32'hffffffff,1,0,16,1,"B_was_evicted_dead_miss_no_insert");
        read_word(32'h1044,20,1,0,0,0,"C_not_corrupted_by_B");
        read_word(32'h1070,80,1,20,16,1,"far_incoming_D_not_inserted");
        read_word(32'h1074,80,0,0,0,0,"D_stream_word_1");
        read_word(32'h1078,80,0,0,0,0,"D_stream_word_2");
        read_word(32'h107c,80,0,0,0,0,"D_stream_word_3");
        read_word(32'h1000,15,1,0,0,0,"different_resident_A_discards_stream_D");
        read_word(32'h1074,80,1,0,16,1,"D_stream_not_long_term_extra_way");
        read_word(32'h1048,32'hffffffff,1,0,0,0,"C_last_event_marks_dead");
        read_word(32'h1080,30,1,0,16,1,"new_E_replaces_dead_C");
        read_word(32'h100c,15,1,0,0,0,"A_still_retained");
        read_word(32'h1040,32'hffffffff,1,0,16,1,"dead_C_really_evicted");

        // A failed non-inserting fill must drain, never become a stream hit,
        // and leave both protected main-cache lines intact.
        fail_reads=1;
        read_word(32'h1070,90,1,0,16,1,"rejected_incoming_error_drains",1);
        fail_reads=0;
        read_word(32'h1000,15,1,0,0,0,"A_survives_failed_bypass_fill");
        read_word(32'h1084,30,1,0,0,0,"E_survives_failed_bypass_fill");
        read_word(32'h1074,90,1,0,16,1,"failed_stream_is_refetched");
        // Failed allocating fill invalidates only its victim, then refills.
        fail_reads=1;
        read_word(32'h10b0,5,1,0,16,1,"allocating_error_no_valid_commit",1);
        fail_reads=0;
        read_word(32'h10b4,5,1,0,16,1,"failed_allocated_line_is_refetched");
        read_word(32'h1004,15,1,0,0,0,"near_A_survives_allocating_error");

        configure(32'h1000,256,1,0,7);
        read_word(32'h1000,10,1,0,16,1,"new_job_invalidates_tags_and_stream");
        read_word(32'h0fff,32'hffffffff,0,0,0,0,"below_allocation_rejected",1);
        read_word(32'h1100,32'hffffffff,0,0,0,0,"past_allocation_rejected",1);
        configure(32'h1ffd,16,1,0,9);
        read_word(32'h1ffd,20,1,0,3,3,"clipped_head_before_4KiB");
        read_word(32'h2000,30,1,0,13,2,"clipped_tail_after_4KiB");
        read_word(32'h200c,30,0,0,0,0,"resident_partial_tail_word");

        // Geometry-disabled tasks keep the exact original low-bit/LRU mode.
        configure(32'h1000,256,0,0,11);
        read_word(32'h1000,10,0,0,16,1,"fallback_A");
        read_word(32'h1020,50,0,0,16,1,"fallback_B_same_low_bit_set");
        read_word(32'h1004,10,0,0,0,0,"fallback_A_MRU");
        read_word(32'h1040,20,0,0,16,1,"fallback_LRU_evicts_B");
        read_word(32'h1008,10,0,0,0,0,"fallback_A_retained");
        read_word(32'h1024,50,0,0,16,1,"fallback_B_refill");
        configure(32'h1000,256,1,1,13);
        read_word(32'h1000,10,0,0,4,1,"explicit_word_bypass");
        read_word(32'h1004,10,0,0,4,1,"word_bypass_no_fake_full_line");
        if(mem_active || rvalid || hint_pending) $fatal(1,"final transaction not drained");
        $display("CACHE_POLICY_PASS requests=%0d actual_read_bytes=%0d actual_ar_handshakes=%0d",
                 requests,read_bytes,ar_count);
        $finish;
    end
    initial begin #2000000;$fatal(1,"cache replacement test timeout");end
endmodule
