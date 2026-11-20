`timescale 1ns/1ps
module tb_guard_compare;
  logic clk=0, rst_n=0, enable=0, cfg_valid=0;
  always #5 clk=~clk;
  logic [31:0] cfg_base[4];
  logic [32:0] cfg_end[4];
  logic s_arvalid=0, s_rready=0, m_arready=0, m_rvalid=0, m_rlast=0;
  logic [31:0] s_araddr=0;
  logic [7:0] s_arlen=0;
  logic [1:0] s_arburst=1, m_rresp=0;
  logic [63:0] m_rdata=0;
  logic narrow_size=0;
  logic [31:0] rng=32'h72da_3e91;
  integer compared_cycles=0;

  function automatic logic [31:0] random_word;
    rng = {rng[30:0], rng[31]^rng[21]^rng[1]^rng[0]};
    return rng;
  endfunction

  for (genvar width_index=0; width_index<2; width_index++) begin : g_width
    localparam int DATA_W=32*(width_index+1);
    localparam int BUS_SHIFT=$clog2(DATA_W/8);
    for (genvar split=0; split<2; split++) begin : g_split
      logic s_arready, s_rvalid, s_rlast, m_arvalid, m_rready, idle;
      logic ref_s_arready, ref_s_rvalid, ref_s_rlast, ref_m_arvalid, ref_m_rready, ref_idle;
      logic [31:0] m_araddr, ref_m_araddr;
      logic [DATA_W-1:0] s_rdata, ref_s_rdata;
      logic [7:0] m_arlen, ref_m_arlen;
      logic [2:0] m_arsize, ref_m_arsize, s_arsize;
      logic [1:0] m_arburst, ref_m_arburst, s_rresp, ref_s_rresp;
      integer fast_cycles=0, slow_cycles=0, idle_cycles=0;
      assign s_arsize=narrow_size ? 3'd0 : 3'(BUS_SHIFT);

      conv_axi_read_guard #(.DATA_W(DATA_W), .SPLIT_GEMM_4K(split)) u_current (
        .clk, .rst_n, .enable, .cfg_valid, .cfg_base, .cfg_end,
        .s_arvalid, .s_arready, .s_araddr, .s_arlen, .s_arsize, .s_arburst,
        .s_rvalid, .s_rready, .s_rdata, .s_rresp, .s_rlast,
        .m_arvalid, .m_arready, .m_araddr, .m_arlen, .m_arsize, .m_arburst,
        .m_rvalid, .m_rready, .m_rdata(m_rdata[DATA_W-1:0]), .m_rresp, .m_rlast, .idle);
      reference_conv_axi_read_guard #(.DATA_W(DATA_W), .SPLIT_GEMM_4K(split)) u_reference (
        .clk, .rst_n, .enable, .cfg_valid, .cfg_base, .cfg_end,
        .s_arvalid, .s_arready(ref_s_arready), .s_araddr, .s_arlen, .s_arsize, .s_arburst,
        .s_rvalid(ref_s_rvalid), .s_rready, .s_rdata(ref_s_rdata), .s_rresp(ref_s_rresp), .s_rlast(ref_s_rlast),
        .m_arvalid(ref_m_arvalid), .m_arready, .m_araddr(ref_m_araddr), .m_arlen(ref_m_arlen),
        .m_arsize(ref_m_arsize), .m_arburst(ref_m_arburst), .m_rvalid, .m_rready(ref_m_rready),
        .m_rdata(m_rdata[DATA_W-1:0]), .m_rresp, .m_rlast, .idle(ref_idle));

      always @(posedge clk) begin
        #1;
        if ({s_arready,s_rvalid,s_rdata,s_rresp,s_rlast,m_arvalid,m_araddr,m_arlen,m_arsize,m_arburst,m_rready,idle} !==
            {ref_s_arready,ref_s_rvalid,ref_s_rdata,ref_s_rresp,ref_s_rlast,ref_m_arvalid,ref_m_araddr,
             ref_m_arlen,ref_m_arsize,ref_m_arburst,ref_m_rready,ref_idle})
          $fatal(1,"guard output mismatch width=%0d split=%0d cycle=%0d",DATA_W,split,compared_cycles);
        if (rst_n) begin
          if (u_current.fast_legal) fast_cycles++;
          else slow_cycles++;
          if (idle) idle_cycles++;
        end
      end
      final begin
        if (fast_cycles==0 || slow_cycles==0 || idle_cycles==0)
          $fatal(1,"missing guard comparison coverage");
        $display("GUARD_COMPARE_CASE_PASS width=%0d split=%0d fast=%0d slow=%0d idle=%0d",
                 DATA_W,split,fast_cycles,slow_cycles,idle_cycles);
      end
    end
  end

  initial begin
    for (int i=0; i<4; i++) begin cfg_base[i]='0; cfg_end[i]='0; end
    repeat(3) @(negedge clk);
    for (int cycle=0; cycle<50000; cycle++) begin
      logic [31:0] word;
      @(negedge clk);
      rst_n=(cycle%7919)!=0;
      word=random_word();
      enable=word[0]; cfg_valid=word[7:4]==0;
      s_arvalid=word[1]; m_arready=word[2]; s_rready=word[3];
      m_rvalid=word[8]; m_rlast=word[9]; m_rresp=word[11:10];
      s_arburst=word[15] ? 2'b01 : word[13:12];
      narrow_size=word[19:16]==0;
      if (cfg_valid) begin
        for (int allocation=0; allocation<4; allocation++) begin
          word=random_word();
          case (cycle%4)
            0: cfg_base[allocation]=32'hffff_f000+{20'd0,word[11:0]};
            1: cfg_base[allocation]=32'h1000*32'(allocation+1)+{24'd0,word[7:0]};
            2: cfg_base[allocation]=word;
            default: cfg_base[allocation]=0;
          endcase
          word=random_word();
          cfg_end[allocation]={1'b0,cfg_base[allocation]}+{20'd0,word[12:0]};
          if (word[15:13]==0) cfg_end[allocation]=33'h1_0000_0000;
        end
      end
      word=random_word();
      s_arlen=word[7:0];
      if (word[8]) s_arlen=8'd0;
      if (word[9]) s_arlen=8'hff;
      s_araddr=word[10] ? cfg_base[word[12:11]]+{20'd0,word[23:12]} : random_word();
      if (word[13]) s_araddr={s_araddr[31:3],3'b000};
      if (word[14]) s_araddr={s_araddr[31:12],12'hff8};
      m_rdata={random_word(),random_word()};
      @(posedge clk); #2;
      compared_cycles++;
    end
    @(negedge clk);
    $display("GUARD_COMPARE_PASS cycles=%0d configurations=4",compared_cycles);
    $finish;
  end
endmodule
