// SPDX-License-Identifier: Apache-2.0
module window_dma_top (
  input logic clk,rst_n,cfg_valid,
  input logic i_abort,
  output logic window_granted,
  output logic cfg_ready,
  input logic [31:0] config_words[16],
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_p0,req_q0,req_cols,
  input logic [1:0] req_tag,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [1:0] rsp_tag,
  output logic [31:0] rsp_col,
  output logic signed [15:0] rsp_data[4],
  output logic [3:0] rsp_mask,
  output logic rsp_last,rsp_error,busy,read_busy,
  output logic [31:0] requests,completions,peak_outstanding,
  output logic [31:0] response_beats,consecutive_responses,request_response_overlap,
  input logic ordinary_req,ordinary_start,
  output logic ordinary_granted,ordinary_busy,ordinary_done,ordinary_error,ordinary_raw_valid,
  output logic [31:0] ordinary_raw_data,
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  input logic rvalid,
  output logic rready,
  input logic [31:0] rdata,
  input logic [1:0] rresp,
  input logic rlast
);
  conv_im2col_pkg::conv_cfg_t cfg;
  logic [31:0] range_base[4];
  logic [32:0] range_end[4];
  always_comb begin
    for(int i=0;i<4;i++)begin range_base[i]=0;range_end[i]=0;end
    range_base[0]=config_words[0];
    range_end[0]=33'(config_words[0])+33'(config_words[1])*33'(config_words[2])*33'(config_words[3]);
    cfg='0;
    cfg.input_base=config_words[0];cfg.input_h=16'(config_words[1]);
    cfg.input_w=16'(config_words[2]);cfg.input_c=16'(config_words[3]);
    cfg.group_c=cfg.input_c;cfg.kernel_h=16'(config_words[4]);cfg.kernel_w=16'(config_words[5]);
    cfg.output_h=16'(config_words[6]);cfg.output_w=16'(config_words[7]);
    cfg.stride_h=16'(config_words[8]);cfg.stride_w=16'(config_words[9]);
    cfg.pad_top=16'(config_words[10]);cfg.pad_left=16'(config_words[11]);
    cfg.input_offset=16'(config_words[12]);cfg.dilation_h=1;cfg.dilation_w=1;
    cfg.windowed=config_words[13][0];cfg.prefetch_enable=config_words[14][0];
    cfg.bypass_cache=config_words[15][0];
  end
  assign requests=dma.u_dma.tb_observer.win_stat_requests;
  assign completions=dma.u_dma.tb_observer.win_stat_completions;
  assign peak_outstanding=dma.u_dma.tb_observer.win_stat_peak_outstanding;
  assign response_beats=dma.u_dma.tb_observer.win_stat_response_beats;
  assign consecutive_responses=dma.u_dma.tb_observer.win_stat_consecutive_responses;
  assign request_response_overlap=dma.u_dma.tb_observer.win_stat_request_response_overlap;
  assign read_busy=dma.u_dma.rd_busy;
  assign window_granted=dma.rd_grant_client==3'd5;
  axi_block_dma_arbiter #(.SIZE(16),.DMA_SIZE(64),.CONV_CACHE_SETS(128),.CONV_CACHE_POLICY(3)) dma (
    .clk,.rst_n,.abort(i_abort),.conv_cfg_valid(cfg_valid),.conv_cfg_ready(cfg_ready),.conv_enable(1'b1),
    .dma_range_enable(1'b0),.conv_cfg(cfg),.conv_range_base(range_base),.conv_range_end(range_end),
    .win_req_valid(req_valid),.win_req_ready(req_ready),.win_req_p0(req_p0),.win_req_q0(req_q0),
    .win_req_cols(req_cols),.win_req_tag(req_tag),.win_rsp_valid(rsp_valid),.win_rsp_ready(rsp_ready),
    .win_rsp_tag(rsp_tag),.win_rsp_col(rsp_col),.win_rsp_data(rsp_data),.win_rsp_mask(rsp_mask),
    .win_rsp_last(rsp_last),.win_rsp_error(rsp_error),.win_busy(busy),
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
    .dw_req(ordinary_req),.dw_start(ordinary_start),.dw_granted(ordinary_granted),
    .dw_im2col(1'b0),.dw_linear_read_mode(1'b0),.dw_base_addr(config_words[0]+32'd64),
    .dw_row_stride(32'd0),.dw_rows_to_read(32'd1),.dw_valid_cols(32'd16),.dw_burst_len_m1(8'd3),
    .dw_use_16bits(1'b0),.dw_lhs_zp(32'd0),.dw_busy(ordinary_busy),.dw_done(ordinary_done),
    .dw_error(ordinary_error),.dw_raw_data(ordinary_raw_data),.dw_raw_valid(ordinary_raw_valid),
    .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),
    .m_axi_rvalid(rvalid),.m_axi_rready(rready),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),
    .m_axi_awready(1'b1),.m_axi_wready(1'b1),.m_axi_bvalid(1'b0),.m_axi_bresp(2'b0)
  );
endmodule
