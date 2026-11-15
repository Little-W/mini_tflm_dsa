// SPDX-License-Identifier: Apache-2.0
// Direct AXI protocol test: exact ranges, page splits, backpressure and RRESP.
module tb_conv_axi_span_reader;
  logic clk;
  initial begin clk=0; forever #5 clk=~clk; end
  logic rst_n=0, req_valid=0, req_ready;
  logic [31:0] req_addr=0;
  logic [15:0] req_bytes=0;
  logic rsp_valid,rsp_ready,rsp_last,rsp_error,busy;
  logic [31:0] rsp_word_addr,rsp_data;
  logic [3:0] rsp_strb;
  logic arvalid,arready,rvalid,rready,rlast;
  logic [31:0] araddr,rdata;
  logic [7:0] arlen;
  logic [2:0] arsize;
  logic [1:0] arburst,rresp;
  logic [31:0] rng;
  bit active,done,inject_fault,fault_sent;
  int unsigned mem_addr,mem_beats,mem_size;
  int unsigned expected_addr,issued_addr,remaining,errors,spans=0;
  longint unsigned last_addr,cycles,read_bytes,total_bursts;

  conv_axi_span_reader dut (.*);

  function automatic logic [7:0] value_at(input logic [31:0] address);
    return address[7:0] ^ address[15:8] ^ address[23:16] ^ address[31:24] ^ 8'h9d;
  endfunction

  always @(posedge clk) begin
    if(!rst_n) begin
      arready<=0;rvalid<=0;rdata<=0;rresp<=0;rlast<=0;rsp_ready<=0;
      rng<=32'h239a3c77;cycles<=0;read_bytes<=0;total_bursts<=0;
      active=0;mem_addr=0;mem_beats=0;mem_size=0;
    end else begin
      rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
      cycles<=cycles+1;
      if(cycles>10000000) $fatal(1,"span timeout");
      arready<=!active && rng[0];
      rsp_ready<=rng[2] || rng[7];
      if(arvalid && arready) begin
        if(active || arburst!=1 || !(arsize==0 || arsize==2)) $fatal(1,"invalid AXI AR");
        if(araddr!=issued_addr) $fatal(1,"noncontiguous AXI AR");
        if(arsize==2 && araddr[1:0]!=0) $fatal(1,"unaligned full word");
        if((araddr&4095)+((32'(arlen)+1)<<arsize)>4096) $fatal(1,"AXI page crossing");
        if(64'(araddr)+((64'(arlen)+1)<<arsize)>last_addr) $fatal(1,"read beyond requested span");
        active=1;mem_addr=araddr;mem_beats=32'(arlen)+1;mem_size=1<<arsize;
        issued_addr=issued_addr+((32'(arlen)+1)<<arsize);
        arready<=0;total_bursts<=total_bursts+1;
      end
      if(rvalid && rready) begin
        rvalid<=0;mem_addr=mem_addr+mem_size;mem_beats=mem_beats-1;
        if(mem_beats==0) active=0;
      end else if(active && !rvalid && rng[3]) begin
        rdata<=32'hdeadbeef;
        for(int b=0;b<4;b++) if(32'(b)<mem_size)
          rdata[((mem_addr&3)+32'(b))*8 +: 8]<=value_at(mem_addr+32'(b));
        rlast<=mem_beats==1;
        rresp<=(inject_fault && !fault_sent) ? 2'b10 : 2'b00;
        if(inject_fault && !fault_sent) fault_sent=1;
        rvalid<=1;
      end
      if(rsp_valid && rsp_ready) begin
        if(rsp_word_addr!={expected_addr[31:2],2'b0}) $fatal(1,"wrong response word address");
        if(rsp_strb!=((mem_size==4) ? 4'b1111 : (4'b0001 << expected_addr[1:0])))
          $fatal(1,"wrong response byte enables");
        for(int b=0;b<4;b++) if(rsp_strb[b]) begin
          if(rsp_data[b*8 +: 8]!=value_at(rsp_word_addr+32'(b))) $fatal(1,"response payload mismatch");
        end
        if(rsp_error!=(rresp!=0)) $fatal(1,"response error mismatch");
        if(rsp_error) errors=errors+1;
        if(rsp_last!=(remaining==mem_size)) $fatal(1,"wrong final span marker");
        expected_addr=expected_addr+mem_size;remaining=remaining-mem_size;
        read_bytes<=read_bytes+64'(mem_size);
        if(rsp_last) done=1;
      end
    end
  end

  assert property (@(posedge clk) disable iff (!rst_n)
    arvalid && !arready |=> arvalid && $stable({araddr,arlen,arsize,arburst}));
  assert property (@(posedge clk) disable iff (!rst_n)
    rsp_valid && !rsp_ready |=> rsp_valid && $stable({rsp_word_addr,rsp_data,rsp_strb,rsp_last,rsp_error}));

  task automatic run_span(input logic [31:0] base,input int unsigned length,input bit fault);
    @(negedge clk);
    if(!req_ready || busy || active || rvalid) $fatal(1,"span did not drain");
    expected_addr=base;issued_addr=base;remaining=length;last_addr=64'(base)+64'(length);
    errors=0;done=0;inject_fault=fault;fault_sent=0;
    req_addr=base;req_bytes=16'(length);req_valid=1;
    do @(posedge clk); while(!req_ready);
    @(negedge clk);req_valid=0;
    do @(posedge clk); while(!done);
    @(negedge clk);
    if(remaining!=0 || 64'(expected_addr)!=last_addr || 64'(issued_addr)!=last_addr)
      $fatal(1,"inexact span coverage");
    if(errors!=(fault ? 1 : 0) || !req_ready || busy || active || rvalid) $fatal(1,"fault/drain contract");
    spans=spans+1;
  endtask

  int unsigned random_state,random_base,random_len;
  initial begin
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    for(int align=0;align<4;align++)
      for(int len=1;len<13;len++) run_span(32'h00000ffc+32'(align),32'(len),len==7);
    run_span(32'h00001003,65535,1);
    run_span(32'hffffe003,8187,0);
    run_span(32'hfffffffd,1,1);
    random_state=32'h893412bc;
    for(int i=0;i<200;i++) begin
      random_state=random_state*1664525+1013904223;
      random_base=random_state & 32'h000fffff;
      random_state=random_state*1664525+1013904223;
      random_len=1+(random_state%8192);
      run_span(random_base,random_len,(i%11)==0);
    end
    $display("RTL_SPAN_PASS spans=%0d cycles=%0d read_bytes=%0d bursts=%0d",spans,cycles,read_bytes,total_bursts);
    $finish;
  end
endmodule
