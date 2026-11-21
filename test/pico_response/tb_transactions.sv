`timescale 1ns/1ps

module tb_transactions #(
    parameter int ADDR_WIDTH = 32,
    parameter int DATA_WIDTH = 32,
    parameter bit REGISTER_RESPONSE = 1'b1
);
    localparam int BYTEW = DATA_WIDTH/8;
    localparam int MEMORY_BYTES = 4096;
    localparam int ADDRESS_PAYLOAD = ADDR_WIDTH+22;
    localparam int WRITE_PAYLOAD = DATA_WIDTH+BYTEW+1;
    localparam logic [ADDR_WIDTH-1:0] MEMORY_BASE = ADDR_WIDTH'(64'h1281230000);

    logic clk=0, rst_n=0;
    logic mem_valid=0, mem_instr=0;
    logic [ADDR_WIDTH-1:0] mem_addr='0;
    logic [DATA_WIDTH-1:0] mem_wdata='0;
    logic [BYTEW-1:0] mem_wstrb='0;
    wire mem_ready;
    wire [DATA_WIDTH-1:0] mem_rdata;
    wire arvalid, awvalid, wvalid, rready, bready;
    logic arready=0, awready=0, wready=0, rvalid=0, bvalid=0;
    wire [ADDR_WIDTH-1:0] araddr, awaddr;
    wire [3:0] arcache, awcache;
    wire [2:0] arprot, awprot, arsize, awsize;
    wire [1:0] arlock, awlock, arburst, awburst;
    wire [7:0] arlen, awlen;
    wire [DATA_WIDTH-1:0] wdata;
    wire [BYTEW-1:0] wstrb;
    wire wlast;
    logic [DATA_WIDTH-1:0] rdata='0;

    pico_native_to_axi #(
        .ADDR_WIDTH(ADDR_WIDTH), .DATA_WIDTH(DATA_WIDTH), .ENABLE_ICACHE(1'b0),
        .ICACHE_LINES(4), .ICACHE_LINE_WORDS(4), .REGISTER_RESPONSE(REGISTER_RESPONSE)
    ) u_dut (
        .clk(clk), .rst_n(rst_n), .mem_valid(mem_valid), .mem_instr(mem_instr),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_ready(mem_ready), .mem_rdata(mem_rdata),
        .m_axi_arvalid(arvalid), .m_axi_arready(arready), .m_axi_araddr(araddr),
        .m_axi_arcache(arcache), .m_axi_arprot(arprot), .m_axi_arlock(arlock),
        .m_axi_arburst(arburst), .m_axi_arlen(arlen), .m_axi_arsize(arsize),
        .m_axi_awvalid(awvalid), .m_axi_awready(awready), .m_axi_awaddr(awaddr),
        .m_axi_awcache(awcache), .m_axi_awprot(awprot), .m_axi_awlock(awlock),
        .m_axi_awburst(awburst), .m_axi_awlen(awlen), .m_axi_awsize(awsize),
        .m_axi_rvalid(rvalid), .m_axi_rready(rready), .m_axi_rdata(rdata),
        .m_axi_rresp(2'b00), .m_axi_rlast(1'b1),
        .m_axi_wvalid(wvalid), .m_axi_wready(wready), .m_axi_wdata(wdata),
        .m_axi_wstrb(wstrb), .m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid), .m_axi_bready(bready), .m_axi_bresp(2'b00)
    );

    // 总线存储器依据实际 AXI 负载写入，参考存储器依据原生请求写入。
    logic [7:0] axi_memory [0:MEMORY_BYTES-1];
    logic [7:0] expected_memory [0:MEMORY_BYTES-1];
    logic read_pending=0, aw_seen=0, w_seen=0, write_pending=0;
    logic [DATA_WIDTH-1:0] read_data_saved='0, write_data_saved='0;
    logic [BYTEW-1:0] write_mask_saved='0;
    logic [ADDR_WIDTH-1:0] write_address_saved='0;
    int read_delay=0, write_delay=0;
    logic request_active=0, request_done=0, request_ar=0, request_aw=0, request_w=0;
    logic [ADDR_WIDTH-1:0] request_address='0;
    logic [DATA_WIDTH-1:0] request_data='0;
    logic [BYTEW-1:0] request_mask='0;
    logic request_instruction=0;
    int request_age=0, channel_order=0;
    // 1 阻塞 AR，2 阻塞 W，3 阻塞 AW，4 延迟 R，5 立即接受地址。
    int forced_mode=0;
    logic response_previous=0;
    logic ar_stalled=0, aw_stalled=0, w_stalled=0;
    logic [ADDRESS_PAYLOAD-1:0] ar_payload_q='0, aw_payload_q='0;
    logic [WRITE_PAYLOAD-1:0] w_payload_q='0;
    logic [31:0] random_state=32'h419ac732;
    int cycles=0, started=0, completed=0, reads=0, writes=0, aborted=0, resets=0;
    int axi_reads=0, axi_writes=0, aw_first=0, w_first=0, simultaneous=0;
    int ar_stall_checks=0, aw_stall_checks=0, w_stall_checks=0, checked_bytes=0;

    function automatic int memory_index(input logic [ADDR_WIDTH-1:0] address);
        logic [ADDR_WIDTH-1:0] offset;
        begin
            offset=address-MEMORY_BASE;
            if(offset>=ADDR_WIDTH'(MEMORY_BYTES) || (offset%BYTEW)!=0)
                $fatal(1,"Memory address outside the test range: %h",address);
            return int'(offset);
        end
    endfunction

    task automatic next_random;
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
    endtask

    task automatic cycle;
        logic af, awf, wf, rf, bf, native_done, response_now;
        logic [ADDRESS_PAYLOAD-1:0] ar_payload, aw_payload;
        logic [WRITE_PAYLOAD-1:0] w_payload;
        int index;
        begin
            next_random();
            arready=rst_n && !read_pending && (random_state[1:0]!=0);
            awready=rst_n && !aw_seen && !write_pending && (random_state[4:2]!=0);
            wready=rst_n && !w_seen && !write_pending && (random_state[7:5]!=0);
            if(channel_order==1)begin awready=rst_n && !aw_seen && request_age>=4; wready=rst_n && !w_seen; end
            if(channel_order==2)begin awready=rst_n && !aw_seen; wready=rst_n && !w_seen && request_age>=5; end
            if(forced_mode==1)arready=0;
            if(forced_mode==2)begin awready=rst_n && !aw_seen;wready=0;end
            if(forced_mode==3)begin awready=0;wready=rst_n && !w_seen;end
            if(forced_mode==4 || forced_mode==5)arready=rst_n && !read_pending;
            rvalid=rst_n && read_pending && read_delay==0 && forced_mode!=4;
            bvalid=rst_n && write_pending && write_delay==0;
            rdata=read_data_saved;
            #2;
            af=arvalid && arready; awf=awvalid && awready; wf=wvalid && wready;
            rf=rvalid && rready; bf=bvalid && bready;
            native_done=mem_valid && mem_ready;
            response_now=rf || bf;
            ar_payload={araddr,arcache,arprot,arlock,arburst,arlen,arsize};
            aw_payload={awaddr,awcache,awprot,awlock,awburst,awlen,awsize};
            w_payload={wdata,wstrb,wlast};
            if(rst_n)begin
                if(mem_ready !== (REGISTER_RESPONSE ? response_previous : response_now))
                    $fatal(1,"Native response latency differs at cycle %0d",cycles);
                if(ar_stalled)begin
                    if(!arvalid || ar_payload!==ar_payload_q)$fatal(1,"AR payload changed under backpressure");
                    ar_stall_checks++;
                end
                if(aw_stalled)begin
                    if(!awvalid || aw_payload!==aw_payload_q)$fatal(1,"AW payload changed under backpressure");
                    aw_stall_checks++;
                end
                if(w_stalled)begin
                    if(!wvalid || w_payload!==w_payload_q)$fatal(1,"W payload changed under backpressure");
                    w_stall_checks++;
                end
                if(mem_ready && !request_active)$fatal(1,"Response without an active native request");
                if(af)begin
                    if(!request_active || request_mask!='0 || request_ar || araddr!==request_address ||
                       arlen!=0 || arsize!=3'($clog2(BYTEW)) || arburst!=1 || arlock!=0 || arcache!=3 ||
                       arprot!==(request_instruction ? 3'b100 : 3'b000))
                        $fatal(1,"Read address transaction differs");
                    request_ar=1;
                end
                if(awf)begin
                    if(!request_active || request_mask=='0 || request_aw || awaddr!==request_address ||
                       awlen!=0 || awsize!=3'($clog2(BYTEW)) || awburst!=1 || awlock!=0 || awcache!=3 || awprot!=0)
                        $fatal(1,"Write address transaction differs");
                    request_aw=1;
                end
                if(wf)begin
                    if(!request_active || request_mask=='0 || request_w || wdata!==request_data ||
                       wstrb!==request_mask || !wlast)$fatal(1,"Write data transaction differs");
                    request_w=1;
                end
                if(native_done)begin
                    if(request_done)$fatal(1,"Duplicate native completion");
                    index=memory_index(request_address);
                    if(request_mask=='0)begin
                        if(!request_ar)$fatal(1,"Read completed before AR acceptance");
                        for(int lane=0;lane<BYTEW;lane++)begin
                            if(mem_rdata[8*lane+:8]!==expected_memory[index+lane])
                                $fatal(1,"Read data mismatch addr=%h lane=%0d",request_address,lane);
                            checked_bytes++;
                        end
                        reads++;
                    end else begin
                        if(!request_aw || !request_w)$fatal(1,"Write completed before AW and W acceptance");
                        for(int lane=0;lane<BYTEW;lane++)
                            if(request_mask[lane])expected_memory[index+lane]=request_data[8*lane+:8];
                        writes++;
                    end
                    request_done=1;completed++;
                end
                ar_stalled=arvalid && !arready;aw_stalled=awvalid && !awready;w_stalled=wvalid && !wready;
                ar_payload_q=ar_payload;aw_payload_q=aw_payload;w_payload_q=w_payload;
            end
            clk=1;
            #2;
            clk=0;
            #1;
            cycles++;
            if(!rst_n)begin
                read_pending=0;aw_seen=0;w_seen=0;write_pending=0;
                read_delay=0;write_delay=0;response_previous=0;
                ar_stalled=0;aw_stalled=0;w_stalled=0;
            end else begin
                if(read_pending && read_delay>0)read_delay--;
                if(write_pending && write_delay>0)write_delay--;
                if(rf)read_pending=0;
                if(bf)begin write_pending=0;aw_seen=0;w_seen=0;end
                if(af)begin
                    if(read_pending)$fatal(1,"More than one outstanding read");
                    index=memory_index(ar_payload[ADDRESS_PAYLOAD-1-:ADDR_WIDTH]);
                    for(int lane=0;lane<BYTEW;lane++)read_data_saved[8*lane+:8]=axi_memory[index+lane];
                    read_pending=1;read_delay=forced_mode==5 ? 0 : int'(random_state[10:8]);axi_reads++;
                end
                if(awf)begin
                    if(w_seen)w_first++;
                    else if(!wf)aw_first++;
                    else simultaneous++;
                    write_address_saved=aw_payload[ADDRESS_PAYLOAD-1-:ADDR_WIDTH];aw_seen=1;
                end
                if(wf)begin
                    write_data_saved=w_payload[WRITE_PAYLOAD-1-:DATA_WIDTH];
                    write_mask_saved=w_payload[BYTEW:1];w_seen=1;
                end
                if(aw_seen && w_seen && !write_pending)begin
                    index=memory_index(write_address_saved);
                    for(int lane=0;lane<BYTEW;lane++)
                        if(write_mask_saved[lane])axi_memory[index+lane]=write_data_saved[8*lane+:8];
                    write_pending=1;write_delay=int'(random_state[13:11]);axi_writes++;
                end
                response_previous=response_now;
                if(request_active)request_age++;
            end
        end
    endtask

    task automatic idle_cycles(input int count);
        mem_valid=0;mem_wstrb='0;mem_instr=0;
        for(int n=0;n<count;n++)begin
            mem_addr=MEMORY_BASE+ADDR_WIDTH'(BYTEW*(n%32));mem_wdata=DATA_WIDTH'(random_state);cycle();
        end
    endtask

    task automatic reset_bridge;
        if(request_active && !request_done)aborted++;
        request_active=0;mem_valid=0;mem_wstrb='0;rst_n=0;
        repeat(3)cycle();
        forced_mode=0;channel_order=0;rst_n=1;resets++;
        idle_cycles(8);
    endtask

    task automatic start_native(input int word_index, input logic [DATA_WIDTH-1:0] data,
                                input logic [BYTEW-1:0] mask, input logic instruction);
        if(request_active)$fatal(1,"Native request overlap in stimulus");
        request_address=MEMORY_BASE+ADDR_WIDTH'(word_index*BYTEW);
        request_data=data;request_mask=mask;request_instruction=instruction;
        request_active=1;request_done=0;request_ar=0;request_aw=0;request_w=0;request_age=0;
        mem_addr=request_address;mem_wdata=data;mem_wstrb=mask;mem_instr=instruction;mem_valid=1;
        started++;
    endtask

    task automatic transact(input int word_index, input logic [DATA_WIDTH-1:0] data,
                            input logic [BYTEW-1:0] mask, input logic instruction, input int gap);
        start_native(word_index,data,mask,instruction);
        while(!request_done)begin
            cycle();
            if(request_age>200)$fatal(1,"Native request timed out");
        end
        request_active=0;mem_valid=0;
        idle_cycles(gap);
    endtask

    initial begin
        for(int n=0;n<MEMORY_BYTES;n++)begin
            axi_memory[n]=8'(n*37+91);expected_memory[n]=8'(n*37+91);
        end
        reset_bridge();
        // 所有非零字节掩码均执行写入和读回，连续请求保留零空闲间隔。
        for(int mask=1;mask<(1<<BYTEW);mask++)begin
            next_random();channel_order=mask%3;
            transact((mask*37)%128,DATA_WIDTH'({random_state,~random_state}),BYTEW'(mask),0,0);
            channel_order=0;transact((mask*37)%128,'0,'0,1'(mask),0);
        end
        for(int trial=0;trial<512;trial++)begin
            next_random();channel_order=0;
            transact(int'(random_state[7:0])%128,DATA_WIDTH'({random_state,~random_state}),
                     random_state[8] ? BYTEW'(random_state[23:16]) : '0,
                     random_state[9],int'(random_state[11:10]));
        end
        // 复位覆盖地址等待、AW/W 独立等待和读响应等待。
        forced_mode=1;start_native(7,'0,'0,1);repeat(4)cycle();reset_bridge();
        forced_mode=2;start_native(8,'1,'1,0);repeat(4)cycle();
        if(!request_aw || request_w)$fatal(1,"AW-only reset condition not reached");reset_bridge();
        forced_mode=3;start_native(9,'1,'1,0);repeat(4)cycle();
        if(request_aw || !request_w)$fatal(1,"W-only reset condition not reached");reset_bridge();
        forced_mode=4;start_native(10,'0,'0,0);repeat(4)cycle();
        if(!request_ar || request_done)$fatal(1,"Read-return reset condition not reached");reset_bridge();
        forced_mode=5;start_native(11,'0,'0,1);
        while(!response_previous)cycle();
        if(REGISTER_RESPONSE && request_done)$fatal(1,"Registered response arrived before its register cycle");
        reset_bridge();
        for(int word_index=0;word_index<128;word_index++)transact(word_index,'0,'0,1'(word_index),word_index%2);
        idle_cycles(12);
        if(started!=completed+aborted || aw_first==0 || w_first==0 || simultaneous==0 ||
           ar_stall_checks==0 || aw_stall_checks==0 || w_stall_checks==0)
            $fatal(1,"Transaction coverage is incomplete");
        for(int n=0;n<MEMORY_BYTES;n++)
            if(axi_memory[n]!==expected_memory[n])$fatal(1,"Final byte memory differs at %0d",n);
        $display("TRANSACTIONS_PASS {\"passed\":true,\"address_width\":%0d,\"data_width\":%0d,\"registered_response\":%0d,\"cycles\":%0d,\"started\":%0d,\"completed\":%0d,\"reads\":%0d,\"writes\":%0d,\"aborted\":%0d,\"resets\":%0d,\"axi_reads\":%0d,\"axi_writes\":%0d,\"aw_first\":%0d,\"w_first\":%0d,\"simultaneous\":%0d,\"ar_stability_checks\":%0d,\"aw_stability_checks\":%0d,\"w_stability_checks\":%0d,\"checked_read_bytes\":%0d}",
                 ADDR_WIDTH,DATA_WIDTH,REGISTER_RESPONSE,cycles,started,completed,reads,writes,aborted,resets,
                 axi_reads,axi_writes,aw_first,w_first,simultaneous,ar_stall_checks,aw_stall_checks,w_stall_checks,checked_bytes);
        $finish;
    end
endmodule
