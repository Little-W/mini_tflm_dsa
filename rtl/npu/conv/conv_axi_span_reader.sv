// SPDX-License-Identifier: Apache-2.0
// Read EXACTLY [req_addr, req_addr+req_bytes), never a surrounding allocation.
// Parameterized AXI4 read master, single outstanding burst, fixed response ID.
// Aligned middle: INCR bursts; unaligned prefix/suffix: byte-sized AXI reads.
// Slave MUST support ARSIZE=0 narrow reads. No unsupported unaligned full-word reads.
module conv_axi_span_reader #( // 读取指定的完整字节区间，将边界与中间数据分别组织为窄读取和递增突发。
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int MAX_REQUEST_BYTES=65535
) (
  input logic clk /* 模块工作时钟。 */, rst_n /* 低有效复位输入。 */,
  input logic req_valid, // 字节范围读取请求有效。
  output logic req_ready, // 能够接收新的字节范围读取请求。
  input logic [31:0] req_addr, // 所需字节范围的起始地址。
  input logic [15:0] req_bytes, // 本次需要读取的精确字节数。
  output logic rsp_valid, // 本拍范围读取结果有效。
  input logic rsp_ready, // 调用方能够接收本拍结果。
  output logic [31:0] rsp_word_addr, // 返回数据所在总线字的字节地址。
  output logic [BUS_WIDTH-1:0] rsp_data, // 当前返回的总线字数据。
  output logic [BUS_WIDTH/8-1:0] rsp_strb, // 当前总线字中属于请求范围的字节掩码。
  output logic rsp_last /* 当前结果为本次字节范围的最后一拍。 */, rsp_error /* 当前字节范围读取发生协议或地址错误。 */,
  output logic arvalid, // AXI 读取接口：读地址请求有效。
  input logic arready, // AXI 读取接口：能够接收读地址请求。
  output logic [31:0] araddr, // AXI 读取接口：读事务起始字节地址。
  output logic [7:0] arlen, // AXI 读取接口：读突发的传输拍数减一。
  output logic [2:0] arsize, // AXI 读取接口：每拍读取字节数的二进制对数。
  output logic [1:0] arburst, // AXI 读取接口：读事务的突发类型。
  input logic rvalid, // AXI 读取接口：返回的读取数据有效。
  output logic rready, // AXI 读取接口：能够接收读取响应。
  input logic [BUS_WIDTH-1:0] rdata, // AXI 读取接口：读取响应的数据。
  input logic [1:0] rresp, // AXI 读取接口：读取响应的状态编码。
  input logic rlast, // AXI 读取接口：当前读突发的最后一拍。
  output logic busy // 正在处理一个字节范围读取请求。
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
  localparam int p_page_low_width = BEAT_W + BUS_SHIFT < 12 ? BEAT_W + BUS_SHIFT : 12;
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
  logic [1:0][11:0] candidate_addr;
  logic [1:0][COUNT_W-1:0] candidate_bytes;
  logic [1:0][BEAT_W-1:0] candidate_beats;
  logic [1:0][7:0] candidate_arlen;
  logic finishing_span, forward_ar;
  logic [31:0] cursor_increment, cursor_advance;
  logic [16:0] cursor_low_sum, cursor_high_zero, cursor_high_one;
  logic [31:0] araddr_q;
  logic [7:0] arlen_q;
  logic [2:0] arsize_q;
  // 高半地址的两种进位结果并行计算，低半进位仅选择最终高半地址。
  assign cursor_increment = 32'(beat_bytes);
  assign cursor_low_sum = {1'b0, cursor[15:0]} + {1'b0, cursor_increment[15:0]};
  assign cursor_high_zero = {1'b0, cursor[31:16]} + {1'b0, cursor_increment[31:16]};
  assign cursor_high_one = {1'b0, cursor[31:16]} + {1'b0, cursor_increment[31:16]} + 17'd1;
  assign cursor_advance = {cursor_low_sum[16] ? cursor_high_one[15:0] : cursor_high_zero[15:0],
                           cursor_low_sum[15:0]};
  assign candidate_addr[0] = req_addr[11:0];
  assign candidate_addr[1] = cursor[11:0];
  assign candidate_bytes[0] = COUNT_W'(req_bytes);
  assign candidate_bytes[1] = left_bytes;
  // 新请求与当前区间分别计算页余量和突发长度，返回握手仅选择已计算的结果。
  for (genvar candidate = 0; candidate < 2; candidate++) begin : g_burst_candidate
    logic [WORD_W-1:0] nwords;
    logic [BEAT_W-1:0] burst_beats;
    logic [p_page_low_width:0] page_low_bytes;
    logic [BEAT_W:0] page_low_words;
    logic near_page_end;
    assign nwords = WORD_W'(candidate_bytes[candidate] >> BUS_SHIFT);
    // 低位减法保留扩展位，覆盖窄读取产生的非整字页余量。
    assign page_low_bytes = {1'b1, {p_page_low_width{1'b0}}} -
        {1'b0, candidate_addr[candidate][p_page_low_width-1:0]};
    assign page_low_words = (BEAT_W+1)'(page_low_bytes >> BUS_SHIFT);
    if (p_page_low_width < 12) begin : g_page_prefix
      assign near_page_end = &candidate_addr[candidate][11:p_page_low_width];
    end else begin : g_complete_page
      assign near_page_end = 1'b1;
    end
    if (BURST_LIMIT == (1<<WORD_W)-1) begin : g_full_word_range
      assign burst_beats = BEAT_W'(nwords);
    end else begin : g_limited_word_range
      assign burst_beats = nwords>WORD_W'(BURST_LIMIT) ? BEAT_W'(BURST_LIMIT) : BEAT_W'(nwords);
    end
    assign candidate_beats[candidate] = near_page_end && {1'b0, burst_beats} > page_low_words ?
        BEAT_W'(page_low_words) : burst_beats;
    logic [BEAT_W-1:0] page_word_complement;
    logic [7:0] page_arlen, burst_arlen;
    // 页末突发编码与请求突发编码并行准备，长度选择后直接保存编码。
    // 非整字起点的页余量向下取整，保留窄读取所需的边界行为。
    assign page_word_complement = BEAT_W'({~candidate_addr[candidate][p_page_low_width-1:BUS_SHIFT]});
    assign page_arlen = candidate_addr[candidate][BUS_SHIFT-1:0] == 0 ?
        8'(page_word_complement) : 8'((BEAT_W+1)'(page_word_complement) - 1'b1);
    assign burst_arlen = 8'(burst_beats - 1'b1);
    always_comb begin
      candidate_arlen[candidate] = near_page_end && {1'b0, burst_beats} > page_low_words ?
          page_arlen : burst_arlen;
`ifndef SYNTHESIS
      if ((^{candidate_addr[candidate], candidate_bytes[candidate]}) === 1'bx)
        candidate_arlen[candidate] = 8'(candidate_beats[candidate] - 1'b1);
`endif
    end
  end
  assign finishing_span = rsp_valid && rsp_ready && rsp_last;
  assign req_ready = state == IDLE || finishing_span;
  assign busy = state != IDLE;
  assign forward_ar = finishing_span && req_valid;
  assign arvalid = state == AR || forward_ar;
  assign araddr = forward_ar ? req_addr : araddr_q;
  assign arlen = forward_ar ?
    ((req_addr[BUS_SHIFT-1:0] != 0 || req_bytes < 16'(BUS_BYTES)) ? 8'd0 : candidate_arlen[0]) : arlen_q;
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
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= candidate_arlen[0];
            beats_left <= candidate_beats[0]; beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= forward_ar && arready ? DATA : AR;
      end else case (state)
        IDLE: ;
        PREP: begin
          araddr_q <= cursor;
          if (cursor[BUS_SHIFT-1:0] != 0 || left_bytes < COUNT_W'(BUS_BYTES)) begin
            arsize_q <= 0; arlen_q <= 0; beats_left <= 1; beat_bytes <= 1;
          end else begin
            arsize_q <= 3'(BUS_SHIFT); arlen_q <= candidate_arlen[1];
            beats_left <= candidate_beats[1]; beat_bytes <= (BUS_SHIFT+1)'(BUS_BYTES);
          end
          state <= AR;
        end
        AR: if (arready) state <= DATA;
        DATA: if (rvalid && rready) begin
          cursor <= cursor_advance;
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
