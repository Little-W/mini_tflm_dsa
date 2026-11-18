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
  input logic prefetch_ref_valid = 1'b0,
  input logic [31:0] prefetch_ref_addr = 32'd0,
  input logic prefetch_ref_index_valid = 1'b0,
  input logic [31:0] prefetch_ref_index = 32'd0,
  input logic [31:0] prefetch_ref_epoch = 32'd0);
  generate if (CACHE_POLICY==3) begin : g_window
    conv_windowed_cache #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .DEMAND_DEPTH(DEMAND_DEPTH),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_window (.*);
  end else begin : g_reference
    conv_read_cache_reference #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_reference (.*);
    assign prefetch_ready=1'b0;
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
  input logic rlast);
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
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .MAX_REQUEST_BYTES(LINE_BYTES)) u_span (
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
      rsp_data<=0;rsp_error<=0;
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
        rsp_error<=0;
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
            state<=FILL_REQ;
          end else if (geometry_q && req_geometry && transient_valid && transient_tag==req_addr[31:4]) begin
            rsp_data<=transient_words[req_addr[3:2]];
            state<=RESP;
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

            if (WAYS==2) lru[set_q]<=!chosen_way[0];
            if (request_geometry_q && first_q) begin
              if (effective_hint_valid) next_use[chosen_way][set_q]<=effective_hint;
              else begin hint_pending<=1;pending_way<=chosen_way;pending_set<=set_q;end
            end
            state<=RAM_READ;
          end else if (request_geometry_q && !has_invalid && !effective_hint_valid) begin
            state<=HINT_WAIT;
          end else begin
            fill_error<=0;
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
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SETS<2 || (SETS&(SETS-1))!=0) $fatal(1,"SETS must be a power of two >=2");
    if (WAYS!=1 && WAYS!=2) $fatal(1,"WAYS must be 1 or 2");
    if (LINE_BYTES<8 || LINE_BYTES>256 || (LINE_BYTES&(LINE_BYTES-1))!=0)
      $fatal(1,"LINE_BYTES must be a power of two in [8,256]");
    if (CACHE_POLICY<0 || CACHE_POLICY>2) $fatal(1,"CACHE_POLICY must be 0, 1, or 2");
  end
`endif
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
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
  input logic prefetch_ref_valid = 1'b0,
  input logic [31:0] prefetch_ref_addr = 32'd0,
  input logic prefetch_ref_index_valid = 1'b0,
  input logic [31:0] prefetch_ref_index = 32'd0,
  input logic [31:0] prefetch_ref_epoch = 32'd0);
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
  logic [WAYS-1:0][31:LB] lookup_tag, pf_tag, incoming_tag, next_tag, hint_lookup_tag;
  logic valid [WAYS][SETS];
  logic [EPOCH_W-1:0] select_epochs [WAYS];
  logic [31:0] select_ranks [WAYS];
  logic [31:0] demand_addr, demand_epoch, demand_retire, demand_progress;
  logic [SI-1:0] demand_set;
  logic response_error;
  logic demand_filled;
  logic [SI-1:0] demand_fill_set;
  logic [WI-1:0] demand_fill_way;
  logic [31:0] lookup_addr, lookup_epoch, lookup_retire, lookup_progress;
  logic [SI-1:0] lookup_set;
  logic lookup_hit;
  logic [WI-1:0] lookup_way;
  logic req_fire, lookup_range;
  logic pf_pending;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [SI-1:0] pf_set;
  logic pf_hit, pf_hit_raw, pf_hit_q, pf_hit_checked, pf_in_flight;
  localparam int PF_DEPTH=8;
  localparam int PF_AW=$clog2(PF_DEPTH), PF_CW=PF_AW+1;
  logic [PF_AW-1:0] pf_head, pf_tail;
  logic [PF_AW-1:0] pf_pick, pf_pick_comb;
  logic pf_pick_current, pf_active_valid;
  logic [PF_CW-1:0] pf_count;
  logic [31:0] pf_queue_addr[PF_DEPTH], pf_queue_index[PF_DEPTH];
  logic [31:0] pf_queue_epoch[PF_DEPTH], pf_queue_retire[PF_DEPTH];
  logic pf_queue_index_valid[PF_DEPTH];
  logic pf_push, pf_pop, pf_duplicate, pf_retire_q, pf_retire_ready;
  logic [PF_DEPTH-1:0] pf_slot_valid, pf_current_candidates, pf_current_ordered;
  logic offer_valid, offer_capture, offer_consume;
  logic offer_checked, offer_duplicate_q, offer_select_next_q;
  logic [31:0] offer_addr_q, offer_index_q, offer_epoch_q, offer_retire_q;
  logic [31:0] offer_next_addr_q, offer_next_index_q, offer_next_epoch_q, offer_next_retire_q;
  logic offer_index_valid_q, offer_next_index_valid_q, offer_next_fragment_q, offer_fresh_q;
  logic offer_range_q, offer_next_range_q, offer_choose_next;
  wire offer_in_range = offer_select_next_q ? offer_next_range_q : offer_range_q;
  logic [SI-1:0] offer_set_q, offer_next_set_q;
  logic [SI-1:0] pf_incoming_set;
  logic [31:0] pf_offer_addr, pf_offer_index, pf_offer_epoch, pf_offer_retire;
  logic pf_offer_index_valid;
  logic [31:0] fill_addr, fill_first, fill_end, fill_epoch, fill_retire, fill_rank;
  logic [SI-1:0] fill_set;
  logic [WI-1:0] fill_way;
  logic fill_prefetch, fill_bad, fill_consumed;
  logic [31:0] select_addr, select_epoch, select_retire, select_rank;
  logic [SI-1:0] select_set;
  logic [WI-1:0] select_way, select_way_next;
  logic select_prefetch, select_launch, select_launch_candidate, select_found, select_expired;
  logic select_stage_valid, select_decision_valid, candidate_prefetch;
  logic [31:0] candidate_addr, candidate_epoch, candidate_retire, candidate_rank, candidate_progress;
  logic [SI-1:0] candidate_set;
  logic select_capture;
  logic candidate_metadata_busy, select_metadata_busy;
  logic [31:0] select_progress, farthest;
  logic [32:0] select_end_wide;
  logic [31:0] select_line_base, select_first, select_end;
  logic ram_ren, ram_wen, spec_read_conflict;
  logic [DA-1:0] ram_raddr, ram_waddr;
  logic [31:0] ram_rdata;
  logic span_req_ready, span_rsp_valid, span_rsp_ready, span_last, span_error, span_busy;
  logic [31:0] span_addr;
  logic [BUS_WIDTH-1:0] span_data;
  logic [BUS_WIDTH/8-1:0] span_strb;
  logic fill_complete, fill_success, completing_demand;
  logic hint_pending_q, hint_buffered;
  logic [31:0] hint_value_q;
  logic [31:LB] hint_tag;
  logic [SI-1:0] hint_set;
  logic [SI-1:0] pf_snapshot_set, incoming_snapshot_set, next_snapshot_set, hint_snapshot_set;
  logic [SI-1:0] incoming_hold_snapshot_set, next_hold_snapshot_set;
  logic pf_snapshot_valid, incoming_snapshot_valid, next_snapshot_valid, hint_snapshot_valid;
  logic incoming_hold_snapshot_valid, next_hold_snapshot_valid;
  wire pf_lookup_ready = pf_snapshot_valid && pf_snapshot_set==pf_set;
  wire pf_match_ready = pf_hit_checked && pf_lookup_ready;
  assign pf_hit = pf_match_ready && pf_hit_q;
  wire hint_lookup_ready = hint_snapshot_valid && hint_snapshot_set==hint_set;
  wire hint_effective_valid = hint_buffered || hint_valid;
  wire [31:0] hint_effective_value = hint_buffered ? hint_value_q : hint_next;
  wire hint_resolved = hint_pending_q && hint_effective_valid && hint_lookup_ready;
  localparam int DQ_AW=DEMAND_DEPTH<=1 ? 1 : $clog2(DEMAND_DEPTH);
  localparam int DQ_CW=$clog2(DEMAND_DEPTH+1);
  typedef struct packed {
    logic [31:0] address, epoch, retire, progress;
    logic [SI-1:0] set_index;
    logic geometry, event_first;
  } demand_t;
  demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request, lookup_read_request;
  logic [SI-1:0] lookup_read_set, lookup_snapshot_set;
  logic [31:2] lookup_read_word, lookup_snapshot_word;
  logic lookup_snapshot_valid, lookup_ready;
  logic [31:0] response_queue_data[DEMAND_DEPTH];
  logic response_queue_error[DEMAND_DEPTH];
  logic [DQ_AW-1:0] request_head, request_tail, response_head, response_tail;
  logic [DQ_CW-1:0] request_count, response_count, outstanding_count;
  logic accepted_request, consumed_response, request_push, request_pop;
  logic response_push, response_pop, work_valid, work_ready;
  logic core_rsp_valid, core_rsp_ready, core_rsp_error, fast_hit_response;
  logic [31:0] core_rsp_data;
  logic [31:0] speculative_data [WAYS];
  function automatic logic [SI-1:0] cache_set(input logic [31:0] address,
      input logic indexed, input logic [31:0] index);
    if (indexed) return SI'(index);
    return SI'(address>>LB) ^ SI'(address>>(LB+SI));
  endfunction

  wire [SI-1:0] initial_pf_set = cache_set(prefetch_addr,
      windowed_q && prefetch_window_index_valid, prefetch_window_index);
  wire [31:0] reference_addr = prefetch_ref_valid ? prefetch_ref_addr : req_addr;
  wire [31:0] reference_index = prefetch_ref_valid ? prefetch_ref_index : req_window_index;
  wire [31:0] reference_epoch = prefetch_ref_valid ? prefetch_ref_epoch : req_window_epoch;
  wire reference_index_valid = prefetch_ref_valid ? prefetch_ref_index_valid : req_window_index_valid;
  wire [SI-1:0] next_pf_set = cache_set(reference_addr + 32'(LINE_BYTES),
      windowed_q && reference_index_valid, reference_index);
  wire incoming_lookup_ready = offer_fresh_q ?
      (incoming_snapshot_valid && incoming_snapshot_set==offer_set_q) :
      (incoming_hold_snapshot_valid && incoming_hold_snapshot_set==offer_set_q);
  wire next_lookup_ready = offer_fresh_q ?
      (next_snapshot_valid && next_snapshot_set==offer_next_set_q) :
      (next_hold_snapshot_valid && next_hold_snapshot_set==offer_next_set_q);

  assign cfg_ready=fill_state==F_IDLE && fg_state==FG_IDLE && !clearing && pf_count==0 && !pf_active_valid && !offer_valid && !select_stage_valid &&
                   outstanding_count==0 && request_count==0 && response_count==0;
  assign req_ready=configured && !clearing && !cfg_valid &&
                   (outstanding_count<DQ_CW'(DEMAND_DEPTH) || consumed_response) &&
                   (windowed_q || outstanding_count==0 || consumed_response);
  assign accepted_request=req_valid && req_ready;
  assign consumed_response=rsp_valid && rsp_ready;
  assign incoming_request={req_addr,req_window_epoch,req_window_retire,req_window_progress,
                           cache_set(req_addr, windowed_q && req_window_index_valid, req_window_index),
                           req_geometry,req_event_first};
  // Advance the registered queue head together with tag/data lookahead.
  // Queue indices only drive these input registers, not the hit controller.
  always_ff @(posedge clk) work_request <= lookup_read_request;
  assign work_valid=request_count!=0;
  assign work_ready=configured && !clearing && (bypass_q || lookup_ready) &&
                    response_count<DQ_CW'(DEMAND_DEPTH) &&
                    (fg_state==FG_IDLE || fg_state==FG_RESP);
  assign req_fire=work_valid && work_ready;
  assign request_push=accepted_request;
  assign request_pop=request_count!=0 && req_fire;
  assign fast_hit_response = fg_state==FG_IDLE && req_fire && lookup_range && lookup_hit;
  assign core_rsp_valid=fg_state==FG_RESP || fast_hit_response;
  assign core_rsp_data=fast_hit_response ? speculative_data[lookup_way] :
                       response_error ? 32'd0 : ram_rdata;
  assign core_rsp_error = fast_hit_response ? 1'b0 : response_error;
  assign core_rsp_ready=response_count<DQ_CW'(DEMAND_DEPTH) ||
                        (response_count!=0 && rsp_ready);
  assign rsp_valid=response_count!=0 || core_rsp_valid;
  assign rsp_data=response_count!=0 ? response_queue_data[response_head] : core_rsp_data;
  assign rsp_error=response_count!=0 ? response_queue_error[response_head] : core_rsp_error;
  assign response_push=core_rsp_valid && core_rsp_ready && (response_count!=0 || !rsp_ready);
  assign response_pop=response_count!=0 && rsp_ready;
  assign hint_pending=hint_pending_q;
  assign pf_pending=pf_active_valid;
  assign prefetch_ready = configured && prefetch_q && !bypass_q && !clearing && !cfg_valid &&
                          (!offer_valid || offer_consume);
  assign offer_capture = prefetch_valid && prefetch_ready;
  assign offer_consume = offer_valid && offer_checked && incoming_lookup_ready &&
      (!offer_next_fragment_q || next_lookup_ready) &&
      (offer_duplicate_q || !offer_in_range || pf_count<PF_CW'(PF_DEPTH));
  assign pf_push = offer_consume && !offer_duplicate_q && offer_in_range;
  assign pf_retire_ready=pf_pending && (pf_hit || pf_in_flight || pf_addr<base_q || pf_addr>=end_q ||
                              (select_launch && select_prefetch));
  assign pf_pop=pf_pending && pf_retire_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pf_retire_q <= 1'b0;
    else if (cfg_valid && cfg_ready) pf_retire_q <= 1'b0;
    else pf_retire_q <= pf_retire_ready;
  end
  assign fill_complete=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  assign fill_success=fill_complete && !fill_bad && !span_error;
  assign completing_demand=fill_success && fg_state==FG_MISS &&
    demand_addr[31:LB]==fill_addr[31:LB] && (bypass_q || demand_set==fill_set);

  // Current-fragment lookahead has priority over the following fragment.
  // The head entry fills any selected interior slot when that slot retires.
  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_prefetch_valid
    // Payload arrays retain their contents while this physical slot is free.
    // Rotating the eight flags preserves FIFO priority without rotating the
    // address and epoch arrays through several independently indexed ports.
    assign pf_current_candidates[slot] = pf_slot_valid[slot] &&
        pf_queue_epoch[slot] == demand_epoch;
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) pf_slot_valid[slot] <= 1'b0;
      else if (cfg_valid && cfg_ready) pf_slot_valid[slot] <= 1'b0;
      else begin
        if (pf_pop && pf_head == PF_AW'(slot)) pf_slot_valid[slot] <= 1'b0;
        if (pf_push && pf_tail == PF_AW'(slot)) pf_slot_valid[slot] <= 1'b1;
      end
    end
  end
  assign pf_current_ordered = PF_DEPTH'({pf_current_candidates, pf_current_candidates} >> pf_head);
  always_comb begin
    pf_pick_comb=pf_head;pf_pick_current=0;
    for (int i=0;i<PF_DEPTH;i++)
      if (pf_current_ordered[i] && !pf_pick_current) begin
        pf_pick_comb=PF_AW'(pf_head+PF_AW'(i));pf_pick_current=1;
      end
  end

  assign lookup_addr = fg_state==FG_MISS ? demand_addr : work_request.address;
  assign lookup_epoch = fg_state==FG_MISS ? demand_epoch : work_request.epoch;
  assign lookup_retire = fg_state==FG_MISS ? demand_retire : work_request.retire;
  assign lookup_progress = fg_state==FG_MISS ? demand_progress : work_request.progress;
  assign lookup_set = bypass_q ? demand_fill_set :
      (fg_state==FG_MISS ? demand_set : work_request.set_index);
  assign lookup_range = lookup_addr>=base_q && lookup_addr<end_q;
  assign pf_set = cache_set(pf_addr, windowed_q && pf_index_valid, pf_index);

  always_comb begin
    lookup_read_request = request_count==0 ? incoming_request : request_queue[request_head];
    if (fg_state != FG_MISS && req_fire && request_count != 0) begin
      if (request_count > DQ_CW'(1))
        lookup_read_request = request_queue[DQ_AW'(request_head + DQ_AW'(1))];
      // The speculative read may use an unaccepted request. The snapshot
      // address check prevents it from satisfying a different request.
      else if (req_valid)
        lookup_read_request = incoming_request;
    end
    lookup_read_set = fg_state==FG_MISS ? lookup_set :
        lookup_read_request.set_index;
    lookup_read_word = fg_state==FG_MISS ? demand_addr[31:2] : lookup_read_request.address[31:2];
  end
  assign lookup_ready = lookup_snapshot_valid && lookup_snapshot_set==lookup_set &&
                        lookup_snapshot_word==lookup_addr[31:2];

  always_comb begin
    lookup_hit=0;lookup_way=0;
    for (int w=0;w<WAYS;w++)
      if (lookup_ready && valid[w][lookup_set] && lookup_tag[w]==lookup_addr[31:LB]) begin
        lookup_hit=1;lookup_way=WI'(w);
      end
    if (bypass_q) begin lookup_hit=demand_filled && fg_state==FG_MISS && lookup_ready;
      lookup_way=demand_fill_way;end
  end

  always_comb begin
    pf_hit_raw=0;
    for (int w=0;w<WAYS;w++)
      if (pf_lookup_ready && valid[w][pf_set] && pf_tag[w]==pf_addr[31:LB]) pf_hit_raw=1;
    pf_in_flight=fill_state!=F_IDLE && fill_addr[31:LB]==pf_addr[31:LB];
    pf_incoming_set=offer_set_q;
    pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==offer_addr_q[31:LB];
    for (int w=0;w<WAYS;w++)
      if (valid[w][pf_incoming_set] && incoming_tag[w]==offer_addr_q[31:LB]) pf_duplicate=1;
    for (int i=0;i<PF_DEPTH;i++)
      if (pf_slot_valid[i] && pf_queue_addr[i][31:LB]==offer_addr_q[31:LB]) pf_duplicate=1;
    offer_choose_next = pf_duplicate && offer_next_fragment_q;
    if (offer_choose_next) begin
      pf_incoming_set=offer_next_set_q;
      pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==offer_next_addr_q[31:LB];
      for (int w=0;w<WAYS;w++)
        if (valid[w][pf_incoming_set] && next_tag[w]==offer_next_addr_q[31:LB]) pf_duplicate=1;
      for (int i=0;i<PF_DEPTH;i++)
        if (pf_slot_valid[i] && pf_queue_addr[i][31:LB]==offer_next_addr_q[31:LB]) pf_duplicate=1;
    end

  end
  assign pf_offer_addr = offer_select_next_q ? offer_next_addr_q : offer_addr_q;
  assign pf_offer_epoch = offer_select_next_q ? offer_next_epoch_q : offer_epoch_q;
  assign pf_offer_retire = offer_select_next_q ? offer_next_retire_q : offer_retire_q;
  assign pf_offer_index = offer_select_next_q ? offer_next_index_q : offer_index_q;
  assign pf_offer_index_valid = offer_select_next_q ? offer_next_index_valid_q : offer_index_valid_q;

  wire demand_candidate = !bypass_q && fg_state==FG_MISS &&
      demand_addr>=base_q && demand_addr<end_q && !completing_demand;
  always_comb begin
    // Payload selection depends on registered ownership. Handshake readiness
    // only determines whether the sampled candidate becomes valid.
    candidate_prefetch = !demand_candidate;
    candidate_addr = candidate_prefetch ? pf_addr : demand_addr;
    candidate_set = candidate_prefetch ? pf_set : demand_set;
    candidate_epoch = candidate_prefetch ? pf_epoch : demand_epoch;
    candidate_retire = candidate_prefetch ? pf_retire : demand_retire;
    candidate_progress = demand_progress;
    candidate_rank = (!candidate_prefetch && hint_pending_q &&
        hint_tag==demand_addr[31:LB] && hint_effective_valid) ? hint_effective_value : INF;
    select_launch_candidate=0;
    if (configured && !clearing && !(cfg_valid && cfg_ready) &&
        (fill_state==F_IDLE || fill_success)) begin
      if (demand_candidate) select_launch_candidate=1;
      else if (pf_pending && pf_match_ready && !pf_in_flight && !req_fire &&
               pf_addr>=base_q && pf_addr<end_q) select_launch_candidate=1;
    end
  end

  always_comb begin
    select_launch = select_stage_valid && select_decision_valid && !select_metadata_busy && (fill_state==F_IDLE || fill_success) &&
        (select_prefetch ?
          (pf_pending && pf_match_ready && pf_addr==select_addr && !pf_hit && !pf_in_flight &&
           !(req_fire && !lookup_hit)) :
          (fg_state==FG_MISS && demand_addr==select_addr && (bypass_q || lookup_ready) && !lookup_hit &&
           lookup_range && !completing_demand));
    select_way_next=0;select_found=0;select_expired=0;farthest=select_ranks[0];
    for (int w=1;w<WAYS;w++)
      if (select_ranks[w]>=farthest) begin
        farthest=select_ranks[w];select_way_next=WI'(w);
      end
    if (windowed_q)
      for (int w=WAYS-1;w>=0;w--)
        if (valid[w][select_set] &&
            ((select_epochs[w]!=EPOCH_W'(select_epoch) &&
              (!select_prefetch || select_epochs[w]!=EPOCH_W'(demand_epoch))) ||
             (select_epochs[w]==EPOCH_W'(select_epoch) && select_ranks[w]<select_progress))) begin
          select_way_next=WI'(w);select_expired=1;
        end
    for (int w=WAYS-1;w>=0;w--)
      if (!valid[w][select_set]) begin select_way_next=WI'(w);select_found=1;end
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
  end
  assign ram_wen=fill_state==F_DATA && span_rsp_valid && span_rsp_ready;
  assign ram_waddr=DA'((32'(fill_way)*SETS+32'(fill_set))*(LINE_BYTES/4)+
                      ((span_addr>>2)&(LINE_BYTES/4-1)));
  localparam int WAY_DEPTH = SETS * (LINE_BYTES/4);
  localparam int WAY_AW = $clog2(WAY_DEPTH);
  localparam int RAM_BANK_SHIFT = $clog2(BUS_WIDTH/32);
  wire [WAY_AW-1:0] speculative_address = WAY_AW'((32'(lookup_read_set) * (LINE_BYTES/4)) +
      (32'(lookup_read_word) & (LINE_BYTES/4-1)));
  wire [WAY_AW-1:0] fill_word_address = WAY_AW'((32'(fill_set) * (LINE_BYTES/4)) +
      ((span_addr >> 2) & (LINE_BYTES/4-1)));
  assign spec_read_conflict = ram_wen &&
      (speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
  for (genvar data_way=0; data_way<WAYS; data_way++) begin : g_data_way
    conv_sdp_ram #(.DEPTH(WAY_DEPTH),.AW(WAY_AW),.WRITE_WIDTH(BUS_WIDTH)) u_data (
      .clk, .rd_en(!spec_read_conflict), .rd_addr(speculative_address), .rd_data(speculative_data[data_way]),
      .wr_en(ram_wen && fill_way==WI'(data_way)), .wr_addr(fill_word_address),
      .wr_data(span_data), .wr_strb(span_strb));
  end
  always_ff @(posedge clk) if (ram_ren) ram_rdata <= speculative_data[lookup_way];
  wire bypass_launch = bypass_q && fg_state==FG_MISS && !demand_filled && lookup_range &&
                       fill_state==F_IDLE && !select_stage_valid;
  wire [31:0] bypass_line_base = {demand_addr[31:2], 2'b0};
  wire [31:0] bypass_first = bypass_line_base < base_q ? base_q : bypass_line_base;
  wire [32:0] bypass_end_wide = {1'b0, bypass_line_base} + 33'd4;
  wire [31:0] bypass_end = bypass_end_wide > {1'b0, end_q} ? end_q : bypass_end_wide[31:0];
  assign span_rsp_ready=fill_state==F_DATA;
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .MAX_REQUEST_BYTES(LINE_BYTES)) u_span(
    .clk,.rst_n,.req_valid(fill_state==F_REQ),.req_ready(span_req_ready),
    .req_addr(fill_first),
    .req_bytes(16'(fill_end-fill_first)),
    .rsp_valid(span_rsp_valid),.rsp_ready(span_rsp_ready),
    .rsp_word_addr(span_addr),.rsp_data(span_data),.rsp_strb(span_strb),
    .rsp_last(span_last),.rsp_error(span_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,.busy(span_busy));

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      request_head<=0;request_tail<=0;request_count<=0;
      response_head<=0;response_tail<=0;response_count<=0;outstanding_count<=0;

    end else if (cfg_valid && cfg_ready) begin
      request_head<=0;request_tail<=0;request_count<=0;
      response_head<=0;response_tail<=0;response_count<=0;outstanding_count<=0;

    end else begin
      case ({accepted_request,consumed_response})
        2'b10: begin
          outstanding_count<=outstanding_count+1'b1;
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
        response_queue_error[response_tail]<=core_rsp_error;
        response_tail<=DEMAND_DEPTH==1 ? DQ_AW'(0) : response_tail+1'b1;
      end
      if (response_pop) response_head<=DEMAND_DEPTH==1 ? DQ_AW'(0) : response_head+1'b1;
    end
  end

  wire metadata_enable=!(cfg_valid && cfg_ready);
  wire metadata_hit=req_fire && lookup_range && lookup_hit;
  wire metadata_fill=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  wire metadata_fill_good=metadata_fill && !(fill_bad || span_error);
  wire metadata_fill_bad=metadata_fill && (fill_bad || span_error);
  assign candidate_metadata_busy = (req_fire && lookup_set==candidate_set) ||
      (metadata_fill && fill_set==candidate_set) ||
      (hint_pending_q && hint_effective_valid && hint_set==candidate_set);
  assign select_metadata_busy = (req_fire && lookup_set==select_set) ||
      (metadata_fill && fill_set==select_set) ||
      (hint_pending_q && hint_effective_valid && hint_set==select_set);
  assign select_capture = !select_stage_valid && select_launch_candidate && !candidate_metadata_busy;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lookup_snapshot_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      lookup_snapshot_valid <= 1'b0;
    end else begin
      lookup_snapshot_set <= lookup_read_set;
      lookup_snapshot_word <= lookup_read_word;
      lookup_snapshot_valid <= !(metadata_enable && metadata_fill_good && fill_set==lookup_read_set) &&
                               !spec_read_conflict;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pf_snapshot_valid<=1'b0;
      incoming_snapshot_valid<=1'b0;
      next_snapshot_valid<=1'b0;
      hint_snapshot_valid<=1'b0;
      incoming_hold_snapshot_valid<=1'b0;
      next_hold_snapshot_valid<=1'b0;
    end else begin
      pf_snapshot_set<=pf_set;
      incoming_snapshot_set<=initial_pf_set;
      next_snapshot_set<=next_pf_set;
      incoming_hold_snapshot_set<=offer_set_q;
      next_hold_snapshot_set<=offer_next_set_q;
      hint_snapshot_set<=hint_set;
      pf_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==pf_set);
      incoming_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==initial_pf_set);
      next_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==next_pf_set);
      incoming_hold_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==offer_set_q);
      next_hold_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==offer_next_set_q);
      hint_snapshot_valid<=!(metadata_enable && metadata_fill_good && fill_set==hint_set);
    end
  end
  // The active prefetch address is held until it retires. The idle cycle
  // between entries clears this validity bit before another address is used.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pf_hit_checked <= 1'b0;
    else if (cfg_valid && cfg_ready) pf_hit_checked <= 1'b0;
    else pf_hit_checked <= pf_pending && pf_lookup_ready &&
        !(metadata_enable && metadata_fill && fill_set==pf_set) &&
        !(select_launch && select_set==pf_set);
  end
  always_ff @(posedge clk) pf_hit_q <= pf_hit_raw;

  wire [31:0] metadata_hit_rank=windowed_q ? work_request.retire : hint_next;
  wire [31:0] metadata_fill_rank=windowed_q ? fill_retire : fill_rank;
  for(genvar metadata_way=0;metadata_way<WAYS;metadata_way++) begin:g_metadata_way
    (* ram_style = "block" *) logic [31:LB] lookup_tag_ram [SETS], pf_tag_ram [SETS];
    (* ram_style = "block" *) logic [31:LB] incoming_tag_ram [SETS], next_tag_ram [SETS], hint_tag_ram [SETS];
    (* ram_style = "block" *) logic [31:LB] incoming_hold_ram [SETS], next_hold_ram [SETS];
    logic [31:LB] incoming_live_q, next_live_q, incoming_hold_q, next_hold_q;
    (* ram_style = "block" *) logic [EPOCH_W-1:0] fill_epoch_ram [SETS], hit_epoch_ram [SETS];
    (* ram_style = "block" *) logic [31:0] fill_rank_ram [SETS], hit_rank_ram [SETS], hint_rank_ram [SETS];
    logic [EPOCH_W-1:0] fill_epoch_q, hit_epoch_q;
    logic [31:0] fill_rank_q, hit_rank_q, hint_rank_q;
    logic [1:0] rank_source_q;
    logic [1:0] rank_source [SETS];
    wire fill_update = metadata_enable && metadata_fill_good && fill_way == WI'(metadata_way);
    wire hit_update = metadata_enable && metadata_hit && lookup_way == WI'(metadata_way);
    wire hint_update = metadata_enable && hint_resolved && !windowed_q &&
        valid[metadata_way][hint_set] && hint_lookup_tag[metadata_way] == hint_tag;
    always_ff @(posedge clk) begin
      if (fill_update) begin
        lookup_tag_ram[fill_set] <= fill_addr[31:LB];
        pf_tag_ram[fill_set] <= fill_addr[31:LB];
        incoming_tag_ram[fill_set] <= fill_addr[31:LB];
        next_tag_ram[fill_set] <= fill_addr[31:LB];
        hint_tag_ram[fill_set] <= fill_addr[31:LB];
        incoming_hold_ram[fill_set] <= fill_addr[31:LB];
        next_hold_ram[fill_set] <= fill_addr[31:LB];
        fill_epoch_ram[fill_set] <= EPOCH_W'(fill_epoch);
        fill_rank_ram[fill_set] <= metadata_fill_rank;
      end
      if (hit_update) begin
        hit_epoch_ram[lookup_set] <= EPOCH_W'(work_request.epoch);
        if (windowed_q || hint_valid) hit_rank_ram[lookup_set] <= metadata_hit_rank;
      end
      if (hint_update) hint_rank_ram[hint_set] <= hint_effective_value;
    end
    always_ff @(posedge clk) lookup_tag[metadata_way] <= lookup_tag_ram[lookup_read_set];
    always_ff @(posedge clk) begin
      pf_tag[metadata_way] <= pf_tag_ram[pf_set];
      incoming_live_q <= incoming_tag_ram[initial_pf_set];
      next_live_q <= next_tag_ram[next_pf_set];
      incoming_hold_q <= incoming_hold_ram[offer_set_q];
      next_hold_q <= next_hold_ram[offer_next_set_q];
      hint_lookup_tag[metadata_way] <= hint_tag_ram[hint_set];
    end
    assign incoming_tag[metadata_way] = offer_fresh_q ? incoming_live_q : incoming_hold_q;
    assign next_tag[metadata_way] = offer_fresh_q ? next_live_q : next_hold_q;
    always_ff @(posedge clk) if (!select_stage_valid) begin
      fill_epoch_q <= fill_epoch_ram[candidate_set];
      hit_epoch_q <= hit_epoch_ram[candidate_set];
      fill_rank_q <= fill_rank_ram[candidate_set];
      hit_rank_q <= hit_rank_ram[candidate_set];
      hint_rank_q <= hint_rank_ram[candidate_set];
      rank_source_q <= rank_source[candidate_set];
    end
    // Windowed hits update the epoch and rank together. The rank source
    // therefore also selects the matching epoch history.
    assign select_epochs[metadata_way] = rank_source_q == 2'd2 ? hit_epoch_q : fill_epoch_q;
    assign select_ranks[metadata_way] = rank_source_q == 2'd2 ? hit_rank_q :
        rank_source_q == 2'd1 ? hint_rank_q : fill_rank_q;
    for(genvar metadata_set=0;metadata_set<SETS;metadata_set++) begin:g_metadata_set
      wire lookup_target=lookup_way==WI'(metadata_way) && lookup_set==SI'(metadata_set);
      wire select_target=select_way==WI'(metadata_way) && select_set==SI'(metadata_set);
      wire fill_target=fill_way==WI'(metadata_way) && fill_set==SI'(metadata_set);
      wire hit_write=metadata_hit && lookup_target;
      wire fill_write=metadata_fill_good && fill_target;
      wire hint_write=hint_resolved && !windowed_q &&
        hint_set==SI'(metadata_set) && valid[metadata_way][metadata_set] &&
        hint_lookup_tag[metadata_way]==hint_tag;
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid[metadata_way][metadata_set] <= 1'b0;
        else if (metadata_enable) begin
          if ((clearing && clear_set==SI'(metadata_set)) ||
              (select_launch && select_target) || (metadata_fill_bad && fill_target))
            valid[metadata_way][metadata_set] <= 1'b0;
          if (fill_write) valid[metadata_way][metadata_set] <= !bypass_q;
        end
      end
`ifdef NPU_SIM_ASSERT
      initial forever @(posedge clk) if (rst_n && valid[metadata_way][metadata_set]) begin
        assert (!$isunknown({lookup_tag_ram[metadata_set], rank_source[metadata_set]}));
        assert (!$isunknown(rank_source[metadata_set] == 2'd2 ? hit_epoch_ram[metadata_set] :
                            fill_epoch_ram[metadata_set]));
        assert (!$isunknown(rank_source[metadata_set] == 2'd2 ? hit_rank_ram[metadata_set] :
                            rank_source[metadata_set] == 2'd1 ? hint_rank_ram[metadata_set] :
                            fill_rank_ram[metadata_set]));
      end
`endif
      always_ff @(posedge clk) if (rst_n && metadata_enable) begin
        if (hit_write && (windowed_q || hint_valid)) rank_source[metadata_set] <= 2'd2;
        if (hint_write) rank_source[metadata_set] <= 2'd1;
        if (fill_write) rank_source[metadata_set] <= 2'd0;
      end
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) offer_valid <= 1'b0;
    else if (cfg_valid && cfg_ready) offer_valid <= 1'b0;
    else case ({offer_capture, offer_consume})
      2'b10: offer_valid <= 1'b1;
      2'b01: offer_valid <= 1'b0;
      default: ;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) offer_fresh_q <= 1'b0;
    else offer_fresh_q <= offer_capture;
  end
  // Resolve the tag comparison before it controls the queue payload enables.
  // The offer fields remain owned by this entry until it is consumed.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) offer_checked <= 1'b0;
    else if ((cfg_valid && cfg_ready) || offer_capture || offer_consume)
      offer_checked <= 1'b0;
    else if (offer_valid && incoming_lookup_ready &&
             (!offer_next_fragment_q || next_lookup_ready))
      offer_checked <= 1'b1;
    else offer_checked <= 1'b0;
  end
  always_ff @(posedge clk) begin
    offer_duplicate_q <= pf_duplicate;
    offer_select_next_q <= offer_choose_next;
  end
  always_ff @(posedge clk) begin
    if (offer_capture) begin
      offer_addr_q <= prefetch_addr;
      offer_range_q <= prefetch_addr >= base_q && prefetch_addr < end_q;
      offer_next_range_q <= (reference_addr + 32'(LINE_BYTES)) >= base_q &&
                            (reference_addr + 32'(LINE_BYTES)) < end_q;
      offer_index_q <= prefetch_window_index;
      offer_epoch_q <= prefetch_window_epoch;
      offer_retire_q <= prefetch_window_retire;
      offer_index_valid_q <= prefetch_window_index_valid;
      offer_next_fragment_q <= prefetch_next_fragment;
      offer_next_addr_q <= reference_addr + 32'(LINE_BYTES);
      offer_next_index_q <= reference_index;
      offer_next_epoch_q <= reference_epoch + 32'd1;
      offer_next_retire_q <= INF;
      offer_next_index_valid_q <= reference_index_valid;
      offer_set_q <= initial_pf_set;
      offer_next_set_q <= next_pf_set;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      select_stage_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      select_stage_valid <= 1'b0;
    end else if (select_launch || (select_stage_valid &&
                 (select_metadata_busy || (select_prefetch ? (!pf_pending || pf_addr!=select_addr || pf_hit || pf_in_flight) :
                  (fg_state!=FG_MISS || demand_addr!=select_addr || lookup_hit || !lookup_range))))) begin
      select_stage_valid <= 1'b0;
    end else if (select_capture) begin
      select_stage_valid <= 1'b1;
    end
  end
  // Separate synchronous metadata reads and replacement comparison from the
  // fill/queue handshake. Any concurrent update to this set cancels the
  // snapshot through select_stage_valid before it can launch a fill.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) select_decision_valid <= 1'b0;
    else if ((cfg_valid && cfg_ready) || !select_stage_valid ||
             select_launch || select_metadata_busy)
      select_decision_valid <= 1'b0;
    else select_decision_valid <= 1'b1;
  end
  always_ff @(posedge clk)
    if (select_stage_valid && !select_decision_valid && !select_metadata_busy)
      select_way <= select_way_next;

  always_ff @(posedge clk) begin
    if (!select_stage_valid) begin
      select_prefetch <= candidate_prefetch;
      select_addr <= candidate_addr;
      select_set <= candidate_set;
      select_epoch <= candidate_epoch;
      select_retire <= candidate_retire;
      select_progress <= candidate_progress;
      select_rank <= candidate_rank;
    end
  end

  // Keep request fields ready independently of the tag-match handshake.
  // The fill state owns these fields until the final successful data beat.
  always_ff @(posedge clk) begin
    if (req_fire && work_request.geometry && work_request.event_first && hint_valid &&
        fill_state!=F_IDLE && fill_addr[31:LB]==work_request.address[31:LB])
      fill_rank <= hint_next;
    if (hint_resolved && fill_state!=F_IDLE && fill_addr[31:LB]==hint_tag)
      fill_rank <= hint_effective_value;
    if (fill_state==F_IDLE || fill_success) begin
      fill_addr <= bypass_q ? demand_addr : select_addr;
      fill_first <= bypass_q ? bypass_first : select_first;
      fill_end <= bypass_q ? bypass_end : select_end;
      fill_set <= bypass_q ? SI'(0) : select_set;
      fill_way <= bypass_q ? WI'(0) : select_way;
      fill_epoch <= bypass_q ? demand_epoch : select_epoch;
      fill_retire <= bypass_q ? demand_retire : select_retire;
      fill_rank <= bypass_q ? INF : select_rank;
      fill_prefetch <= !bypass_q && select_prefetch;
    end
  end

  always_ff @(posedge clk) begin
    if (pf_push) begin
      pf_queue_addr[pf_tail] <= pf_offer_addr;
      pf_queue_index[pf_tail] <= pf_offer_index;
      pf_queue_index_valid[pf_tail] <= pf_offer_index_valid;
      pf_queue_epoch[pf_tail] <= pf_offer_epoch;
      pf_queue_retire[pf_tail] <= pf_offer_retire;
    end
    if (pf_pop && pf_pick != pf_head) begin
      pf_queue_addr[pf_pick] <= pf_queue_addr[pf_head];
      pf_queue_index[pf_pick] <= pf_queue_index[pf_head];
      pf_queue_index_valid[pf_pick] <= pf_queue_index_valid[pf_head];
      pf_queue_epoch[pf_pick] <= pf_queue_epoch[pf_head];
      pf_queue_retire[pf_pick] <= pf_queue_retire[pf_head];
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fg_state<=FG_IDLE;fill_state<=F_IDLE;configured<=0;clearing<=0;clear_set<=0;
      base_q<=0;end_q<=0;bypass_q<=0;windowed_q<=0;prefetch_q<=0;
      demand_addr<=0;demand_set<=0;demand_epoch<=0;demand_retire<=INF;demand_progress<=0;
      demand_filled<=0;demand_fill_set<=0;demand_fill_way<=0;
      response_error<=0;pf_head<=0;pf_tail<=0;pf_count<=0;pf_active_valid<=0;
      fill_bad<=0;fill_consumed<=0;
      hint_pending_q<=0;hint_buffered<=0;hint_tag<=0;hint_set<=0;

    end else begin
      if (cfg_valid && cfg_ready) begin
        configured<=1;clearing<=1;clear_set<=0;fg_state<=FG_IDLE;
        base_q<=cfg_base;end_q<=cfg_base+cfg_bytes;bypass_q<=cfg_bypass;
        windowed_q<=cfg_windowed;prefetch_q<=cfg_prefetch_enable;
        pf_head<=0;pf_tail<=0;pf_count<=0;pf_active_valid<=0;hint_pending_q<=0;hint_buffered<=0;demand_filled<=0;

      end else begin
        if (clearing) begin
          if (clear_set==SI'(SETS-1)) clearing<=0;
          else clear_set<=clear_set+1'b1;
        end
        if (fg_state==FG_RESP && core_rsp_ready) fg_state<=FG_IDLE;
        if (req_fire) begin
          demand_addr<=work_request.address;demand_set<=work_request.set_index;
          demand_epoch<=work_request.epoch;demand_retire<=work_request.retire;
          demand_progress<=work_request.progress;demand_filled<=0;response_error<=0;
          if (!lookup_range) begin response_error<=1;fg_state<=FG_RESP;end
          else if (lookup_hit) begin
            fg_state<=fast_hit_response ? FG_IDLE : FG_RESP;
          end else begin
            fg_state<=FG_MISS;
            if (fill_state!=F_IDLE && fill_prefetch && fill_addr[31:LB]==work_request.address[31:LB]) begin
              fill_consumed<=1;
            end
          end
          if (work_request.geometry && work_request.event_first) begin
            if (hint_valid) begin
              hint_pending_q<=0;
            end else begin hint_pending_q<=1;hint_tag<=work_request.address[31:LB];hint_set<=lookup_set;end
          end
        end
        if (fg_state==FG_MISS && lookup_hit) begin
          fg_state<=FG_RESP;response_error<=0;demand_filled<=0;
        end
        if (hint_pending_q && hint_valid && !hint_lookup_ready && !hint_buffered) begin
          hint_buffered<=1'b1;
          hint_value_q<=hint_next;
        end
        if (hint_resolved) begin
          hint_pending_q<=0;
          hint_buffered<=0;
        end
        if (!pf_active_valid && pf_count != 0 && !clearing) begin
          pf_pick<=pf_pick_comb;
          pf_addr<=pf_queue_addr[pf_pick_comb];
          pf_index<=pf_queue_index[pf_pick_comb];
          pf_epoch<=pf_queue_epoch[pf_pick_comb];
          pf_retire<=pf_queue_retire[pf_pick_comb];
          pf_index_valid<=pf_queue_index_valid[pf_pick_comb];
          pf_active_valid<=1'b1;
        end
        if (pf_pop) pf_active_valid<=1'b0;
        case ({pf_push,pf_pop})
          2'b10: pf_count<=pf_count+1'b1;
          2'b01: pf_count<=pf_count-1'b1;
          default: ;
        endcase
        if (pf_push) pf_tail<=pf_tail+1'b1;
        if (pf_pop) pf_head<=pf_head+1'b1;
        if (select_launch) begin
          fill_bad<=0;fill_consumed<=0;
          fill_state<=F_REQ;
        end
        if (bypass_launch) begin
          fill_bad<=0;fill_consumed<=0;
          fill_state<=F_REQ;
        end
        if (fill_state==F_REQ && span_req_ready) fill_state<=F_DATA;
        if (fill_state==F_DATA && span_rsp_valid && span_rsp_ready) begin

          fill_bad<=fill_bad || span_error;
          if (span_last) begin
            fill_state<=select_launch ? F_REQ : F_IDLE;
            if (fill_bad || span_error) begin
              if (!fill_prefetch || (fg_state==FG_MISS && demand_addr[31:LB]==fill_addr[31:LB])) begin
                response_error<=1;fg_state<=FG_RESP;
              end
            end else begin
              if (!fill_prefetch && bypass_q) begin
                demand_filled<=1;demand_fill_set<=fill_set;demand_fill_way<=fill_way;
              end
            end
          end
        end
      end
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SETS<2 || (SETS&(SETS-1))!=0) $fatal(1,"SETS must be a power of two >=2");
    if (WAYS!=1 && WAYS!=2) $fatal(1,"WAYS must be 1 or 2");
    if (LINE_BYTES<8 || LINE_BYTES>256 || (LINE_BYTES&(LINE_BYTES-1))!=0)
      $fatal(1,"LINE_BYTES must be a power of two in [8,256]");
    if (DEMAND_DEPTH<1 || (DEMAND_DEPTH&(DEMAND_DEPTH-1))!=0)
      $fatal(1,"DEMAND_DEPTH must be a positive power of two");
  end
`endif
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
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
    if (ram_ren && ram_wen) assert((int'(ram_raddr)/(BUS_WIDTH/32))!=(int'(ram_waddr)/(BUS_WIDTH/32)));
    assert(pf_count<=PF_CW'(PF_DEPTH));
    if (select_launch) begin
      assert(select_first<select_end && (fill_state==F_IDLE || fill_success));
      if (fill_complete) assert(select_set!=fill_set || select_way!=fill_way);
    end
  end
`endif
endmodule


/* verilator lint_on DECLFILENAME */
