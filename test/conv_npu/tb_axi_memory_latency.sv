`timescale 1ns/1ps
module axi_memory_latency_case #(
    parameter int FIRST_LATENCY=8,
    parameter int OUTSTANDING=4
)(output logic done=0);
    localparam int COMMANDS=8;
    logic clk=0,rst_n=0;
    always #5 clk=~clk;
    logic arvalid,arready,rvalid,rready,rlast;
    logic [31:0] araddr;
    logic [7:0] arlen;
    logic [63:0] rdata;
    logic [1:0] rresp;
    logic [31:0] other_lo[4],other_hi[4];
    logic [31:0] addresses[COMMANDS];
    int lengths[COMMANDS];
    int issued=0,completed=0,beat_index=0;
    longint unsigned cycle=0,ar_cycles[COMMANDS];
    longint unsigned first_ar=0,last_r=0,previous_last=0;
    longint unsigned latency_min=64'hffffffffffffffff,latency_max=0;
    longint unsigned transition_min=64'hffffffffffffffff;
    int observed_outstanding=0,read_beats=0,stall_cycles=0;
    assign arvalid=rst_n && issued<COMMANDS && issued-completed<OUTSTANDING;
    assign araddr=issued<COMMANDS ? addresses[issued] : 0;
    assign arlen=issued<COMMANDS ? 8'(lengths[issued]-1) : 0;
    assign rready=rst_n && (completed<6 || !(cycle%7==2 || cycle%7==3));
    conv_test_axi_memory #(.WORDS(4096),.BUS_WIDTH(64),.READ_FIRST_LATENCY(FIRST_LATENCY),
        .READ_BEAT_CYCLES(1),.PIPELINED_READ(1)) mem(
        .clk,.rst_n,.new_job(1'b0),.protect_input(1'b0),.inject_error(1'b0),
        .inject_write_error(1'b0),.input_lo(32'd0),.input_hi(32'd0),.other_lo,.other_hi,
        .error_injected(),.read_bytes(),.input_read_bytes(),.read_requests(),.write_bytes(),
        .arvalid,.arready,.araddr,.arlen,.arsize(3'd3),.arburst(2'b01),
        .rvalid,.rready,.rdata,.rresp,.rlast,
        .awvalid(1'b0),.awready(),.awaddr(32'd0),.awlen(8'd0),.awsize(3'd3),.awburst(2'b01),
        .wvalid(1'b0),.wready(),.wdata(64'd0),.wstrb(8'd0),.wlast(1'b0),
        .bvalid(),.bready(1'b1),.bresp());
    initial begin
        addresses='{32'h100,32'h108,32'h110,32'h118,32'h200,32'h1000,32'h2008,32'h2100};
        lengths='{1,1,1,1,32,256,1,8};
        for(int i=0;i<4;i++)begin other_lo[i]=0;other_hi[i]=0;end
        for(int i=0;i<4096;i++)mem.mem[i]=32'h52a30000^32'(i);
        repeat(4)@(negedge clk);
        rst_n=1;
    end
    always @(posedge clk)if(rst_n && !done)begin
        cycle<=cycle+1;
        if(cycle>2000)$fatal(1,"latency memory timeout");
        if(arvalid && arready)begin
            ar_cycles[issued]<=cycle;
            if(issued==0)first_ar<=cycle;
            if(issued-completed+1>observed_outstanding)observed_outstanding<=issued-completed+1;
            issued<=issued+1;
        end
        if(rvalid && !rready)stall_cycles<=stall_cycles+1;
        if(rvalid && rready)begin
            logic [31:0] word_address;
            logic [63:0] expected;
            longint unsigned latency;
            word_address=(addresses[completed]>>2)+32'(beat_index*2);
            expected={32'h52a30000^(word_address+1),32'h52a30000^word_address};
            assert(rresp==0 && rdata===expected)else $fatal(1,"read payload mismatch");
            assert(rlast==(beat_index==lengths[completed]-1))else $fatal(1,"RLAST mismatch");
            if(beat_index==0)begin
                latency=cycle-ar_cycles[completed];
                assert(latency>=64'(FIRST_LATENCY))else $fatal(1,"response before deadline");
                if(completed==0)assert(latency==64'(FIRST_LATENCY))else $fatal(1,"first response latency differs");
                if(latency<latency_min)latency_min<=latency;
                if(latency>latency_max)latency_max<=latency;
                if(completed>0 && cycle-previous_last<transition_min)transition_min<=cycle-previous_last;
            end
            read_beats<=read_beats+1;
            if(rlast)begin
                previous_last<=cycle;beat_index<=0;completed<=completed+1;
                if(completed==COMMANDS-1)begin last_r<=cycle;done<=1;end
            end else beat_index<=beat_index+1;
        end
    end
    always @(posedge done)begin
        assert(read_beats==301)else $fatal(1,"read beat count mismatch");
        if(OUTSTANDING==4)assert(transition_min==1)else $fatal(1,"mature queued requests contain an idle cycle");
        $display("MEMORY_LATENCY_PASS latency=%0d outstanding=%0d observed_outstanding=%0d first_latency=%0d min_latency=%0d max_latency=%0d min_transition=%0d read_beats=%0d elapsed=%0d stalls=%0d",
            FIRST_LATENCY,OUTSTANDING,observed_outstanding,FIRST_LATENCY,latency_min,latency_max,transition_min,read_beats,last_r-first_ar+1,stall_cycles);
    end
endmodule
module tb_axi_memory_latency;
    localparam int LATENCIES[5]='{1,2,3,8,17};
    wire [9:0] done;
    for(genvar i=0;i<5;i++)begin:g_latency
        axi_memory_latency_case #(.FIRST_LATENCY(LATENCIES[i]),.OUTSTANDING(1)) one(.done(done[2*i]));
        axi_memory_latency_case #(.FIRST_LATENCY(LATENCIES[i]),.OUTSTANDING(4)) four(.done(done[2*i+1]));
    end
    initial begin wait(&done);#1;$display("AXI_MEMORY_LATENCY_PASS cases=10");$finish;end
endmodule
