// Directed tests for exact allocation reads, byte lanes and the legacy bypass.
module tb_conv_axi_read_guard;
  logic clk;
  initial begin clk=0;forever #5 clk=~clk;end
  logic rst_n=0,enable=1,cfg_valid=0;
  logic [31:0] cfg_base[4];
  logic [32:0] cfg_end[4];
  logic s_arvalid=0,s_arready,s_rvalid,s_rready,s_rlast;
  logic [31:0] s_araddr=0,s_rdata;
  logic [7:0] s_arlen=0;
  logic [2:0] s_arsize=2;
  logic [1:0] s_arburst=1,s_rresp;
  logic m_arvalid,m_arready,m_rvalid,m_rready,m_rlast,idle;
  logic [31:0] m_araddr,m_rdata;
  logic [7:0] m_arlen;
  logic [2:0] m_arsize;
  logic [1:0] m_arburst,m_rresp;
  conv_axi_read_guard dut(.*);

  logic [31:0] rng;
  bit mem_active,fault_enable,fault_sent;
  longint unsigned mem_addr,fault_addr,logical_addr;
  int unsigned mem_left,mem_size,logical_left;
  int unsigned cycles,commands=0,responses=0,error_responses=0;
  longint unsigned external_bytes,external_bursts;

  function automatic bit allowed(input longint unsigned addr);
    bit yes;
    yes=0;
    for(int i=0;i<4;i++)
      if(cfg_base[i]!=0 && addr>=64'(cfg_base[i]) && addr<64'(cfg_end[i])) yes=1;
    return yes;
  endfunction
  function automatic logic[7:0] value_at(input longint unsigned addr);
    return 8'((addr*13) ^ (addr>>5) ^ (addr>>17) ^ 64'hd7);
  endfunction

  always @(posedge clk) begin
    if(!rst_n) begin
      m_arready<=0;m_rvalid<=0;m_rdata<=0;m_rresp<=0;m_rlast<=0;s_rready<=0;
      rng<=32'h891234bc;mem_active=0;mem_addr=0;mem_left=0;mem_size=0;
      cycles<=0;external_bytes<=0;external_bursts<=0;
    end else begin
      cycles<=cycles+1;
      if(cycles>100000) $fatal(1,"guard timeout");
      rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
      m_arready<=!mem_active && rng[0];
      s_rready<=rng[1] || rng[7];
      if(!enable) begin
        if(m_arvalid!=s_arvalid || s_arready!=m_arready || m_araddr!=s_araddr ||
           m_arlen!=s_arlen || m_arsize!=s_arsize || m_arburst!=s_arburst ||
           s_rvalid!=m_rvalid || m_rready!=s_rready || s_rdata!=m_rdata ||
           s_rresp!=m_rresp || s_rlast!=m_rlast) $fatal(1,"GEMM bypass changed the channel");
      end
      if(m_arvalid && m_arready) begin
        if(mem_active || m_arburst!=1 || !(m_arsize==0 || m_arsize==2)) $fatal(1,"bad external AR");
        if((m_araddr&4095)+((32'(m_arlen)+1)<<m_arsize)>4096) $fatal(1,"external 4 KiB crossing");
        if(m_arsize==2 && m_araddr[1:0]!=0) $fatal(1,"unaligned full-width request");
        for(int byte_index=0;byte_index<((32'(m_arlen)+1)<<m_arsize);byte_index++)
          if(enable && !allowed(64'(m_araddr)+64'(byte_index)))
            $fatal(1,"read outside allocations: %h",64'(m_araddr)+64'(byte_index));
        mem_active=1;mem_addr=64'(m_araddr);mem_left=32'(m_arlen)+1;mem_size=1<<m_arsize;
        m_arready<=0;external_bursts<=external_bursts+1;
      end
      if(m_rvalid && m_rready) begin
        m_rvalid<=0;external_bytes<=external_bytes+64'(mem_size);
        mem_addr=mem_addr+64'(mem_size);mem_left=mem_left-1;
        if(mem_left==0) mem_active=0;
      end else if(mem_active && !m_rvalid && rng[2]) begin
        m_rdata<=32'hbadacafe;
        for(int b=0;b<4;b++) if(32'(b)<mem_size)
          m_rdata[((32'(mem_addr)&3)+32'(b))*8 +:8]<=value_at(mem_addr+64'(b));
        m_rlast<=mem_left==1;
        m_rresp<=(fault_enable && !fault_sent && mem_addr==fault_addr) ? 2'b10 : 2'b00;
        if(fault_enable && !fault_sent && mem_addr==fault_addr) fault_sent=1;
        m_rvalid<=1;
      end
      if(s_rvalid && s_rready) begin
        logic[31:0] expected_word;
        bit expected_error;
        if(logical_left==0) $fatal(1,"extra upstream response");
        expected_word='0;
        for(int b=0;b<4;b++)
          if(!enable || allowed(logical_addr+64'(b))) expected_word[b*8 +:8]=value_at(logical_addr+64'(b));
        expected_error=fault_enable && fault_addr>=logical_addr && fault_addr<logical_addr+4;
        if(s_rdata!=expected_word) $fatal(1,"wrong guarded word addr=%h got=%h expected=%h",logical_addr,s_rdata,expected_word);
        if(s_rresp!=(expected_error ? 2'b10 : 2'b00)) $fatal(1,"RRESP not propagated/accumulated");
        if(s_rlast!=(logical_left==1)) $fatal(1,"wrong upstream RLAST");
        logical_addr=logical_addr+4;logical_left=logical_left-1;responses=responses+1;
        if(expected_error) error_responses=error_responses+1;
      end
    end
  end

  task automatic configure(input bit high_address);
    @(negedge clk);
    if(!idle || mem_active || m_rvalid || s_rvalid) $fatal(1,"configure before drain");
    for(int i=0;i<4;i++) begin cfg_base[i]=0;cfg_end[i]=0;end
    if(high_address) begin
      cfg_base[0]=32'hfffffffd;cfg_end[0]=33'h1_00000000;
      cfg_base[1]=32'h00000004;cfg_end[1]=33'h00000000c;
    end else begin
      cfg_base[0]=32'h1003;cfg_end[0]=33'h1011;
      cfg_base[1]=32'h2001;cfg_end[1]=33'h2007;
      cfg_base[2]=32'h2ffb;cfg_end[2]=33'h3015;
      cfg_base[3]=32'h4000;cfg_end[3]=33'h4100;
    end
    cfg_valid=1;
    @(negedge clk);cfg_valid=0;
  endtask

  task automatic request(input logic[31:0] addr,input int count,input int wanted_bytes,
                         input int wanted_bursts,input bit inject=0,input logic[31:0] fail_addr=0);
    longint unsigned bytes_before,bursts_before;
    @(negedge clk);
    if(!idle || mem_active || m_rvalid || s_rvalid) $fatal(1,"request before drain");
    bytes_before=external_bytes;bursts_before=external_bursts;
    fault_enable=inject;fault_sent=0;fault_addr=64'(fail_addr);
    logical_addr=64'(addr);logical_left=32'(count);
    s_araddr=addr;s_arlen=8'(count-1);s_arvalid=1;
    do @(posedge clk);while(!s_arready);
    @(negedge clk);s_arvalid=0;
    while(logical_left!=0) @(negedge clk);
    @(negedge clk);
    if(external_bytes-bytes_before!=64'(wanted_bytes) || external_bursts-bursts_before!=64'(wanted_bursts))
      $fatal(1,"wrong traffic bytes=%0d bursts=%0d expected=%0d/%0d",external_bytes-bytes_before,external_bursts-bursts_before,wanted_bytes,wanted_bursts);
    if(inject && !fault_sent) $fatal(1,"requested fault never exercised");
    commands=commands+1;
  endtask

  initial begin
    for(int i=0;i<4;i++) begin cfg_base[i]=0;cfg_end[i]=0;end
    logical_left=0;fault_enable=0;fault_sent=0;fault_addr=0;
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    configure(0);
    request(32'h1000,8,14,5);                 // 3-byte prefix and suffix, padded tail words
    request(32'h2000,2,6,6);                 // nonzero byte lanes at both allocation ends
    request(32'h2ff8,8,26,8);                // split at 4 KiB without crossing ARs
    request(32'h4020,4,16,1);                // safe burst remains a burst
    request(32'h2000,4,6,6,1,32'h2001);     // RRESP survives later successful byte reads
    request(32'h4020,4,16,1,1,32'h4024);     // fast path forwards RRESP on its original beat
    request(32'h5000,4,0,0);                 // zero padding never issues an external read
    configure(1);
    request(32'hfffffffc,4,3,3);             // no 32-bit wrap into allocation at 0x4
    configure(0);
    @(negedge clk);enable=0;
    request(32'h6000,4,16,1);                // legacy GEMM reads are an exact wire bypass
    @(negedge clk);enable=1;
    request(32'h4020,4,16,1);                // mixed bypass/guarded task recovery
    $display("CONV_READ_GUARD_PASS commands=%0d responses=%0d error_responses=%0d read_bytes=%0d bursts=%0d cycles=%0d",
      commands,responses,error_responses,external_bytes,external_bursts,cycles);
    $finish;
  end
endmodule
