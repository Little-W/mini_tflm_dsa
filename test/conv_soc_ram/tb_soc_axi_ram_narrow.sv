// Exact-byte AXI read verification against the real SoC RAM.
module tb_soc_axi_ram_narrow;
  parameter int DP=1031, OUTSTANDING=4;
  localparam int MEM_BYTES=DP*4;
  logic clk;
  initial begin clk=0; forever #5 clk=~clk; end
  logic rst_n=0;
  logic s_axi_awvalid=0,s_axi_awready;
  logic [31:0] s_axi_awaddr=0;
  logic [3:0] s_axi_awcache=0;
  logic [2:0] s_axi_awprot=0,s_axi_awsize=2;
  logic [1:0] s_axi_awlock=0,s_axi_awburst=1;
  logic [7:0] s_axi_awlen=0;
  logic s_axi_wvalid=0,s_axi_wready,s_axi_wlast=0;
  logic [31:0] s_axi_wdata=0;
  logic [3:0] s_axi_wstrb=15;
  logic s_axi_bvalid,s_axi_bready=1;
  logic [1:0] s_axi_bresp;
  logic s_axi_arvalid=0,s_axi_arready;
  logic [31:0] s_axi_araddr=0;
  logic [3:0] s_axi_arcache=0;
  logic [2:0] s_axi_arprot=0,s_axi_arsize=0;
  logic [1:0] s_axi_arlock=0,s_axi_arburst=1;
  logic [7:0] s_axi_arlen=0;
  logic s_axi_rvalid,s_axi_rready,s_axi_rlast;
  logic [31:0] s_axi_rdata;
  logic [1:0] s_axi_rresp;
  logic mem_reload_req=0;
  soc_axi_ram #(.DP(DP),.READ_OUTSTANDING(OUTSTANDING)) dut (.*);

  longint unsigned ref_addr[1024];
  int ref_left[1024],ref_size[1024],ref_burst[1024];
  bit ref_bad[1024];
  int head=0,tail=0,cycles=0,beats=0,errors=0,writes=0;
  int no_random=0,random_state=32'h1234567;
  int last_perf_cycle=-1,perf_beats=0,perf_cycles=0;
  bit perf_phase=0,last_perf_was_last=0;

  function automatic logic [7:0] value_at(input longint unsigned addr);
    return 8'((addr*37) ^ (addr>>3) ^ (addr>>12) ^ 64'hb3);
  endfunction
  function automatic logic [31:0] word_at(input int unsigned word);
    logic [31:0] result;
    for(int b=0;b<4;b++) result[b*8 +:8]=value_at(64'(word)*4+64'(b));
    return result;
  endfunction

  // Consumer stalls are independent of the RAM's own +RAM_* timing controls.
  always @(negedge clk) begin
    if(!rst_n) s_axi_rready=0;
    else begin
      random_state=random_state*1664525+1013904223;
      s_axi_rready=(no_random!=0) || ((random_state&7)!=0);
    end
  end

  always @(posedge clk) if(rst_n) begin
    cycles<=cycles+1;
    if(cycles>200000) $fatal(1,"SoC RAM test timeout");
    if(s_axi_bvalid && s_axi_bready && s_axi_bresp!=0) $fatal(1,"initialization write failed");
    if(s_axi_wvalid && s_axi_wready) writes=writes+1;
    if(s_axi_arvalid && s_axi_arready) begin
      longint unsigned width,aligned,last_exclusive;
      if(tail>=1024) $fatal(1,"scoreboard full");
      width=64'd1<<s_axi_arsize;
      aligned=64'(s_axi_araddr)/width*width;
      last_exclusive=aligned+width*((s_axi_arburst==0) ? 64'd1 : (64'(s_axi_arlen)+1));
      ref_addr[tail]=64'(s_axi_araddr);
      ref_left[tail]=32'(s_axi_arlen)+1;
      ref_size[tail]=32'(s_axi_arsize);
      ref_burst[tail]=32'(s_axi_arburst);
      ref_bad[tail]=(s_axi_arsize>2) || (s_axi_arburst>1) ||
                    ((s_axi_arburst==0) && s_axi_arlen>15) ||
                    ((aligned/4096)!=((last_exclusive-1)/4096));
      tail=tail+1;
    end
    if(s_axi_rvalid && s_axi_rready) begin
      longint unsigned a,word_base,beat_end,width;
      bit want_error;
      if(head>=tail) $fatal(1,"unsolicited RAM response");
      a=ref_addr[head];width=64'd1<<ref_size[head];
      word_base=a/4*4;beat_end=(a/width+1)*width;
      want_error=ref_bad[head] || a>=64'(MEM_BYTES);
      if(s_axi_rresp!=(want_error ? 2'b10 : 2'b00))
        $fatal(1,"wrong RRESP cmd=%0d addr=%h size=%0d got=%b",head,a,ref_size[head],s_axi_rresp);
      if(want_error) begin
        if(s_axi_rdata!=0) $fatal(1,"faulted read leaked aliased RAM data");
        errors=errors+1;
      end else begin
        for(int b=0;b<4;b++) if(word_base+64'(b)>=a && word_base+64'(b)<beat_end)
          if(s_axi_rdata[b*8 +:8]!=value_at(word_base+64'(b)))
            $fatal(1,"wrong byte cmd=%0d addr=%h lane=%0d data=%h",head,a,b,s_axi_rdata);
      end
      if(s_axi_rlast!=(ref_left[head]==1)) $fatal(1,"incorrect RLAST");
      ref_left[head]=ref_left[head]-1;
      if(ref_burst[head]!=0) ref_addr[head]=beat_end;
      if(ref_left[head]==0) head=head+1;
      beats=beats+1;
      if(perf_phase) begin
        if(no_random!=0 && last_perf_cycle>=0 && cycles!=last_perf_cycle+1 &&
           !(OUTSTANDING==1 && last_perf_was_last))
          $fatal(1,"full-width pipeline bubble cycle=%0d previous=%0d",cycles,last_perf_cycle);
        if(last_perf_cycle>=0) perf_cycles=perf_cycles+cycles-last_perf_cycle;
        last_perf_cycle=cycles;last_perf_was_last=s_axi_rlast;perf_beats=perf_beats+1;
      end
    end
  end

  assert property (@(posedge clk) disable iff (!rst_n)
    s_axi_rvalid && !s_axi_rready |=> s_axi_rvalid && $stable({s_axi_rdata,s_axi_rresp,s_axi_rlast}));

  task automatic read_cmd(input logic[31:0] addr,input int size,input int count,input int burst=1);
    @(negedge clk);
    s_axi_araddr=addr;s_axi_arsize=3'(size);s_axi_arlen=8'(count-1);s_axi_arburst=2'(burst);s_axi_arvalid=1;
    do @(posedge clk);while(!s_axi_arready);
    @(negedge clk);s_axi_arvalid=0;
  endtask
  task automatic drain();
    while(head!=tail) @(negedge clk);
    repeat(2) @(negedge clk);
    if(s_axi_rvalid) $fatal(1,"extra response after drain");
  endtask
  task automatic write_words(input int first,input int count);
    @(negedge clk);s_axi_awaddr=32'(first*4);s_axi_awlen=8'(count-1);s_axi_awvalid=1;
    do @(posedge clk);while(!s_axi_awready);
    @(negedge clk);s_axi_awvalid=0;
    for(int w=0;w<count;w++) begin
      s_axi_wdata=word_at(32'(first+w));s_axi_wlast=w==count-1;s_axi_wvalid=1;
      do @(posedge clk);while(!s_axi_wready);
      @(negedge clk);
    end
    s_axi_wvalid=0;s_axi_wlast=0;
    do @(posedge clk);while(!s_axi_bvalid);
    @(negedge clk);
  endtask

  int pos,count,source_rng;
  initial begin
    void'($value$plusargs("NO_RANDOM=%d",no_random));
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    pos=0;
    while(pos<DP) begin
      count=(DP-pos<256) ? DP-pos : 256;
      write_words(pos,count);pos=pos+count;
    end
    perf_phase=1;
    for(int j=0;j<16;j++) read_cmd(32'(j*64),2,16);
    drain();perf_phase=0;
    for(int size=0;size<3;size++) for(int lane=0;lane<4;lane++) begin
      read_cmd(32'(256+lane),size,1);
      read_cmd(32'(256+lane),size,17);
      read_cmd(32'(512+lane),size,5,0);
    end
    read_cmd(4093,0,3);read_cmd(4095,0,1);read_cmd(4095,0,2);
    read_cmd(4095,1,1);read_cmd(4095,2,1);read_cmd(4095,2,2);
    read_cmd(4096,0,17);read_cmd(4096,2,7);
    read_cmd(32'(MEM_BYTES-1),0,1);read_cmd(32'(MEM_BYTES-1),1,1);
    read_cmd(32'(MEM_BYTES-1),2,1);read_cmd(32'(MEM_BYTES-3),0,7);
    read_cmd(32'(MEM_BYTES),1,3);read_cmd(32'hffffffff,0,1);read_cmd(32'hfffffffc,2,2);
    read_cmd(16,3,2);read_cmd(16,1,4,2);read_cmd(16,0,17,0);
    source_rng=32'h5123abc;
    for(int j=0;j<200;j++) begin
      source_rng=source_rng*1664525+1013904223;
      read_cmd(32'($unsigned(source_rng)%(MEM_BYTES+128)),j%3,1+(j%32));
    end
    drain();
    if(writes!=DP || perf_beats!=256) $fatal(1,"incomplete write/performance coverage");
    $display("SOC_RAM_NARROW_PASS dp=%0d outstanding=%0d commands=%0d beats=%0d error_beats=%0d writes=%0d cycles=%0d perf_beats=%0d perf_intervals=%0d no_random=%0d",
      DP,OUTSTANDING,tail,beats,errors,writes,cycles,perf_beats,perf_cycles,no_random);
    $finish;
  end
endmodule
