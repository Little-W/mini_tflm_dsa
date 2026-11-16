// SPDX-License-Identifier: Apache-2.0
// Shared input cache. Policy 3 uses convolution-window lifetime and geometric
// lookahead; policies 0-2 provide fixed-capacity replacement comparisons.
module conv_read_cache #(
  parameter int SETS=128,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter int DEMAND_DEPTH=4,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI
) (
  input logic clk, rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_base, cfg_bytes,
  input logic cfg_bypass,
  input logic cfg_geometry = 1'b0,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_addr,
  input logic req_geometry = 1'b0,
  input logic req_event_first = 1'b0,
  input logic hint_valid = 1'b0,
  input logic [31:0] hint_next = 32'hffff_ffff,
  output logic hint_pending,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [31:0] rsp_data,
  output logic rsp_error,
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
  input logic cfg_windowed = 1'b0,
  input logic cfg_prefetch_enable = 1'b0,
  input logic req_window_index_valid = 1'b0,
  input logic [31:0] req_window_index = 32'd0,
  input logic [31:0] req_window_epoch = 32'd0,
  input logic [31:0] req_window_retire = 32'hffff_ffff,
  input logic [31:0] req_window_progress = 32'd0,
  input logic prefetch_valid = 1'b0,
  output logic prefetch_ready,
  input logic [31:0] prefetch_addr = 32'd0,
  input logic prefetch_window_index_valid = 1'b0,
  input logic [31:0] prefetch_window_index = 32'd0,
  input logic [31:0] prefetch_window_epoch = 32'd0,
  input logic [31:0] prefetch_window_retire = 32'hffff_ffff,
  input logic prefetch_next_fragment = 1'b0,
  output logic [31:0] stat_hits, stat_misses, stat_read_bytes,
  output logic [31:0] stat_prefetch_lines, stat_prefetch_used,
  output logic [31:0] stat_prefetch_wasted, stat_prefetch_unused, stat_prefetch_bytes,
  output logic [31:0] stat_prefetch_late
);
  generate if (CACHE_POLICY==3) begin : g_window
    conv_windowed_cache #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .DEMAND_DEPTH(DEMAND_DEPTH),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_window (.*);
  end else begin : g_reference
    conv_read_cache_reference #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_reference (.*);
    assign prefetch_ready=1'b0;
    assign stat_prefetch_lines=0;
    assign stat_prefetch_used=0;
    assign stat_prefetch_wasted=0;
    assign stat_prefetch_unused=0;
    assign stat_prefetch_bytes=0;
    assign stat_prefetch_late=0;
  end endgenerate
endmodule

// SPDX-License-Identifier: Apache-2.0
// Blocking read-only cache. Policy 0: original LRU. Policy 1: geometric
// next-line-use. Policy 2: geometric next-use plus reversible XOR set indexing.
// A 16-byte transient buffer serves only the current consecutive line run.
/* verilator lint_off DECLFILENAME */
module conv_read_cache_reference #(
  parameter int SETS=32,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=2,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI
) (
  input logic clk, rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_base, cfg_bytes,
  input logic cfg_bypass,
  input logic cfg_geometry = 1'b0,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_addr,
  input logic req_geometry = 1'b0,
  input logic req_event_first = 1'b0,
  input logic hint_valid = 1'b0,
  input logic [31:0] hint_next = 32'hffff_ffff,
  output logic hint_pending,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [31:0] rsp_data,
  output logic rsp_error,
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
  output logic [31:0] stat_hits, stat_misses, stat_read_bytes
);
  localparam logic [31:0] INF = 32'hffff_ffff;
  typedef enum logic [3:0] {UNCONFIGURED, CLEAR, IDLE, TAG_READ, TAG_EVAL,
    HINT_WAIT, FILL_REQ, FILL, COMMIT, STREAM_READ, RAM_READ, RAM_WAIT, RESP} st_t;
  st_t state;
  logic [TAGW-1:0] tags [0:WAYS-1][0:SETS-1];
  logic valids [0:WAYS-1][0:SETS-1];
  logic [31:0] next_use [0:WAYS-1][0:SETS-1];
  logic lru [0:SETS-1];
  logic [TAGW-1:0] tag_q [0:WAYS-1];
  logic valid_q [0:WAYS-1];
  logic [31:0] next_q [0:WAYS-1];
  logic lru_q;
  logic [SI-1:0] set_q, clear_set, pending_set;
  logic [WI-1:0] way_q, chosen_way, victim_way, pending_way;
  logic [31:0] base_q, end_q, addr_q, line_base;
  logic [31:0] fill_first, fill_end, fetch_base, fetch_bytes;
  logic [32:0] fetch_limit;
  logic bypass_q, geometry_q, request_geometry_q, first_q, allocation_q;
  logic hint_seen;
  logic [31:0] hint_q;
  logic effective_hint_valid;
  logic [31:0] effective_hint, farthest;
  logic [TAGW-1:0] wanted_tag;
  logic hit, has_invalid, fill_error;
  logic transient_valid;
  logic [27:0] transient_tag;
  logic [31:0] transient_words [4];
  logic ram_ren, ram_wen;
  logic [DA-1:0] ram_raddr, ram_waddr;
  logic [31:0] ram_rdata;
  logic span_req_valid, span_req_ready;
  logic span_rsp_valid, span_rsp_ready, span_last, span_error;
  logic [31:0] span_addr;
  logic [BUS_WIDTH-1:0] span_data;
  logic [BUS_WIDTH/8-1:0] span_strb;
  logic span_busy;

  function automatic logic [SI-1:0] address_set(input logic [31:0] address,
                                                input logic geometric);
    logic [SI-1:0] raw_set;
    raw_set = SI'(address >> LB);
    return raw_set ^ ((geometric && CACHE_POLICY==2) ? SI'(address >> (LB+SI)) : SI'(0));
  endfunction
  assign cfg_ready = state==UNCONFIGURED || (state==IDLE && !hint_pending);
  assign req_ready = state==IDLE && !cfg_valid &&
    !(hint_pending && (req_event_first || req_addr[31:LB]!=addr_q[31:LB]));
  assign rsp_valid = state==RESP;
  assign wanted_tag = addr_q[31:LB+SI];
  assign line_base = {addr_q[31:LB],{LB{1'b0}}};
  assign fetch_base = bypass_q ? {addr_q[31:2],2'b0} : line_base;
  assign fetch_bytes = bypass_q ? 32'd4 : 32'(LINE_BYTES);
  assign fill_first = fetch_base<base_q ? base_q : fetch_base;
  assign fetch_limit = {1'b0,fetch_base}+{1'b0,fetch_bytes};
  assign fill_end = fetch_limit>{1'b0,end_q} ? end_q : fetch_limit[31:0];
  assign effective_hint_valid = hint_seen || hint_valid;
  assign effective_hint = hint_seen ? hint_q : hint_next;

  always_comb begin
    hit=0; has_invalid=0;
    chosen_way = WAYS==1 ? WI'(0) : WI'(lru_q);
    victim_way=0; farthest=next_q[0];
    for (int w=1; w<WAYS; w++)
      if (next_q[w]>farthest) begin farthest=next_q[w];victim_way=WI'(w);end
    if (request_geometry_q) chosen_way=victim_way;
    for (int w=WAYS-1; w>=0; w--)
      if (!valid_q[w]) begin chosen_way=WI'(w);has_invalid=1;end
    for (int w=0; w<WAYS; w++)
      if (valid_q[w] && tag_q[w]==wanted_tag) begin hit=1;chosen_way=WI'(w);end
  end
  assign ram_ren = state==RAM_READ;
  assign ram_raddr = DA'((32'(way_q)*SETS+32'(set_q))*(LINE_BYTES/4)
                         +((addr_q>>2)&(LINE_BYTES/4-1)));
  // Non-admitted misses MUST NOT overwrite a valid main-cache data line.
  assign ram_wen = state==FILL && span_rsp_valid && span_rsp_ready && allocation_q;
  assign ram_waddr = DA'((32'(way_q)*SETS+32'(set_q))*(LINE_BYTES/4)
                         +((span_addr>>2)&(LINE_BYTES/4-1)));
  conv_sdp_ram #(.DEPTH(DEPTH),.AW(DA),.WRITE_WIDTH(BUS_WIDTH)) u_data (
    .clk,.rd_en(ram_ren),.rd_addr(ram_raddr),.rd_data(ram_rdata),
    .wr_en(ram_wen),.wr_addr(ram_waddr),.wr_data(span_data),.wr_strb(span_strb)
  );
  assign span_req_valid = state==FILL_REQ;
  assign span_rsp_ready = state==FILL;
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_span (
    .clk,.rst_n,.req_valid(span_req_valid),.req_ready(span_req_ready),
    .req_addr(fill_first),.req_bytes(16'(fill_end-fill_first)),
    .rsp_valid(span_rsp_valid),.rsp_ready(span_rsp_ready),
    .rsp_word_addr(span_addr),.rsp_data(span_data),.rsp_strb(span_strb),
    .rsp_last(span_last),.rsp_error(span_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,.busy(span_busy)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=UNCONFIGURED;base_q<=0;end_q<=0;addr_q<=0;
      clear_set<=0;set_q<=0;way_q<=0;lru_q<=0;bypass_q<=0;geometry_q<=0;
      request_geometry_q<=0;first_q<=0;allocation_q<=0;fill_error<=0;
      hint_seen<=0;hint_q<=INF;hint_pending<=0;pending_set<=0;pending_way<=0;
      transient_valid<=0;transient_tag<=0;
      for (int i=0;i<4;i++) transient_words[i]<=0;
      rsp_data<=0;rsp_error<=0;stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;
    end else begin
      if (hint_pending && hint_valid) begin
        next_use[pending_way][pending_set]<=hint_next;
        hint_pending<=0;
      end
      if (state!=IDLE && request_geometry_q && hint_valid && !hint_seen) begin
        hint_seen<=1;hint_q<=hint_next;
      end
      if (cfg_valid && cfg_ready) begin
        base_q<=cfg_base;end_q<=cfg_base+cfg_bytes;bypass_q<=cfg_bypass;
        geometry_q<=cfg_geometry && !cfg_bypass && CACHE_POLICY!=0 && LINE_BYTES==16;
        clear_set<=0;state<=CLEAR;hint_pending<=0;transient_valid<=0;
        stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;rsp_error<=0;
      end else case (state)
        UNCONFIGURED: ;
        CLEAR: begin
          for (int w=0;w<WAYS;w++) valids[w][clear_set]<=0;
          lru[clear_set]<=0;
          if (clear_set==SI'(SETS-1)) state<=IDLE;
          else clear_set<=clear_set+1'b1;
        end
        IDLE: if (req_valid && req_ready) begin
          addr_q<=req_addr;set_q<=address_set(req_addr,geometry_q);
          request_geometry_q<=geometry_q && req_geometry;
          first_q<=req_event_first;hint_seen<=hint_valid;hint_q<=hint_next;
          rsp_error<=0;
          // Even a main-cache HIT on another line ends the transient lifetime.
          if (transient_valid && transient_tag!=req_addr[31:4]) transient_valid<=0;
          if (req_addr<base_q || req_addr>=end_q) begin
            rsp_data<=0;rsp_error<=1;state<=RESP;
          end else if (bypass_q) begin
            way_q<=0;allocation_q<=1;fill_error<=0;
            stat_misses<=stat_misses+1;state<=FILL_REQ;
          end else if (geometry_q && req_geometry && transient_valid && transient_tag==req_addr[31:4]) begin
            rsp_data<=transient_words[req_addr[3:2]];
            stat_hits<=stat_hits+1;state<=RESP;
          end else state<=TAG_READ;
        end
        TAG_READ: begin
          for (int w=0;w<WAYS;w++) begin
            tag_q[w]<=tags[w][set_q];valid_q[w]<=valids[w][set_q];
            next_q[w]<=next_use[w][set_q];
          end
          lru_q<=lru[set_q];state<=TAG_EVAL;
        end
        TAG_EVAL, HINT_WAIT: begin
          way_q<=chosen_way;
          if (hit) begin
            stat_hits<=stat_hits+1;
            if (WAYS==2) lru[set_q]<=!chosen_way[0];
            if (request_geometry_q && first_q) begin
              if (effective_hint_valid) next_use[chosen_way][set_q]<=effective_hint;
              else begin hint_pending<=1;pending_way<=chosen_way;pending_set<=set_q;end
            end
            state<=RAM_READ;
          end else if (request_geometry_q && !has_invalid && !effective_hint_valid) begin
            state<=HINT_WAIT;
          end else begin
            stat_misses<=stat_misses+1;fill_error<=0;
            transient_valid<=0;
            if (request_geometry_q) begin
              for (int i=0;i<4;i++) transient_words[i]<=0;
            end
            if (request_geometry_q && effective_hint_valid &&
                (effective_hint==INF || (!has_invalid && effective_hint>=farthest))) begin
              allocation_q<=0;
            end else begin
              allocation_q<=1;valids[chosen_way][set_q]<=0;
            end
            state<=FILL_REQ;
          end
        end
        FILL_REQ: if (span_req_ready) state<=FILL;
        FILL: if (span_rsp_valid && span_rsp_ready) begin
          stat_read_bytes<=stat_read_bytes+32'($countones(span_strb));
          fill_error<=fill_error || span_error;
          if (request_geometry_q)
            for (int b=0;b<BUS_WIDTH/8;b++)
              if (span_strb[b]) transient_words[(int'(span_addr[3:0])+b)/4][8*(b%4)+:8]<=span_data[8*b+:8];
          if (span_last) begin
            if (fill_error || span_error) begin
              rsp_error<=1;rsp_data<=0;transient_valid<=0;state<=RESP;
            end else if (request_geometry_q) begin
              state<=COMMIT;
            end else begin
              if (!bypass_q) begin
                tags[way_q][set_q]<=wanted_tag;valids[way_q][set_q]<=1;
                next_use[way_q][set_q]<=INF;
                if (WAYS==2) lru[set_q]<=!way_q[0];
              end
              state<=RAM_READ;
            end
          end
        end
        COMMIT: if (effective_hint_valid) begin
          if (allocation_q && effective_hint!=INF) begin
            tags[way_q][set_q]<=wanted_tag;valids[way_q][set_q]<=1;
            next_use[way_q][set_q]<=effective_hint;
            if (WAYS==2) lru[set_q]<=!way_q[0];
            state<=RAM_READ;
          end else begin
            transient_valid<=1;transient_tag<=addr_q[31:4];state<=STREAM_READ;
          end
        end
        STREAM_READ: begin rsp_data<=transient_words[addr_q[3:2]];rsp_error<=0;state<=RESP;end
        RAM_READ: state<=RAM_WAIT;
        RAM_WAIT: begin rsp_data<=ram_rdata;rsp_error<=0;state<=RESP;end
        RESP: if (rsp_ready) state<=IDLE;
        default: state<=UNCONFIGURED;
      endcase
    end
  end
`ifndef SYNTHESIS
  initial begin
    if (SETS<2 || (SETS&(SETS-1))!=0) $fatal(1,"SETS must be a power of two >=2");
    if (WAYS!=1 && WAYS!=2) $fatal(1,"WAYS must be 1 or 2");
    if (LINE_BYTES<8 || LINE_BYTES>256 || (LINE_BYTES&(LINE_BYTES-1))!=0)
      $fatal(1,"LINE_BYTES must be a power of two in [8,256]");
    if (CACHE_POLICY<0 || CACHE_POLICY>2) $fatal(1,"CACHE_POLICY must be 0, 1, or 2");
  end
`endif
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (cfg_valid && cfg_ready) begin
      assert (cfg_bytes!=0);
      assert ({1'b0,cfg_base}+{1'b0,cfg_bytes}<33'h1_0000_0000);
    end
    if (state==FILL_REQ) assert (!span_busy);
    if (state==FILL) assert (span_busy);
    if (ram_wen) assert (span_addr[31:LB]==addr_q[31:LB]);
    if (state==FILL && !allocation_q) assert (!ram_wen);
    if (hint_pending) assert (geometry_q);
  end
`endif
endmodule

module conv_windowed_cache #(
  parameter int SETS=32,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter int DEMAND_DEPTH=4,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI
) (
  input logic clk, rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input logic [31:0] cfg_base, cfg_bytes,
  input logic cfg_bypass,
  input logic cfg_geometry = 1'b0,
  input logic req_valid,
  output logic req_ready,
  input logic [31:0] req_addr,
  input logic req_geometry = 1'b0,
  input logic req_event_first = 1'b0,
  input logic hint_valid = 1'b0,
  input logic [31:0] hint_next = 32'hffff_ffff,
  output logic hint_pending,
  output logic rsp_valid,
  input logic rsp_ready,
  output logic [31:0] rsp_data,
  output logic rsp_error,
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
  input logic cfg_windowed = 1'b0,
  input logic cfg_prefetch_enable = 1'b0,
  input logic req_window_index_valid = 1'b0,
  input logic [31:0] req_window_index = 32'd0,
  input logic [31:0] req_window_epoch = 32'd0,
  input logic [31:0] req_window_retire = 32'hffff_ffff,
  input logic [31:0] req_window_progress = 32'd0,
  input logic prefetch_valid = 1'b0,
  output logic prefetch_ready,
  input logic [31:0] prefetch_addr = 32'd0,
  input logic prefetch_window_index_valid = 1'b0,
  input logic [31:0] prefetch_window_index = 32'd0,
  input logic [31:0] prefetch_window_epoch = 32'd0,
  input logic [31:0] prefetch_window_retire = 32'hffff_ffff,
  input logic prefetch_next_fragment = 1'b0,
  output logic [31:0] stat_hits, stat_misses, stat_read_bytes,
  output logic [31:0] stat_prefetch_lines, stat_prefetch_used,
  output logic [31:0] stat_prefetch_wasted, stat_prefetch_unused, stat_prefetch_bytes,
  output logic [31:0] stat_prefetch_late
);
  localparam logic [31:0] INF=32'hffff_ffff;
  localparam int EPOCH_W=17-LB;
  typedef enum logic [1:0] {FG_IDLE, FG_MISS, FG_RESP} fg_state_t;
  typedef enum logic [1:0] {F_IDLE, F_REQ, F_DATA} fill_state_t;
  fg_state_t fg_state;
  fill_state_t fill_state;
  logic configured, clearing;
  logic [SI-1:0] clear_set;
  logic [31:0] base_q, end_q;
  logic bypass_q, windowed_q, prefetch_q;
  logic [31:LB] tags [WAYS][SETS];
  logic valid [WAYS][SETS], prefetched [WAYS][SETS];
  logic [EPOCH_W-1:0] epochs [WAYS][SETS];
  logic [31:0] use_rank [WAYS][SETS];
  logic [31:0] demand_addr, demand_index, demand_epoch, demand_retire, demand_progress;
  logic demand_index_valid, response_error;
  logic demand_filled;
  logic [SI-1:0] demand_fill_set;
  logic [WI-1:0] demand_fill_way;
  logic [31:0] lookup_addr, lookup_index, lookup_epoch, lookup_retire, lookup_progress;
  logic lookup_index_valid;
  logic [SI-1:0] lookup_set;
  logic lookup_hit;
  logic [WI-1:0] lookup_way;
  logic req_fire, lookup_range;
  logic pf_pending;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [SI-1:0] pf_set;
  logic pf_hit, pf_in_flight;
  localparam int PF_DEPTH=8;
  localparam int PF_AW=$clog2(PF_DEPTH), PF_CW=PF_AW+1;
  logic [PF_AW-1:0] pf_head, pf_tail;
  logic [PF_AW-1:0] pf_pick;
  logic pf_pick_current;
  logic [PF_CW-1:0] pf_count;
  logic [31:0] pf_queue_addr[PF_DEPTH], pf_queue_index[PF_DEPTH];
  logic [31:0] pf_queue_epoch[PF_DEPTH], pf_queue_retire[PF_DEPTH];
  logic pf_queue_index_valid[PF_DEPTH];
  logic pf_push, pf_pop, pf_duplicate;
  logic [SI-1:0] pf_incoming_set;
  logic [31:0] pf_offer_addr, pf_offer_index, pf_offer_epoch, pf_offer_retire;
  logic pf_offer_index_valid;
  logic [31:0] fill_addr, fill_first, fill_end, fill_epoch, fill_retire, fill_rank;
  logic [SI-1:0] fill_set;
  logic [WI-1:0] fill_way;
  logic fill_prefetch, fill_bad, fill_consumed;
  logic [31:0] select_addr, select_epoch, select_retire, select_rank;
  logic [SI-1:0] select_set;
  logic [WI-1:0] select_way;
  logic select_prefetch, select_launch, select_found, select_expired;
  logic [31:0] select_progress, farthest;
  logic [32:0] select_end_wide;
  logic [31:0] select_line_base, select_first, select_end;
  logic ram_ren, ram_wen;
  logic [DA-1:0] ram_raddr, ram_waddr;
  logic [31:0] ram_rdata;
  logic span_req_ready, span_rsp_valid, span_rsp_ready, span_last, span_error, span_busy;
  logic [31:0] span_addr;
  logic [BUS_WIDTH-1:0] span_data;
  logic [BUS_WIDTH/8-1:0] span_strb;
  logic fill_complete, fill_success, completing_demand;
  logic hint_pending_q;
  logic [31:LB] hint_tag;
  logic [SI-1:0] hint_set;
  logic [31:0] evicted_prefetch;
  logic [31:0] resident_prefetch;
  localparam int DQ_AW=DEMAND_DEPTH<=1 ? 1 : $clog2(DEMAND_DEPTH);
  localparam int DQ_CW=$clog2(DEMAND_DEPTH+1);
  typedef struct packed {
    logic [31:0] address, index, epoch, retire, progress;
    logic index_valid, geometry, event_first;
  } demand_t;
  demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request;
  logic [31:0] response_queue_data[DEMAND_DEPTH];
  logic response_queue_error[DEMAND_DEPTH];
  logic [DQ_AW-1:0] request_head, request_tail, response_head, response_tail;
  logic [DQ_CW-1:0] request_count, response_count, outstanding_count;
  logic accepted_request, consumed_response, request_push, request_pop;
  logic response_push, response_pop, work_valid, work_ready;
  logic core_rsp_valid, core_rsp_ready;
  logic [31:0] core_rsp_data;
  logic [SI-1:0] accepted_set;
  logic accepted_hit, accepted_range;
  // Acceptance counts remain comparable when a queued miss later becomes a
  // hit. Lookup counts separately describe the requests when they execute.
  logic [31:0] stat_peak_outstanding, stat_lookup_hits, stat_lookup_misses;

  function automatic logic [SI-1:0] cache_set(input logic [31:0] address,
      input logic indexed, input logic [31:0] index);
    if (indexed) return SI'(index);
    return SI'(address>>LB) ^ SI'(address>>(LB+SI));
  endfunction

  assign cfg_ready=fill_state==F_IDLE && fg_state==FG_IDLE && !clearing && !pf_pending &&
                   outstanding_count==0 && request_count==0 && response_count==0;
  assign req_ready=configured && !clearing && !cfg_valid &&
                   (outstanding_count<DQ_CW'(DEMAND_DEPTH) || consumed_response) &&
                   (windowed_q || outstanding_count==0 || consumed_response);
  assign accepted_request=req_valid && req_ready;
  assign consumed_response=rsp_valid && rsp_ready;
  assign incoming_request={req_addr,req_window_index,req_window_epoch,
                           req_window_retire,req_window_progress,
                           req_window_index_valid,req_geometry,req_event_first};
  assign work_request=request_count!=0 ? request_queue[request_head] : incoming_request;
  assign work_valid=request_count!=0 || accepted_request;
  assign work_ready=configured && !clearing &&
                    (fg_state==FG_IDLE || (fg_state==FG_RESP && core_rsp_ready));
  assign req_fire=work_valid && work_ready;
  assign request_push=accepted_request && (request_count!=0 || !work_ready);
  assign request_pop=request_count!=0 && req_fire;
  assign core_rsp_valid=fg_state==FG_RESP;
  assign core_rsp_data=response_error ? 32'd0 : ram_rdata;
  assign core_rsp_ready=response_count<DQ_CW'(DEMAND_DEPTH) ||
                        (response_count!=0 && rsp_ready);
  assign rsp_valid=response_count!=0 || core_rsp_valid;
  assign rsp_data=response_count!=0 ? response_queue_data[response_head] : core_rsp_data;
  assign rsp_error=response_count!=0 ? response_queue_error[response_head] : response_error;
  assign response_push=core_rsp_valid && core_rsp_ready && (response_count!=0 || !rsp_ready);
  assign response_pop=response_count!=0 && rsp_ready;
  assign hint_pending=hint_pending_q;
  assign pf_pending=pf_count!=0;
  assign pf_addr=pf_queue_addr[pf_pick];
  assign pf_index=pf_queue_index[pf_pick];
  assign pf_epoch=pf_queue_epoch[pf_pick];
  assign pf_retire=pf_queue_retire[pf_pick];
  assign pf_index_valid=pf_queue_index_valid[pf_pick];
  assign prefetch_ready=configured && prefetch_q && !bypass_q && !clearing &&
                         !cfg_valid && (pf_count<PF_CW'(PF_DEPTH) || pf_pop || pf_duplicate);
  assign pf_push=prefetch_valid && prefetch_ready && !pf_duplicate &&
                 pf_offer_addr>=base_q && pf_offer_addr<end_q;
  assign pf_pop=pf_pending && (pf_hit || pf_in_flight || pf_addr<base_q || pf_addr>=end_q ||
                              (select_launch && select_prefetch));
  assign fill_complete=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  assign fill_success=fill_complete && !fill_bad && !span_error;
  assign completing_demand=fill_success && fg_state==FG_MISS &&
    demand_addr[31:LB]==fill_addr[31:LB] && (bypass_q || lookup_set==fill_set);

  // Current-fragment lookahead has priority over the following fragment.
  // The head entry fills any selected interior slot when that slot retires.
  always_comb begin
    pf_pick=pf_head;pf_pick_current=0;
    for (int i=0;i<PF_DEPTH;i++)
      if (PF_CW'(i)<pf_count && !pf_pick_current &&
          pf_queue_epoch[PF_AW'(pf_head+PF_AW'(i))]==demand_epoch) begin
        pf_pick=PF_AW'(pf_head+PF_AW'(i));pf_pick_current=1;
      end
  end

  always_comb begin
    accepted_set=cache_set(req_addr,windowed_q && req_window_index_valid,req_window_index);
    accepted_range=req_addr>=base_q && req_addr<end_q;
    accepted_hit=0;
    for (int w=0;w<WAYS;w++)
      if (!bypass_q && valid[w][accepted_set] && tags[w][accepted_set]==req_addr[31:LB])
        accepted_hit=1;
    lookup_addr=fg_state==FG_MISS ? demand_addr : work_request.address;
    lookup_index=fg_state==FG_MISS ? demand_index : work_request.index;
    lookup_index_valid=fg_state==FG_MISS ? demand_index_valid : work_request.index_valid;
    lookup_epoch=fg_state==FG_MISS ? demand_epoch : work_request.epoch;
    lookup_retire=fg_state==FG_MISS ? demand_retire : work_request.retire;
    lookup_progress=fg_state==FG_MISS ? demand_progress : work_request.progress;
    lookup_set=cache_set(lookup_addr,windowed_q && lookup_index_valid,lookup_index);
    lookup_range=lookup_addr>=base_q && lookup_addr<end_q;
    lookup_hit=0;lookup_way=0;
    for (int w=0;w<WAYS;w++)
      if (valid[w][lookup_set] && tags[w][lookup_set]==lookup_addr[31:LB]) begin
        lookup_hit=1;lookup_way=WI'(w);
      end
    if (bypass_q) begin lookup_hit=demand_filled && fg_state==FG_MISS;
      lookup_set=demand_fill_set;lookup_way=demand_fill_way;end
    pf_set=cache_set(pf_addr,windowed_q && pf_index_valid,pf_index);
    pf_hit=0;
    for (int w=0;w<WAYS;w++)
      if (valid[w][pf_set] && tags[w][pf_set]==pf_addr[31:LB]) pf_hit=1;
    pf_in_flight=fill_state!=F_IDLE && fill_addr[31:LB]==pf_addr[31:LB];
    pf_incoming_set=cache_set(prefetch_addr,windowed_q && prefetch_window_index_valid,prefetch_window_index);
    pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==prefetch_addr[31:LB];
    for (int w=0;w<WAYS;w++)
      if (valid[w][pf_incoming_set] && tags[w][pf_incoming_set]==prefetch_addr[31:LB]) pf_duplicate=1;
    for (int i=0;i<PF_DEPTH;i++)
      if (PF_CW'(i)<pf_count && pf_queue_addr[PF_AW'(pf_head+PF_AW'(i))][31:LB]==prefetch_addr[31:LB]) pf_duplicate=1;
    pf_offer_addr=prefetch_addr;pf_offer_epoch=prefetch_window_epoch;pf_offer_retire=prefetch_window_retire;
    pf_offer_index=prefetch_window_index;pf_offer_index_valid=prefetch_window_index_valid;
    if (pf_duplicate && prefetch_next_fragment) begin
      pf_offer_addr=req_addr+32'(LINE_BYTES);
      pf_offer_epoch=req_window_epoch+1;pf_offer_retire=INF;
      pf_offer_index=req_window_index;pf_offer_index_valid=req_window_index_valid;
      pf_incoming_set=cache_set(pf_offer_addr,windowed_q && pf_offer_index_valid,pf_offer_index);
      pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==pf_offer_addr[31:LB];
      for (int w=0;w<WAYS;w++)
        if (valid[w][pf_incoming_set] && tags[w][pf_incoming_set]==pf_offer_addr[31:LB]) pf_duplicate=1;
      for (int i=0;i<PF_DEPTH;i++)
        if (PF_CW'(i)<pf_count && pf_queue_addr[PF_AW'(pf_head+PF_AW'(i))][31:LB]==pf_offer_addr[31:LB]) pf_duplicate=1;
    end

    select_prefetch=0;select_launch=0;
    select_addr=demand_addr;select_set=lookup_set;
    select_epoch=demand_epoch;select_retire=demand_retire;select_progress=demand_progress;
    select_rank=(hint_pending_q && hint_tag==demand_addr[31:LB] && hint_valid) ? hint_next : INF;
    if (configured && !clearing && !(cfg_valid && cfg_ready) &&
        (fill_state==F_IDLE || fill_success)) begin
      if (fg_state==FG_MISS && !lookup_hit && lookup_range && !completing_demand) select_launch=1;
      else if (pf_pending && !pf_hit && !pf_in_flight && !(req_fire && !lookup_hit) &&
               pf_addr>=base_q && pf_addr<end_q) begin
        select_launch=1;select_prefetch=1;
        select_addr=pf_addr;select_set=pf_set;select_epoch=pf_epoch;
        select_retire=pf_retire;select_progress=demand_progress;select_rank=INF;
      end
    end
    select_way=0;select_found=0;select_expired=0;farthest=use_rank[0][select_set];
    for (int w=1;w<WAYS;w++)
      if (use_rank[w][select_set]>=farthest) begin
        farthest=use_rank[w][select_set];select_way=WI'(w);
      end
    if (windowed_q)
      for (int w=WAYS-1;w>=0;w--)
        if (valid[w][select_set] &&
            ((epochs[w][select_set]!=EPOCH_W'(select_epoch) &&
              (!select_prefetch || epochs[w][select_set]!=EPOCH_W'(demand_epoch))) ||
             (epochs[w][select_set]==EPOCH_W'(select_epoch) && use_rank[w][select_set]<select_progress))) begin
          select_way=WI'(w);select_expired=1;
        end
    for (int w=WAYS-1;w>=0;w--)
      if (!valid[w][select_set]) begin select_way=WI'(w);select_found=1;end
    if (select_launch && ((req_fire && lookup_hit) || (fg_state==FG_MISS && lookup_hit)) &&
        select_set==lookup_set && select_way==lookup_way) select_launch=0;
    // The completing line becomes visible to demand lookup on the next cycle.
    if (select_launch && fill_complete && select_set==fill_set && select_way==fill_way)
      select_launch=0;
    // A pending miss is served before lookahead can claim another data line.
    select_line_base=bypass_q ? {select_addr[31:2],2'b0} : {select_addr[31:LB],{LB{1'b0}}};
    select_first=select_line_base<base_q ? base_q : select_line_base;
    select_end_wide={1'b0,select_line_base}+33'(bypass_q ? 4 : LINE_BYTES);
    select_end=select_end_wide>{1'b0,end_q} ? end_q : select_end_wide[31:0];
    ram_ren=(req_fire && lookup_range && lookup_hit) ||
            (fg_state==FG_MISS && lookup_hit);
    ram_raddr=DA'((32'(lookup_way)*SETS+32'(lookup_set))*(LINE_BYTES/4)+
                  ((lookup_addr>>2)&(LINE_BYTES/4-1)));
    resident_prefetch=0;
    for (int w=0;w<WAYS;w++)
      for (int s=0;s<SETS;s++)
        if (valid[w][s] && prefetched[w][s]) resident_prefetch=resident_prefetch+1;
  end
  assign stat_prefetch_wasted=evicted_prefetch;
  assign stat_prefetch_unused=resident_prefetch;
  assign ram_wen=fill_state==F_DATA && span_rsp_valid && span_rsp_ready;
  assign ram_waddr=DA'((32'(fill_way)*SETS+32'(fill_set))*(LINE_BYTES/4)+
                      ((span_addr>>2)&(LINE_BYTES/4-1)));
  conv_sdp_ram #(.DEPTH(DEPTH),.AW(DA),.WRITE_WIDTH(BUS_WIDTH)) u_data(
    .clk,.rd_en(ram_ren),.rd_addr(ram_raddr),.rd_data(ram_rdata),
    .wr_en(ram_wen),.wr_addr(ram_waddr),.wr_data(span_data),.wr_strb(span_strb));
  assign span_rsp_ready=fill_state==F_DATA;
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_span(
    .clk,.rst_n,.req_valid(fill_state==F_REQ || select_launch),.req_ready(span_req_ready),
    .req_addr(select_launch ? select_first : fill_first),
    .req_bytes(16'(select_launch ? select_end-select_first : fill_end-fill_first)),
    .rsp_valid(span_rsp_valid),.rsp_ready(span_rsp_ready),
    .rsp_word_addr(span_addr),.rsp_data(span_data),.rsp_strb(span_strb),
    .rsp_last(span_last),.rsp_error(span_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,.busy(span_busy));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      request_head<=0;request_tail<=0;request_count<=0;
      response_head<=0;response_tail<=0;response_count<=0;outstanding_count<=0;
      stat_peak_outstanding<=0;
    end else if (cfg_valid && cfg_ready) begin
      request_head<=0;request_tail<=0;request_count<=0;
      response_head<=0;response_tail<=0;response_count<=0;outstanding_count<=0;
      stat_peak_outstanding<=0;
    end else begin
      case ({accepted_request,consumed_response})
        2'b10: begin
          outstanding_count<=outstanding_count+1'b1;
          if (32'(outstanding_count)+1>stat_peak_outstanding)
            stat_peak_outstanding<=32'(outstanding_count)+1;
        end
        2'b01: outstanding_count<=outstanding_count-1'b1;
        default: ;
      endcase
      case ({request_push,request_pop})
        2'b10: request_count<=request_count+1'b1;
        2'b01: request_count<=request_count-1'b1;
        default: ;
      endcase
      if (request_push) begin
        request_queue[request_tail]<=incoming_request;
        request_tail<=DEMAND_DEPTH==1 ? DQ_AW'(0) : request_tail+1'b1;
      end
      if (request_pop) request_head<=DEMAND_DEPTH==1 ? DQ_AW'(0) : request_head+1'b1;
      case ({response_push,response_pop})
        2'b10: response_count<=response_count+1'b1;
        2'b01: response_count<=response_count-1'b1;
        default: ;
      endcase
      if (response_push) begin
        response_queue_data[response_tail]<=core_rsp_data;
        response_queue_error[response_tail]<=response_error;
        response_tail<=DEMAND_DEPTH==1 ? DQ_AW'(0) : response_tail+1'b1;
      end
      if (response_pop) response_head<=DEMAND_DEPTH==1 ? DQ_AW'(0) : response_head+1'b1;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fg_state<=FG_IDLE;fill_state<=F_IDLE;configured<=0;clearing<=0;clear_set<=0;
      base_q<=0;end_q<=0;bypass_q<=0;windowed_q<=0;prefetch_q<=0;
      demand_addr<=0;demand_index<=0;demand_epoch<=0;demand_retire<=INF;demand_progress<=0;
      demand_index_valid<=0;demand_filled<=0;demand_fill_set<=0;demand_fill_way<=0;
      response_error<=0;pf_head<=0;pf_tail<=0;pf_count<=0;
      for (int i=0;i<PF_DEPTH;i++) begin
        pf_queue_addr[i]<=0;pf_queue_index[i]<=0;pf_queue_epoch[i]<=0;
        pf_queue_retire[i]<=INF;pf_queue_index_valid[i]<=0;
      end
      fill_addr<=0;fill_first<=0;fill_end<=0;fill_epoch<=0;fill_retire<=INF;fill_rank<=INF;
      fill_set<=0;fill_way<=0;fill_prefetch<=0;fill_bad<=0;fill_consumed<=0;
      hint_pending_q<=0;hint_tag<=0;hint_set<=0;
      stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;stat_lookup_hits<=0;stat_lookup_misses<=0;
      stat_prefetch_lines<=0;stat_prefetch_used<=0;stat_prefetch_bytes<=0;stat_prefetch_late<=0;
      evicted_prefetch<=0;
      for (int w=0;w<WAYS;w++) for (int s=0;s<SETS;s++) begin
        valid[w][s]<=0;prefetched[w][s]<=0;tags[w][s]<=0;
        epochs[w][s]<=0;use_rank[w][s]<=INF;
      end
    end else begin
      if (cfg_valid && cfg_ready) begin
        configured<=1;clearing<=1;clear_set<=0;fg_state<=FG_IDLE;
        base_q<=cfg_base;end_q<=cfg_base+cfg_bytes;bypass_q<=cfg_bypass;
        windowed_q<=cfg_windowed;prefetch_q<=cfg_prefetch_enable;
        pf_head<=0;pf_tail<=0;pf_count<=0;hint_pending_q<=0;demand_filled<=0;
        stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;stat_lookup_hits<=0;stat_lookup_misses<=0;
        stat_prefetch_lines<=0;stat_prefetch_used<=0;stat_prefetch_bytes<=0;stat_prefetch_late<=0;
        evicted_prefetch<=0;
      end else begin
        if (clearing) begin
          for (int w=0;w<WAYS;w++) begin
            valid[w][clear_set]<=0;prefetched[w][clear_set]<=0;
          end
          if (clear_set==SI'(SETS-1)) clearing<=0;
          else clear_set<=clear_set+1'b1;
        end
        if (fg_state==FG_RESP && core_rsp_ready) fg_state<=FG_IDLE;
        if (accepted_request && accepted_range) begin
          if (accepted_hit) stat_hits<=stat_hits+1;
          else begin
            stat_misses<=stat_misses+1;
            if (fill_state!=F_IDLE && fill_prefetch && fill_addr[31:LB]==req_addr[31:LB])
              stat_prefetch_late<=stat_prefetch_late+1;
          end
        end
        if (req_fire) begin
          demand_addr<=work_request.address;demand_index<=work_request.index;
          demand_index_valid<=work_request.index_valid;
          demand_epoch<=work_request.epoch;demand_retire<=work_request.retire;
          demand_progress<=work_request.progress;demand_filled<=0;response_error<=0;
          if (!lookup_range) begin response_error<=1;fg_state<=FG_RESP;end
          else if (lookup_hit) begin
            stat_lookup_hits<=stat_lookup_hits+1;fg_state<=FG_RESP;
            if (prefetched[lookup_way][lookup_set]) begin
              prefetched[lookup_way][lookup_set]<=0;stat_prefetch_used<=stat_prefetch_used+1;
            end
            epochs[lookup_way][lookup_set]<=EPOCH_W'(work_request.epoch);
            if (windowed_q) use_rank[lookup_way][lookup_set]<=work_request.retire;
            else if (hint_valid) use_rank[lookup_way][lookup_set]<=hint_next;
          end else begin
            stat_lookup_misses<=stat_lookup_misses+1;fg_state<=FG_MISS;
            if (fill_state!=F_IDLE && fill_prefetch && fill_addr[31:LB]==work_request.address[31:LB]) begin
              fill_consumed<=1;
            end
          end
          if (work_request.geometry && work_request.event_first) begin
            if (hint_valid) begin
              hint_pending_q<=0;
              if (fill_state!=F_IDLE && fill_addr[31:LB]==work_request.address[31:LB]) fill_rank<=hint_next;
            end else begin hint_pending_q<=1;hint_tag<=work_request.address[31:LB];hint_set<=lookup_set;end
          end
        end
        if (fg_state==FG_MISS && lookup_hit) begin
          fg_state<=FG_RESP;response_error<=0;demand_filled<=0;
          if (prefetched[lookup_way][lookup_set]) begin
            prefetched[lookup_way][lookup_set]<=0;stat_prefetch_used<=stat_prefetch_used+1;
          end
        end
        if (hint_pending_q && hint_valid) begin
          hint_pending_q<=0;
          for (int w=0;w<WAYS;w++)
            if (!windowed_q && valid[w][hint_set] && tags[w][hint_set]==hint_tag) use_rank[w][hint_set]<=hint_next;
          if (fill_state!=F_IDLE && fill_addr[31:LB]==hint_tag) fill_rank<=hint_next;
        end
        case ({pf_push,pf_pop})
          2'b10: pf_count<=pf_count+1'b1;
          2'b01: pf_count<=pf_count-1'b1;
          default: ;
        endcase
        if (pf_push) begin
          pf_queue_addr[pf_tail]<=pf_offer_addr;pf_queue_index[pf_tail]<=pf_offer_index;
          pf_queue_index_valid[pf_tail]<=pf_offer_index_valid;
          pf_queue_epoch[pf_tail]<=pf_offer_epoch;pf_queue_retire[pf_tail]<=pf_offer_retire;
          pf_tail<=pf_tail+1'b1;
        end
        if (pf_pop) begin
          if (pf_pick!=pf_head) begin
            pf_queue_addr[pf_pick]<=pf_queue_addr[pf_head];pf_queue_index[pf_pick]<=pf_queue_index[pf_head];
            pf_queue_index_valid[pf_pick]<=pf_queue_index_valid[pf_head];
            pf_queue_epoch[pf_pick]<=pf_queue_epoch[pf_head];pf_queue_retire[pf_pick]<=pf_queue_retire[pf_head];
          end
          pf_head<=pf_head+1'b1;
        end
        if (select_launch) begin
          fill_addr<=select_addr;fill_first<=select_first;fill_end<=select_end;
          fill_set<=select_set;fill_way<=select_way;fill_epoch<=select_epoch;
          fill_retire<=select_retire;fill_rank<=select_rank;
          fill_prefetch<=select_prefetch;fill_bad<=0;fill_consumed<=0;
          fill_state<=span_req_ready ? F_DATA : F_REQ;
          if (prefetched[select_way][select_set] && valid[select_way][select_set])
            evicted_prefetch<=evicted_prefetch+1;
          valid[select_way][select_set]<=0;prefetched[select_way][select_set]<=0;
        end
        if (fill_state==F_REQ && span_req_ready) fill_state<=F_DATA;
        if (fill_state==F_DATA && span_rsp_valid && span_rsp_ready) begin
          stat_read_bytes<=stat_read_bytes+32'($countones(span_strb));
          if (fill_prefetch) stat_prefetch_bytes<=stat_prefetch_bytes+32'($countones(span_strb));
          fill_bad<=fill_bad || span_error;
          if (span_last) begin
            fill_state<=select_launch ? F_DATA : F_IDLE;
            if (fill_bad || span_error) begin
              valid[fill_way][fill_set]<=0;
              if (!fill_prefetch || (fg_state==FG_MISS && demand_addr[31:LB]==fill_addr[31:LB])) begin
                response_error<=1;fg_state<=FG_RESP;
              end
            end else begin
              tags[fill_way][fill_set]<=fill_addr[31:LB];valid[fill_way][fill_set]<=!bypass_q;
              epochs[fill_way][fill_set]<=EPOCH_W'(fill_epoch);
              use_rank[fill_way][fill_set]<=windowed_q ? fill_retire : fill_rank;
              prefetched[fill_way][fill_set]<=fill_prefetch;
              if (fill_prefetch) stat_prefetch_lines<=stat_prefetch_lines+1;
              if (!fill_prefetch && bypass_q) begin
                demand_filled<=1;demand_fill_set<=fill_set;demand_fill_way<=fill_way;
              end
            end
          end
        end
      end
    end
  end
`ifndef SYNTHESIS
  initial begin
    if (SETS<2 || (SETS&(SETS-1))!=0) $fatal(1,"SETS must be a power of two >=2");
    if (WAYS!=1 && WAYS!=2) $fatal(1,"WAYS must be 1 or 2");
    if (LINE_BYTES<8 || LINE_BYTES>256 || (LINE_BYTES&(LINE_BYTES-1))!=0)
      $fatal(1,"LINE_BYTES must be a power of two in [8,256]");
    if (DEMAND_DEPTH<1 || (DEMAND_DEPTH&(DEMAND_DEPTH-1))!=0)
      $fatal(1,"DEMAND_DEPTH must be a positive power of two");
  end
`endif
`ifdef CONV_ASSERT
  always_ff @(posedge clk) if (rst_n) begin
    if (cfg_valid && cfg_ready) begin
      assert(cfg_bytes!=0);
      assert({1'b0,cfg_base}+{1'b0,cfg_bytes}<33'h1_0000_0000);
    end
    if (ram_ren) assert(lookup_range);
    assert(outstanding_count<=DQ_CW'(DEMAND_DEPTH));
    assert(request_count<=DQ_CW'(DEMAND_DEPTH));
    assert(response_count<=DQ_CW'(DEMAND_DEPTH));
    if (consumed_response) assert(outstanding_count!=0);
    if (cfg_valid && cfg_ready) assert(outstanding_count==0);
    if (ram_ren && ram_wen) assert((ram_raddr/(BUS_WIDTH/32))!=(ram_waddr/(BUS_WIDTH/32)));
    assert(pf_count<=PF_CW'(PF_DEPTH));
    if (select_launch) begin
      assert(select_first<select_end && (fill_state==F_IDLE || fill_success));
      if (fill_complete) assert(select_set!=fill_set || select_way!=fill_way);
    end
  end
`endif
endmodule

/* verilator lint_on DECLFILENAME */
