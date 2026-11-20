`timescale 1ns/1ps
module arbiter_read_tb #(parameter int BUS_WIDTH=32);
    logic clk=0, rst_n=0, abort=0;
    always #5 clk=~clk;
    logic [4:0] request=0, start=0;
    wire [4:0] granted, busy, done;
    logic serve_reads=0, arready=1;
    wire arvalid, rready, idle;
    wire [31:0] araddr;
    wire [7:0] arlen;
    wire [2:0] arsize;
    int pending=0, ar_count=0, r_count=0;
    int completions[5]='{default:0};
    int cases=0, checks=0, cancellations=0, simultaneous_release=0;
    int accepted_overlap=0;
    int cycle=0, last_command_cycle=-1, minimum_command_interval=100000;
    int grant_withdrawals=0, full_context_checks=0;
    wire rvalid=serve_reads && pending!=0;

    axi_block_dma_arbiter #(.DATA_WIDTH(8),.KERNEL_WIDTH(8),.SIZE(4),
        .DMA_SIZE(4),.BUS_WIDTH(BUS_WIDTH),.CACHE_BLOCKS(4)) dut (
        .clk,.rst_n,.abort,
        .ia_req(request[0]),.ia_start(start[0]),.ia_granted(granted[0]),.ia_busy(busy[0]),.ia_done(done[0]),
        .ia_linear_read_mode(1'b0),.ia_base_addr(32'h1000),.ia_row_stride(32'd16),
        .ia_rows_to_read(32'd1),.ia_burst_len_m1(8'd0),.ia_slot_id(2'd0),.ia_use_16bits(1'b0),.ia_lhs_zp(32'd0),
        .kernel_req(request[1]),.kernel_start(start[1]),.kernel_granted(granted[1]),.kernel_busy(busy[1]),.kernel_done(done[1]),
        .kernel_linear_read_mode(1'b0),.kernel_base_addr(32'h2000),.kernel_row_stride(32'd16),
        .kernel_rows_to_read(32'd1),.kernel_burst_len_m1(8'd0),.kernel_slot_id(1'b0),.kernel_use_16bits(1'b0),.kernel_lhs_zp(32'd0),
        .bias_req(request[2]),.bias_start(start[2]),.bias_granted(granted[2]),.bias_busy(busy[2]),.bias_done(done[2]),
        .bias_linear_read_mode(1'b0),.bias_base_addr(32'h3000),.bias_row_stride(32'd16),
        .bias_rows_to_read(32'd1),.bias_burst_len_m1(8'd0),.bias_slot_id(1'b0),.bias_use_16bits(1'b0),.bias_lhs_zp(32'd0),
        .quant_req(request[3]),.quant_start(start[3]),.quant_granted(granted[3]),.quant_busy(busy[3]),.quant_done(done[3]),
        .quant_linear_read_mode(1'b0),.quant_base_addr(32'h4000),.quant_row_stride(32'd16),
        .quant_rows_to_read(32'd1),.quant_burst_len_m1(8'd0),.quant_slot_id(1'b0),.quant_use_16bits(1'b0),.quant_lhs_zp(32'd0),
        .dw_req(request[4]),.dw_start(start[4]),.dw_granted(granted[4]),.dw_busy(busy[4]),.dw_done(done[4]),
        .dw_base_addr(32'h5000),.dw_row_stride(32'd16),.dw_rows_to_read(32'd1),.dw_valid_cols(32'd4),
        .oa_req(1'b0),.oa_start(1'b0),.oa_base_addr(32'd0),.oa_row_stride(32'd0),
        .oa_rows_to_read(32'd0),.oa_burst_len_m1(8'd0),.oa_src_wdata('0),.oa_src_wmask('0),.oa_src_wvalid(1'b0),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),
        .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata({(BUS_WIDTH/8){8'h5a}}),.m_axi_rresp(2'b00),.m_axi_rlast(1'b1),
        .m_axi_awready(1'b1),.m_axi_wready(1'b1),.m_axi_bvalid(1'b0),.m_axi_bresp(2'b00),.idle
    );

    task automatic check(input bit condition,input string message);
        if(!condition)$fatal(1,"%s",message);
        checks++;
    endtask
    always @(posedge clk) begin
        cycle++;
        if(!rst_n)begin
            last_command_cycle=-1;
            pending<=0;ar_count<=0;r_count<=0;
            completions<='{default:0};
        end else begin
            case({arvalid&&arready,rvalid&&rready})
                2'b10:pending<=pending+1;
                2'b01:pending<=pending-1;
                default:;
            endcase
            if(arvalid&&arready)begin
                check(arlen==0 && arsize==$clog2(BUS_WIDTH/8),"One native AXI beat per descriptor");
                ar_count<=ar_count+1;
            end
            if(rvalid&&rready)r_count<=r_count+1;
            for(int i=0;i<5;i++)if(done[i])completions[i]<=completions[i]+1;
            if(abort && dut.rd_dma_start_q)begin
                cancellations++;
                if(dut.rd_dma_done)simultaneous_release++;
            end
            if(dut.rd_client_inflight[1]==2)accepted_overlap++;
            if(dut.rd_dma_start)begin
                if(last_command_cycle>=0 && cycle-last_command_cycle<minimum_command_interval)
                    minimum_command_interval=cycle-last_command_cycle;
                last_command_cycle=cycle;
            end
            check(int'(dut.rd_pending_count)==int'(dut.rd_client_inflight[0])+int'(dut.rd_client_inflight[1])+
                  int'(dut.rd_client_inflight[2])+int'(dut.rd_client_inflight[3])+int'(dut.rd_client_inflight[4]),
                  "Outstanding count matches all client contexts");
            check(dut.rd_pending_count<=4,"At most four outstanding response contexts");
        end
    end
    task automatic reset_case;
        @(negedge clk);rst_n=0;request=0;start=0;abort=0;serve_reads=0;arready=1;
        repeat(3)@(negedge clk);
        rst_n=1;
        @(negedge clk);
    endtask
    task automatic launch(input int client);
        request=5'(1<<client);start=5'(1<<client);
        do @(posedge clk);while(!granted[client]);
        @(negedge clk);request=0;start=0;
        check(dut.rd_dma_start_q,"Client descriptor enters the registered command stage");
    endtask
    task automatic drained;
        for(int cycle=0;cycle<100;cycle++)begin
            @(negedge clk);
            if(idle)begin
                check(busy==0 && pending==0,"Drained DMA has no client or AXI ownership");
                return;
            end
        end
        $fatal(1,"DMA did not drain");
    endtask
    task automatic recovery(input int client,input int previous_ar,input int previous_done);
        abort=0;serve_reads=1;
        @(negedge clk);
        launch(client);drained();
        check(ar_count==previous_ar+1 && completions[client]==previous_done+1,
              "A following descriptor completes without reset");
        cases++;
    endtask
    initial begin
        // Cancel each client before the registered descriptor reaches DMA.
        for(int client=0;client<5;client++)begin
            reset_case();launch(client);abort=1;
            drained();
            check(ar_count==0 && completions[client]==0,"Cancelled descriptor issues no read or completion");
            recovery(client,0,0);
        end
        // The command register may wait behind an accepted, stalled address.
        for(int client=0;client<5;client++)begin
            reset_case();arready=0;
            launch(1);@(negedge clk);
            check(arvalid && !dut.rd_dma_start_ready,"Accepted descriptor holds its AXI address");
            launch(client);abort=1;
            repeat(3)@(negedge clk);
            check(!dut.rd_dma_start_q && busy[1] && arvalid,"Abort cancels the pending descriptor and retains the accepted read");
            arready=1;serve_reads=1;drained();
            check(ar_count==1 && completions[1]==1,"Only the accepted descriptor reaches AXI");
            recovery(client,1,client==1 ? 1 : 0);
        end
        // Cancellation and an older registered completion may share an edge.
        for(int client=0;client<5;client++)begin
            reset_case();launch(1);
            wait(pending==1);@(negedge clk);
            request=5'(1<<client);start=5'(1<<client);
            do @(negedge clk);while(!granted[client]);
            serve_reads=1;
            @(posedge clk);
            @(negedge clk);request=0;start=0;abort=1;
            check(dut.rd_dma_done,"Older response completion coincides with cancellation");
            drained();
            check(ar_count==1 && completions[1]==1,"Concurrent release preserves the older completion exactly once");
            recovery(client,1,client==1 ? 1 : 0);
        end
        // Both kernel contexts already accepted by DMA retain their responses.
        reset_case();launch(1);@(negedge clk);launch(1);@(negedge clk);
        abort=1;serve_reads=1;drained();
        check(ar_count==2 && completions[1]==2,"Accepted kernel contexts drain in order");
        recovery(1,2,2);
        // 授予可以等待启动；请求撤销后不产生DMA命令。
        for(int client=0;client<5;client++)begin
            reset_case();
            request=5'(1<<client);
            do @(negedge clk);while(!granted[client]);
            repeat(3)begin
                check(granted[client] && !dut.rd_dma_start_q && busy==0,"Reserved grant holds before start");
                @(negedge clk);
            end
            request=0;
            @(negedge clk);
            check(granted==0 && idle && ar_count==0,"Withdrawn request releases its grant");
            grant_withdrawals++;
            recovery(client,0,0);
        end
        // 两个权重请求和两个独立客户端占满四个返回上下文。
        reset_case();launch(1);launch(1);launch(3);launch(0);
        request=5'b00100;start=5'b00100;
        repeat(8)begin
            @(negedge clk);
            check(dut.rd_pending_count==4 && !granted[2],"Fifth context waits for a completed response");
            full_context_checks++;
        end
        request=0;start=0;serve_reads=1;drained();
        check(ar_count==4 && completions[1]==2 && completions[3]==1 && completions[0]==1,
              "Four accepted contexts retain their client tags");
        check(minimum_command_interval==2,"Continuous command acceptance interval remains two cycles");
        check(cancellations==15 && simultaneous_release==5 && accepted_overlap>0,"Read cancellation boundary coverage");
        $display("{\"passed\":true,\"bus_width\":%0d,\"cases\":%0d,\"checks\":%0d,\"cancelled_descriptors\":%0d,\"simultaneous_releases\":%0d,\"kernel_overlap_cycles\":%0d,\"minimum_command_interval\":%0d,\"grant_withdrawals\":%0d,\"full_context_checks\":%0d}",
            BUS_WIDTH,cases,checks,cancellations,simultaneous_release,accepted_overlap,minimum_command_interval,grant_withdrawals,full_context_checks);
        $finish;
    end
    initial begin #100000;$fatal(1,"Read arbiter test timeout");end
endmodule
