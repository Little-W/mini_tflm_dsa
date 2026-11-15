// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// In-order AXI memory with correct byte lanes for narrow INCR reads.
// Inputs in 0x10000..0x1ffff are guarded by exact allocation bounds.
module conv_test_axi_memory #(
    parameter int WORDS = 131072,
    parameter int QUEUE_DEPTH = 16
) (
    input logic clk, rst_n, new_job,
    input logic protect_input, inject_error,
    input logic inject_write_error=1'b0,
    input logic [31:0] input_lo, input_hi,
    input logic [31:0] other_lo[4],other_hi[4],
    output logic error_injected,
    output longint unsigned read_bytes, input_read_bytes, read_requests, write_bytes,
    input logic arvalid, output logic arready,
    input logic [31:0] araddr, input logic [7:0] arlen,
    input logic [2:0] arsize, input logic [1:0] arburst,
    output logic rvalid, input logic rready,
    output logic [31:0] rdata, output logic [1:0] rresp, output logic rlast,
    input logic awvalid, output logic awready,
    input logic [31:0] awaddr, input logic [7:0] awlen,
    input logic [2:0] awsize, input logic [1:0] awburst,
    input logic wvalid, output logic wready,
    input logic [31:0] wdata, input logic [3:0] wstrb, input logic wlast,
    output logic bvalid, input logic bready, output logic [1:0] bresp
);
    logic [31:0] mem[WORDS];
    // Test-only accounting, indexed by byte address within the input arena.
    int unsigned input_hist[65536];
    logic input_required[65536];
    logic [31:0] qa[QUEUE_DEPTH];
    logic [8:0] qn[QUEUE_DEPTH];
    logic [2:0] qs[QUEUE_DEPTH];
    logic [1:0] qe[QUEUE_DEPTH];
    int unsigned wp=0,rp=0,count=0;
    bit rd_active=0,wr_active=0;
    logic [31:0] rd_addr=0,wr_addr=0;
    logic [8:0] rd_left=0,wr_left=0;
    logic [2:0] rd_size=0,wr_size=0;
    logic [1:0] rd_error=0;
    logic [31:0] random_state=32'h12345678;
    bit random_wait;
    wire pop = !rd_active && count!=0;
    wire push = arvalid && arready;
    initial random_wait = !$test$plusargs("NO_RANDOM_WAIT");

    function automatic logic [31:0] beat(input logic [31:0] addr,input logic [2:0] size);
        logic [31:0] result;
        int unsigned lane;
        result=32'ha5a5a5a5;
        for(int i=0;i<4;i++)begin
            lane=(addr&32'd3);
            if(i>=int'(lane) && i<int'(lane)+(1<<size))
                result[i*8+:8]=mem[int'(addr>>2)][i*8+:8];
        end
        return result;
    endfunction

    assign arready=rst_n && count<QUEUE_DEPTH && (!random_wait || random_state[0]);
    assign awready=rst_n && !wr_active && !bvalid && (!random_wait || random_state[3]);
    assign wready=rst_n && wr_active && (!random_wait || random_state[7]);

    always @(posedge clk) begin
        if(!rst_n)begin
            for(int i=0;i<65536;i++)input_hist[i]=0;
            wp<=0;rp<=0;count<=0;rd_active<=0;wr_active<=0;
            rvalid<=0;rlast<=0;rdata<=0;rresp<=0;bvalid<=0;bresp<=0;
            read_bytes<=0;input_read_bytes<=0;read_requests<=0;write_bytes<=0;
            error_injected<=0;random_state<=32'h12345678;
        end else begin
            random_state<={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
            if(new_job)begin
                for(int i=0;i<65536;i++)input_hist[i]=0;
                assert(count==0 && !rd_active && !rvalid && !wr_active && !bvalid)
                    else $fatal(1,"new job before previous AXI transactions drained");
                read_bytes<=0;input_read_bytes<=0;read_requests<=0;write_bytes<=0;
                error_injected<=0;random_state<=32'h12345678;
            end
            case({push,pop})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
                default:;
            endcase
            if(push)begin : accept_read
                longint unsigned bytes_last;
                bit input_access;
                bit range_allowed;
                bytes_last=(64'(arlen)+1)<<arsize;
                input_access=protect_input && araddr>=32'h10000 && araddr<32'h20000;
                range_allowed=(araddr>=input_lo && 64'(araddr)+bytes_last<=64'(input_hi));
                for(int region=0;region<4;region++)begin
                    if(other_lo[region]!=0 && araddr>=other_lo[region] &&
                       64'(araddr)+bytes_last<=64'(other_hi[region]))range_allowed=1;
                end
                assert(arsize<=2 && arburst==2'b01) else $fatal(1,"unsupported AXI read");
                assert(64'(araddr)+bytes_last<=64'(WORDS)*4) else $fatal(1,"memory read out of range");
                assert((64'(araddr)&4095)+bytes_last<=4096) else $fatal(1,"AXI read crosses 4 KiB");
                if(protect_input)assert(range_allowed)
                    else $fatal(1,"Conv read outside all allocated tensors addr=%h bytes=%0d",araddr,bytes_last);
                if(input_access)begin
                    assert(araddr>=input_lo && 64'(araddr)+bytes_last<=64'(input_hi))
                        else $fatal(1,"input overread addr=%h bytes=%0d legal=[%h,%h)",araddr,bytes_last,input_lo,input_hi);
                    input_read_bytes<=input_read_bytes+bytes_last;
                    for(int unsigned byte_index=0;64'(byte_index)<bytes_last;byte_index++)begin
                        input_hist[int'(araddr-32'h10000)+int'(byte_index)]++;
                    end
                end
                qa[wp]<=araddr;qn[wp]<={1'b0,arlen}+9'd1;qs[wp]<=arsize;qe[wp]<=0;
                if((input_access || !protect_input) && inject_error && !error_injected)begin
                    qe[wp]<=2'b10;error_injected<=1;
                end
                wp<=wp==QUEUE_DEPTH-1?0:wp+1;
                read_bytes<=read_bytes+bytes_last;read_requests<=read_requests+1;
            end
            if(pop)begin
                rd_active<=1;rd_addr<=qa[rp];rd_left<=qn[rp];rd_size<=qs[rp];rd_error<=qe[rp];
                rp<=rp==QUEUE_DEPTH-1?0:rp+1;
            end
            if(rd_active && !rvalid && (!random_wait || random_state[5]))begin
                rvalid<=1;rdata<=beat(rd_addr,rd_size);rresp<=rd_error;rlast<=rd_left==1;
            end
            if(rvalid && rready)begin
                rvalid<=0;
                if(rd_left==1)begin rd_active<=0;rd_left<=0;end
                else begin
                    rd_left<=rd_left-1;
                    rd_addr<=(rd_addr&~((32'd1<<rd_size)-1))+(32'd1<<rd_size);
                end
            end
            if(awvalid && awready)begin
                assert(awsize<=2 && awburst==2'b01) else $fatal(1,"unsupported AXI write");
                assert(64'(awaddr)+((64'(awlen)+1)<<awsize)<=64'(WORDS)*4) else $fatal(1,"write out of range");
                assert((64'(awaddr)&4095)+((64'(awlen)+1)<<awsize)<=4096) else $fatal(1,"AXI write crosses 4 KiB");
                wr_active<=1;wr_addr<=awaddr;wr_left<={1'b0,awlen}+9'd1;wr_size<=awsize;
            end
            if(wvalid && wready)begin
                assert(wlast==(wr_left==1)) else $fatal(1,"bad WLAST");
                for(int i=0;i<4;i++)if(wstrb[i])mem[int'(wr_addr>>2)][i*8+:8]<=wdata[i*8+:8];
                write_bytes<=write_bytes+64'($countones(wstrb));
                if(wr_left==1)begin
                    wr_active<=0;bvalid<=1;bresp<=0;
                    if(inject_write_error && !error_injected)begin bresp<=2'b10;error_injected<=1;end
                end
                else begin wr_left<=wr_left-1;wr_addr<=(wr_addr&~((32'd1<<wr_size)-1))+(32'd1<<wr_size);end
            end
            if(bvalid && bready)bvalid<=0;
        end
    end

    logic ar_stalled=0,aw_stalled=0,w_stalled=0;
    logic [44:0] old_ar,old_aw;
    logic [36:0] old_w;
    always @(posedge clk)begin
        if(!rst_n)begin ar_stalled<=0;aw_stalled<=0;w_stalled<=0;end
        else begin
            if(ar_stalled)assert(arvalid && {araddr,arlen,arsize,arburst}===old_ar)else $fatal(1,"unstable stalled AR");
            if(aw_stalled)assert(awvalid && {awaddr,awlen,awsize,awburst}===old_aw)else $fatal(1,"unstable stalled AW");
            if(w_stalled)assert(wvalid && {wdata,wstrb,wlast}===old_w)else $fatal(1,"unstable stalled W");
            ar_stalled<=arvalid&&!arready;aw_stalled<=awvalid&&!awready;w_stalled<=wvalid&&!wready;
            old_ar<={araddr,arlen,arsize,arburst};old_aw<={awaddr,awlen,awsize,awburst};old_w<={wdata,wstrb,wlast};
        end
    end
endmodule
