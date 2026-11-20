`timescale 1ns/1ps
module registered_error_tb #(parameter int BUS_WIDTH=32);
    logic clk=0, rst_n=0, abort=0;
    always #5 clk=~clk;
    logic [4:0] request=0, start=0;
    wire [4:0] granted, busy, done;
    logic serve_reads=0, arready=1;
    logic [1:0] rresp=0, bresp=0;
    logic oa_request=0, oa_start=0, serve_writes=1, serve_b=0;
    logic [31:0] write_rows=1;
    wire oa_granted, awvalid, wvalid, wlast, bready, bus_error;
    wire [31:0] awaddr;
    wire [7:0] awlen;
    wire [BUS_WIDTH/8-1:0] wstrb;
    int write_bursts[$];
    int b_pending=0, aw_count=0, w_count=0, b_count=0;
    int read_error_beats=0, write_error_beats=0, consecutive_error_cycles=0;
    int normal_completion_with_error=0, error_descriptor_cancellations=0;
    int recovery_cases=0, error_cases=0;
    logic previous_error=0;
    wire bvalid=serve_b && b_pending!=0;
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

    axi_block_dma_arbiter #(.DATA_WIDTH(16),.KERNEL_WIDTH(16),.SIZE(4),
        .DMA_SIZE(4),.BUS_WIDTH(BUS_WIDTH),.CACHE_BLOCKS(4),
        .CONV_CACHE_SETS(4),.CONV_CACHE_WAYS(2),.CONV_CACHE_POLICY(3),
        .p_register_bus_error(1'b1)) dut (
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
        .oa_req(oa_request),.oa_start(oa_start),.oa_granted(oa_granted),
        .oa_base_addr(32'h6000),.oa_row_stride(32'd16),
        .oa_rows_to_read(write_rows),.oa_burst_len_m1(8'd3),
        .oa_src_wdata({(BUS_WIDTH/8){8'h96}}),.oa_src_wmask('1),.oa_src_wvalid(1'b1),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),
        .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata({(BUS_WIDTH/8){8'h5a}}),.m_axi_rresp(rresp),.m_axi_rlast(1'b1),
        .m_axi_awready(1'b1),.m_axi_awvalid(awvalid),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),
        .m_axi_wready(serve_writes),.m_axi_wvalid(wvalid),.m_axi_wlast(wlast),.m_axi_wstrb(wstrb),
        .m_axi_bvalid(bvalid),.m_axi_bready(bready),.m_axi_bresp(bresp),.idle,.bus_error
    );

    task automatic check(input bit condition,input string message);
        if(!condition)$fatal(1,"%s",message);
        checks++;
    endtask
    always @(posedge clk) begin
        cycle++;
        if(!rst_n)begin
            last_command_cycle=-1;
            write_bursts.delete(); b_pending=0;aw_count=0;w_count=0;b_count=0;previous_error=0;
            pending<=0;ar_count<=0;r_count<=0;
            completions<='{default:0};
        end else begin
            if(bvalid && bready) begin
                check(b_pending>0,"Write response has an outstanding address");
                b_pending--; b_count++;
                if(bresp[1])write_error_beats++;
            end
            if(awvalid) begin
                check((int'(awaddr[11:0])+(int'(awlen)+1)*(BUS_WIDTH/8))<=4096,
                      "Write burst remains inside a 4 KiB page");
                write_bursts.push_back(int'(awlen)+1); aw_count++;
            end
            if(wvalid && serve_writes) begin
                check(write_bursts.size()!=0,"Write data follows an accepted address");
                check(wlast==(write_bursts[0]==1),"Write data retains the final-beat marker");
                write_bursts[0]--; w_count++;
                if(write_bursts[0]==0) begin
                    void'(write_bursts.pop_front()); b_pending++;
                end
            end
            if(rvalid && rready && rresp[1])read_error_beats++;
            if(bus_error && previous_error)consecutive_error_cycles++;
            previous_error=bus_error;
            if(dut.bus_error_event && dut.rd_dma_done && !dut.dma_rd_error)
                normal_completion_with_error++;
            if(dut.bus_error_event && dut.rd_dma_start_q)error_descriptor_cancellations++;
            case({arvalid&&arready,rvalid&&rready})
                2'b10:pending<=pending+1;
                2'b01:pending<=pending-1;
                default:;
            endcase
            if(arvalid&&arready)begin
                check(arlen==0 && arsize==3'($clog2(BUS_WIDTH/8)),"One native AXI beat per descriptor");
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
        rresp=0;bresp=0;oa_request=0;oa_start=0;serve_writes=1;serve_b=0;write_rows=1;
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
                check(write_bursts.size()==0 && b_pending==0,"Accepted writes drain completely");
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
    task automatic launch_write(input int rows);
        write_rows=32'(rows);oa_request=1;oa_start=1;
        do @(posedge clk);while(!oa_granted);
        @(negedge clk);oa_request=0;oa_start=0;
    endtask
    task automatic clean_report;
        repeat(3)@(negedge clk);
        check(!bus_error,"Error report clears after completed responses");
    endtask
    task automatic recover_error(input int client,input int previous_ar,input int previous_done);
        rresp=0;bresp=0;abort=0;serve_b=1;serve_reads=1;
        clean_report();
        launch(client);drained();clean_report();
        check(ar_count==previous_ar+1 && completions[client]==previous_done+1,
              "A normal descriptor follows an error without reset");
        recovery_cases++;
    endtask
    initial begin
        // 描述符交付 DMA 前逐项检查五个请求方的取消行为。
        for(int client=0;client<5;client++)begin
            reset_case();launch(client);abort=1;
            drained();
            check(ar_count==0 && completions[client]==0,"Cancelled descriptor issues no read or completion");
            recovery(client,0,0);
        end
        // 新描述符可以等待前一个已接收且尚未完成握手的地址。
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
        // 取消新描述符与旧描述符完成可以共用时钟边沿。
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
        // 两个已接收的权重描述符分别保留返回结果。
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
        // 各读请求方的最后一个响应出错后，命令仍完成并允许后续任务。
        for(int client=0;client<5;client++)begin
            reset_case();launch(client);
            wait(pending==1);@(negedge clk);
            rresp=2'b10;serve_reads=1;
            @(negedge clk);
            check(bus_error,"Physical read error is reported on the following cycle");
            drained();
            check(completions[client]==1,"Failed read context completes exactly once");
            recover_error(client,1,1);error_cases++;
        end
        // 已交付的两个权重描述符在连续错误响应下分别释放。
        reset_case();launch(1);@(negedge clk);launch(1);
        repeat(2)@(negedge clk);
        rresp=2'b10;serve_reads=1;drained();
        check(ar_count==2 && completions[1]==2,"Consecutive error responses preserve both contexts");
        recover_error(1,2,2);error_cases++;
        // 旧命令的正常完成与写错误响应可以同时发生。
        reset_case();launch(1);launch_write(1);
        wait(pending==1 && b_pending==1);@(negedge clk);
        serve_reads=1;
        @(negedge clk);
        check(dut.rd_dma_done && !dut.dma_rd_error,"Read completes normally before write error");
        bresp=2'b10;serve_b=1;
        drained();
        check(completions[1]==1 && b_count==1,"Read completion and failed write both drain");
        recover_error(1,1,1);error_cases++;
        // 上游中止与读错误在同周期到达时保留已接收命令。
        reset_case();launch(0);wait(pending==1);@(negedge clk);
        rresp=2'b11;serve_reads=1;abort=1;drained();
        check(completions[0]==1,"External abort and read error retain the accepted response");
        recover_error(0,1,1);error_cases++;
        // 写回可以积累多个待返回响应，连续错误使后续地址停止发出。
        reset_case();launch_write(8);
        wait(b_pending>=2);@(negedge clk);
        bresp=2'b10;serve_b=1;drained();
        check(aw_count==b_count && b_count>=2,"All accepted write responses drain after errors");
        recover_error(2,0,0);error_cases++;
        // 错误握手周期取消尚未交付的描述符，不增加总线事务。
        reset_case();launch(1);wait(pending==1);@(negedge clk);
        request=5'b00100;start=5'b00100;
        do @(negedge clk);while(!granted[2]);
        @(negedge clk);request=0;start=0;rresp=2'b10;serve_reads=1;
        check(dut.rd_dma_start_q,"New descriptor is waiting before the error response");
        drained();
        check(ar_count==1 && completions[1]==1 && completions[2]==0,
              "Error cancels a pending descriptor while completing the earlier response");
        recover_error(2,1,0);error_cases++;
        check(read_error_beats>=9 && write_error_beats>=3 && consecutive_error_cycles>0,
              "Read, write and consecutive error responses are exercised");
        check(normal_completion_with_error>0 && error_descriptor_cancellations>0,
              "Simultaneous completion and descriptor cancellation are exercised");
        $display("{\"passed\":true,\"bus_width\":%0d,\"ordinary_cases\":%0d,\"error_cases\":%0d,\"recovery_cases\":%0d,\"checks\":%0d,\"read_error_beats\":%0d,\"write_error_beats\":%0d,\"consecutive_error_cycles\":%0d,\"normal_completion_with_error\":%0d,\"error_descriptor_cancellations\":%0d}",
            BUS_WIDTH,cases,error_cases,recovery_cases,checks,read_error_beats,write_error_beats,
            consecutive_error_cycles,normal_completion_with_error,error_descriptor_cancellations);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1,"DMA timeout ordinary=%0d error=%0d pending_r=%0d pending_b=%0d accepted_aw=%0d accepted_w=%0d rd_active=%0d wr_active=%0d",
               cases,error_cases,pending,b_pending,aw_count,w_count,dut.rd_active,dut.wr_active);
    end
endmodule
