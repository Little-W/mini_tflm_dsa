// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
// A requested 16-byte sector finishes while its 64-byte allocation is held.
// The production AXI-Lite wrapper supplies the actual clock-gating logic.
module tb_operand_drain;
  localparam int WORDS=16384;
  localparam logic [31:0] A=32'h1000, B=32'h2000, GOUT=32'h7000;
  localparam logic [31:0] CI=32'h3003, CW=32'h4001, CO=32'h6003;
  localparam logic [31:0] QM=32'h5000, QS=32'h5010, BI=32'h5020;
  logic clk=0,rst_n=0;
  always #5 clk=~clk;
  logic [15:0] awaddr=0,araddr=0;
  logic [31:0] wdata=0,rdata;
  logic [3:0] wstrb=0;
  logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
  wire awready,wready,bvalid,arready,rvalid;
  wire [1:0] bresp,rresp;
  wire irq,npu_busy;
  wire ma,mar,mr,mrr,mrl,mwa,mwar,mw,mwr,mwl,mb,mbr;
  wire [31:0] maa,mrd,mwaa,mwd;
  wire [7:0] mal,mwal;
  wire [2:0] mas,mwas;
  wire [1:0] mab,mwab,mre,mbe;
  wire [3:0] mws;
  wire mem_rvalid,mem_rready,mem_rlast;
  wire [31:0] mem_rdata;
  wire [1:0] mem_rresp;
  logic release_tail=0;
  wire hold_tail;
  longint unsigned read_bytes,input_read_bytes,read_requests,write_bytes;
  wire error_injected;
  logic [31:0] unused_ranges[4]='{default:'0};

  npu_axil_top #(.SIZE(16),.PS_FRAME_COUNT(16),.ENABLE_CLOCK_GATING(1)) dut (
    .clk,.rst_n,
    .s_axil_awaddr(awaddr),.s_axil_awprot(3'd0),.s_axil_awvalid(awvalid),.s_axil_awready(awready),
    .s_axil_wdata(wdata),.s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
    .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
    .s_axil_araddr(araddr),.s_axil_arprot(3'd0),.s_axil_arvalid(arvalid),.s_axil_arready(arready),
    .s_axil_rdata(rdata),.s_axil_rresp(rresp),.s_axil_rvalid(rvalid),.s_axil_rready(rready),
    .m_axi_arvalid(ma),.m_axi_arready(mar),.m_axi_araddr(maa),.m_axi_arcache(),.m_axi_arprot(),.m_axi_arlock(),
    .m_axi_arburst(mab),.m_axi_arlen(mal),.m_axi_arsize(mas),
    .m_axi_rvalid(mr),.m_axi_rready(mrr),.m_axi_rdata(mrd),.m_axi_rresp(mre),.m_axi_rlast(mrl),
    .m_axi_awvalid(mwa),.m_axi_awready(mwar),.m_axi_awaddr(mwaa),.m_axi_awcache(),.m_axi_awprot(),.m_axi_awlock(),
    .m_axi_awburst(mwab),.m_axi_awlen(mwal),.m_axi_awsize(mwas),
    .m_axi_wvalid(mw),.m_axi_wready(mwr),.m_axi_wdata(mwd),.m_axi_wstrb(mws),.m_axi_wlast(mwl),
    .m_axi_bvalid(mb),.m_axi_bready(mbr),.m_axi_bresp(mbe),.irq,.npu_busy
  );
  // These optional core controls are not exposed by the production AXI-Lite
  // wrapper. Test-only elaboration/input overrides preserve its real gate.
  defparam dut.u_npu_top.OPERAND_CACHE_ENABLE=1;
  initial force dut.u_npu_top.cfg_operand_fetch64=1'b1;

  // This tiny task's ordinary IA read is issued before its weight read. Hold
  // the final weight allocation so every element needed by compute has arrived.
  assign hold_tail=!release_tail && memory.rd_active && memory.rd_addr==B+32'd16;
  assign mr=mem_rvalid && !hold_tail;
  assign mem_rready=mrr && !hold_tail;
  assign mrd=mem_rdata;assign mre=mem_rresp;assign mrl=mem_rlast;
  conv_test_axi_memory #(.WORDS(WORDS)) memory (
    .clk,.rst_n,.new_job(1'b0),.protect_input(1'b0),.inject_error(1'b0),
    .input_lo(32'd0),.input_hi(32'd0),.other_lo(unused_ranges),.other_hi(unused_ranges),
    .error_injected,.read_bytes,.input_read_bytes,.read_requests,.write_bytes,
    .arvalid(ma),.arready(mar),.araddr(maa),.arlen(mal),.arsize(mas),.arburst(mab),
    .rvalid(mem_rvalid),.rready(mem_rready),.rdata(mem_rdata),.rresp(mem_rresp),.rlast(mem_rlast),
    .awvalid(mwa),.awready(mwar),.awaddr(mwaa),.awlen(mwal),.awsize(mwas),.awburst(mwab),
    .wvalid(mw),.wready(mwr),.wdata(mwd),.wstrb(mws),.wlast(mwl),
    .bvalid(mb),.bready(mbr),.bresp(mbe)
  );

  int starts=0,done_handshakes=0,flushes=0;
  int external_reads=0;
  always @(posedge clk) if(rst_n) begin
    if(dut.u_npu_top.cfg_start_event) starts++;
    if(dut.npu_done_valid && dut.npu_done_ready) done_handshakes++;
    if(dut.u_npu_top.g_operand_cache.range_stage[2]) flushes++;
    case ({ma&&mar,mr&&mrr&&mrl})
      2'b10:external_reads++;
      2'b01:external_reads--;
      default:;
    endcase
    assert(external_reads>=0) else $fatal(1,"unexpected external RLAST");
  end

  task automatic wr(input logic [15:0] address,input logic [31:0] value,input logic [1:0] expect_resp=0);
    bit aa,ww;int timeout;
    aa=0;ww=0;timeout=0;
    @(negedge clk);awaddr=address;wdata=value;wstrb=15;awvalid=1;wvalid=1;
    while(!aa || !ww) begin
      @(posedge clk);if(awvalid&&awready)aa=1;if(wvalid&&wready)ww=1;
      @(negedge clk);if(aa)awvalid=0;if(ww)wvalid=0;
      timeout++;assert(timeout<1000)else $fatal(1,"AXIL write address timeout");
    end
    bready=1;
    do begin @(posedge clk);timeout++;assert(timeout<1000)else $fatal(1,"AXIL B timeout");end while(!bvalid);
    assert(bresp==expect_resp)else $fatal(1,"AXIL BRESP addr=%h got=%d expected=%d",address,bresp,expect_resp);
    @(negedge clk);bready=0;
  endtask
  task automatic rd(input logic [15:0] address,output logic [31:0] value);
    int timeout;
    timeout=0;@(negedge clk);araddr=address;arvalid=1;
    do begin @(posedge clk);timeout++;assert(timeout<1000)else $fatal(1,"AXIL AR timeout");end while(!arready);
    @(negedge clk);arvalid=0;rready=1;
    do begin @(posedge clk);timeout++;assert(timeout<1000)else $fatal(1,"AXIL R timeout");end while(!rvalid);
    assert(rresp==0)else $fatal(1,"AXIL read response");value=rdata;
    @(negedge clk);rready=0;
  endtask
  task automatic common;
    wr('h01c,0);wr('h038,0);wr('h03c,0);wr('h040,0);
    wr('h044,32'h40000000);wr('h048,0);wr('h04c,32'hffffff80);wr('h050,127);
    wr('h054,1);wr('h058,1);wr('h05c,0);
    wr('h060,1);wr('h064,1);wr('h068,1);wr('h06c,1);wr('h004,4);
  endtask
  task automatic gemm;
    common();wr('h010,A);wr('h014,B);wr('h018,GOUT);
    wr('h020,1);wr('h024,16);wr('h028,1);wr('h02c,64);wr('h030,64);wr('h034,1);
    wr('h000,1);
  endtask
  task automatic conv;
    common();wr('h010,CI);wr('h014,CW);wr('h018,CO);wr('h01c,BI);
    wr('h020,2);wr('h024,12);wr('h028,2);wr('h02c,32);wr('h030,12);wr('h034,2);
    wr('h044,QM);wr('h048,QS);wr('h05c,1);
    wr('h074,CI);wr('h078,32'h00030002);wr('h07c,32'h00030003);wr('h080,0);
    wr('h084,32'h00020002);wr('h088,32'h00020001);wr('h08c,32'h00010001);
    wr('h090,32'h00010001);wr('h094,0);wr('h098,2);
    wr('h000,32'h4f);
  endtask
  task automatic put_byte(input int unsigned address,input int value);
    memory.mem[address>>2][(address&3)*8+:8]=8'(value);
  endtask
  function automatic int signed get_byte(input int unsigned address);
    return int'($signed(memory.mem[address>>2][(address&3)*8+:8]));
  endfunction
  task automatic await_done(input int job);
    logic[31:0] status;int limit;
    status=0;limit=0;
    while(!status[2])begin rd('h004,status);limit++;assert(limit<10000)else $fatal(1,"job %d timeout",job);end
    assert(status[4:3]==0)else $fatal(1,"job %d error %h",job,status);
    assert(external_reads==0 && memory.count==0 && !memory.rd_active)
      else $fatal(1,"DONE with pending external traffic");
    wr('h004,4);
  endtask
  task automatic await_gated;
    repeat(12)@(negedge clk);
    assert(!dut.npu_clk_gate_en)else $fatal(1,"clock did not gate after drained task");
  endtask

  bit expect_red;
  int timeout,hold_flushes,hold_done;
  int expected[4];
  logic [31:0] status;
  initial begin
    expect_red=$test$plusargs("EXPECT_RED");
    for(int i=0;i<WORDS;i++)memory.mem[i]=32'ha5a5a5a5;
    for(int i=0;i<64;i++)begin put_byte(A+32'(i),i<16?i+1:90);put_byte(B+32'(i),i<16?1:91);end
    for(int i=0;i<18;i++)put_byte(CI+32'(i),i+1);
    for(int i=0;i<24;i++)put_byte(CW+32'(i),i<12?1:2);
    memory.mem[QM>>2]=32'h40000000;memory.mem[(QM>>2)+1]=32'h40000000;
    memory.mem[QS>>2]=32'hffffffff;memory.mem[(QS>>2)+1]=32'hfffffffe;
    memory.mem[BI>>2]=8;memory.mem[(BI>>2)+1]=32'hfffffff8;
    // Independent direct convolution (all values make rounding exact).
    for(int p=0;p<2;p++)for(int oc=0;oc<2;oc++)begin
      int acc;
      acc=oc==0?8:-8;
      for(int ky=0;ky<2;ky++)for(int kx=0;kx<2;kx++)for(int ch=0;ch<3;ch++)
        acc+=(get_byte(CI+32'((ky*3+p+kx)*3+ch))+2)*(oc+1);
      assert((acc%((oc==0)?4:8))==0)else $fatal(1,"reference requires exact scaling");
      expected[p*2+oc]=acc/((oc==0)?4:8);
    end
    repeat(8)@(negedge clk);rst_n=1;repeat(8)@(negedge clk);
    gemm();
    timeout=0;
    while(!(hold_tail && dut.u_npu_top.controller_done_valid))begin
      @(negedge clk);timeout++;
      assert(timeout<10000)else $fatal(1,"no held completion: starts=%0d busy=%0d gate=%0d pending=%0d ready=%0d ctrl=%0d err=%0d hold=%0d extreads=%0d mem_active=%0d addr=%h left=%0d cachecount=%0d bypass=%0d fetch=%0d",
        starts,npu_busy,dut.npu_clk_gate_en,dut.npu_start_pending_q,dut.npu_sa_ready,
        dut.u_npu_top.u_npu_controller.current_state,dut.npu_err_code,hold_tail,external_reads,
        memory.rd_active,memory.rd_addr,memory.rd_left,dut.u_npu_top.g_operand_cache.u_cache.count,
        dut.u_npu_top.g_operand_cache.single_group_bypass,dut.u_npu_top.g_operand_cache.fetch64_q);
    end
    assert(get_byte(GOUT)==68)else $fatal(1,"first GEMM data incorrect");
    assert(memory.rd_left==12 && external_reads==1)else $fatal(1,"wrong held burst state");
    hold_flushes=flushes;hold_done=done_handshakes;
    if(expect_red)begin
      repeat(12)@(negedge clk);rd('h004,status);
      assert(status[2] && dut.npu_sa_ready)else $fatal(1,"old early retirement was not reproduced");
      assert(dut.u_npu_top.g_operand_cache.u_cache.count==1)else $fatal(1,"old suffix not retained");
      $display("OPERAND_DRAIN_RED_EARLY_DONE pending_reads=%0d remaining_beats=%0d",external_reads,memory.rd_left);
      conv();repeat(12)@(negedge clk);
      assert(starts==2 && dut.u_npu_top.g_operand_cache.single_group_bypass && flushes>hold_flushes)
        else $fatal(1,"old next task did not switch/flush pending traffic");
      assert(hold_tail && external_reads>=1)else $fatal(1,"pending suffix unexpectedly drained");
      $display("OPERAND_DRAIN_RED_REPRODUCED starts=%0d flushes=%0d remaining_beats=%0d",starts,flushes,memory.rd_left);
      $finish;
    end else begin
      repeat(250)begin
        @(negedge clk);
        assert(!dut.npu_done_valid && !dut.npu_sa_ready && npu_busy)
          else $fatal(1,"completed or reopened job before prefetch suffix drained");
        assert(dut.npu_clk_gate_en && !dut.u_npu_top.g_operand_cache.single_group_bypass)
          else $fatal(1,"clock/route changed while prefetch suffix pending");
        assert(flushes==hold_flushes && starts==1 && done_handshakes==hold_done)
          else $fatal(1,"job side effect while suffix held");
      end
      wr('h000,1,2'b10); // Active task: duplicate START must not cause a flush.
      @(negedge clk);release_tail=1;
      await_done(0);await_gated();
      $display("OPERAND_DRAIN_GEMM_RETIRED done_handshakes=%0d remaining_reads=%0d",done_handshakes,external_reads);
      conv();await_done(1);
      for(int i=0;i<4;i++)assert(get_byte(CO+32'(i))==expected[i])
        else $fatal(1,"Conv output %d got=%d expected=%d",i,get_byte(CO+32'(i)),expected[i]);
      assert(get_byte(CO-1)==-91 && get_byte(CO+4)==-91)else $fatal(1,"Conv output guard overwritten");
      await_gated();
      for(int i=0;i<16;i++)begin put_byte(A+32'(i),2);put_byte(B+32'(i),3);end
      gemm();await_done(2);assert(get_byte(GOUT)==48)else $fatal(1,"final GEMM stale data");await_gated();
      assert(starts==3 && flushes==3 && done_handshakes==3 && external_reads==0)
        else $fatal(1,"job/drain accounting mismatch starts=%0d flushes=%0d done=%0d reads=%0d",
                    starts,flushes,done_handshakes,external_reads);
      $display("OPERAND_DRAIN_PASS jobs=%0d flushes=%0d done_handshakes=%0d held_cycles=250 conv_outputs=4 read_bytes=%0d write_bytes=%0d",starts,flushes,done_handshakes,read_bytes,write_bytes);
      $finish;
    end
  end
  initial begin #20000000;$fatal(1,"global timeout");end
endmodule
