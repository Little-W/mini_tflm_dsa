// SPDX-License-Identifier: Apache-2.0
// Read EXACTLY [req_addr, req_addr+req_bytes), never a surrounding allocation.
// Parameterized AXI4 read master, single outstanding burst, fixed response ID.
// Aligned middle: INCR bursts; unaligned prefix/suffix: byte-sized AXI reads.
// Slave MUST support ARSIZE=0 narrow reads. No unsupported unaligned full-word reads.
module conv_axi_span_reader #(
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int MAX_REQUEST_BYTES=65535
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
  // Prefix and suffix transfers consume one byte at a time. The counter
  // represents the exact span and a full bus beat without adding padding.
  localparam int SPAN_W=$clog2(MAX_REQUEST_BYTES+1);
  localparam int COUNT_W=SPAN_W>BUS_SHIFT ? SPAN_W : BUS_SHIFT+1;
  localparam int WORD_W=COUNT_W-BUS_SHIFT;
  localparam int MAX_SPAN_BEATS=MAX_REQUEST_BYTES/BUS_BYTES;
  localparam int BURST_LIMIT=MAX_SPAN_BEATS<DMA_MAX_BYTES/BUS_BYTES ?
      MAX_SPAN_BEATS : DMA_MAX_BYTES/BUS_BYTES;
  localparam int BEAT_W=BURST_LIMIT<2 ? 1 : $clog2(BURST_LIMIT+1);
  localparam int PAGE_WORD_W=13-BUS_SHIFT;
  localparam int COMPARE_W=BEAT_W>PAGE_WORD_W ? BEAT_W : PAGE_WORD_W;
  `ifdef NPU_SIM_ASSERT
initial begin
    if (DMA_MAX_BYTES < BUS_BYTES || DMA_MAX_BYTES > 256*BUS_BYTES ||
        (DMA_MAX_BYTES & (DMA_MAX_BYTES - 1)) != 0)
      $fatal(1, "DMA_MAX_BYTES must contain a power-of-two count of 1 through 256 complete AXI beats");
    if (MAX_REQUEST_BYTES < 1 || MAX_REQUEST_BYTES > 65535)
      $fatal(1, "MAX_REQUEST_BYTES must be in [1,65535]");
  end
`endif

  typedef enum logic [1:0] {IDLE, PREP, AR, DATA} st_t;
  st_t state;
  logic [31:0] cursor;
  logic [COUNT_W-1:0] left_bytes;
  logic [BEAT_W-1:0] beats_left;
  logic [BUS_SHIFT:0] beat_bytes;
  logic [WORD_W-1:0] nwords;
  logic [PAGE_WORD_W-1:0] page_words;
  logic [BEAT_W-1:0] burst_beats, next_beats;
  logic [12:0] page_bytes;
  logic [11:0] prepare_addr;
  logic [COUNT_W-1:0] prepare_bytes;
  logic finishing_span, forward_ar;
  logic [31:0] araddr_q;
  logic [7:0] arlen_q;
  logic [2:0] arsize_q;
  assign prepare_addr = req_ready ? req_addr[11:0] : cursor[11:0];
  assign prepare_bytes = req_ready ? COUNT_W'(req_bytes) : left_bytes;
  assign nwords = WORD_W'(prepare_bytes >> BUS_SHIFT);
  assign page_bytes = 13'd4096 - {1'b0,prepare_addr};
  assign page_words = PAGE_WORD_W'(page_bytes >> BUS_SHIFT);
  generate if (BURST_LIMIT == (1<<WORD_W)-1) begin : g_full_word_range
    assign burst_beats = BEAT_W'(nwords);
  end else begin : g_limited_word_range
    assign burst_beats = nwords>WORD_W'(BURST_LIMIT) ? BEAT_W'(BURST_LIMIT) : BEAT_W'(nwords);
  end endgenerate
  assign next_beats = COMPARE_W'(burst_beats)>COMPARE_W'(page_words) ? BEAT_W'(page_words) : burst_beats;
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
  assign rsp_last = (left_bytes == COUNT_W'(beat_bytes));
  assign rsp_error = (rresp != 2'b00) || (rlast != (beats_left == 1));
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE; cursor <= 0; left_bytes <= 0; beats_left <= 0;
      beat_bytes <= 0; araddr_q <= 0; arlen_q <= 0; arsize_q <= 0;
    end else begin
      if (req_valid && req_ready) begin
          cursor <= req_addr; left_bytes <= COUNT_W'(req_bytes); araddr_q <= req_addr;
          if (req_addr[BUS_SHIFT-1:0] != 0 || req_bytes < 16'(BUS_BYTES)) begin
            arsize_q <= 0; arlen_q <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= 8'(next_beats - 1'b1);
            beats_left <= next_beats; beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= forward_ar && arready ? DATA : AR;
      end else case (state)
        IDLE: ;
        PREP: begin
          araddr_q <= cursor;
          if (cursor[BUS_SHIFT-1:0] != 0 || left_bytes < COUNT_W'(BUS_BYTES)) begin
            arsize_q <= 0; arlen_q <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= 8'(next_beats - 1'b1);
            beats_left <= next_beats; beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= AR;
        end
        AR: if (arready) state <= DATA;
        DATA: if (rvalid && rready) begin
          cursor <= cursor + 32'(beat_bytes);
          left_bytes <= left_bytes - COUNT_W'(beat_bytes);
          beats_left <= beats_left - 1'b1;
          if (left_bytes == COUNT_W'(beat_bytes)) state <= IDLE;
          else if (beats_left == 1) state <= PREP;
        end
        default: state <= IDLE;
      endcase
    end
  end
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
    if (req_valid && req_ready) assert (req_bytes != 0);
    if (rvalid && rready) assert (rlast == (beats_left == 1));
    if (arvalid) assert ({1'b0,araddr[11:0]} + (({5'b0,arlen}+1) << arsize) <= 4096);
  end
  generate if (MAX_REQUEST_BYTES < 65535) begin : g_request_bounds
    initial forever @(posedge clk) if (rst_n && req_valid && req_ready)
      assert (req_bytes<=16'(MAX_REQUEST_BYTES));
  end endgenerate
`endif
endmodule
