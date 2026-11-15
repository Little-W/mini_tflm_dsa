// AXI responder and independent handshake/byte-address counters for reuse tests.
module axi_counted_memory #(
    parameter logic [31:0] TRACK_BASE=32'h1003,
    parameter int TRACK_BYTES=256
) (
    input logic clk,rst_n,
    input logic [31:0] allocation_base,allocation_bytes,epoch,
    input logic block_ar,
    input logic arvalid, output logic arready,
    input logic [31:0] araddr,
    input logic [7:0] arlen,
    input logic [2:0] arsize,
    input logic [1:0] arburst,
    output logic rvalid,input logic rready,
    output logic [31:0] rdata,
    output logic [1:0] rresp,
    output logic rlast,
    output longint unsigned read_bytes,ar_count,
    output logic active
);
    int unsigned byte_reads[TRACK_BYTES];
    logic [31:0] rng;
    logic [31:0] address;
    int unsigned left,step;
    function automatic logic[7:0] value_at(input logic[31:0] addr);
        return 8'((addr*32'd29) ^ (addr>>4) ^ epoch);
    endfunction
    always @(posedge clk) begin
        if(!rst_n) begin
            arready<=0;rvalid<=0;rdata<=0;rresp<=0;rlast<=0;
            rng<=32'h925a2b67;address=0;left=0;step=0;active=0;
            read_bytes<=0;ar_count<=0;
            for(int i=0;i<TRACK_BYTES;i++) byte_reads[i]=0;
        end else begin
            rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            arready<=!active && !block_ar && rng[0];
            if(arvalid && arready) begin
                if(active || arburst!=1 || !(arsize==0 || arsize==2)) $fatal(1,"bad AXI request");
                if((araddr&4095)+((32'(arlen)+1)<<arsize)>4096) $fatal(1,"4 KiB crossing");
                if(araddr<allocation_base || 64'(araddr)+((64'(arlen)+1)<<arsize)>
                   64'(allocation_base)+64'(allocation_bytes)) $fatal(1,"allocation overread");
                if(arsize==2 && araddr[1:0]!=0) $fatal(1,"unaligned full word");
                active=1;address=araddr;left=32'(arlen)+1;step=1<<arsize;
                arready<=0;ar_count<=ar_count+1;
                $display("REUSE_EXTERNAL_AR addr=%h beats=%0d size=%0d",araddr,32'(arlen)+1,arsize);
            end
            if(rvalid && rready) begin
                for(int b=0;b<4;b++) if(32'(b)<step) begin
                    if(address+32'(b)<TRACK_BASE || address+32'(b)>=TRACK_BASE+32'(TRACK_BYTES))
                        $fatal(1,"byte counter mapping exceeded");
                    byte_reads[address+32'(b)-TRACK_BASE]=byte_reads[address+32'(b)-TRACK_BASE]+1;
                end
                read_bytes<=read_bytes+64'(step);rvalid<=0;
                address=address+step;left=left-1;if(left==0) active=0;
            end else if(active && !rvalid && rng[2]) begin
                rdata<=32'hbadacafe;
                for(int b=0;b<4;b++) if(32'(b)<step)
                    rdata[((address&3)+32'(b))*8 +:8]<=value_at(address+32'(b));
                rresp<=0;rlast<=left==1;rvalid<=1;
            end
        end
    end
    assert property (@(posedge clk) disable iff(!rst_n)
        arvalid && !arready |=> arvalid && $stable({araddr,arlen,arsize,arburst}));
    assert property (@(posedge clk) disable iff(!rst_n)
        rvalid && !rready |=> rvalid && $stable({rdata,rresp,rlast}));
endmodule
