// SPDX-License-Identifier: Apache-2.0
// Connect virtual matrix tile descriptors to the convolution frontend.
//
// Original IA controller runs on a VIRTUAL s16 matrix:
//   logical rows = OH*OW, cols = KH*KW*group_c,
//   lhs_base = virtual_base, lhs_row_stride_b = virtual_stride_b.
// This wrapper decodes each original tl_base_addr, then reads the REAL NHWC
// tensor through conv_cfg.input_base. No virtual matrix is allocated or read.
// Direct p0/q0 outputs from the controller are preferable for performance; they
// can connect directly to conv_im2col_frontend and bypass this 32-cycle decoder.
module conv_ia_tile_path #(
  parameter int SIZE=16,
  parameter int CACHE_BLOCKS=4,
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_SETS=128, CACHE_WAYS=2, LINE_BYTES=16,
  parameter int SW=(CACHE_BLOCKS<=1 ? 1 : $clog2(CACHE_BLOCKS)),
  parameter int CW=$clog2(SIZE),
  parameter int RW=$clog2(SIZE+1)
) (
  input logic clk,rst_n,
  input logic init_cfg,
  output logic cfg_ready,
  input conv_im2col_pkg::conv_cfg_t conv_cfg,
  input logic [31:0] virtual_base,virtual_stride_b,
  input logic tl_start,
  input logic [31:0] tl_base_addr,tl_rows_to_read,
  input logic [SW-1:0] tl_slot_id,
  output logic tl_busy,tl_tile_done,error,
  output logic [SW-1:0] tl_wr_slot,
  output logic [CW-1:0] tl_wr_row,tl_wr_col_base,
  output logic signed [15:0] tl_wr_data[4],
  output logic tl_wr_valid[4],
  output logic tl_wr_use_16bits,
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input logic rvalid,
  output logic rready,
  input logic [BUS_WIDTH-1:0] rdata,
  input logic [1:0] rresp,
  input logic rlast
);

  typedef enum logic [2:0] {IDLE,DIV_START,DIV_WAIT,ISSUE,WAIT_TILE,FAULT} st_t;
  st_t state;
  logic seen_cfg;
  logic [31:0] vbase,vstride,delta,p0,q0,rows;
  logic [SW-1:0] slot;
  logic div_done,div_busy,div_zero;
  logic [31:0] quotient,remainder;
  logic fe_cfg_ready,fe_tile_ready,fe_done,fe_error,fe_tile_error,fe_busy;
  logic fe_wr_valid,fe_wr_ready;
  logic [SW-1:0] fe_wr_slot;
  logic [CW-1:0] fe_wr_row,fe_wr_col;
  logic signed [15:0] fe_wr_data[2];
  logic [1:0] fe_wr_mask;
  assign cfg_ready=(state==IDLE || state==FAULT) && fe_cfg_ready;
  assign tl_busy=state!=IDLE || !seen_cfg || error;
  assign tl_tile_done=state==WAIT_TILE && fe_done;
  conv_udiv32 u_decode (.clk,.rst_n,.start(state==DIV_START),
    .dividend(delta),.divisor(vstride),.busy(div_busy),.done(div_done),
    .div_zero,.quotient,.remainder);
  conv_im2col_frontend #(.SIZE(SIZE),.SLOT_W(SW),
    .CACHE_SETS(CACHE_SETS),.CACHE_WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_front (
    .clk,.rst_n,.cfg_valid(init_cfg && cfg_ready),.cfg_ready(fe_cfg_ready),.cfg(conv_cfg),
    .tile_valid(state==ISSUE),.tile_ready(fe_tile_ready),.tile_p0(p0),.tile_q0(q0),
    .tile_rows(RW'(rows)),.tile_slot(slot),
    .wr_valid(fe_wr_valid),.wr_ready(fe_wr_ready),.wr_slot(fe_wr_slot),
    .wr_row(fe_wr_row),.wr_col(fe_wr_col),.wr_data(fe_wr_data),.wr_mask(fe_wr_mask),
    .tile_done(fe_done),.tile_error(fe_tile_error),.error(fe_error),.busy(fe_busy),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
  );
  conv_ia_write_adapter #(.SIZE(SIZE),.CACHE_BLOCKS(CACHE_BLOCKS)) u_write (
    .selected(state==WAIT_TILE),.in_valid(fe_wr_valid),.in_ready(fe_wr_ready),
    .in_slot(fe_wr_slot),.in_row(fe_wr_row),.in_col(fe_wr_col),.in_data(fe_wr_data),.in_mask(fe_wr_mask),
    .tl_wr_slot,.tl_wr_row,.tl_wr_col_base,.tl_wr_data,.tl_wr_valid,.tl_wr_use_16bits
  );
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE;seen_cfg<=0;error<=0;vbase<=0;vstride<=0;delta<=0;
      p0<=0;q0<=0;rows<=0;slot<=0;
    end else if(init_cfg && cfg_ready) begin
      vbase<=virtual_base;vstride<=virtual_stride_b;state<=IDLE;
      seen_cfg<=virtual_stride_b!=0 && !virtual_stride_b[0];
      error<=virtual_stride_b==0 || virtual_stride_b[0];
    end else if(fe_error || fe_tile_error) begin error<=1;state<=FAULT; end
    else case(state)
      IDLE: if(tl_start && !tl_busy) begin
        if(tl_base_addr<vbase || tl_rows_to_read==0 || tl_rows_to_read>SIZE) begin
          error<=1;state<=FAULT;
        end else begin
          delta<=tl_base_addr-vbase;rows<=tl_rows_to_read;slot<=tl_slot_id;state<=DIV_START;
        end
      end
      DIV_START:state<=DIV_WAIT;
      DIV_WAIT:if(div_done) begin
        if(div_zero || remainder[0])begin error<=1;state<=FAULT;end
        else begin p0<=quotient;q0<=remainder>>1;state<=ISSUE;end
      end
      ISSUE:if(fe_tile_ready)state<=WAIT_TILE;
      WAIT_TILE:if(fe_done)state<=IDLE;
      FAULT:;
      default:state<=FAULT;
    endcase
  end
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk)if(rst_n)begin
    if(init_cfg)assert(cfg_ready);
    if(tl_start)assert(!tl_busy);
  end
`endif
endmodule
