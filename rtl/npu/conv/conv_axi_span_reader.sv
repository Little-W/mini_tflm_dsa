// SPDX-License-Identifier: Apache-2.0
// Read EXACTLY [req_addr, req_addr+req_bytes), never a surrounding allocation.
// Parameterized AXI4 read master, single outstanding burst, fixed response ID.
// Aligned middle: INCR bursts; unaligned prefix/suffix: byte-sized AXI reads.
// Slave MUST support ARSIZE=0 narrow reads. No unsupported unaligned full-word reads.
module conv_axi_span_reader #(
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8)
) (
  input logic clk, rst_n,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_addr,
  input logic [15:0] req_bytes,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [31:0] rsp_word_addr,
  output logic [BUS_WIDTH-1:0] rsp_data,
  output logic [BUS_WIDTH/8-1:0] rsp_strb,
  output logic rsp_last, rsp_error,
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
  input logic rlast,
  output logic busy
);
  localparam int BUS_BYTES=BUS_WIDTH/8;
  localparam int BUS_SHIFT=$clog2(BUS_BYTES);
  initial begin
    if (DMA_MAX_BYTES < BUS_BYTES || DMA_MAX_BYTES > 256*BUS_BYTES ||
        (DMA_MAX_BYTES & (DMA_MAX_BYTES - 1)) != 0)
      $fatal(1, "DMA_MAX_BYTES must contain a power-of-two count of 1 through 256 complete AXI beats");
  end
  typedef enum logic [1:0] {IDLE, PREP, AR, DATA} st_t;
  st_t state;
  logic [31:0] cursor;
  logic [16:0] left_bytes;
  logic [8:0] beats_left;
  logic [BUS_SHIFT:0] beat_bytes;
  logic [16:0] nwords, page_words, next_beats;
  logic [31:0] prepare_addr;
  logic [16:0] prepare_bytes;
  logic finishing_span, forward_ar;
  logic [31:0] araddr_q;
  logic [7:0] arlen_q;
  logic [2:0] arsize_q;
  always_comb begin
    prepare_addr = req_ready ? req_addr : cursor;
    prepare_bytes = req_ready ? {1'b0,req_bytes} : left_bytes;
    nwords = prepare_bytes >> BUS_SHIFT;
    page_words = (17'd4096 - {5'b0,prepare_addr[11:0]}) >> BUS_SHIFT;
    next_beats = nwords;
    if (next_beats > 17'(DMA_MAX_BYTES/BUS_BYTES)) next_beats = 17'(DMA_MAX_BYTES/BUS_BYTES);
    if (next_beats > page_words) next_beats = page_words;
  end
  assign finishing_span = rsp_valid && rsp_ready && rsp_last;
  assign req_ready = state == IDLE || finishing_span;
  assign busy = state != IDLE;
  assign forward_ar = finishing_span && req_valid;
  assign arvalid = state == AR || forward_ar;
  assign araddr = forward_ar ? req_addr : araddr_q;
  assign arlen = forward_ar ?
    ((req_addr[BUS_SHIFT-1:0] != 0 || req_bytes < 16'(BUS_BYTES)) ? 8'd0 : 8'(next_beats - 1'b1)) : arlen_q;
  assign arsize = forward_ar ?
    ((req_addr[BUS_SHIFT-1:0] != 0 || req_bytes < 16'(BUS_BYTES)) ? 3'd0 : 3'(BUS_SHIFT)) : arsize_q;
  assign arburst = 2'b01;
  assign rsp_valid = state == DATA && rvalid;
  assign rready = state == DATA && rsp_ready;
  assign rsp_word_addr = {cursor[31:BUS_SHIFT],{BUS_SHIFT{1'b0}}};
  assign rsp_data = rdata;
  assign rsp_strb = (beat_bytes == (BUS_SHIFT+1)'(BUS_BYTES)) ? {BUS_BYTES{1'b1}} : (BUS_BYTES'(1) << cursor[BUS_SHIFT-1:0]);
  assign rsp_last = (left_bytes == 17'(beat_bytes));
  assign rsp_error = (rresp != 2'b00) || (rlast != (beats_left == 1));
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE; cursor <= 0; left_bytes <= 0; beats_left <= 0;
      beat_bytes <= 0; araddr_q <= 0; arlen_q <= 0; arsize_q <= 0;
    end else begin
      if (req_valid && req_ready) begin
          cursor <= req_addr; left_bytes <= {1'b0,req_bytes}; araddr_q <= req_addr;
          if (req_addr[BUS_SHIFT-1:0] != 0 || req_bytes < 16'(BUS_BYTES)) begin
            arsize_q <= 0; arlen_q <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= 8'(next_beats - 1'b1);
            beats_left <= 9'(next_beats); beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= forward_ar && arready ? DATA : AR;
      end else case (state)
        IDLE: ;
        PREP: begin
          araddr_q <= cursor;
          if (cursor[BUS_SHIFT-1:0] != 0 || left_bytes < 17'(BUS_BYTES)) begin
            arsize_q <= 0; arlen_q <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= 8'(next_beats - 1'b1);
            beats_left <= 9'(next_beats); beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= AR;
        end
        AR: if (arready) state <= DATA;
        DATA: if (rvalid && rready) begin
          cursor <= cursor + 32'(beat_bytes);
          left_bytes <= left_bytes - 17'(beat_bytes);
          beats_left <= beats_left - 1'b1;
          if (left_bytes == 17'(beat_bytes)) state <= IDLE;
          else if (beats_left == 1) state <= PREP;
        end
        default: state <= IDLE;
      endcase
    end
  end
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (req_valid && req_ready) assert (req_bytes != 0);
    if (rvalid && rready) assert (rlast == (beats_left == 1));
    if (arvalid) assert ({1'b0,araddr[11:0]} + (({5'b0,arlen}+1) << arsize) <= 4096);
  end
`endif
endmodule
