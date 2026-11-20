module tb_cache_pipeline #(
    parameter int DEMAND_DEPTH=4,
    parameter int BUS_WIDTH=32,
    parameter int READ_WIDTH=32,
    parameter int CACHE_SETS=8,
    parameter int CACHE_WAYS=2,
    parameter int LINE_BYTES=16,
    parameter int HIT_LATENCY=(DEMAND_DEPTH>1 ? 2 : 1)
);
    localparam int READ_BYTES=READ_WIDTH/8;
    localparam int READ_SHIFT=$clog2(READ_BYTES);
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,cfg_valid=0,cfg_ready,cfg_bypass=0;
    logic cfg_windowed=1,cfg_prefetch_enable=0;
    logic [31:0] cfg_base=32'h1003,cfg_bytes=2042;
    logic req_valid=0,req_ready,rsp_valid,rsp_ready=0,rsp_error;
    logic [31:0] req_addr=0,stat_hits,stat_misses,stat_read_bytes;
    logic [READ_WIDTH-1:0] rsp_data;
    logic req_geometry=0,req_event_first=0,hint_valid=0,hint_pending;
    logic [31:0] hint_next=32'hffffffff;
    logic req_window_index_valid=0;
    logic [31:0] req_window_index=3,req_window_epoch=0;
    logic [31:0] req_window_retire=32'hffffffff,req_window_progress=0;
    logic prefetch_valid=0,prefetch_ready;
    logic [31:0] prefetch_addr=0;
    logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted;
    logic [31:0] stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
    logic arvalid,arready,rvalid,rready,rlast;
    logic [31:0] araddr;
    logic [BUS_WIDTH-1:0] rdata;
    logic [7:0] arlen;
    logic [2:0] arsize;
    logic [1:0] arburst,rresp,mem_rresp;
    logic [31:0] epoch=1;
    logic block_ar=0,mem_active,fail_reads=0,req_expect_error=0;
    longint unsigned read_bytes,ar_count;
    int cycle=0,accepted=0,completed=0,cancelled=0,pending=0,peak=0,tests=0;
    int accepted_cycle[4096],completed_cycle[4096];
    logic [31:0] expected_address[4096];
    logic [READ_WIDTH-1:0] expected_data[4096];
    logic [READ_BYTES-1:0] expected_mask[4096];
    logic expected_error[4096];
    bit stalled_response=0;
    logic [READ_WIDTH:0] stalled_value=0;
    int warm_accept_interval=0,warm_return_interval=0;

    conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
        .CACHE_POLICY(3),.DEMAND_DEPTH(DEMAND_DEPTH),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH)) dut(
        .cfg_geometry(1'b0),.prefetch_next_fragment(1'b0),
        .prefetch_window_index_valid(1'b0),.prefetch_window_index(0),
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

    assign rresp=fail_reads ? 2'b10 : mem_rresp;
    axi_counted_memory #(.BUS_WIDTH(BUS_WIDTH),.TRACK_BASE(32'h1000),.TRACK_BYTES(4096)) mem(
        .clk,.rst_n,.allocation_base(cfg_base),.allocation_bytes(cfg_bytes),.epoch,.block_ar,
        .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,
        .rresp(mem_rresp),.rlast,.read_bytes,.ar_count,.active(mem_active));

    always @(posedge clk) begin
        cycle=cycle+1;
        if(!rst_n) begin
            cancelled=cancelled+pending;pending=0;completed=accepted;stalled_response=0;
        end else begin
            if(stalled_response && (!rsp_valid || {rsp_error,rsp_data}!=stalled_value))
                $fatal(1,"response changed under backpressure");
            stalled_response=rsp_valid && !rsp_ready;
            stalled_value={rsp_error,rsp_data};
            if(req_valid && req_ready) begin
                logic [31:0] a;
                a={req_addr[31:READ_SHIFT],{READ_SHIFT{1'b0}}};
                if(accepted>=4096) $fatal(1,"scoreboard capacity");
                expected_address[accepted]=req_addr;
                expected_error[accepted]=req_expect_error || req_addr<cfg_base || req_addr>=cfg_base+cfg_bytes;
                expected_data[accepted]=0;expected_mask[accepted]=0;
                for(int b=0;b<READ_BYTES;b++) if(a+32'(b)>=cfg_base && a+32'(b)<cfg_base+cfg_bytes) begin
                    expected_mask[accepted][b]=1;
                    expected_data[accepted][b*8 +:8]=8'(((a+32'(b))*32'd29)^((a+32'(b))>>4)^epoch);
                end
                accepted_cycle[accepted]=cycle;accepted=accepted+1;pending=pending+1;
            end
            if(rsp_valid && rsp_ready) begin
                if(pending==0 || completed>=accepted) $fatal(1,"response without request");
                if(rsp_error!=expected_error[completed])
                    $fatal(1,"response error mismatch request=%0d address=%h got=%0d expected=%0d",
                           completed,expected_address[completed],rsp_error,expected_error[completed]);
                if(!rsp_error) for(int b=0;b<READ_BYTES;b++) if(expected_mask[completed][b])
                    if(rsp_data[b*8 +:8]!=expected_data[completed][b*8 +:8])
                        $fatal(1,"response data/order mismatch request=%0d address=%h got=%h expected=%h",
                               completed,expected_address[completed],rsp_data,expected_data[completed]);
                completed_cycle[completed]=cycle;completed=completed+1;pending=pending-1;
            end
            if(pending>peak) peak=pending;
            if(pending>DEMAND_DEPTH) $fatal(1,"accepted requests exceed capacity");
            if(cfg_valid && cfg_ready && (pending!=0 || mem_active || rvalid))
                $fatal(1,"configuration accepted before draining");
        end
    end

    always @(negedge clk) if(rst_n) begin
        if(32'(dut.g_window.u_window.outstanding_count)!=pending)
            $fatal(1,"cache credit count differs from accepted requests");
        if(32'(dut.g_window.u_window.outstanding_count)!=
           32'(dut.g_window.u_window.request_count)+32'(dut.g_window.u_window.response_count)+
           32'(dut.g_window.u_window.fg_state!=0))
            $fatal(1,"request and response queue ownership");
    end

    task automatic reset_cache;
        @(negedge clk);rst_n=0;req_valid=0;prefetch_valid=0;cfg_valid=0;rsp_ready=0;
        block_ar=0;fail_reads=0;req_expect_error=0;
        repeat(3) @(negedge clk);
        rst_n=1;
    endtask

    task automatic configure(input int new_epoch,input bit windowed=1,
                             input bit prefetch=0,input bit bypass=0);
        @(negedge clk);
        if(pending!=0 || mem_active || rvalid) $fatal(1,"configure called with pending work");
        epoch=32'(new_epoch);cfg_windowed=windowed;cfg_prefetch_enable=prefetch;cfg_bypass=bypass;
        req_window_index_valid=0;req_geometry=0;req_event_first=0;hint_valid=0;
        req_expect_error=0;cfg_valid=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;
        while(!req_ready) @(negedge clk);
    endtask

    function automatic logic [31:0] stream_address(input int index,input int mode);
        case(mode)
            0:return 32'h1004;
            1:return 32'h1100+32'(4*(index%16));
            2:return 32'h1014+32'(LINE_BYTES*((index*5)%13));
            3:case(index%4)
                0:return 32'h1002;
                1:return 32'h1004;
                2:return 32'h2000;
                default:return 32'h1014;
              endcase
            4:return 32'h1204;
            5:return 32'h1304;
            6:return 32'h1404+32'(LINE_BYTES*index);
            default:return index%2!=0 ? 32'h17fc : 32'h1003;
        endcase
    endfunction

    task automatic stream(input int count,input int mode,input bit random_backpressure=0,
                          input bit expect_error=0);
        int sent;
        logic [31:0] random_state;
        sent=0;random_state=32'h84a3db21;
        @(negedge clk);req_valid=1;req_addr=stream_address(0,mode);req_expect_error=expect_error;
        while(sent<count) begin
            @(posedge clk);
            if(req_ready) sent=sent+1;
            @(negedge clk);
            if(sent<count) req_addr=stream_address(sent,mode);
            else req_valid=0;
            if(random_backpressure) begin
                random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
                rsp_ready=random_state[0] || random_state[3];
            end
        end
        req_expect_error=0;
    endtask

    task automatic drain;
        @(negedge clk);rsp_ready=1;
        while(pending!=0 || rsp_valid || !cfg_ready) @(negedge clk);
        if(mem_active || rvalid) $fatal(1,"memory response remains after drain");
    endtask

    task automatic offer_prefetch(input logic [31:0] address);
        @(negedge clk);prefetch_addr=address;prefetch_valid=1;
        do @(posedge clk);while(!prefetch_ready);
        @(negedge clk);prefetch_valid=0;
    endtask

    task automatic report(input string name);
        tests=tests+1;
        $display("CACHE_PIPELINE_CASE name=%s accepted=%0d completed=%0d cancelled=%0d peak=%0d hits=%0d misses=%0d lookup_hits=%0d lookup_misses=%0d read_bytes=%0d ar_count=%0d",
                 name,accepted,completed-cancelled,cancelled,peak,stat_hits,stat_misses,
                 dut.g_window.u_window.tb_observer.stat_lookup_hits,dut.g_window.u_window.tb_observer.stat_lookup_misses,
                 read_bytes,ar_count);
    endtask

    initial begin
        longint unsigned old_bytes;
        int first;
        reset_cache();configure(1);
        @(negedge clk);block_ar=1;rsp_ready=0;
        repeat(3) @(negedge clk);
        stream(DEMAND_DEPTH,0);
        repeat(7) begin
            @(negedge clk);
            if(req_ready || cfg_ready || pending!=DEMAND_DEPTH) $fatal(1,"cold request credit handling");
        end
        if(stat_hits!=0 || stat_misses!=DEMAND_DEPTH) $fatal(1,"cold acceptance statistics");
        if(dut.g_window.u_window.tb_observer.stat_peak_outstanding!=DEMAND_DEPTH) $fatal(1,"peak outstanding counter");
        block_ar=0;drain();
        if(dut.g_window.u_window.tb_observer.stat_lookup_misses!=1 ||
           dut.g_window.u_window.tb_observer.stat_lookup_hits!=DEMAND_DEPTH-1)
            $fatal(1,"queued cold requests must retain their acceptance miss classification");
        report("cold_queue");

        stream(16,1);drain();
        old_bytes=read_bytes;first=accepted;
        stream(64,1);drain();
        for(int i=first;i<first+64;i++) begin
            if(completed_cycle[i]-accepted_cycle[i]!=HIT_LATENCY) $fatal(1,"warm response latency");
            if(i>first) begin
                if(accepted_cycle[i]-accepted_cycle[i-1]!=1 ||
                   completed_cycle[i]-completed_cycle[i-1]!=1) $fatal(1,"warm pipeline throughput");
            end
        end
        warm_accept_interval=1;warm_return_interval=1;
        if(read_bytes!=old_bytes) $fatal(1,"resident stream generated AXI reads");
        report("continuous_hits");

        @(negedge clk);rsp_ready=0;
        stream(DEMAND_DEPTH,1);
        repeat(12) begin
            @(negedge clk);
            if(req_ready || cfg_ready || !rsp_valid || pending!=DEMAND_DEPTH)
                $fatal(1,"response queue backpressure");
        end
        drain();
        if(read_bytes!=old_bytes) $fatal(1,"blocked hit stream generated AXI reads");
        report("blocked_responses");

        configure(2);req_window_index_valid=1;
        stream(48,2,1);drain();
        report("conflicting_lines");

        configure(3);stream(12,3,1);drain();
        report("ordered_range_errors");

        configure(4);old_bytes=read_bytes;
        @(negedge clk);fail_reads=1;block_ar=1;rsp_ready=0;
        repeat(3) @(negedge clk);
        stream(DEMAND_DEPTH,4,0,1);block_ar=0;drain();
        if(read_bytes-old_bytes!=64'(DEMAND_DEPTH*LINE_BYTES) || stat_hits!=0 ||
           dut.g_window.u_window.tb_observer.stat_lookup_misses!=DEMAND_DEPTH)
            $fatal(1,"failed fills were admitted to cache");
        @(negedge clk);fail_reads=0;
        stream(1,4);drain();old_bytes=read_bytes;
        stream(4,4);drain();
        if(read_bytes!=old_bytes) $fatal(1,"fill recovery did not cache data");
        report("fill_error_and_recovery");

        configure(5,1,1);
        @(negedge clk);block_ar=1;rsp_ready=0;
        repeat(3) @(negedge clk);
        offer_prefetch(32'h1300);
        while(!arvalid) @(negedge clk);
        stream(DEMAND_DEPTH,5);
        if(stat_hits!=0 || stat_misses!=DEMAND_DEPTH || stat_prefetch_late!=DEMAND_DEPTH)
            $fatal(1,"prefetch acceptance statistics");
        block_ar=0;drain();
        if(stat_prefetch_lines!=1 || stat_prefetch_used!=1) $fatal(1,"prefetch demand reuse");
        report("pending_prefetch_acceptance");

        configure(6,1,1);
        @(negedge clk);block_ar=1;fail_reads=1;rsp_ready=0;
        repeat(3) @(negedge clk);
        offer_prefetch(32'h1300);
        while(!arvalid) @(negedge clk);
        stream(DEMAND_DEPTH,5,0,1);block_ar=0;drain();
        if(stat_prefetch_lines!=0 || stat_hits!=0) $fatal(1,"failed prefetch admitted data");
        @(negedge clk);fail_reads=0;
        stream(1,5);drain();
        report("prefetch_error_recovery");

        configure(6,1,1);
        @(negedge clk);block_ar=1;rsp_ready=0;
        repeat(3) @(negedge clk);
        stream(DEMAND_DEPTH,6);offer_prefetch(32'h1510);
        @(negedge clk);cfg_valid=1;
        repeat(8) begin
            @(negedge clk);
            if(cfg_ready || req_ready) $fatal(1,"configuration did not wait for outstanding work");
        end
        block_ar=0;rsp_ready=1;
        do @(posedge clk);while(!cfg_ready);
        @(negedge clk);cfg_valid=0;epoch=7;
        while(!req_ready) @(negedge clk);
        stream(4,6);drain();
        report("configuration_drain");

        configure(8);
        @(negedge clk);rsp_ready=0;
        stream(DEMAND_DEPTH,6);
        while(!rsp_valid) @(negedge clk);
        reset_cache();configure(9);
        stream(8,6,1);drain();
        if(cancelled!=DEMAND_DEPTH) $fatal(1,"reset did not cancel outstanding requests");
        report("reset_pending_work");

        configure(10,1,0,1);stream(12,7,1);drain();
        if(stat_hits!=0 || dut.g_window.u_window.tb_observer.stat_lookup_hits!=0)
            $fatal(1,"bypass request counted as resident");
        report("bypass_clipped_words");

        configure(11,0);
        @(negedge clk);block_ar=1;rsp_ready=0;req_geometry=1;req_event_first=1;
        repeat(3) @(negedge clk);
        stream(1,0);
        repeat(6) begin
            @(negedge clk);
            if(req_ready || pending!=1 || !hint_pending) $fatal(1,"geometry request serialization");
        end
        hint_valid=1;hint_next=12;
        @(negedge clk);hint_valid=0;
        if(hint_pending) $fatal(1,"geometry hint completion");
        block_ar=0;drain();report("geometry_hint_order");

        if(pending!=0 || accepted!=completed || peak!=DEMAND_DEPTH)
            $fatal(1,"final request accounting");
        $display("CACHE_PIPELINE_PASS tests=%0d accepted=%0d completed=%0d cancelled=%0d peak_outstanding=%0d warm_accept_interval=%0d warm_return_interval=%0d demand_depth=%0d ways=%0d",
                 tests,accepted,completed-cancelled,cancelled,peak,warm_accept_interval,warm_return_interval,
                 DEMAND_DEPTH,CACHE_WAYS);
        $finish;
    end
    initial begin #20000000;$fatal(1,"cache pipeline timeout");end
endmodule
