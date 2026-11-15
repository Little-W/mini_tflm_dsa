`timescale 1ns/1ps
module predictor_tb;
  import conv_im2col_pkg::*;
  logic clk=0, rst_n=0, cfg_valid=0, start=0;
  always #5 clk=~clk;
  conv_cfg_t cfg;
  logic [31:0] cfg_r, cfg_groups;
  logic cfg_eligible, enabled, busy, done;
  logic [31:0] input_y, input_x, channel, current_p, current_q, current_group, next_rank;
  conv_next_use_predictor dut (.*);

  string config_path, vectors_path;
  integer config_fd, vectors_fd, cases, scan_result;
  integer total_vectors=0, enabled_cases=0, disabled_cases=0, maximum_latency=0;
  logic [31:0] fields[0:21];
  logic [31:0] expected_rank;
  integer latency;

  initial begin
    cfg='0; cfg_r=0; cfg_groups=0;
    input_y=0;input_x=0;channel=0;current_p=0;current_q=0;current_group=0;
    if (!$value$plusargs("CONFIG=%s",config_path) ||
        !$value$plusargs("VECTORS=%s",vectors_path) ||
        !$value$plusargs("CASES=%d",cases)) $fatal(1,"missing input paths/count");
    config_fd=$fopen(config_path,"r"); vectors_fd=$fopen(vectors_path,"r");
    if (!config_fd || !vectors_fd) $fatal(1,"cannot open predictor vectors");
    repeat(3) @(negedge clk);
    rst_n=1;
    for (integer ci=0;ci<cases;ci++) begin
      scan_result=$fscanf(config_fd,
        "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
        fields[0],fields[1],fields[2],fields[3],fields[4],fields[5],fields[6],fields[7],
        fields[8],fields[9],fields[10],fields[11],fields[12],fields[13],fields[14],fields[15],
        fields[16],fields[17],fields[18],fields[19],fields[20],fields[21]);
      if (scan_result!=22) $fatal(1,"bad configuration %0d",ci);
      @(negedge clk);
      cfg='0;
      cfg.input_base=fields[0];
      cfg.input_h=fields[1][15:0];cfg.input_w=fields[2][15:0];cfg.input_c=fields[3][15:0];
      cfg.group_c=fields[4][15:0];cfg.group_offset=fields[5][15:0];
      cfg.kernel_h=fields[6][15:0];cfg.kernel_w=fields[7][15:0];
      cfg.output_h=fields[8][15:0];cfg.output_w=fields[9][15:0];
      cfg.stride_h=fields[10][15:0];cfg.stride_w=fields[11][15:0];
      cfg.dilation_h=fields[12][15:0];cfg.dilation_w=fields[13][15:0];
      cfg.pad_top=fields[14][15:0];cfg.pad_left=fields[15][15:0];
      cfg_r=fields[16];cfg_groups=fields[17];
      cfg.input_s16=fields[18][0];cfg.bypass_cache=fields[19][0];
      cfg_valid=1;
      #1;
      if (cfg_eligible!==fields[20][0])
        $fatal(1,"configuration eligibility case=%0d expected=%0d actual=%0d",ci,fields[20],cfg_eligible);
      @(posedge clk); #1;
      if (enabled!==fields[20][0] || busy || done)
        $fatal(1,"configuration latch case=%0d enabled=%0d busy=%0d done=%0d",ci,enabled,busy,done);
      if (enabled) enabled_cases++; else disabled_cases++;
      @(negedge clk); cfg_valid=0;
      for (integer vi=0;vi<fields[21];vi++) begin
        @(negedge clk);
        scan_result=$fscanf(vectors_fd,"%h %h %h %h %h %h %h\n",
          input_y,input_x,channel,current_p,current_q,current_group,expected_rank);
        if (scan_result!=7) $fatal(1,"bad vector case=%0d vector=%0d",ci,vi);
        if (busy || done) $fatal(1,"predictor not idle before vector");
        start=1;
        @(posedge clk); #1;
        latency=0;
        while (!done) begin
          @(negedge clk); start=0;
          @(posedge clk); #1;
          latency++;
          if (latency>32) $fatal(1,"predictor timeout case=%0d vector=%0d",ci,vi);
        end
        if (busy || next_rank!==expected_rank)
          $fatal(1,"prediction case=%0d vector=%0d p=%0d q=%0d group=%0d expected=%08x actual=%08x busy=%0d",
            ci,vi,current_p,current_q,current_group,expected_rank,next_rank,busy);
        if (fields[20][0] && latency!=fields[6]*fields[7])
          $fatal(1,"tap latency case=%0d expected=%0d actual=%0d",ci,fields[6]*fields[7],latency);
        if (latency>maximum_latency) maximum_latency=latency;
        total_vectors++;
        @(negedge clk); start=0;
        @(posedge clk); #1;
        if (done || next_rank!==expected_rank) $fatal(1,"done must pulse and result must hold");
      end
      $display("PREDICTOR_CASE_PASS case=%0d enabled=%0d vectors=%0d",ci,fields[20],fields[21]);
    end
    $fclose(config_fd);$fclose(vectors_fd);
    $display("PREDICTOR_PASS cases=%0d enabled_cases=%0d disabled_cases=%0d vectors=%0d max_tap_latency=%0d",
      cases,enabled_cases,disabled_cases,total_vectors,maximum_latency);
    $finish;
  end
endmodule
