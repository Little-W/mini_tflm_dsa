// SPDX-License-Identifier: Apache-2.0
module window_error_top #(parameter int TILE=16, PE_COUNT=(TILE<8 ? TILE : 8), CACHE_SETS=128, CACHE_POLICY=3)(
  input logic clk,rst_n,start,done_ready,inject_fault,
  output logic [31:0] injected_errors,write_launches_in_failed,
  output logic dma_idle,write_idle,
  input logic [31:0] config_words[40],
  output logic [31:0] pe_count,
  output logic [31:0] observed_window_elements, expected_window_elements,
  output logic ready,done_valid,
  output logic [1:0] error,
  output logic [31:0] stat_cycles,stat_compute,stat_dma_wait,cache_reads,
  output logic [31:0] cache_hits,cache_misses,cache_prefetch_lines,cache_prefetch_used,
  output logic [31:0] cache_prefetch_wasted,cache_prefetch_unused,cache_prefetch_bytes,cache_prefetch_late,
  output logic [31:0] quant_inputs,quant_consecutive,mac_quant_overlap,mac_write_overlap,all_overlap,
  output logic [31:0] write_bursts16,write_beats16,
  output logic [31:0] window_requests,window_completions,window_peak_outstanding,
  output logic [31:0] window_response_beats,window_consecutive_responses,window_request_response_overlap,
  output logic m_axi_arvalid,input logic m_axi_arready,
  output logic [31:0] m_axi_araddr,output logic [7:0] m_axi_arlen,
  output logic [2:0] m_axi_arsize,output logic [1:0] m_axi_arburst,
  input logic m_axi_rvalid,output logic m_axi_rready,input logic [31:0] m_axi_rdata,
  input logic [1:0] m_axi_rresp,input logic m_axi_rlast,
  output logic m_axi_awvalid,input logic m_axi_awready,
  output logic [31:0] m_axi_awaddr,output logic [7:0] m_axi_awlen,
  output logic [2:0] m_axi_awsize,output logic [1:0] m_axi_awburst,
  output logic m_axi_wvalid,input logic m_axi_wready,output logic [31:0] m_axi_wdata,
  output logic [3:0] m_axi_wstrb,output logic m_axi_wlast,
  input logic m_axi_bvalid,output logic m_axi_bready,input logic [1:0] m_axi_bresp
);
  import vector_engine_pkg::*;
  localparam int DMA_SIZE=4*TILE;
  vector_engine_cfg_t cfg;
  assign pe_count=32'(PE_COUNT);
  assign observed_window_elements=engine.window_received;
  assign expected_window_elements=engine.active;
  always_comb begin
    cfg='0;
    cfg.op=4'(config_words[0]); cfg.vector_s16=config_words[0][8];cfg.length=config_words[1];
    cfg.input_base=config_words[2];cfg.rhs_base=config_words[3];cfg.output_base=config_words[4];
    cfg.bias_base=config_words[5];cfg.multiplier_base=config_words[6];cfg.shift_base=config_words[7];
    cfg.output_offset=$signed(config_words[8]);cfg.activation_min=$signed(config_words[9]);cfg.activation_max=$signed(config_words[10]);
    cfg.image.input_base=config_words[2];
    cfg.image.input_h=16'(config_words[11]);cfg.image.input_w=16'(config_words[12]);
    cfg.image.input_c=16'(config_words[13]);cfg.image.group_c=16'(config_words[13]);
    cfg.image.kernel_h=16'(config_words[14]);cfg.image.kernel_w=16'(config_words[15]);
    cfg.image.output_h=16'(config_words[16]);cfg.image.output_w=16'(config_words[17]);
    cfg.image.stride_h=16'(config_words[18]);cfg.image.stride_w=16'(config_words[19]);
    cfg.image.dilation_h=16'(config_words[20]);cfg.image.dilation_w=16'(config_words[21]);
    cfg.image.pad_top=16'(config_words[22]);cfg.image.pad_left=16'(config_words[23]);
    cfg.image.input_offset=16'(config_words[24]);cfg.image.bypass_cache=config_words[25][0];
    cfg.add.input1_offset=$signed(config_words[26]);cfg.add.input2_offset=$signed(config_words[27]);
    cfg.add.input1_multiplier=$signed(config_words[28]);cfg.add.input1_shift=$signed(config_words[29]);
    cfg.add.input2_multiplier=$signed(config_words[30]);cfg.add.input2_shift=$signed(config_words[31]);
    cfg.add.left_shift=$signed(config_words[32]);cfg.add.output_multiplier=$signed(config_words[33]);
    cfg.add.output_shift=$signed(config_words[34]);
  end
  logic dma_cfg_valid,dma_cfg_ready,dma_conv_enable,dma_range_enable;
  conv_im2col_pkg::conv_cfg_t dma_conv_cfg;
  logic [31:0] dma_range_base[4];logic [32:0] dma_range_end[4];
    logic win_req_valid,win_req_ready,win_rsp_valid,win_rsp_ready;
    logic [31:0] win_req_p0,win_req_q0,win_req_cols,win_rsp_col;
    logic [1:0] win_req_tag,win_rsp_tag;
    logic signed [15:0] win_rsp_data[4];
    logic [3:0] win_rsp_mask;
    logic win_rsp_last,win_rsp_error,win_busy;
  logic rd_req,rd_start,rd_granted,rd_im2col,rd_use_16bits,rd_busy,rd_done,rd_error;
  logic [31:0] rd_p0,rd_q0,rd_base_addr,rd_row_stride,rd_rows_to_read,rd_valid_cols,rd_raw_data;
  logic [7:0] rd_burst_len_m1;logic rd_raw_valid;logic signed [15:0] rd_data[4];logic rd_valid[4];
  logic [$clog2(DMA_SIZE)-1:0] rd_col_base;
  logic wr_req,wr_start,wr_granted,src_wvalid,src_wready,wr_busy,wr_done,wr_error;
  logic [31:0] wr_base_addr,wr_row_stride,wr_rows_to_write,src_wdata;
  logic [7:0] wr_burst_len_m1;logic [3:0] src_wmask;
  logic engine_response_valid,engine_response_ready,engine_response_error;
  logic response_allow,fault_target;
  assign fault_target=inject_fault && injected_errors==0 &&
    win_rsp_valid && win_rsp_last && window_completions==1;
  assign response_allow=!fault_target ||
    (engine.wb_state==engine.WB_REQ && !wr_granted);
  assign win_rsp_ready=engine_response_ready && response_allow;
  assign engine_response_valid=win_rsp_valid && response_allow;
  assign engine_response_error=win_rsp_error || (fault_target && response_allow);
  vector_engine #(.TILE(TILE),.DMA_SIZE(DMA_SIZE),.PE_COUNT(PE_COUNT)) engine(
    .win_rsp_valid(engine_response_valid),.win_rsp_ready(engine_response_ready),
    .win_rsp_error(engine_response_error),.*);
  assign dma_idle=dma.idle;
  assign write_idle=engine.wb_state==engine.WB_IDLE;
  // Hold the second position's final response while the first position
  // completes quantization. Deliver a terminal error one cycle before the
  // output request receives the write arbiter's grant.
  always_ff @(posedge clk) begin
    if (!rst_n || (start && ready)) begin
      injected_errors<=0;write_launches_in_failed<=0;
    end else begin
      if (fault_target && response_allow && win_rsp_valid && win_rsp_ready) begin
        assert(window_requests==2 && window_completions==1);
        assert(engine.wb_state==engine.WB_REQ && !wr_granted);
        injected_errors<=injected_errors+1;
      end
      if (wr_start && engine.state==engine.FAILED) begin
        assert(wr_granted && !wr_busy);
        write_launches_in_failed<=write_launches_in_failed+1;
      end
      if (done_valid) begin
        assert(dma_idle && write_idle);
        assert(window_requests==window_completions);
      end
    end
  end
  assign window_requests=dma.u_dma.win_stat_requests;
  assign window_completions=dma.u_dma.win_stat_completions;
  assign window_peak_outstanding=dma.u_dma.win_stat_peak_outstanding;
  assign window_response_beats=dma.u_dma.win_stat_response_beats;
  assign window_consecutive_responses=dma.u_dma.win_stat_consecutive_responses;
  assign window_request_response_overlap=dma.u_dma.win_stat_request_response_overlap;
  logic mac_active,quant_issue,quant_active,write_active;
  logic previous_quant_issue,previous_quant_more,previous_quant_bank,write16;
  logic [31:0] previous_quant_index,write16_beats;
  assign mac_active=engine.depthwise && engine.state==engine.EXECUTE;
  assign quant_active=engine.depthwise && engine.q_active && engine.state!=engine.FAILED;
  assign quant_issue=quant_active && engine.q_issue<engine.q_count;
  assign write_active=engine.depthwise && engine.wb_state!=engine.WB_IDLE;
  assign cache_prefetch_lines=dma.u_dma.conv_stat_prefetch_lines;
  assign cache_prefetch_used=dma.u_dma.conv_stat_prefetch_used;
  assign cache_prefetch_wasted=dma.u_dma.conv_stat_prefetch_wasted;
  assign cache_prefetch_unused=dma.u_dma.conv_stat_prefetch_unused;
  assign cache_prefetch_bytes=dma.u_dma.conv_stat_prefetch_bytes;
  assign cache_prefetch_late=dma.u_dma.conv_stat_prefetch_late;
  always_ff @(posedge clk) begin
    if (!rst_n || (start && ready)) begin
      quant_inputs<=0;quant_consecutive<=0;mac_quant_overlap<=0;mac_write_overlap<=0;all_overlap<=0;
      write_bursts16<=0;write_beats16<=0;write16<=0;write16_beats<=0;
      previous_quant_issue<=0;previous_quant_more<=0;previous_quant_bank<=0;previous_quant_index<=0;
    end else begin
      previous_quant_issue<=quant_issue;
      previous_quant_more<=quant_issue && engine.q_issue+1<engine.q_count;
      previous_quant_bank<=engine.q_bank;previous_quant_index<=engine.q_issue;
      if (quant_issue) quant_inputs<=quant_inputs+1;
      if (quant_issue && previous_quant_issue) quant_consecutive<=quant_consecutive+1;
      if (previous_quant_more && engine.state!=engine.FAILED) begin
        assert(quant_issue && engine.q_bank==previous_quant_bank);
        assert(engine.q_issue==previous_quant_index+1);
      end
      if (mac_active && quant_active) mac_quant_overlap<=mac_quant_overlap+1;
      if (mac_active && write_active) mac_write_overlap<=mac_write_overlap+1;
      if (mac_active && quant_active && write_active) all_overlap<=all_overlap+1;
      if (wr_start) begin
        write16<=engine.depthwise && engine.bank_bytes[engine.write_bank]==16 &&
                 engine.bank_address[engine.write_bank][1:0]==0;
        write16_beats<=0;
        if (engine.depthwise && engine.bank_bytes[engine.write_bank]==16 &&
            engine.bank_address[engine.write_bank][1:0]==0) begin
          assert(wr_burst_len_m1==3);
          write_bursts16<=write_bursts16+1;
        end
      end
      if (write16 && src_wvalid && src_wready) begin
        write16_beats<=write16_beats+1;write_beats16<=write_beats16+1;
        assert(src_wmask==4'b1111);
      end
      if (write16 && wr_done) begin assert(write16_beats==4);write16<=0;end
    end
  end
  axi_block_dma_arbiter #(.SIZE(TILE),.DMA_SIZE(DMA_SIZE),.DATA_WIDTH(16),
    .CONV_CACHE_SETS(CACHE_SETS),.CONV_CACHE_POLICY(CACHE_POLICY)) dma(
    .clk,.rst_n,.conv_cfg_valid(dma_cfg_valid),.conv_cfg_ready(dma_cfg_ready),
    .conv_enable(dma_conv_enable),.dma_range_enable,.conv_cfg(dma_conv_cfg),
    .conv_range_base(dma_range_base),.conv_range_end(dma_range_end),
    .conv_stat_read_bytes(cache_reads),.conv_stat_hits(cache_hits),.conv_stat_misses(cache_misses),
    .ia_req(1'b0),.ia_start(1'b0),.ia_linear_read_mode(1'b0),.ia_base_addr(32'd0),
    .ia_row_stride(32'd0),.ia_rows_to_read(32'd0),.ia_burst_len_m1(8'd0),.ia_slot_id(2'd0),.ia_use_16bits(1'b0),.ia_lhs_zp(32'd0),
    .kernel_req(1'b0),.kernel_start(1'b0),.kernel_linear_read_mode(1'b0),.kernel_base_addr(32'd0),
    .kernel_row_stride(32'd0),.kernel_rows_to_read(32'd0),.kernel_burst_len_m1(8'd0),.kernel_slot_id(1'b0),.kernel_use_16bits(1'b0),.kernel_lhs_zp(32'd0),
    .bias_req(1'b0),.bias_start(1'b0),.bias_linear_read_mode(1'b0),.bias_base_addr(32'd0),
    .bias_row_stride(32'd0),.bias_rows_to_read(32'd0),.bias_burst_len_m1(8'd0),.bias_slot_id(1'b0),.bias_use_16bits(1'b0),.bias_lhs_zp(32'd0),
    .quant_req(1'b0),.quant_start(1'b0),.quant_linear_read_mode(1'b0),.quant_base_addr(32'd0),
    .quant_row_stride(32'd0),.quant_rows_to_read(32'd0),.quant_burst_len_m1(8'd0),.quant_slot_id(1'b0),.quant_use_16bits(1'b0),.quant_lhs_zp(32'd0),
    .oa_req(1'b0),.oa_start(1'b0),.oa_base_addr(32'd0),.oa_row_stride(32'd0),
    .oa_rows_to_read(32'd0),.oa_burst_len_m1(8'd0),.oa_src_wdata(32'd0),.oa_src_wmask(4'd0),.oa_src_wvalid(1'b0),
            .win_req_valid,.win_req_ready,.win_req_p0,.win_req_q0,.win_req_cols,.win_req_tag,
            .win_rsp_valid,.win_rsp_ready,.win_rsp_tag,.win_rsp_col,.win_rsp_data,.win_rsp_mask,
            .win_rsp_last,.win_rsp_error,.win_busy,
    .dw_req(rd_req),.dw_start(rd_start),.dw_granted(rd_granted),.dw_im2col(rd_im2col),
    .dw_p0(rd_p0),.dw_q0(rd_q0),.dw_base_addr(rd_base_addr),.dw_row_stride(rd_row_stride),
    .dw_rows_to_read(rd_rows_to_read),.dw_valid_cols(rd_valid_cols),.dw_burst_len_m1(rd_burst_len_m1),
    .dw_use_16bits(rd_use_16bits),.dw_busy(rd_busy),.dw_done(rd_done),.dw_error(rd_error),
    .dw_data(rd_data),.dw_valid(rd_valid),.dw_col_base(rd_col_base),.dw_raw_data(rd_raw_data),.dw_raw_valid(rd_raw_valid),
    .dw_wr_req(wr_req),.dw_wr_start(wr_start),.dw_wr_granted(wr_granted),.dw_wr_base_addr(wr_base_addr),
    .dw_wr_row_stride(wr_row_stride),.dw_wr_rows_to_write(wr_rows_to_write),.dw_wr_burst_len_m1(wr_burst_len_m1),
    .dw_src_wdata(src_wdata),.dw_src_wmask(src_wmask),.dw_src_wvalid(src_wvalid),.dw_src_wready(src_wready),
    .dw_wr_busy(wr_busy),.dw_wr_done(wr_done),.dw_wr_error(wr_error),
    .m_axi_arvalid,.m_axi_arready,.m_axi_araddr,.m_axi_arlen,.m_axi_arsize,.m_axi_arburst,
    .m_axi_rvalid,.m_axi_rready,.m_axi_rdata,.m_axi_rresp,.m_axi_rlast,
    .m_axi_awvalid,.m_axi_awready,.m_axi_awaddr,.m_axi_awlen,.m_axi_awsize,.m_axi_awburst,
    .m_axi_wvalid,.m_axi_wready,.m_axi_wdata,.m_axi_wstrb,.m_axi_wlast,
    .m_axi_bvalid,.m_axi_bready,.m_axi_bresp
  );
endmodule
