// SPDX-License-Identifier: Apache-2.0
// Read EXACTLY [req_addr, req_addr+req_bytes), never a surrounding allocation.
// 32-bit AXI4 read master, single outstanding burst, RID fixed by the integrator.
// Aligned middle: INCR bursts; unaligned prefix/suffix: byte-sized AXI reads.
// Slave MUST support ARSIZE=0 narrow reads. No unsupported unaligned full-word reads.
module conv_axi_span_reader (
  input logic clk, rst_n,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_addr,
  input logic [15:0] req_bytes,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [31:0] rsp_word_addr, rsp_data,
  output logic [3:0] rsp_strb,
  output logic rsp_last, rsp_error,
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input logic rvalid,
  output logic rready,
  input logic [31:0] rdata,
  input logic [1:0] rresp,
  input logic rlast,
  output logic busy
);
  typedef enum logic [1:0] {IDLE, PREP, AR, DATA} st_t;
  st_t state;
  logic [31:0] cursor;
  logic [16:0] left_bytes;
  logic [8:0] beats_left;
  logic [2:0] beat_bytes;
  logic [16:0] nwords, page_words, next_beats;
  always_comb begin
    nwords = left_bytes >> 2;
    page_words = (17'd4096 - {5'b0,cursor[11:0]}) >> 2;
    next_beats = nwords;
    if (next_beats > 256) next_beats = 256;
    if (next_beats > page_words) next_beats = page_words;
  end
  assign req_ready = state == IDLE;
  assign busy = state != IDLE;
  assign arvalid = state == AR;
  assign arburst = 2'b01;
  assign rsp_valid = state == DATA && rvalid;
  assign rready = state == DATA && rsp_ready;
  assign rsp_word_addr = {cursor[31:2],2'b0};
  assign rsp_data = rdata;
  assign rsp_strb = (beat_bytes == 4) ? 4'b1111 : (4'b0001 << cursor[1:0]);
  assign rsp_last = (left_bytes == 17'(beat_bytes));
  assign rsp_error = (rresp != 2'b00) || (rlast != (beats_left == 1));
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE; cursor <= 0; left_bytes <= 0; beats_left <= 0;
      beat_bytes <= 0; araddr <= 0; arlen <= 0; arsize <= 0;
    end else begin
      case (state)
        IDLE: if (req_valid && req_ready) begin
          cursor <= req_addr; left_bytes <= {1'b0,req_bytes}; state <= PREP;
        end
        PREP: begin
          araddr <= cursor;
          if (cursor[1:0] != 0 || left_bytes < 4) begin
            arsize <= 0; arlen <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize <= 2; arlen <= 8'(next_beats - 1'b1);
            beats_left <= 9'(next_beats); beat_bytes <= 4;
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
