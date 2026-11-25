// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module conv_windowed_cache #(
  parameter int SETS=32,
  parameter int WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int READ_WIDTH=32,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter int DEMAND_DEPTH=4,
  parameter int SI=$clog2(SETS),
  parameter int LB=$clog2(LINE_BYTES),
  parameter int WB=$clog2(LINE_BYTES/4),
  parameter int WI=(WAYS==1 ? 1 : $clog2(WAYS)),
  parameter int DEPTH=WAYS*SETS*(LINE_BYTES/4),
  parameter int DA=$clog2(DEPTH),
  parameter int TAGW=32-LB-SI,
  parameter bit p_defer_retire_shift=1'b0,
  parameter bit p_preview_request=1'b0
) (
  input wire logic clk, rst_n,
  input wire logic cfg_valid,
  output logic cfg_ready,
  input wire logic [31:0] cfg_base, cfg_bytes,
  input wire logic cfg_bypass,
  input wire logic cfg_geometry = 1'b0,
  input wire logic req_valid,
  output logic req_ready,
  input wire logic preview_valid = 1'b0,
  input wire logic [31:0] preview_addr = 32'd0,
  input wire logic preview_index_valid = 1'b0,
  input wire logic [31:0] preview_index = 32'd0,
  input wire logic [31:0] req_addr,
  input wire logic req_geometry = 1'b0,
  input wire logic req_event_first = 1'b0,
  input wire logic hint_valid = 1'b0,
  input wire logic [31:0] hint_next = 32'hffff_ffff,
  output logic hint_pending,
  output logic rsp_valid,
  input wire logic rsp_ready,
  output logic [READ_WIDTH-1:0] rsp_data,
  output logic rsp_error,
  output logic rsp_success,
  output logic rsp_failure,
  output logic arvalid,
  input wire logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input wire logic rvalid,
  output logic rready,
  input wire logic [BUS_WIDTH-1:0] rdata,
  input wire logic [1:0] rresp,
  input wire logic rlast,
  input wire logic cfg_windowed = 1'b0,
  input wire logic cfg_prefetch_enable = 1'b0,
  input wire logic req_window_index_valid = 1'b0,
  input wire logic [31:0] req_window_index = 32'd0,
  input wire logic [31:0] req_window_epoch = 32'd0,
  input wire logic [31:0] req_window_retire = 32'hffff_ffff,
  input wire logic [31:0] req_window_progress = 32'd0,
  input wire logic prefetch_valid = 1'b0,
  output logic prefetch_ready,
  input wire logic [31:0] prefetch_addr = 32'd0,
  input wire logic prefetch_window_index_valid = 1'b0,
  input wire logic [31:0] prefetch_window_index = 32'd0,
  input wire logic [31:0] prefetch_window_epoch = 32'd0,
  input wire logic [31:0] prefetch_window_retire = 32'hffff_ffff,
  input wire logic prefetch_next_fragment = 1'b0,
  input wire logic prefetch_ref_valid = 1'b0,
  input wire logic [31:0] prefetch_ref_addr = 32'd0,
  input wire logic prefetch_ref_index_valid = 1'b0,
  input wire logic [31:0] prefetch_ref_index = 32'd0,
  input wire logic [31:0] prefetch_ref_epoch = 32'd0);
  localparam int p_read_bytes = READ_WIDTH / 8;
  localparam int p_read_shift = $clog2(p_read_bytes);
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
  logic [WAYS-1:0] valid_lookup, valid_prefetch, valid_incoming;
  logic [WAYS-1:0] valid_next, valid_select, valid_hint;
  logic [EPOCH_W-1:0] select_epochs [WAYS];
  logic [31:0] select_ranks [WAYS];
  logic [31:0] demand_addr, demand_epoch, demand_retire, demand_progress;
  logic [SI-1:0] demand_set;
  logic response_error;
  logic demand_filled;
  logic [SI-1:0] demand_fill_set;
  logic [WI-1:0] demand_fill_way;
  logic [31:0] lookup_addr;
  logic [SI-1:0] lookup_set;
  logic [3:0][SI-1:0] lookup_candidate_set;
  logic [1:0][SI-1:0] lookup_input_set;
  logic lookup_hit;
  logic [WAYS-1:0] work_tag_hits, demand_tag_hits;
  logic [WI-1:0] lookup_way;
  logic req_fire, lookup_range, work_range, demand_range;
  logic pf_pending;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [SI-1:0] pf_set;
  logic pf_hit, pf_hit_raw, pf_hit_q, pf_hit_checked, pf_in_flight;
  localparam int PF_DEPTH=8;
  localparam int PF_AW=$clog2(PF_DEPTH), PF_CW=PF_AW+1;
  logic [PF_AW-1:0] pf_head, pf_tail;
  logic [PF_AW-1:0] pf_pick, pf_pick_comb;
  logic pf_active_valid;
  logic [PF_CW-1:0] pf_count;
  logic [PF_AW-1:0] pf_slot_map_q[PF_DEPTH];
  logic [PF_AW-1:0] pf_push_slot, pf_pop_slot, pf_read_slot;
  logic [PF_DEPTH-1:0] pf_physical_valid_q, pf_epoch_matches;
  logic pf_offer_matches_work, pf_offer_matches_demand;
  logic prefetch_keys_i_wr_en;
  logic [PF_AW-1:0] prefetch_keys_i_wr_addr;
  logic [63:0] prefetch_keys_i_wr_data;
`ifndef ASIC_SYNTHESIS
  logic [0:0] prefetch_keys_i_wr_mask;
  logic [PF_DEPTH-1:0] prefetch_keys_i_rd_en;
  logic [PF_DEPTH-1:0][PF_AW-1:0] prefetch_keys_i_rd_addr;
`endif
  logic [PF_DEPTH-1:0][63:0] prefetch_keys_o_rd_data;
  logic [63:0] pf_selected_keys;
  logic prefetch_payload_i_wr_en, prefetch_payload_i_rd_en;
  logic [PF_AW-1:0] prefetch_payload_i_wr_addr, prefetch_payload_i_rd_addr;
  logic [64:0] prefetch_payload_i_wr_data, prefetch_payload_o_rd_data;
  logic [0:0] prefetch_payload_i_wr_mask;
  logic prefetch_retire_i_wr_en;
  logic [PF_AW-1:0] prefetch_retire_i_wr_addr;
  logic [31:0] prefetch_retire_i_wr_data;
  logic [0:0] prefetch_retire_i_wr_mask, prefetch_retire_i_rd_en;
  logic [0:0][PF_AW-1:0] prefetch_retire_i_rd_addr;
  logic [0:0][31:0] prefetch_retire_o_rd_data;
  logic prefetch_index_i_wr_en;
  logic [PF_AW-1:0] prefetch_index_i_wr_addr;
  logic [32:0] prefetch_index_i_wr_data;
  logic [0:0] prefetch_index_i_wr_mask, prefetch_index_i_rd_en;
  logic [0:0][PF_AW-1:0] prefetch_index_i_rd_addr;
  logic [0:0][32:0] prefetch_index_o_rd_data;
  logic pf_push, pf_pop, pf_duplicate, pf_retire_q, pf_retire_ready;
  logic [PF_DEPTH-1:0] pf_slot_valid, pf_current_by_slot;
  logic [PF_DEPTH-1:0] pf_pick_by_slot;
  logic offer_valid, offer_capture, offer_consume;
  logic offer_checked, offer_duplicate_q, offer_select_next_q;
  logic [31:0] offer_addr_q, offer_index_q, offer_epoch_q, offer_retire_q;
  logic [31:0] offer_next_addr_q, offer_next_index_q, offer_next_epoch_q, offer_next_retire_q;
  logic offer_index_valid_q, offer_next_index_valid_q, offer_next_fragment_q, offer_fresh_q;
  logic offer_range_q, offer_next_range_q, offer_choose_next;
  wire offer_in_range = offer_select_next_q ? offer_next_range_q : offer_range_q;
  logic [SI-1:0] offer_set_q, offer_next_set_q;
  logic [31:0] pf_offer_addr, pf_offer_index, pf_offer_epoch, pf_offer_retire;
  logic pf_offer_index_valid;
  logic [31:0] fill_addr, fill_first, fill_end, fill_epoch, fill_retire, fill_rank;
  logic [SI-1:0] fill_set;
  logic [WI-1:0] fill_way;
  logic fill_prefetch, fill_bad;
  logic [31:0] select_addr, select_epoch, select_retire, select_rank;
  logic [SI-1:0] select_set;
  logic [WI-1:0] select_way, select_way_next;
  logic select_prefetch, select_launch, select_launch_candidate;
  logic select_stage_valid, select_decision_valid, candidate_prefetch;
  logic [31:0] candidate_addr, candidate_epoch, candidate_retire, candidate_rank, candidate_progress;
  logic [SI-1:0] candidate_set;
  logic candidate_metadata_busy, select_metadata_busy;
  logic [31:0] select_progress, farthest;
  logic [31:0] reference_next_address;
   logic [31:0] reference_next_epoch, configured_end;
  logic [WAYS-1:0] rank_before_progress, unused_rank_progress_equal;
  logic rank_one_below_zero, unused_rank_way_equal;
  // 完整地址与代次算术并行准备，配置及预取接收只控制保存边沿。
  assign configured_end = cfg_base + cfg_bytes;
  // 释放序号和替换顺序使用完整无符号比较，由工具推断行为级算术资源。
  for (genvar rank_way = 0; rank_way < WAYS; rank_way++) begin : g_rank_progress
    unsigned_compare #(.p_width(32)) u_compare (
      .i_a(select_ranks[rank_way]), .i_b(select_progress),
      .o_less(rank_before_progress[rank_way]), .o_equal(unused_rank_progress_equal[rank_way])
    );
  end
  if (WAYS == 2) begin : g_two_way_rank
    unsigned_compare #(.p_width(32)) u_compare (
      .i_a(select_ranks[1]), .i_b(select_ranks[0]),
      .o_less(rank_one_below_zero), .o_equal(unused_rank_way_equal)
    );
  end else begin : g_other_way_rank
    assign rank_one_below_zero = 1'b0;
    assign unused_rank_way_equal = 1'b0;
  end
  logic unused_reference_next_carry;
  logic [11:0][31:0] range_i_a, range_i_b;
  logic [11:0] range_below, unused_range_equal;
  logic [31:0] select_line_base, select_first;
  logic [31:0] fill_candidate_end;
  logic [1:0][31:0] fill_end_candidates;
  logic ram_ren, ram_wen, spec_read_conflict;
`ifdef NPU_SIM_ASSERT
  logic [DA-1:0] ram_raddr, ram_waddr;
`endif
  logic [READ_WIDTH-1:0] ram_rdata;
  logic span_req_ready, span_rsp_valid, span_rsp_ready, span_last, span_error;
  logic [31:0] span_addr;
  logic [32:0] span_request_bytes_wide;
  // 完整起止地址相减后选择有效长度，避免长度选择与逐位进位串接。
  assign span_request_bytes_wide = {1'b0, fill_end} - {1'b0, fill_first};
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
  logic [1:0] pf_snapshot_set_matches;
  logic pf_snapshot_set_match;
  wire pf_lookup_ready = pf_snapshot_valid && pf_snapshot_set_match;
  // 普通组号与窗口索引分别比较，窗口模式只选择单比特匹配结果。
  assign pf_snapshot_set_matches[0] = pf_snapshot_set ==
      (SI'(pf_addr>>LB) ^ SI'(pf_addr>>(LB+SI)));
  assign pf_snapshot_set_matches[1] = pf_snapshot_set == SI'(pf_index);
  always_comb begin
    pf_snapshot_set_match = pf_snapshot_set_matches[0];
    if (windowed_q && pf_index_valid) pf_snapshot_set_match = pf_snapshot_set_matches[1];
  end
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
    logic geometry, event_first, in_range;
  } demand_t;
  demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request, lookup_read_request;
  demand_t preview_request, lookup_input_request, processing_request;
  logic lookup_input_valid, preview_selected_q, preview_active, preview_source_select;
  logic preview_below_base, preview_below_end;
  logic unused_preview_base_equal, unused_preview_end_equal;
  logic [1:0][31:0] retire_decode_input, retire_decode_output;
  logic [SI-1:0] lookup_read_set, lookup_snapshot_set;
  logic [31:2] lookup_read_word;
  logic lookup_snapshot_valid, lookup_ready;
  logic work_lookup_ready, demand_lookup_ready;
  logic work_word_matches_q, demand_word_matches_q, work_snapshot_matches_q;
  logic work_word_matches_next, work_snapshot_matches_next, response_snapshot_ready;
  logic demand_word_matches_next, direct_response_snapshot_ready;
  logic lookup_idle_set_match;
  logic [1:0] lookup_head_matches, lookup_input_matches;
  logic [1:0] lookup_preview_matches, lookup_request_matches;
  logic lookup_next_work_match;
  logic lookup_idle_demand_match, lookup_pop_work_match;
  logic [READ_WIDTH-1:0] response_queue_data[DEMAND_DEPTH];
  logic response_queue_error[DEMAND_DEPTH];
  logic [DQ_AW-1:0] request_head, request_tail, response_head, response_tail;
  logic [DQ_CW-1:0] request_count, response_count, outstanding_count;
  logic accepted_request, consumed_response, request_push, request_pop;
  logic response_push, response_pop, work_valid, work_ready;
  logic core_rsp_valid, core_rsp_ready, core_rsp_error, fast_hit_response;
  logic bypass_launch;
  logic incoming_range;
  logic [READ_WIDTH-1:0] core_rsp_data;
  logic [READ_WIDTH-1:0] speculative_data [WAYS];
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
  assign reference_next_epoch = reference_epoch + 32'd1;
  wire reference_index_valid = prefetch_ref_valid ? prefetch_ref_index_valid : req_window_index_valid;
  wire [SI-1:0] next_pf_set = cache_set(reference_next_address,
      windowed_q && reference_index_valid, reference_index);
  logic [3:0] offer_read_set_match_q;
  logic offer_read_set_match_valid;
  logic [3:0][SI-1:0] offer_read_next_set;
  logic [1:0][SI-1:0] offer_next_set;
  logic [3:0] offer_read_set_matches, offer_parallel_set_matches;
  logic [1:0] offer_current_set_matches;
  // 预取描述和读取快照同时更新时保存组号匹配结果，队列接收直接使用资格位。
  // 下一状态使用相同的条件更新顺序，复位和未知控制值保持原有读取行为。
  always_comb begin
    offer_next_set = {offer_next_set_q, offer_set_q};
    if (offer_capture) offer_next_set = {next_pf_set, initial_pf_set};
    offer_read_next_set = {offer_next_set_q, offer_set_q, next_pf_set, initial_pf_set};
    if (!rst_n) begin
      offer_read_next_set = {next_hold_snapshot_set, incoming_hold_snapshot_set,
                             next_snapshot_set, incoming_snapshot_set};
    end
  end
  // 描述组号与各读取快照并行比较，保存条件只选择单个匹配结果。
  assign offer_current_set_matches[0] = initial_pf_set == offer_set_q;
  assign offer_current_set_matches[1] = next_pf_set == offer_next_set_q;
  for (genvar offer_port = 0; offer_port < 4; offer_port++) begin : g_offer_set_match
    localparam int p_source = offer_port % 2;
    logic [SI-1:0] reset_read_set, captured_set, held_set;
    logic reset_captured_match, reset_held_match;
    if (offer_port == 0) begin : g_incoming
      assign reset_read_set = incoming_snapshot_set;
    end else if (offer_port == 1) begin : g_next
      assign reset_read_set = next_snapshot_set;
    end else if (offer_port == 2) begin : g_held_incoming
      assign reset_read_set = incoming_hold_snapshot_set;
    end else begin : g_held_next
      assign reset_read_set = next_hold_snapshot_set;
    end
    assign captured_set = p_source == 0 ? initial_pf_set : next_pf_set;
    assign held_set = p_source == 0 ? offer_set_q : offer_next_set_q;
    assign reset_captured_match = reset_read_set == captured_set;
    assign reset_held_match = reset_read_set == held_set;
    conv_cache_offer_match_select #(.p_capture_matches(offer_port < 2)) u_select (
      .rst_n(rst_n), .i_capture(offer_capture),
      .i_current_match(offer_current_set_matches[p_source]),
      .i_reset_captured_match(reset_captured_match), .i_reset_held_match(reset_held_match),
      .o_match(offer_parallel_set_matches[offer_port])
    );
  end
  always_comb begin
    offer_read_set_matches = offer_parallel_set_matches;
`ifndef SYNTHESIS
    // 未知组号仍执行完整字段比较，保留各读取端口的四态结果。
    if ((^{rst_n, offer_capture, initial_pf_set, next_pf_set,
           offer_set_q, offer_next_set_q, incoming_snapshot_set, next_snapshot_set,
           incoming_hold_snapshot_set, next_hold_snapshot_set}) === 1'bx) begin
      offer_read_set_matches[0] = offer_read_next_set[0] == offer_next_set[0];
      offer_read_set_matches[1] = offer_read_next_set[1] == offer_next_set[1];
      offer_read_set_matches[2] = offer_read_next_set[2] == offer_next_set[0];
      offer_read_set_matches[3] = offer_read_next_set[3] == offer_next_set[1];
    end
`endif
  end
  always_ff @(posedge clk) begin
    offer_read_set_match_q <= offer_read_set_matches;
  end
  // 保存采样边沿的复位状态，未知复位恢复期间仍按快照字段计算四态结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) offer_read_set_match_valid <= 1'b0;
    else offer_read_set_match_valid <= rst_n;
  end
  logic incoming_lookup_ready, next_lookup_ready;
  always_comb begin
    case (offer_read_set_match_valid)
      1'b0, 1'b1: begin
        incoming_lookup_ready = offer_fresh_q ?
            (incoming_snapshot_valid && offer_read_set_match_q[0]) :
            (incoming_hold_snapshot_valid && offer_read_set_match_q[2]);
        next_lookup_ready = offer_fresh_q ?
            (next_snapshot_valid && offer_read_set_match_q[1]) :
            (next_hold_snapshot_valid && offer_read_set_match_q[3]);
      end
      default: begin
        incoming_lookup_ready = offer_fresh_q ?
            (incoming_snapshot_valid && incoming_snapshot_set == offer_set_q) :
            (incoming_hold_snapshot_valid && incoming_hold_snapshot_set == offer_set_q);
        next_lookup_ready = offer_fresh_q ?
            (next_snapshot_valid && next_snapshot_set == offer_next_set_q) :
            (next_hold_snapshot_valid && next_hold_snapshot_set == offer_next_set_q);
      end
    endcase
  end

  // 地址范围比较共享操作数列表，完整扩展减法由综合工具推断。
  // 每对端口依次比较下界和上界，最后两项分别检查普通填充和旁路填充的起点。
  assign range_i_a = {{demand_addr[31:p_read_shift], {p_read_shift{1'b0}}}, select_line_base,
      reference_next_address, reference_next_address, prefetch_addr, prefetch_addr,
      demand_addr, demand_addr, pf_addr, pf_addr, req_addr, req_addr};
  for (genvar range_port = 0; range_port < 12; range_port++) begin : g_address_range
    assign range_i_b[range_port] = range_port < 10 && (range_port % 2) != 0 ? end_q : base_q;
    unsigned_compare #(.p_width(32)) u_compare (
      .i_a(range_i_a[range_port]), .i_b(range_i_b[range_port]),
      .o_less(range_below[range_port]), .o_equal(unused_range_equal[range_port])
    );
  end
  if (LINE_BYTES > 0 && (LINE_BYTES & (LINE_BYTES-1)) == 0) begin : g_reference_line
    conv_cache_next_line #(.p_line_shift($clog2(LINE_BYTES))) u_reference_next (
      .i_address(reference_addr), .o_address(reference_next_address),
      .o_carry(unused_reference_next_carry)
    );
  end else begin : g_reference_bytes
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_reference_next (
      .i_a(reference_addr), .i_b(32'(LINE_BYTES)), .i_carry(1'b0),
      .o_sum(reference_next_address), .o_carry(unused_reference_next_carry)
    );
  end


  localparam int p_cfg_idle_width = 6 + PF_CW + 3*DQ_CW;
  logic [p_cfg_idle_width-1:0] cfg_idle_state;
  assign cfg_idle_state = {fg_state, clearing, pf_count, pf_active_valid, offer_valid,
                           outstanding_count, request_count, response_count, select_stage_valid};
  // 缓存各状态并行检查，填充状态独立参与最终接收条件。
  assign cfg_ready = fill_state == F_IDLE && !(|cfg_idle_state);
  if (DEMAND_DEPTH == 1) begin : g_direct_request_ready
    logic enabled, saved_ready, fast_ready;
    assign enabled = configured && !clearing && !cfg_valid;
    assign saved_ready = enabled && (outstanding_count == 0 ||
        (rsp_ready && (response_count != 0 || fg_state == FG_RESP)));
    assign fast_ready = enabled && rsp_ready &&
        g_direct_response_lookup.fast_response_conditions[0] && lookup_snapshot_valid;
    // 空闲名额、已保存响应和当前命中独立准备，接收资格直接归并。
    conv_cache_snapshot_response #(.p_ways(WAYS)) u_ready (
      .i_saved_valid(saved_ready), .i_control_ready(fast_ready),
      .i_snapshot_match(work_snapshot_matches_q), .i_range(work_range),
      .i_hits(work_tag_hits), .o_valid(req_ready)
    );
  end else begin : g_queued_request_ready
    assign req_ready = configured && !clearing && !cfg_valid &&
        (outstanding_count < DQ_CW'(DEMAND_DEPTH) || consumed_response) &&
        (windowed_q || outstanding_count == 0 || consumed_response);
  end
  assign accepted_request=req_valid && req_ready;
  assign consumed_response=rsp_valid && rsp_ready;
  assign incoming_range = !range_below[0] && range_below[1];
  assign incoming_request={req_addr,req_window_epoch,req_window_retire,req_window_progress,
                           cache_set(req_addr, windowed_q && req_window_index_valid, req_window_index),
                           req_geometry,req_event_first,incoming_range};
  // 完整请求保存时同步读取标签和数据，正式接收沿使用对应的读取快照。
  unsigned_compare #(.p_width(32)) u_preview_base (
    .i_a(preview_addr), .i_b(base_q),
    .o_less(preview_below_base), .o_equal(unused_preview_base_equal)
  );
  unsigned_compare #(.p_width(32)) u_preview_end (
    .i_a(preview_addr), .i_b(end_q),
    .o_less(preview_below_end), .o_equal(unused_preview_end_equal)
  );
  always_comb begin
    preview_request = incoming_request;
    preview_request.address = preview_addr;
    preview_request.set_index = cache_set(preview_addr,
        windowed_q && preview_index_valid, preview_index);
    preview_request.in_range = !preview_below_base && preview_below_end;
  end
  // 读取数据来源只依赖已保存的请求状态；预读有效信号独立保存资格。
  // 正式请求等待进入队列时准备其自身地址，空闲或直接处理时准备下一候选。
  assign preview_source_select = p_preview_request && DEMAND_DEPTH == 1 &&
      (!req_valid || (preview_active && req_fire));
  assign lookup_input_request = preview_source_select ? preview_request : incoming_request;
  assign lookup_input_valid = req_valid || (p_preview_request && DEMAND_DEPTH == 1);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) preview_selected_q <= 1'b0;
    else preview_selected_q <= preview_valid && preview_source_select && fg_state != FG_MISS &&
        (request_count == 0 || (req_fire && request_count == DQ_CW'(1)));
  end
  // 空闲请求名额可直接消费前一边沿准备的快照，正式请求仍完整握手。
  assign preview_active = p_preview_request && DEMAND_DEPTH == 1 &&
      req_valid && preview_selected_q && request_count == 0 && outstanding_count == 0 && !cfg_valid;
  always_comb begin
    processing_request = work_request;
    if (preview_active) begin
      processing_request.epoch = incoming_request.epoch;
      processing_request.retire = incoming_request.retire;
      processing_request.progress = incoming_request.progress;
      processing_request.geometry = incoming_request.geometry;
      processing_request.event_first = incoming_request.event_first;
    end
  end
  assign retire_decode_input[0] = processing_request.retire;
  assign retire_decode_input[1] = offer_retire_q;
  if (p_defer_retire_shift) begin : g_retire_shift
    // 接收元数据后完成行释放位置移位，需求和预取分别使用已有接收寄存级。
    // 位[17:0]为被移位数，位[21:18]为右移量，位22表示禁止释放。
    for (genvar retire_port = 0; retire_port < 2; retire_port++) begin : g_port
      logic [8:0] unused_padding;
      logic disabled;
      logic [3:0] shift;
      logic [17:0] row_value;
      logic [31:0] shifted_value;

      assign {unused_padding, disabled, shift, row_value} = retire_decode_input[retire_port];
      assign shifted_value = {14'd0, row_value} >> shift;
      assign retire_decode_output[retire_port] = disabled ? INF : shifted_value;
    end
  end else begin : g_retire_value
    assign retire_decode_output = retire_decode_input;
  end
  // 各个队列位置先比较字地址，最后根据队列状态选择一位结果。
  assign lookup_head_matches = {request_queue[request_head].address[31:2] == work_request.address[31:2],
                                request_queue[request_head].address[31:2] == demand_addr[31:2]};
  assign lookup_next_work_match =
      request_queue[DQ_AW'(request_head + DQ_AW'(1))].address[31:2] == work_request.address[31:2];
  // 两种输入地址并行比较，读取来源仅选择已经形成的单比特结果。
  logic [1:0] lookup_input_matches_parallel;
  logic [1:0][1:0][9:0] lookup_word_group_matches;
  for (genvar word_group = 0; word_group < 10; word_group++) begin : g_input_word_group
    localparam int p_low = 2 + word_group*3;
    assign lookup_word_group_matches[0][0][word_group] =
        incoming_request.address[p_low+:3] == demand_addr[p_low+:3];
    assign lookup_word_group_matches[0][1][word_group] =
        incoming_request.address[p_low+:3] == work_request.address[p_low+:3];
    assign lookup_word_group_matches[1][0][word_group] =
        preview_request.address[p_low+:3] == demand_addr[p_low+:3];
    assign lookup_word_group_matches[1][1][word_group] =
        preview_request.address[p_low+:3] == work_request.address[p_low+:3];
  end
  assign lookup_preview_matches = {&lookup_word_group_matches[1][1], &lookup_word_group_matches[1][0]};
  assign lookup_request_matches = {&lookup_word_group_matches[0][1], &lookup_word_group_matches[0][0]};
  onehot_mux #(.p_choices(2), .p_width(2)) u_input_word_match (
    .i_select({preview_source_select, !preview_source_select}),
    .i_data({lookup_preview_matches, lookup_request_matches}),
    .o_data(lookup_input_matches_parallel)
  );
  always_comb begin
    lookup_input_matches = lookup_input_matches_parallel;
    case (preview_source_select)
      1'b0, 1'b1: begin end
      default: lookup_input_matches =
          {lookup_input_request.address[31:2] == work_request.address[31:2],
           lookup_input_request.address[31:2] == demand_addr[31:2]};
    endcase
  end
  assign lookup_idle_demand_match = request_count == 0 ? lookup_input_matches[0] : lookup_head_matches[0];
  assign lookup_idle_set_match =
      (bypass_q ? demand_fill_set : demand_set) == lookup_read_request.set_index;
  assign lookup_pop_work_match = (request_count == 0 && lookup_input_matches[1]) ||
      (request_count == DQ_CW'(1) && ((lookup_input_valid && lookup_input_matches[1]) ||
                                     (!lookup_input_valid && lookup_head_matches[1]))) ||
      (request_count > DQ_CW'(1) && lookup_next_work_match);
  assign work_word_matches_next = fg_state != FG_MISS || lookup_idle_demand_match;
  assign work_snapshot_matches_next = fg_state != FG_MISS ||
      (lookup_idle_demand_match && lookup_idle_set_match);
  assign response_snapshot_ready = work_snapshot_matches_next && lookup_read_request.in_range;
  assign demand_word_matches_next = fg_state == FG_MISS ?
      (!req_fire || demand_addr[31:2] == work_request.address[31:2]) :
      (req_fire ? lookup_pop_work_match : lookup_idle_demand_match);
  // 单项队列在原查询边沿保存地址、范围边界和来源状态。
  // 范围、字地址与组号比较使用同拍字段，命中控制保持原有响应周期。
  if (DEMAND_DEPTH == 1) begin : g_direct_snapshot_fields
    logic [SI-1:0] expected_set;
    assign expected_set = bypass_q ? demand_fill_set : demand_set;
    conv_cache_snapshot_fields #(.p_set_width(SI), .p_capture_range(1'b1)) u_fields (
      .clk(clk), .i_request(lookup_read_request),
      .i_fg_state(fg_state), .i_request_count(request_count),
      .i_req_fire(req_fire), .i_lookup_input_valid(lookup_input_valid),
      .i_preview_source_select(preview_source_select),
      .i_work_word(work_request.address[31:2]), .i_demand_word(demand_addr[31:2]),
      .i_expected_set(expected_set), .i_base(base_q), .i_end(end_q),
      .i_request_range(incoming_request.in_range),
      .i_head_range(request_queue[request_head].in_range),
`ifndef SYNTHESIS
      .i_reference({response_snapshot_ready, work_snapshot_matches_next,
          work_word_matches_next, demand_word_matches_next, lookup_read_request.in_range}),
`endif
      .o_request(work_request), .o_work_word_matches(work_word_matches_q),
      .o_work_snapshot_matches(work_snapshot_matches_q),
      .o_demand_word_matches(demand_word_matches_q),
      .o_response_snapshot_ready(direct_response_snapshot_ready)
    );
  end else begin : g_queued_snapshot_fields
    always_ff @(posedge clk) begin
      work_request <= lookup_read_request;
      work_word_matches_q <= work_word_matches_next;
      work_snapshot_matches_q <= work_snapshot_matches_next;
      demand_word_matches_q <= demand_word_matches_next;
    end
    assign direct_response_snapshot_ready = 1'b0;
  end
  assign work_range = work_request.in_range;
  assign work_valid=request_count!=0 || preview_active;
  logic work_capacity_ready, work_snapshot_ready;
  // 工作请求的容量和快照资格独立计算，旁路只参与单比特选择。
  assign work_capacity_ready = configured && !clearing &&
      response_count < DQ_CW'(DEMAND_DEPTH) &&
      (fg_state == FG_IDLE || fg_state == FG_RESP);
  always_comb begin
    work_snapshot_ready = bypass_q || (lookup_snapshot_valid && work_snapshot_matches_q);
`ifndef SYNTHESIS
    if ((^bypass_q) === 1'bx)
      work_snapshot_ready = bypass_q || work_lookup_ready;
`endif
  end
  assign work_ready = work_capacity_ready && work_snapshot_ready;
  logic work_fire_parallel;
  conv_cache_request_qualification u_request_qualification (
    .i_available(work_valid && work_capacity_ready), .i_bypass(bypass_q),
    .i_snapshot_valid(lookup_snapshot_valid), .i_snapshot_match(work_snapshot_matches_q),
    .o_fire(work_fire_parallel)
  );
  always_comb begin
    req_fire = work_fire_parallel;
`ifndef SYNTHESIS
    if ((^bypass_q) === 1'bx) req_fire = work_valid && work_ready;
`endif
  end
  assign request_push=accepted_request && !(preview_active && req_fire);
  assign request_pop=request_count!=0 && req_fire;
  // 标签与请求字段共用原查询边沿，返回控制读取保存后的比较结果。
  // 工作地址与缺失地址分别匹配同拍标签，并独立形成命中资格。
  if (DEMAND_DEPTH > 1) begin : g_registered_tag_compare
    // 返回队列提供寄存边界，标签先同步读取，再与同拍保存的请求地址比较。
    for (genvar hit_way = 0; hit_way < WAYS; hit_way++) begin : g_way
      localparam int p_tag_groups = (32 - LB + 2) / 3;
      logic [p_tag_groups-1:0] work_group_matches, demand_group_matches;
      logic work_tag_matches, demand_tag_matches;
      for (genvar tag_group = 0; tag_group < p_tag_groups; tag_group++) begin : g_tag_group
        localparam int p_low = LB + tag_group * 3;
        localparam int p_width = (32 - p_low < 3) ? 32 - p_low : 3;
        assign work_group_matches[tag_group] =
          lookup_tag[hit_way][p_low +: p_width] == work_request.address[p_low +: p_width];
        assign demand_group_matches[tag_group] =
          lookup_tag[hit_way][p_low +: p_width] == demand_addr[p_low +: p_width];
      end
      assign work_tag_matches = &work_group_matches;
      assign demand_tag_matches = &demand_group_matches;
      assign work_tag_hits[hit_way] = valid_lookup[hit_way] && work_tag_matches;
      assign demand_tag_hits[hit_way] = valid_lookup[hit_way] && demand_tag_matches;
    end
  end else begin : g_direct_tag_compare
    logic [WAYS-1:0][31:LB] lookup_tag_raw;
    logic [WAYS-1:0] lookup_valid_next;
    logic [WAYS-1:0][3:0][31:LB] lookup_source_tags;
    logic [WAYS-1:0][3:0] lookup_source_valid_next;
    logic cache_active_q;
    // 配置接收与最后一组清除在原时钟边沿保存运行状态。
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) cache_active_q <= 1'b0;
      else if (cfg_valid && cfg_ready) cache_active_q <= 1'b0;
      else begin
        cache_active_q <= configured && !clearing;
        if (clearing && clear_set == SI'(SETS-1)) cache_active_q <= configured;
      end
    end
    // 单个在途请求与标签在同一读取边沿保存，地址比较使用更新后的请求描述。
    for (genvar hit_way = 0; hit_way < WAYS; hit_way++) begin : g_lookup_tag
      logic lookup_forwarded_valid_q;
      logic work_saved_tag_matches, demand_saved_tag_matches;
      always_ff @(posedge clk) lookup_forwarded_valid_q <= lookup_valid_next[hit_way];
      // 完整标签匹配独立归并，替换状态和响应选择使用已完成的一位结果。
      conv_cache_snapshot_equal #(.p_width(32-LB)) u_work_tag (
        .i_a(lookup_tag[hit_way][31:LB]), .i_b(work_request.address[31:LB]),
        .o_equal(work_saved_tag_matches)
      );
      conv_cache_snapshot_equal #(.p_width(32-LB)) u_demand_tag (
        .i_a(lookup_tag[hit_way][31:LB]), .i_b(demand_addr[31:LB]),
        .o_equal(demand_saved_tag_matches)
      );
      conv_cache_tag_qualification u_work_qualification (
        .i_cache_active(cache_active_q), .i_valid(lookup_forwarded_valid_q),
        .i_tag_match(work_saved_tag_matches), .i_fill_active(g_saved_fill_match.fill_active_q),
        .i_fill_selected(fill_way == WI'(hit_way)),
        .i_fill_set_match(g_saved_fill_match.lookup_fill_set_match_q), .o_hit(work_tag_hits[hit_way])
      );
      conv_cache_tag_qualification u_demand_qualification (
        .i_cache_active(cache_active_q), .i_valid(lookup_forwarded_valid_q),
        .i_tag_match(demand_saved_tag_matches), .i_fill_active(g_saved_fill_match.fill_active_q),
        .i_fill_selected(fill_way == WI'(hit_way)),
        .i_fill_set_match(g_saved_fill_match.lookup_fill_set_match_q), .o_hit(demand_tag_hits[hit_way])
      );
    end
  end
  if (DEMAND_DEPTH == 1) begin : g_direct_response_lookup
    logic [READ_WIDTH-1:0] fast_hit_data;
    always_comb begin
      // 有效命中至少包含一路，较高路号继续保持优先选择。
      fast_hit_data = speculative_data[0];
      for (int hit_way = 1; hit_way < WAYS; hit_way++) begin
        if (work_tag_hits[hit_way]) begin
          fast_hit_data = speculative_data[hit_way];
        end
      end
    end
    logic [1:0] fast_response_conditions;
    logic response_snapshot_ready_q;
    // 范围与字匹配由同拍保存的原始字段形成，有效位独立控制响应资格。
    assign response_snapshot_ready_q = direct_response_snapshot_ready;
    // 请求、快照和命中状态并行合并，运行与填充状态使用独立保存的资格位。
    assign fast_response_conditions[0] = fg_state == FG_IDLE && !bypass_q &&
        work_valid && response_count < DQ_CW'(DEMAND_DEPTH);
    assign fast_response_conditions[1] = lookup_snapshot_valid && response_snapshot_ready_q;
    assign fast_hit_response = (&fast_response_conditions) && (|work_tag_hits);
    // 空闲阶段的有效响应使用命中数据，数据选择与命中接收资格并行。
    assign core_rsp_data=fg_state == FG_IDLE ? fast_hit_data :
                         response_error ? '0 : ram_rdata;
  end else begin : g_queued_response_lookup
    logic fast_control_ready, fast_snapshot_ready;
    // 队列容量、快照资格与数据命中并行检查，共用原有返回寄存边沿。
    assign fast_control_ready = fg_state == FG_IDLE && configured && !clearing &&
        work_valid && response_count < DQ_CW'(DEMAND_DEPTH);
    assign fast_snapshot_ready = lookup_snapshot_valid && work_snapshot_matches_q;
    always_comb begin
      fast_hit_response = fast_control_ready && fast_snapshot_ready &&
          work_range && !bypass_q && (|work_tag_hits);
`ifndef SYNTHESIS
      // 控制状态含未知值时，按完整查询条件计算四态结果。
      if ((^{fg_state, bypass_q}) === 1'bx)
        fast_hit_response = fg_state == FG_IDLE && req_fire && lookup_range && lookup_hit;
`endif
    end
    assign core_rsp_data = fast_hit_response ? speculative_data[lookup_way] :
                           response_error ? '0 : ram_rdata;
  end
  assign core_rsp_valid=fg_state==FG_RESP || fast_hit_response;
  assign core_rsp_error = fast_hit_response ? 1'b0 : response_error;
  assign core_rsp_ready=response_count<DQ_CW'(DEMAND_DEPTH) ||
                        (response_count!=0 && rsp_ready);
  if (DEMAND_DEPTH > 1) begin : g_registered_response
    // 完成结果先写入返回队列，数据、错误状态和有效位跨越同一时钟边界。
    // 两个以上在途名额可同时接收请求、保存结果和返回前一个结果。
    assign rsp_valid = response_count != 0;
    assign rsp_data = response_queue_data[response_head];
    assign rsp_error = response_queue_error[response_head];
    assign response_push = core_rsp_valid && core_rsp_ready;
    assign rsp_success = rsp_valid && !rsp_error;
    assign rsp_failure = rsp_valid && rsp_error;
  end else begin : g_single_response
    // 单个在途名额保持同步读出后的直接返回，以维持每周期一个字的吞吐率。
    conv_cache_snapshot_response #(.p_ways(WAYS)) u_valid (
      .i_saved_valid(response_count != 0 || fg_state == FG_RESP),
      .i_control_ready(g_direct_response_lookup.fast_response_conditions[0] && lookup_snapshot_valid),
      .i_snapshot_match(work_snapshot_matches_q), .i_range(work_range),
      .i_hits(work_tag_hits), .o_valid(rsp_valid)
    );
    logic [WAYS-1:0][READ_WIDTH-1:0] response_data_by_way;
    // 各路分别准备队列、命中和普通响应数据，较晚的命中位只选择完整结果。
    for (genvar response_way = 0; response_way < WAYS; response_way++) begin : g_response_way
      assign response_data_by_way[response_way] = response_count != 0 ?
          response_queue_data[response_head] :
          (fg_state == FG_IDLE ? speculative_data[response_way] :
           (response_error ? '0 : ram_rdata));
    end
    conv_cache_response_data_select #(.p_ways(WAYS), .p_width(READ_WIDTH)) u_data (
      .i_hits(work_tag_hits), .i_data(response_data_by_way), .o_data(rsp_data)
    );
    assign rsp_error = response_count != 0 ? response_queue_error[response_head] : core_rsp_error;
    assign response_push = core_rsp_valid && core_rsp_ready && (response_count != 0 || !rsp_ready);
    logic saved_success, parallel_success;
    assign saved_success = (response_count != 0 && !response_queue_error[response_head]) ||
        (response_count == 0 && fg_state == FG_RESP && !response_error);
    conv_cache_snapshot_response #(.p_ways(WAYS)) u_success (
      .i_saved_valid(saved_success),
      .i_control_ready(g_direct_response_lookup.fast_response_conditions[0] && lookup_snapshot_valid),
      .i_snapshot_match(work_snapshot_matches_q), .i_range(work_range),
      .i_hits(work_tag_hits), .o_valid(parallel_success)
    );
    // 命中、已保存响应和普通响应并行形成传输资格，错误选择独立于命中有效。
    always_comb begin
      rsp_success = parallel_success;
      rsp_failure = (response_count != 0 && response_queue_error[response_head]) ||
          (response_count == 0 && fg_state == FG_RESP && response_error);
      case (^{response_count, fg_state, fast_hit_response, response_error,
               response_queue_error[response_head]})
        1'b0, 1'b1: begin end
        default: begin
          rsp_success = rsp_valid && !rsp_error;
          rsp_failure = rsp_valid && rsp_error;
        end
      endcase
    end
  end
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
  assign pf_retire_ready=pf_pending && (pf_hit || pf_in_flight || range_below[2] || !range_below[3] ||
                              (select_launch && select_prefetch));
  assign pf_pop=pf_pending && pf_retire_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pf_retire_q <= 1'b0;
    else if (cfg_valid && cfg_ready) pf_retire_q <= 1'b0;
    else pf_retire_q <= pf_retire_ready;
  end
  assign fill_complete=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  assign fill_success=fill_complete && !fill_bad && !span_error;
  logic completion_tag_matches, unused_completion_less;
  // 完整标签在独立组合层次内并行比较，填充资格只在末级合并。
  parallel_unsigned_compare #(.p_width(32-LB)) u_completion_tag (
    .i_a(demand_addr[31:LB]), .i_b(fill_addr[31:LB]),
    .o_less(unused_completion_less), .o_equal(completion_tag_matches)
  );
  assign completing_demand=fill_success && fg_state==FG_MISS &&
    completion_tag_matches && (bypass_q || demand_set==fill_set);

  // 逻辑位置保留预取优先次序；物理位置只在接收新描述时写入数据。
  // 移除非队首项时交换位置映射，整个描述不经过复制多路选择器。
  assign pf_push_slot = pf_slot_map_q[pf_tail];
  assign pf_pop_slot = pf_slot_map_q[pf_pick];
  // 代次比较与需求接收及预取写入同时保存，选择活动项时直接读取比较结果。
  conv_cache_snapshot_equal #(.p_width(32)) u_offer_work_epoch (
    .i_a(pf_offer_epoch), .i_b(processing_request.epoch), .o_equal(pf_offer_matches_work)
  );
  conv_cache_snapshot_equal #(.p_width(32)) u_offer_demand_epoch (
    .i_a(pf_offer_epoch), .i_b(demand_epoch), .o_equal(pf_offer_matches_demand)
  );
  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_prefetch_valid
    logic slot_work_epoch_matches, slot_epoch_next;
    conv_cache_snapshot_equal #(.p_width(32)) u_slot_work_epoch (
      .i_a(prefetch_keys_o_rd_data[slot][31:0]), .i_b(processing_request.epoch),
      .o_equal(slot_work_epoch_matches)
    );
    conv_cache_prefetch_epoch_value u_epoch_value (
      .i_push(pf_push && pf_push_slot == PF_AW'(slot)), .i_fire(req_fire),
      .i_offer_work(pf_offer_matches_work), .i_offer_demand(pf_offer_matches_demand),
      .i_slot_work(slot_work_epoch_matches), .o_value(slot_epoch_next)
    );
`ifndef ASIC_SYNTHESIS
    assign prefetch_keys_i_rd_addr[slot] = PF_AW'(slot);
`endif
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        pf_slot_valid[slot] <= 1'b0;
        pf_physical_valid_q[slot] <= 1'b0;
        pf_epoch_matches[slot] <= 1'b0;
        pf_slot_map_q[slot] <= PF_AW'(slot);
      end else if (cfg_valid && cfg_ready) begin
        pf_slot_valid[slot] <= 1'b0;
        pf_physical_valid_q[slot] <= 1'b0;
        pf_epoch_matches[slot] <= 1'b0;
        pf_slot_map_q[slot] <= PF_AW'(slot);
      end else begin
        if (pf_pop && pf_head == PF_AW'(slot)) pf_slot_valid[slot] <= 1'b0;
        if (pf_push && pf_tail == PF_AW'(slot)) pf_slot_valid[slot] <= 1'b1;
        if (pf_pop && pf_pop_slot == PF_AW'(slot)) pf_physical_valid_q[slot] <= 1'b0;
        if (pf_push && pf_push_slot == PF_AW'(slot)) pf_physical_valid_q[slot] <= 1'b1;
        // 同周期接收新需求和新预取时，比较两份新代次；其余有效项跟随需求代次更新。
        if (pf_push && pf_push_slot == PF_AW'(slot))
          pf_epoch_matches[slot] <= slot_epoch_next;
        else if (req_fire)
          pf_epoch_matches[slot] <= slot_epoch_next;
        if (pf_pop && pf_pick != pf_head) begin
          if (pf_head == PF_AW'(slot)) pf_slot_map_q[slot] <= pf_slot_map_q[pf_pick];
          else if (pf_pick == PF_AW'(slot)) pf_slot_map_q[slot] <= pf_slot_map_q[pf_head];
        end
      end
    end
  end
  assign prefetch_keys_i_wr_en = pf_push;
  assign prefetch_keys_i_wr_addr = pf_push_slot;
  assign prefetch_keys_i_wr_data = {pf_offer_addr, pf_offer_epoch};
`ifdef ASIC_SYNTHESIS
  // 每个物理槽位保存一份地址和代次，固定槽位比较与活动项读取共享内容。
  // 异步读取保持当前周期的选择结果，写入仍只发生在预取入队时。
  logic [63:0] prefetch_key_entries [PF_DEPTH];
  always_ff @(posedge clk) begin
    if (prefetch_keys_i_wr_en)
      prefetch_key_entries[prefetch_keys_i_wr_addr] <= prefetch_keys_i_wr_data;
  end
  for (genvar key_slot=0; key_slot<PF_DEPTH; key_slot++) begin : g_prefetch_key_output
    assign prefetch_keys_o_rd_data[key_slot] = prefetch_key_entries[key_slot];
  end
  assign pf_selected_keys = prefetch_key_entries[pf_read_slot];
`else
  assign prefetch_keys_i_wr_mask = 1'b1;
  assign prefetch_keys_i_rd_en = '1;
  // 活动预取项使用独立读取端口，固定位置比较继续并行读取各项关键字段。
  // 两份存储共用同一写入事件，同步接收寄存级并入行为级块存储器读取。
  regfile #(
    .p_data_width(64), .p_depth(PF_DEPTH), .p_addr_width(PF_AW),
    .p_write_unit(64), .p_read_ports(1), .p_sync_read(1'b0), .p_ram_style("block")
  ) u_prefetch_selected (
    .clk(clk), .i_wr_en(prefetch_keys_i_wr_en), .i_wr_addr(prefetch_keys_i_wr_addr),
    .i_wr_data(prefetch_keys_i_wr_data), .i_wr_mask(prefetch_keys_i_wr_mask),
    .i_rd_en(1'b1), .i_rd_addr(pf_read_slot), .o_rd_data(pf_selected_keys)
  );
  regfile #(
    .p_data_width(64), .p_depth(PF_DEPTH), .p_addr_width(PF_AW),
    .p_write_unit(64), .p_read_ports(PF_DEPTH), .p_sync_read(1'b0)
  ) u_prefetch_keys (
    .clk(clk), .i_wr_en(prefetch_keys_i_wr_en), .i_wr_addr(prefetch_keys_i_wr_addr),
    .i_wr_data(prefetch_keys_i_wr_data), .i_wr_mask(prefetch_keys_i_wr_mask),
    .i_rd_en(prefetch_keys_i_rd_en), .i_rd_addr(prefetch_keys_i_rd_addr), .o_rd_data(prefetch_keys_o_rd_data)
  );
`endif
  assign prefetch_payload_i_wr_en = pf_push;
  assign prefetch_payload_i_wr_addr = pf_push_slot;
  assign prefetch_payload_i_wr_data = {pf_offer_index_valid, pf_offer_index, pf_offer_retire};
  assign prefetch_payload_i_wr_mask = 1'b1;
  assign prefetch_payload_i_rd_en = 1'b1;
  assign prefetch_payload_i_rd_addr = pf_read_slot;
  // 缓存行释放序号与索引独立存储，原有接收寄存级并入释放序号的块 RAM。
  // 两个存储体共用地址和写使能，完整保留每项 65 位描述及其读取周期。
  assign prefetch_retire_i_wr_en = prefetch_payload_i_wr_en;
  assign prefetch_retire_i_wr_addr = prefetch_payload_i_wr_addr;
  assign prefetch_retire_i_wr_data = prefetch_payload_i_wr_data[31:0];
  assign prefetch_retire_i_wr_mask = prefetch_payload_i_wr_mask;
  assign prefetch_retire_i_rd_en[0] = prefetch_payload_i_rd_en;
  assign prefetch_retire_i_rd_addr[0] = prefetch_payload_i_rd_addr;
  assign prefetch_payload_o_rd_data[31:0] = prefetch_retire_o_rd_data[0];
  regfile #(
    .p_data_width(32), .p_depth(PF_DEPTH), .p_addr_width(PF_AW),
    .p_write_unit(32), .p_read_ports(1), .p_sync_read(1'b0), .p_ram_style("block")
  ) u_prefetch_retire (
    .clk(clk), .i_wr_en(prefetch_retire_i_wr_en), .i_wr_addr(prefetch_retire_i_wr_addr),
    .i_wr_data(prefetch_retire_i_wr_data), .i_wr_mask(prefetch_retire_i_wr_mask),
    .i_rd_en(prefetch_retire_i_rd_en), .i_rd_addr(prefetch_retire_i_rd_addr),
    .o_rd_data(prefetch_retire_o_rd_data)
  );
  assign prefetch_index_i_wr_en = prefetch_payload_i_wr_en;
  assign prefetch_index_i_wr_addr = prefetch_payload_i_wr_addr;
  assign prefetch_index_i_wr_data = prefetch_payload_i_wr_data[64:32];
  assign prefetch_index_i_wr_mask = prefetch_payload_i_wr_mask;
  assign prefetch_index_i_rd_en[0] = prefetch_payload_i_rd_en;
  assign prefetch_index_i_rd_addr[0] = prefetch_payload_i_rd_addr;
  assign prefetch_payload_o_rd_data[64:32] = prefetch_index_o_rd_data[0];
  regfile #(
    .p_data_width(33), .p_depth(PF_DEPTH), .p_addr_width(PF_AW),
    .p_write_unit(33), .p_read_ports(1), .p_sync_read(1'b0), .p_ram_style("block")
  ) u_prefetch_index (
    .clk(clk), .i_wr_en(prefetch_index_i_wr_en), .i_wr_addr(prefetch_index_i_wr_addr),
    .i_wr_data(prefetch_index_i_wr_data), .i_wr_mask(prefetch_index_i_wr_mask),
    .i_rd_en(prefetch_index_i_rd_en), .i_rd_addr(prefetch_index_i_rd_addr),
    .o_rd_data(prefetch_index_o_rd_data)
  );
  // 从队首开始循环查找第一个代次匹配项，无匹配时选择队首。
  // 固定逻辑位置只检查一次代次，各位置并行检查循环次序中更早的匹配项。
  for (genvar slot = 0; slot < PF_DEPTH; slot++) begin : g_prefetch_match
    assign pf_current_by_slot[slot] = pf_slot_valid[slot] &&
        pf_epoch_matches[pf_slot_map_q[slot]];
  end
  for (genvar slot = 0; slot < PF_DEPTH; slot++) begin : g_prefetch_priority
    logic [PF_DEPTH-1:0] preceding_matches;
    for (genvar other = 0; other < PF_DEPTH; other++) begin : g_preceding
      if (other < slot) begin : g_lower
        assign preceding_matches[other] = pf_current_by_slot[other] &&
            ((pf_head <= PF_AW'(other)) ||
             ((slot == PF_DEPTH-1) ? 1'b0 : pf_head > PF_AW'(slot)));
      end else if (other > slot) begin : g_higher
        assign preceding_matches[other] = pf_current_by_slot[other] &&
            ((pf_head > PF_AW'(slot)) &&
             ((other == PF_DEPTH-1) ? 1'b1 : pf_head <= PF_AW'(other)));
      end else begin : g_self
        assign preceding_matches[other] = 1'b0;
      end
    end
    assign pf_pick_by_slot[slot] = (pf_current_by_slot[slot] && !(|preceding_matches)) ||
        (!(|pf_current_by_slot) && pf_head == PF_AW'(slot));
  end
  for (genvar bit_index = 0; bit_index < PF_AW; bit_index++) begin : g_prefetch_encode
    logic [PF_DEPTH-1:0] logical_bits, physical_bits;
    for (genvar slot = 0; slot < PF_DEPTH; slot++) begin : g_slot
      localparam logic [PF_AW-1:0] p_slot = PF_AW'(slot);
      assign logical_bits[slot] = pf_pick_by_slot[slot] && p_slot[bit_index];
      assign physical_bits[slot] = pf_pick_by_slot[slot] && pf_slot_map_q[slot][bit_index];
    end
    assign pf_pick_comb[bit_index] = |logical_bits;
    assign pf_read_slot[bit_index] = |physical_bits;
  end

  assign lookup_addr = fg_state==FG_MISS ? demand_addr : work_request.address;
  assign lookup_set = bypass_q ? demand_fill_set :
      (fg_state==FG_MISS ? demand_set : work_request.set_index);
  assign lookup_range = fg_state == FG_MISS ? demand_range : work_range;
  assign pf_set = cache_set(pf_addr, windowed_q && pf_index_valid, pf_index);

  if (DEMAND_DEPTH == 1) begin : g_direct_read_source
    logic read_input;
    logic [2:0] source_select;
    logic [2:0][$bits(demand_t)-1:0] source_data;
    demand_t parallel_request;
    assign read_input = request_count == 0 ||
        (fg_state != FG_MISS && req_fire && lookup_input_valid);
    assign source_select = {read_input && preview_source_select,
        read_input && !preview_source_select, !read_input};
    assign source_data = {preview_request, incoming_request, request_queue[request_head]};
    onehot_mux #(.p_choices(3), .p_width($bits(demand_t))) u_source (
      .i_select(source_select), .i_data(source_data), .o_data(parallel_request)
    );
    always_comb begin
      lookup_read_request = parallel_request;
`ifndef SYNTHESIS
      if ((^{fg_state, req_fire, lookup_input_valid, request_count,
             preview_source_select, source_data}) === 1'bx) begin
        lookup_read_request = request_count == 0 ? lookup_input_request : request_queue[request_head];
        if (fg_state != FG_MISS && req_fire && request_count != 0 && lookup_input_valid)
          lookup_read_request = lookup_input_request;
      end
`endif
    end
  end else begin : g_queued_read_source
    always_comb begin
      lookup_read_request = request_count==0 ? lookup_input_request : request_queue[request_head];
      if (fg_state != FG_MISS && req_fire && request_count != 0) begin
        if (request_count > DQ_CW'(1))
          lookup_read_request = request_queue[DQ_AW'(request_head + DQ_AW'(1))];
        else if (lookup_input_valid)
          lookup_read_request = lookup_input_request;
      end
    end
  end
  always_comb begin
    lookup_read_set = fg_state==FG_MISS ? lookup_set :
        lookup_read_request.set_index;
    lookup_read_word = fg_state==FG_MISS ? demand_addr[31:2] : lookup_read_request.address[31:2];
  end
  logic [3:0][31:2] lookup_candidate_word;
  logic [3:0] lookup_candidate_fill_match, lookup_candidate_conflict;
  logic lookup_fill_match, lookup_snapshot_good;
  logic metadata_enable, metadata_fill_good;
  logic [1:0] lookup_candidate_select;
  // 四个位置独立读取有效位，出队状态只选择已经形成的单比特结果。
  assign lookup_candidate_set[0] = request_queue[request_head].set_index;
  assign lookup_candidate_set[1] = request_queue[DQ_AW'(request_head + DQ_AW'(1))].set_index;
  assign lookup_candidate_set[2] = lookup_input_request.set_index;
  assign lookup_candidate_set[3] = bypass_q ? demand_fill_set : demand_set;
  assign lookup_input_set = {preview_request.set_index, incoming_request.set_index};
  assign lookup_candidate_word[0] = request_queue[request_head].address[31:2];
  assign lookup_candidate_word[1] = request_queue[DQ_AW'(request_head + DQ_AW'(1))].address[31:2];
  assign lookup_candidate_word[2] = lookup_input_request.address[31:2];
  assign lookup_candidate_word[3] = demand_addr[31:2];
  always_comb begin
    lookup_candidate_select = request_count == 0 ? 2'd2 : 2'd0;
    if (fg_state != FG_MISS && req_fire && request_count != 0) begin
      if (request_count > DQ_CW'(1)) lookup_candidate_select = 2'd1;
      else if (lookup_input_valid) lookup_candidate_select = 2'd2;
    end
    if (fg_state == FG_MISS) lookup_candidate_select = 2'd3;
  end
  // 保存后的填充组号和查询组号直接比较，保持各自的更新和暂停条件。
  if (DEMAND_DEPTH == 1) begin : g_saved_fill_match
    logic lookup_fill_set_match_q, fill_active_q, next_fill_active;
    always_ff @(posedge clk) fill_active_q <= next_fill_active;
    // 填充活动状态独立保存，最后数据拍与下一填充可以同时发生。
    always_comb begin
      next_fill_active = fill_state != F_IDLE;
      if (!rst_n) next_fill_active = 1'b0;
      else if (cfg_valid && cfg_ready) begin
      end else begin
        if (select_launch || bypass_launch) next_fill_active = 1'b1;
        if (fill_state == F_DATA && span_rsp_valid && span_rsp_ready && span_last)
          next_fill_active = select_launch;
      end
    end
    assign lookup_fill_set_match_q = fill_set == lookup_snapshot_set;
  end
  // 两种请求分别匹配已有快照，队首出队直接使用工作请求的匹配结果。
  conv_cache_work_lookup u_work_lookup (
    .i_valid(lookup_snapshot_valid), .i_bypass(bypass_q),
    .i_set_match(lookup_snapshot_set == demand_fill_set),
    .i_word_match(work_word_matches_q), .i_snapshot_match(work_snapshot_matches_q),
    .o_ready(work_lookup_ready)
  );
  conv_cache_metadata_eligibility u_demand_lookup (
    .i_conditions({lookup_snapshot_valid,
        lookup_snapshot_set == (bypass_q ? demand_fill_set : demand_set),
        demand_word_matches_q, 2'b11}),
    .o_eligible(demand_lookup_ready)
  );
  assign lookup_ready = fg_state == FG_MISS ? demand_lookup_ready : work_lookup_ready;

  conv_cache_lookup_hit #(.p_ways(WAYS)) u_lookup_hit (
    .i_bypass(bypass_q), .i_miss(fg_state == FG_MISS), .i_filled(demand_filled),
    .i_demand_ready(demand_lookup_ready), .i_work_ready(work_lookup_ready),
    .i_demand_hits(demand_tag_hits), .i_work_hits(work_tag_hits), .o_hit(lookup_hit)
  );
  always_comb begin
    lookup_way = '0;
    for (int way = 0; way < WAYS; way++)
      if (lookup_ready && (fg_state == FG_MISS ? demand_tag_hits[way] : work_tag_hits[way]))
        lookup_way = WI'(way);
    if (bypass_q) lookup_way = demand_fill_way;
  end

  localparam int p_prefetch_fill_tag_groups = (32-LB+2)/3;
  logic [p_prefetch_fill_tag_groups-1:0] prefetch_fill_tag_matches;
  // 预取地址和在途填充地址按独立分组比较，末级只合并相等结果。
  for (genvar tag_group=0; tag_group<p_prefetch_fill_tag_groups; tag_group++) begin : g_prefetch_fill_tag
    localparam int p_low = LB+tag_group*3;
    localparam int p_width = 32-p_low<3 ? 32-p_low : 3;
    assign prefetch_fill_tag_matches[tag_group] =
        pf_addr[p_low+:p_width] == fill_addr[p_low+:p_width];
  end
  always_comb begin
    pf_hit_raw=0;
    for (int w=0;w<WAYS;w++)
      if (pf_lookup_ready && valid_prefetch[w] && pf_tag[w]==pf_addr[31:LB]) pf_hit_raw=1;
    pf_in_flight=fill_state!=F_IDLE && (&prefetch_fill_tag_matches);
    pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==offer_addr_q[31:LB];
    for (int w=0;w<WAYS;w++)
      if (valid_incoming[w] && incoming_tag[w]==offer_addr_q[31:LB]) pf_duplicate=1;
    for (int i=0;i<PF_DEPTH;i++)
      if (pf_physical_valid_q[i] && prefetch_keys_o_rd_data[i][63:32+LB]==offer_addr_q[31:LB]) pf_duplicate=1;
    offer_choose_next = pf_duplicate && offer_next_fragment_q;
    if (offer_choose_next) begin
      pf_duplicate=fill_state!=F_IDLE && fill_addr[31:LB]==offer_next_addr_q[31:LB];
      for (int w=0;w<WAYS;w++)
        if (valid_next[w] && next_tag[w]==offer_next_addr_q[31:LB]) pf_duplicate=1;
      for (int i=0;i<PF_DEPTH;i++)
        if (pf_physical_valid_q[i] && prefetch_keys_o_rd_data[i][63:32+LB]==offer_next_addr_q[31:LB]) pf_duplicate=1;
    end

  end
  assign pf_offer_addr = offer_select_next_q ? offer_next_addr_q : offer_addr_q;
  assign pf_offer_epoch = offer_select_next_q ? offer_next_epoch_q : offer_epoch_q;
  assign pf_offer_retire = offer_select_next_q ? offer_next_retire_q : retire_decode_output[1];
  assign pf_offer_index = offer_select_next_q ? offer_next_index_q : offer_index_q;
  assign pf_offer_index_valid = offer_select_next_q ? offer_next_index_valid_q : offer_index_valid_q;

  wire demand_candidate = !bypass_q && fg_state==FG_MISS &&
      !range_below[4] && range_below[5] && !completing_demand;
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
               !range_below[2] && range_below[3]) select_launch_candidate=1;
    end
  end

  localparam int p_address_compare_groups = (32 + 2) / 3;
  logic [p_address_compare_groups-1:0] select_demand_address_match;
  logic [p_address_compare_groups-1:0] select_prefetch_address_match;
  // 请求身份按固定小组并行比较，状态资格在完整比较之后合并。
  for (genvar group_index = 0; group_index < p_address_compare_groups; group_index++) begin : g_select_address
    localparam int p_low = group_index * 3;
    localparam int p_width = 32 - p_low < 3 ? 32 - p_low : 3;
    assign select_demand_address_match[group_index] =
        demand_addr[p_low +: p_width] == select_addr[p_low +: p_width];
    assign select_prefetch_address_match[group_index] =
        pf_addr[p_low +: p_width] == select_addr[p_low +: p_width];
  end
  logic select_fill_capacity_ready, select_prefetch_ready, select_demand_ready;
  logic select_victim_conflict;
  logic select_request_set_match, select_hint_busy;
  logic select_prefetch_blocked, select_demand_blocked;
  wire metadata_fill;

  // 请求组号、提示冲突和命中结果并行准备，需求接收只在最后一级参与选择。
  // 预取同时检查同组访问和需求缺失，普通填充只检查同组访问。
  assign select_request_set_match = lookup_set == select_set;
  assign select_hint_busy = hint_pending_q && hint_effective_valid && hint_set == select_set;
  conv_cache_select_busy #(.p_prefetch(1'b1)) u_prefetch_busy (
    .i_hint_busy(select_hint_busy), .i_fire(req_fire),
    .i_set_match(select_request_set_match), .i_hit(lookup_hit), .o_busy(select_prefetch_blocked)
  );
  conv_cache_select_busy #(.p_prefetch(1'b0)) u_demand_busy (
    .i_hint_busy(select_hint_busy), .i_fire(req_fire),
    .i_set_match(select_request_set_match), .i_hit(lookup_hit), .o_busy(select_demand_blocked)
  );
  always_comb begin
    select_fill_capacity_ready = select_stage_valid && select_decision_valid &&
        (fill_state == F_IDLE || (fill_success && fill_set != select_set));
`ifndef SYNTHESIS
    if ((^{fill_state, fill_success}) === 1'bx)
      select_fill_capacity_ready = select_stage_valid && select_decision_valid &&
          !(metadata_fill && fill_set == select_set) && (fill_state == F_IDLE || fill_success);
`endif
  end
  assign select_prefetch_ready = pf_pending && pf_match_ready && (&select_prefetch_address_match) &&
      !pf_hit && !pf_in_flight;
  logic select_demand_snapshot_ready, select_demand_request_ready;
  // 替换需求直接检查保存的需求字段，前台状态在末级选择是否使用该结果。
  assign select_demand_snapshot_ready = bypass_q ||
      (lookup_snapshot_valid && lookup_snapshot_set == demand_set && demand_word_matches_q);
  assign select_demand_request_ready = fg_state == FG_MISS &&
      (&select_demand_address_match) && demand_range;
  always_comb begin
    select_demand_ready = select_demand_request_ready &&
        select_demand_snapshot_ready && !completing_demand;
`ifndef SYNTHESIS
    if ((^{fg_state, bypass_q}) === 1'bx)
      select_demand_ready = fg_state == FG_MISS && demand_addr == select_addr &&
          (bypass_q || lookup_ready) && lookup_range && !completing_demand;
`endif
  end
  logic [WAYS-1:0] demand_selected_victim;
  // 命中路号与目标路直接比较，保留较高路号优先的选择次序。
  for (genvar victim_way = 0; victim_way < WAYS; victim_way++) begin : g_victim_match
    logic higher_way_hit;
    if (victim_way == WAYS-1) begin : g_last
      assign higher_way_hit = 1'b0;
    end else begin : g_lower
      assign higher_way_hit = |demand_tag_hits[WAYS-1:victim_way+1];
    end
    assign demand_selected_victim[victim_way] = demand_tag_hits[victim_way] &&
        !higher_way_hit && select_way == WI'(victim_way);
  end
  logic demand_victim_eligible, bypass_victim_eligible, victim_conflict_parallel;
  conv_cache_metadata_eligibility u_demand_victim (
    .i_conditions({fg_state == FG_MISS, demand_lookup_ready, !bypass_q,
        select_set == demand_set, 1'b1}), .o_eligible(demand_victim_eligible)
  );
  conv_cache_metadata_eligibility #(.p_conditions(6)) u_bypass_victim (
    .i_conditions({fg_state == FG_MISS, demand_lookup_ready, bypass_q, demand_filled,
        select_set == demand_fill_set, select_way == demand_fill_way}),
    .o_eligible(bypass_victim_eligible)
  );
  conv_cache_victim_qualification #(.p_ways(WAYS)) u_victim_qualification (
    .i_demand_eligible(demand_victim_eligible), .i_bypass_eligible(bypass_victim_eligible),
    .i_selected_hits(demand_selected_victim), .o_conflict(victim_conflict_parallel)
  );
  always_comb begin
    select_victim_conflict = victim_conflict_parallel;
`ifndef SYNTHESIS
    // 未知地址与命中结果使用逐路选择的四态结果。
    if ((^{fg_state, bypass_q, demand_tag_hits, demand_lookup_ready,
           select_way, demand_fill_way, select_set, lookup_set}) === 1'bx) begin
      select_victim_conflict = fg_state == FG_MISS && lookup_hit &&
          select_set == lookup_set && select_way == lookup_way;
    end
`endif
  end
  logic select_launch_eligible;
  // 替换请求及占用条件提前合并，填充完成只参与最终发送资格。
  assign select_launch_eligible = !select_victim_conflict &&
      ((select_prefetch && select_prefetch_ready && !select_prefetch_blocked) ||
       (!select_prefetch && select_demand_ready && !lookup_hit && !select_demand_blocked));
  always_comb begin
    select_launch = select_fill_capacity_ready && select_launch_eligible;
    case (^{select_fill_capacity_ready, select_prefetch, select_prefetch_ready,
             select_prefetch_blocked, select_demand_ready, lookup_hit,
             select_demand_blocked, select_victim_conflict})
      1'b0, 1'b1: begin end
      default: begin
        select_launch = select_fill_capacity_ready &&
            (select_prefetch ? (select_prefetch_ready && !select_prefetch_blocked) :
                               (select_demand_ready && !lookup_hit && !select_demand_blocked));
        if (select_launch && select_victim_conflict) select_launch = 1'b0;
      end
    endcase
    select_way_next=0;farthest=select_ranks[0];
    for (int w=1;w<WAYS;w++)
      if (WAYS == 2 ? !rank_one_below_zero : select_ranks[w] >= farthest) begin
        farthest=select_ranks[w];select_way_next=WI'(w);
      end
    if (windowed_q)
      for (int w=WAYS-1;w>=0;w--)
        if (valid_select[w] &&
            ((select_epochs[w]!=EPOCH_W'(select_epoch) &&
              (!select_prefetch || select_epochs[w]!=EPOCH_W'(demand_epoch))) ||
             (select_epochs[w]==EPOCH_W'(select_epoch) && rank_before_progress[w]))) begin
          select_way_next=WI'(w);
        end
    for (int w=WAYS-1;w>=0;w--)
      if (!valid_select[w]) begin select_way_next=WI'(w);end
    ram_ren=(req_fire && lookup_range && lookup_hit) ||
            (fg_state==FG_MISS && lookup_hit);
  end
  // 缺失请求与预取分别准备完整填充地址，状态只选择对应地址。
  assign select_line_base=bypass_q ? {select_addr[31:p_read_shift],{p_read_shift{1'b0}}} : {select_addr[31:LB],{LB{1'b0}}};
  assign select_first=range_below[10] ? base_q : select_line_base;
  // 自然对齐的下一边界与张量上界并行计算，旁路只选择完整结果。
  for (genvar fill_mode=0; fill_mode<2; fill_mode++) begin : g_fill_end
    localparam int p_shift = fill_mode == 0 ? LB : p_read_shift;
    localparam int p_index_width = 32-p_shift;
    logic [p_index_width-1:0] line_index, next_line_index;
    logic line_before_limit, unused_limit_equal, unused_index_carry;
    assign line_index = fill_mode == 0 ? select_addr[31:p_shift] : demand_addr[31:p_shift];
    parallel_prefix_add #(
      .p_width(p_index_width), .p_group_width(4), .p_preserve_groups(1'b1)
    ) u_next_line (
      .i_a(line_index), .i_b({p_index_width{1'b0}}), .i_carry(1'b1),
      .o_sum(next_line_index), .o_carry(unused_index_carry)
    );
    unsigned_compare #(.p_width(p_index_width)) u_line_limit (
      .i_a(line_index), .i_b(end_q[31:p_shift]),
      .o_less(line_before_limit), .o_equal(unused_limit_equal)
    );
    assign fill_end_candidates[fill_mode] = line_before_limit ?
        {next_line_index, {p_shift{1'b0}}} : end_q;
  end
  always_comb begin
    fill_candidate_end = bypass_q ? fill_end_candidates[1] : fill_end_candidates[0];
    case (^{bypass_q, select_addr, demand_addr, end_q})
      1'b0, 1'b1: begin end
      default: begin
        logic [31:0] selected_line_base;
        logic [32:0] selected_end_wide;
        // 未知输入保留完整三十三位加法及上界比较的传播。
        selected_line_base = bypass_q ?
            {demand_addr[31:p_read_shift], {p_read_shift{1'b0}}} : {select_addr[31:LB], {LB{1'b0}}};
        selected_end_wide = {1'b0, selected_line_base} + 33'(bypass_q ? p_read_bytes : LINE_BYTES);
        fill_candidate_end = selected_end_wide > {1'b0, end_q} ? end_q : selected_end_wide[31:0];
      end
    endcase
  end
  assign ram_wen=fill_state==F_DATA && span_rsp_valid && span_rsp_ready;
`ifdef NPU_SIM_ASSERT
  assign ram_raddr=DA'((32'(lookup_way)*SETS+32'(lookup_set))*(LINE_BYTES/4)+
                  ((lookup_addr>>2)&(LINE_BYTES/4-1)));
  assign ram_waddr=DA'((32'(fill_way)*SETS+32'(fill_set))*(LINE_BYTES/4)+
                      ((span_addr>>2)&(LINE_BYTES/4-1)));
`endif
  localparam int WAY_DEPTH = SETS * (LINE_BYTES/4);
  localparam int WAY_AW = $clog2(WAY_DEPTH);
  localparam int RAM_BANK_SHIFT = $clog2((BUS_WIDTH > READ_WIDTH ? BUS_WIDTH : READ_WIDTH)/32);
  wire [WAY_AW-1:0] speculative_address = WAY_AW'((32'(lookup_read_set) * (LINE_BYTES/4)) +
      (32'(lookup_read_word) & (LINE_BYTES/4-1)));
  wire [WAY_AW-1:0] fill_word_address = WAY_AW'((32'(fill_set) * (LINE_BYTES/4)) +
      ((span_addr >> 2) & (LINE_BYTES/4-1)));
  logic [1:0][1:0] input_conflict_results;
  logic [1:0] selected_input_conflict;
  for (genvar source_index = 0; source_index < 2; source_index++) begin : g_input_conflict
    logic [31:2] source_word;
    logic [WAY_AW-1:0] source_address;
    assign source_word = source_index == 0 ? incoming_request.address[31:2] : preview_request.address[31:2];
    assign source_address = WAY_AW'((32'(lookup_input_set[source_index]) * (LINE_BYTES/4)) +
        (32'(source_word) & (LINE_BYTES/4-1)));
    assign input_conflict_results[source_index][0] =
        (source_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
    assign input_conflict_results[source_index][1] = lookup_input_set[source_index] == fill_set;
  end
  onehot_mux #(.p_choices(2), .p_width(2)) u_input_conflict (
    .i_select({preview_source_select, !preview_source_select}),
    .i_data(input_conflict_results), .o_data(selected_input_conflict)
  );
  // 四个读取位置独立检查填充冲突，请求出队只选择单比特比较结果。
  // 原始地址仍驱动存储器端口，冲突状态与地址采用相同的位置选择。
  for (genvar candidate = 0; candidate < 4; candidate++) begin : g_lookup_conflict
    logic [WAY_AW-1:0] candidate_address;
    assign candidate_address = WAY_AW'((32'(lookup_candidate_set[candidate]) * (LINE_BYTES/4)) +
        (32'(lookup_candidate_word[candidate]) & (LINE_BYTES/4-1)));
    if (candidate == 2) begin : g_input
      // 输入来源仅选择已经计算完成的冲突和填充组号匹配结果。
      always_comb begin
        {lookup_candidate_fill_match[candidate], lookup_candidate_conflict[candidate]} =
            selected_input_conflict;
        case (preview_source_select)
          1'b0, 1'b1: begin end
          default: begin
            lookup_candidate_conflict[candidate] =
                (candidate_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
            lookup_candidate_fill_match[candidate] = lookup_candidate_set[candidate] == fill_set;
          end
        endcase
      end
    end else begin : g_stored
      assign lookup_candidate_conflict[candidate] =
          (candidate_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
      assign lookup_candidate_fill_match[candidate] = lookup_candidate_set[candidate] == fill_set;
    end
  end
  always_comb begin
    case (^{fg_state, req_fire, lookup_input_valid, request_count})
      1'b0, 1'b1: begin
        lookup_fill_match = lookup_candidate_fill_match[lookup_candidate_select];
      end
      default: begin
        lookup_fill_match = fill_set == lookup_read_set;
      end
    endcase
  end
  if (DEMAND_DEPTH == 1 && WB >= RAM_BANK_SHIFT) begin : g_direct_lookup_qualification
    logic read_input;
    logic [3:0] source_select, source_set_matches, source_word_matches;
    logic [2:0][1:0] stored_results;
    logic [1:0] stored_selected;
    logic parallel_conflict, parallel_snapshot_good;
    logic metadata_write;

    // 正式输入、队首和缺失请求先完成资格；预读结果只参与最终单比特归并。
    assign read_input = request_count == 0 || (req_fire && lookup_input_valid);
    assign source_select[0] = fg_state != FG_MISS && !read_input;
    assign source_select[1] = fg_state != FG_MISS && read_input && !preview_source_select;
    assign source_select[2] = fg_state == FG_MISS;
    assign source_select[3] = fg_state != FG_MISS && read_input && preview_source_select;
    assign source_set_matches[0] = lookup_candidate_set[0] == fill_set;
    assign source_set_matches[2] = lookup_candidate_set[3] == fill_set;
    conv_cache_input_set_match #(.p_set_width(SI), .p_line_shift(LB)) u_formal_set (
      .i_address(req_addr), .i_index(req_window_index),
      .i_indexed(windowed_q && req_window_index_valid), .i_fill_set(fill_set),
      .o_match(source_set_matches[1])
    );
    conv_cache_input_set_match #(.p_set_width(SI), .p_line_shift(LB)) u_preview_set (
      .i_address(preview_addr), .i_index(preview_index),
      .i_indexed(windowed_q && preview_index_valid), .i_fill_set(fill_set),
      .o_match(source_set_matches[3])
    );
    if (WB > RAM_BANK_SHIFT) begin : g_word_offset
      assign source_word_matches[0] = lookup_candidate_word[0][LB-1:RAM_BANK_SHIFT+2] ==
          span_addr[LB-1:RAM_BANK_SHIFT+2];
      assign source_word_matches[1] = req_addr[LB-1:RAM_BANK_SHIFT+2] ==
          span_addr[LB-1:RAM_BANK_SHIFT+2];
      assign source_word_matches[2] = demand_addr[LB-1:RAM_BANK_SHIFT+2] ==
          span_addr[LB-1:RAM_BANK_SHIFT+2];
      assign source_word_matches[3] = preview_addr[LB-1:RAM_BANK_SHIFT+2] ==
          span_addr[LB-1:RAM_BANK_SHIFT+2];
    end else begin : g_complete_line
      assign source_word_matches = '1;
    end
    assign metadata_write = metadata_enable && metadata_fill_good;
    for (genvar source_index = 0; source_index < 3; source_index++) begin : g_stored
      assign stored_results[source_index][0] = ram_wen &&
          source_set_matches[source_index] && source_word_matches[source_index];
      assign stored_results[source_index][1] =
          !(source_set_matches[source_index] &&
            (metadata_write || (ram_wen && source_word_matches[source_index])));
    end
    onehot_mux #(.p_choices(3), .p_width(2)) u_stored (
      .i_select(source_select[2:0]), .i_data(stored_results), .o_data(stored_selected)
    );
    conv_cache_lookup_qualification u_preview_qualification (
      .i_stored_conflict(stored_selected[0]), .i_stored_valid(stored_selected[1]),
      .i_preview_selected(source_select[3]), .i_preview_set_match(source_set_matches[3]),
      .i_preview_word_match(source_word_matches[3]), .i_data_write(ram_wen),
      .i_metadata_write(metadata_write), .o_conflict(parallel_conflict),
      .o_valid(parallel_snapshot_good)
    );
    always_comb begin
      spec_read_conflict = parallel_conflict;
      lookup_snapshot_good = parallel_snapshot_good;
      case (^{fg_state, req_fire, lookup_input_valid, request_count, preview_source_select,
               bypass_q, windowed_q, req_window_index_valid, preview_index_valid,
               req_addr, preview_addr, req_window_index, preview_index, span_addr,
               request_queue[request_head].address, request_queue[request_head].set_index,
               demand_addr, demand_set, demand_fill_set, fill_set})
        1'b0, 1'b1: begin end
        default: begin
          spec_read_conflict = ram_wen &&
              (speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
          lookup_snapshot_good = !(metadata_enable && metadata_fill_good && lookup_fill_match) &&
              !spec_read_conflict;
        end
      endcase
    end
  end else begin : g_queued_lookup_qualification
    always_comb begin
      case (^{fg_state, req_fire, lookup_input_valid, request_count})
        1'b0, 1'b1:
          spec_read_conflict = ram_wen && lookup_candidate_conflict[lookup_candidate_select];
        default:
          spec_read_conflict = ram_wen &&
              (speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
      endcase
    end
    assign lookup_snapshot_good = !(metadata_enable && metadata_fill_good && lookup_fill_match) &&
        !spec_read_conflict;
  end
  for (genvar data_way=0; data_way<WAYS; data_way++) begin : g_data_way
    conv_sdp_ram #(.DEPTH(WAY_DEPTH),.AW(WAY_AW),.WRITE_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH)) u_data (
      .clk, .rd_en(!spec_read_conflict), .rd_addr(speculative_address), .rd_data(speculative_data[data_way]),
      .wr_en(ram_wen && fill_way==WI'(data_way)), .wr_addr(fill_word_address),
      .wr_data(span_data), .wr_strb(span_strb));
  end
  always_ff @(posedge clk) if (ram_ren) ram_rdata <= speculative_data[lookup_way];
  assign bypass_launch = bypass_q && fg_state==FG_MISS && !demand_filled && lookup_range &&
                       fill_state==F_IDLE && !select_stage_valid;
  wire [31:0] bypass_line_base = {demand_addr[31:p_read_shift], {p_read_shift{1'b0}}};
  wire [31:0] bypass_first = range_below[11] ? base_q : bypass_line_base;
  assign span_rsp_ready=fill_state==F_DATA;
  conv_axi_span_reader #(.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .MAX_REQUEST_BYTES(LINE_BYTES)) u_span(
    .clk,.rst_n,.req_valid(fill_state==F_REQ),.req_ready(span_req_ready),
    .req_addr(fill_first),
    .req_bytes(span_request_bytes_wide[15:0]),
    .rsp_valid(span_rsp_valid),.rsp_ready(span_rsp_ready),
    .rsp_word_addr(span_addr),.rsp_data(span_data),.rsp_strb(span_strb),
    .rsp_last(span_last),.rsp_error(span_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast,.busy());

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

  assign metadata_enable=!(cfg_valid && cfg_ready);
  wire metadata_hit=req_fire && lookup_range && lookup_hit;
  assign metadata_fill=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  assign metadata_fill_good=metadata_fill && !(fill_bad || span_error);
`ifndef SYNTHESIS
  wire metadata_fill_bad=metadata_fill && (fill_bad || span_error);
`endif
  logic candidate_prefetch_busy, candidate_demand_busy;
  // 元数据冲突分别检查两个候选位置，再依据候选种类选择结果。
  assign candidate_prefetch_busy = (req_fire && lookup_set == pf_set) ||
      (metadata_fill && fill_set == pf_set) ||
      (hint_pending_q && hint_effective_valid && hint_set == pf_set);
  assign candidate_demand_busy = (req_fire && lookup_set == demand_set) ||
      (metadata_fill && fill_set == demand_set) ||
      (hint_pending_q && hint_effective_valid && hint_set == demand_set);
  assign candidate_metadata_busy = candidate_prefetch ? candidate_prefetch_busy : candidate_demand_busy;
  assign select_metadata_busy = (req_fire && lookup_set==select_set) ||
      (metadata_fill && fill_set==select_set) ||
      (hint_pending_q && hint_effective_valid && hint_set==select_set);
  // 快照内容在时钟边沿保存，复位及配置接收期间保持已有内容。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else if (cfg_valid && cfg_ready) begin
    end else begin
      lookup_snapshot_set <= lookup_read_set;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lookup_snapshot_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      lookup_snapshot_valid <= 1'b0;
    end else begin
      lookup_snapshot_valid <= lookup_snapshot_good;
    end
  end
  // 各端口地址独立保存，异步复位仅清除对应的有效状态。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else begin
      pf_snapshot_set<=pf_set;
      incoming_snapshot_set<=initial_pf_set;
      next_snapshot_set<=next_pf_set;
      incoming_hold_snapshot_set<=offer_set_q;
      next_hold_snapshot_set<=offer_next_set_q;
      hint_snapshot_set<=hint_set;
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

  wire [31:0] metadata_hit_rank=windowed_q ? retire_decode_output[0] : hint_next;
  wire [31:0] metadata_fill_rank=windowed_q ? fill_retire : fill_rank;
  logic metadata_work_eligible, metadata_demand_eligible;
  conv_cache_metadata_eligibility u_work_metadata (
    .i_conditions({req_fire, lookup_range, !bypass_q, fg_state != FG_MISS, work_lookup_ready}),
    .o_eligible(metadata_work_eligible)
  );
  conv_cache_metadata_eligibility u_demand_metadata (
    .i_conditions({req_fire, lookup_range, !bypass_q, fg_state == FG_MISS, demand_lookup_ready}),
    .o_eligible(metadata_demand_eligible)
  );
  // 每路元数据通过独立模块维护，调度器提供访问事件和对应地址。
  for (genvar metadata_way = 0; metadata_way < WAYS; metadata_way++) begin : g_metadata_way
    logic lookup_saved_fill_match;
    logic [31:LB] unused_lookup_tag_raw;
    logic lookup_valid_raw, lookup_valid_saved;
    logic [3:0][31:LB] lookup_source_tags;
    logic [3:0] lookup_source_valid;
    if (DEMAND_DEPTH == 1) begin : g_direct_lookup
      logic lookup_valid_next;
      logic [3:0] source_valid_next;
      assign lookup_saved_fill_match = g_saved_fill_match.lookup_fill_set_match_q;
      assign g_direct_tag_compare.lookup_tag_raw[metadata_way] = unused_lookup_tag_raw;
      assign g_direct_tag_compare.lookup_source_tags[metadata_way] = lookup_source_tags;
      // 运行状态在同一边沿清除；未启用期间的读取结果由运行状态统一屏蔽。
      always_comb begin
        lookup_valid_next = lookup_valid_raw;
        source_valid_next = lookup_source_valid;
        case (^{rst_n, cfg_valid && cfg_ready})
          1'b0, 1'b1: begin end
          default: begin
            lookup_valid_next = lookup_valid_saved;
            source_valid_next = {4{lookup_valid_saved}};
          end
        endcase
      end
      assign g_direct_tag_compare.lookup_source_valid_next[metadata_way] = source_valid_next;
      assign g_direct_tag_compare.lookup_valid_next[metadata_way] = lookup_valid_next;
    end else begin : g_queued_lookup
      assign lookup_saved_fill_match = 1'b0;
    end
    logic selected_metadata_hit, metadata_hit_parallel, metadata_bypass_eligible;
    conv_cache_metadata_eligibility u_bypass_metadata (
      .i_conditions({req_fire, lookup_range, bypass_q, demand_lookup_ready,
          demand_filled && fg_state == FG_MISS && demand_fill_way == WI'(metadata_way)}),
      .o_eligible(metadata_bypass_eligible)
    );
    // 每路命中直接更新对应元数据，运行资格不经过编码后的路号选择。
    conv_cache_metadata_hit_select #(.p_ways(WAYS), .p_selected_way(metadata_way)) u_hit_select (
      .i_work_eligible(metadata_work_eligible), .i_demand_eligible(metadata_demand_eligible),
      .i_bypass_eligible(metadata_bypass_eligible), .i_work_hits(work_tag_hits),
      .i_demand_hits(demand_tag_hits), .o_hit(metadata_hit_parallel)
    );
    always_comb begin
      selected_metadata_hit = metadata_hit_parallel;
      case (^{fg_state, bypass_q, demand_filled, work_lookup_ready, demand_lookup_ready,
               req_fire, lookup_range, demand_fill_way, work_tag_hits, demand_tag_hits})
        1'b0, 1'b1: begin end
        default: selected_metadata_hit = metadata_hit && lookup_way == WI'(metadata_way);
      endcase
    end
    conv_cache_metadata_way #(
      .p_sets(SETS), .p_demand_depth(DEMAND_DEPTH), .p_preview_request(p_preview_request), .p_set_width(SI),
      .p_line_shift(LB), .p_epoch_width(EPOCH_W)
    ) u_metadata (
      .clk(clk), .rst_n(rst_n),
      .i_cfg_accept(cfg_valid && cfg_ready), .i_configured(configured),
      .i_clearing(clearing), .i_bypass(bypass_q), .i_windowed(windowed_q),
      .i_metadata_enable(metadata_enable), .i_metadata_fill(metadata_fill),
      .i_metadata_fill_good(metadata_fill_good), .i_metadata_hit(selected_metadata_hit),
      .i_fill_active(fill_state != F_IDLE),
      .i_fill_selected(fill_way == WI'(metadata_way)),
      .i_hit_selected(1'b1),
      .i_clear_set(clear_set), .i_fill_set(fill_set),
      .i_lookup_set(lookup_set), .i_candidate_set(candidate_set),
      .i_read_set({hint_set, select_set, offer_next_set_q, offer_set_q, pf_set, lookup_read_set}),
      .i_offer_tag_set({offer_capture ? next_pf_set : offer_next_set_q,
                        offer_capture ? initial_pf_set : offer_set_q}),
      .i_lookup_snapshot_set(lookup_snapshot_set),
      .i_lookup_candidate_set(lookup_candidate_set),
      .i_lookup_input_set(lookup_input_set),
      .i_lookup_candidate_select(lookup_candidate_select),
      .i_lookup_saved_fill_match(lookup_saved_fill_match),
      .i_fill_tag(fill_addr[31:LB]), .i_hint_tag(hint_tag),
      .i_fill_epoch(EPOCH_W'(fill_epoch)), .i_hit_epoch(EPOCH_W'(processing_request.epoch)),
      .i_fill_rank(metadata_fill_rank), .i_hit_rank(metadata_hit_rank),
      .i_hint_rank(hint_effective_value), .i_hint_resolved(hint_resolved),
      .i_hint_valid(hint_valid), .i_select_stage_valid(select_stage_valid),
`ifndef SYNTHESIS
      .i_lookup_unknown((^{fg_state, req_fire, request_count, req_valid,
                          request_head, lookup_candidate_set}) === 1'bx),
`endif
`ifdef NPU_SIM_ASSERT
      .i_tag_read_valid({hint_lookup_ready, next_lookup_ready, incoming_lookup_ready,
                         pf_lookup_ready, lookup_ready}),
      .i_select_metadata_busy(select_metadata_busy),
`endif
      .o_valid({valid_hint[metadata_way], valid_select[metadata_way], valid_next[metadata_way],
                valid_incoming[metadata_way], valid_prefetch[metadata_way], valid_lookup[metadata_way]}),
      .o_tags({hint_lookup_tag[metadata_way], next_tag[metadata_way], incoming_tag[metadata_way],
               pf_tag[metadata_way], lookup_tag[metadata_way]}),
      .o_lookup_tag_raw(unused_lookup_tag_raw),
      .o_lookup_valid_raw(lookup_valid_raw), .o_lookup_valid_saved(lookup_valid_saved),
      .o_lookup_source_tags(lookup_source_tags), .o_lookup_source_valid(lookup_source_valid),
      .o_epoch(select_epochs[metadata_way]), .o_rank(select_ranks[metadata_way])
    );
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
      offer_range_q <= !range_below[6] && range_below[7];
      offer_next_range_q <= !range_below[8] && range_below[9];
      offer_index_q <= prefetch_window_index;
      offer_epoch_q <= prefetch_window_epoch;
      offer_retire_q <= prefetch_window_retire;
      offer_index_valid_q <= prefetch_window_index_valid;
      offer_next_fragment_q <= prefetch_next_fragment;
      offer_next_addr_q <= reference_next_address;
      offer_next_index_q <= reference_index;
      offer_next_epoch_q <= reference_next_epoch;
      offer_next_retire_q <= INF;
      offer_next_index_valid_q <= reference_index_valid;
      offer_set_q <= initial_pf_set;
      offer_next_set_q <= next_pf_set;
    end
  end

  logic select_snapshot_usable, select_retire_ready;
  // 快照保持条件与替换完成条件并行计算，状态只合并已完成的判断。
  assign select_snapshot_usable = !select_metadata_busy &&
      (select_prefetch ?
        (pf_pending && pf_addr == select_addr && !pf_hit && !pf_in_flight) :
        (fg_state == FG_MISS && demand_addr == select_addr && !lookup_hit && lookup_range));
  assign select_retire_ready = select_decision_valid && (fill_state == F_IDLE || fill_success) &&
      (select_prefetch ?
        (pf_match_ready && !(req_fire && !lookup_hit) &&
          !select_victim_conflict) :
        ((bypass_q || lookup_ready) && !completing_demand));
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      select_stage_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      select_stage_valid <= 1'b0;
    end else if (select_stage_valid) begin
      select_stage_valid <= select_snapshot_usable && !select_retire_ready;
    end else begin
      select_stage_valid <= select_launch_candidate && !candidate_metadata_busy;
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
    if (req_fire && processing_request.geometry && processing_request.event_first && hint_valid &&
        fill_state!=F_IDLE && fill_addr[31:LB]==work_request.address[31:LB])
      fill_rank <= hint_next;
    if (hint_resolved && fill_state!=F_IDLE && fill_addr[31:LB]==hint_tag)
      fill_rank <= hint_effective_value;
    if (fill_state==F_IDLE || fill_success) begin
      fill_addr <= bypass_q ? demand_addr : select_addr;
      fill_first <= bypass_q ? bypass_first : select_first;
      fill_end <= fill_candidate_end;
      fill_set <= bypass_q ? SI'(0) : select_set;
      fill_way <= bypass_q ? WI'(0) : select_way;
      fill_epoch <= bypass_q ? demand_epoch : select_epoch;
      fill_retire <= bypass_q ? demand_retire : select_retire;
      fill_rank <= bypass_q ? INF : select_rank;
      fill_prefetch <= !bypass_q && select_prefetch;
    end
  end

  // 预取载荷与提示值使用原有接收条件，控制状态负责其有效周期。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else if (cfg_valid && cfg_ready) begin
    end else begin
      if (hint_pending_q && hint_valid && !hint_lookup_ready && !hint_buffered)
        hint_value_q <= hint_next;
      if (!pf_active_valid && pf_count != 0 && !clearing) begin
        pf_pick<=pf_pick_comb;
        pf_addr<=pf_selected_keys[63:32];
        pf_index<=prefetch_payload_o_rd_data[63:32];
        pf_epoch<=pf_selected_keys[31:0];
        pf_retire<=prefetch_payload_o_rd_data[31:0];
        pf_index_valid<=prefetch_payload_o_rd_data[64];
      end
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      fg_state<=FG_IDLE;fill_state<=F_IDLE;configured<=0;clearing<=0;clear_set<=0;
      base_q<=0;end_q<=0;bypass_q<=0;windowed_q<=0;prefetch_q<=0;
      demand_addr<=0;demand_set<=0;demand_epoch<=0;demand_retire<=INF;demand_progress<=0;
      demand_range<=0;
      demand_filled<=0;demand_fill_set<=0;demand_fill_way<=0;
      response_error<=0;pf_head<=0;pf_tail<=0;pf_count<=0;pf_active_valid<=0;
      fill_bad<=0;
      hint_pending_q<=0;hint_buffered<=0;hint_tag<=0;hint_set<=0;

    end else begin
      if (cfg_valid && cfg_ready) begin
        configured<=1;clearing<=1;clear_set<=0;fg_state<=FG_IDLE;
        base_q<=cfg_base;end_q<=configured_end;bypass_q<=cfg_bypass;
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
          demand_range<=work_range;
          demand_epoch<=processing_request.epoch;demand_retire<=retire_decode_output[0];
          demand_progress<=processing_request.progress;demand_filled<=0;response_error<=0;
          if (!lookup_range) begin response_error<=1;fg_state<=FG_RESP;end
          else if (lookup_hit) begin
            fg_state<=fast_hit_response ? FG_IDLE : FG_RESP;
          end else begin
            fg_state<=FG_MISS;
          end
          if (processing_request.geometry && processing_request.event_first) begin
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
        end
        if (hint_resolved) begin
          hint_pending_q<=0;
          hint_buffered<=0;
        end
        if (!pf_active_valid && pf_count != 0 && !clearing) begin
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
          fill_bad<=0;
          fill_state<=F_REQ;
        end
        if (bypass_launch) begin
          fill_bad<=0;
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
  wire [32:0] select_end_wide = {1'b0, select_line_base} + 33'(bypass_q ? p_read_bytes : LINE_BYTES);
  wire [31:0] select_end = select_end_wide > {1'b0, end_q} ? end_q : select_end_wide[31:0];

  initial forever @(posedge clk) if (rst_n) begin
    if (cfg_valid && cfg_ready) begin
      assert(cfg_bytes!=0);
      assert({1'b0,cfg_base}+{1'b0,cfg_bytes}<33'h1_0000_0000);
    end
    if (ram_ren) assert(lookup_range);
    assert(outstanding_count<=DQ_CW'(DEMAND_DEPTH));
    assert(request_count<=DQ_CW'(DEMAND_DEPTH));
    assert(response_count<=DQ_CW'(DEMAND_DEPTH));
    if (consumed_response) assert(outstanding_count!=0 || accepted_request);
    if (preview_active) begin
      assert(work_request.address == incoming_request.address);
      assert(work_request.set_index == incoming_request.set_index);
      assert(work_request.in_range == incoming_request.in_range);
      if (req_fire) assert(accepted_request);
    end
    if (cfg_valid && cfg_ready) assert(outstanding_count==0);
    if (ram_ren && ram_wen) assert((int'(ram_raddr)/(BUS_WIDTH/32))!=(int'(ram_waddr)/(BUS_WIDTH/32)));
    assert(pf_count<=PF_CW'(PF_DEPTH));
    assert ($countones(pf_slot_valid) == pf_count);
    assert ($countones(pf_physical_valid_q) == pf_count);
    for (int slot=0; slot<PF_DEPTH; slot++) begin
      assert (pf_slot_valid[slot] == pf_physical_valid_q[pf_slot_map_q[slot]]);
      for (int other=slot+1; other<PF_DEPTH; other++)
        assert (pf_slot_map_q[slot] != pf_slot_map_q[other]);
    end
    if (select_launch) begin
      assert(select_first<select_end && (fill_state==F_IDLE || fill_success));
      if (fill_complete) assert(select_set!=fill_set || select_way!=fill_way);
    end
  end
`endif
endmodule

// 请求字段与完整匹配结果在同一查询边沿保存，后级直接使用保存的资格。
module conv_cache_snapshot_fields #(
  parameter int p_set_width = 4,
  parameter int p_request_width = 131+p_set_width,
  parameter bit p_capture_range = 1'b0
) (
  input wire logic clk,
  input wire logic [p_request_width-1:0] i_request,
  input wire logic [1:0] i_fg_state,
  input wire logic i_request_count, i_req_fire, i_lookup_input_valid, i_preview_source_select,
  input wire logic [31:2] i_work_word, i_demand_word,
  input wire logic [p_set_width-1:0] i_expected_set,
  input wire logic [31:0] i_base, i_end,
  input wire logic i_request_range, i_head_range,
`ifndef SYNTHESIS
  input wire logic [4:0] i_reference,
`endif
  output logic [p_request_width-1:0] o_request,
  output logic o_work_word_matches, o_work_snapshot_matches, o_demand_word_matches,
  output logic o_response_snapshot_ready
);
  localparam logic [1:0] p_miss_state = 2'd1;
  logic [p_request_width-2:0] request_fields_q;
  logic was_miss_q, request_fire_q;
  logic [31:0] saved_address;
  logic [31:0] request_address;
  logic [p_set_width-1:0] request_set;
  logic current_demand_equal, current_work_equal, previous_word_equal, set_equal;
  logic current_demand_equal_nxt, current_work_equal_nxt, previous_word_equal_nxt, set_equal_nxt;
  logic work_word_match, work_snapshot_match, demand_word_match, work_range;
  logic [4:0] results;

  always_ff @(posedge clk) begin
    request_fields_q <= i_request[p_request_width-1:1];
    was_miss_q <= i_fg_state == p_miss_state;
    request_fire_q <= i_req_fire;
    current_demand_equal <= current_demand_equal_nxt;
    current_work_equal <= current_work_equal_nxt;
    previous_word_equal <= previous_word_equal_nxt;
    set_equal <= set_equal_nxt;
  end
  assign saved_address = request_fields_q[p_request_width-2-:32];
  assign request_address = i_request[p_request_width-1-:32];
  assign request_set = i_request[3+:p_set_width];
  // 比较两侧均使用本次查询输入，保存边沿与完整请求字段保持一致。
  conv_cache_snapshot_equal #(.p_width(30)) u_current_demand (
    .i_a(request_address[31:2]), .i_b(i_demand_word), .o_equal(current_demand_equal_nxt)
  );
  conv_cache_snapshot_equal #(.p_width(30)) u_current_work (
    .i_a(request_address[31:2]), .i_b(i_work_word), .o_equal(current_work_equal_nxt)
  );
  conv_cache_snapshot_equal #(.p_width(30)) u_previous_words (
    .i_a(i_demand_word), .i_b(i_work_word), .o_equal(previous_word_equal_nxt)
  );
  conv_cache_snapshot_equal #(.p_width(p_set_width)) u_set (
    .i_a(request_set), .i_b(i_expected_set), .o_equal(set_equal_nxt)
  );
  // 完整请求已包含同一来源的范围结果，可随其余字段直接保存。
  if (p_capture_range) begin : g_request_range
    logic request_range;
    always_ff @(posedge clk) request_range <= i_request[0];
    assign work_range = request_range;
  end else begin : g_saved_range
    logic [31:0] range_base_q, range_end_q;
    logic preview_range_q, stored_range_q, read_input, below_base, below_end;
    assign read_input = !i_request_count ||
        (i_fg_state != p_miss_state && i_req_fire && i_lookup_input_valid);
    always_ff @(posedge clk) begin
      range_base_q <= i_base;
      range_end_q <= i_end;
      preview_range_q <= read_input && i_preview_source_select;
      stored_range_q <= read_input ? i_request_range : i_head_range;
    end
    conv_cache_snapshot_range u_base (
      .i_address(saved_address), .i_bound(range_base_q), .o_below(below_base)
    );
    conv_cache_snapshot_range u_end (
      .i_address(saved_address), .i_bound(range_end_q), .o_below(below_end)
    );
    assign work_range = preview_range_q ? (!below_base && below_end) : stored_range_q;
  end
  assign work_word_match = !was_miss_q || current_demand_equal;
  assign work_snapshot_match = !was_miss_q || (current_demand_equal && set_equal);
  assign demand_word_match = was_miss_q ? (!request_fire_q || previous_word_equal) :
      (request_fire_q ? current_work_equal : current_demand_equal);
`ifndef SYNTHESIS
  logic unknown_control_q;
  logic [4:0] reference_q;
  always_ff @(posedge clk) begin
    unknown_control_q <= (^{i_fg_state, i_request_count, i_req_fire,
                            i_lookup_input_valid, i_preview_source_select}) === 1'bx;
    reference_q <= i_reference;
  end
`endif
  always_comb begin
    results = {work_snapshot_match && work_range, work_snapshot_match,
               work_word_match, demand_word_match, work_range};
`ifndef SYNTHESIS
    // 未知来源控制继续使用完整描述选择的采样结果。
    if (unknown_control_q) results = reference_q;
`endif
  end
  assign o_request = {request_fields_q, results[0]};
  assign {o_response_snapshot_ready, o_work_snapshot_matches,
          o_work_word_matches, o_demand_word_matches} = results[4:1];
endmodule

// 三位相等关系分别形成，完整相等条件独立归并。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_equal #(
  parameter int p_width = 30
) (
  input wire logic [p_width-1:0] i_a, i_b,
  output logic o_equal
);
  localparam int p_groups = (p_width+2)/3;
  logic [p_groups-1:0] group_equal;
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_low = group_index*3;
    localparam int p_bits = p_width-p_low < 3 ? p_width-p_low : 3;
    assign group_equal[group_index] = i_a[p_low+:p_bits] == i_b[p_low+:p_bits];
  end
  assign o_equal = &group_equal;
endmodule

// 保存地址与范围端点并行比较，末级响应控制接收完整的大小关系。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_range (
  input wire logic [31:0] i_address, i_bound,
  output logic o_below
);
  logic below_parallel, unused_equal;
  parallel_unsigned_compare #(.p_width(32), .p_preserve_groups(1'b1)) u_range (
    .i_a(i_address), .i_b(i_bound), .o_less(below_parallel), .o_equal(unused_equal)
  );
`ifdef SYNTHESIS
  assign o_below = below_parallel;
`else
  logic below_reference, unused_reference_equal;
  unsigned_compare #(.p_width(32)) u_reference (
    .i_a(i_address), .i_b(i_bound),
    .o_less(below_reference), .o_equal(unused_reference_equal)
  );
  // 含未知位时沿用字节分组比较的传播规则。
  always_comb begin
    case (^{i_address, i_bound})
      1'b0, 1'b1: o_below = below_parallel;
      default: o_below = below_reference;
    endcase
  end
`endif
endmodule

// 固定缓存行跨度分别形成每个地址位的进位条件，低位字节偏移保持不变。
module conv_cache_next_line #(
  parameter int p_line_shift = 7
) (
  input wire logic [31:0] i_address,
  output logic [31:0] o_address,
  output logic o_carry
);
  logic [31:0] next_address;
  logic next_carry;
  if (p_line_shift > 0) begin : g_byte_offset
    assign next_address[p_line_shift-1:0] = i_address[p_line_shift-1:0];
  end
  assign next_address[p_line_shift] = ~i_address[p_line_shift];
  for (genvar address_bit = p_line_shift+1; address_bit < 32; address_bit++) begin : g_address_bit
    conv_cache_increment_bit #(.p_lower_width(address_bit-p_line_shift)) u_increment (
      .i_bit(i_address[address_bit]), .i_lower(i_address[p_line_shift+:address_bit-p_line_shift]),
      .o_bit(next_address[address_bit])
    );
  end
  assign next_carry = &i_address[31:p_line_shift];
`ifndef SYNTHESIS
  logic [31:0] four_state_address;
  logic four_state_carry;
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_four_state (
    .i_a(i_address), .i_b(32'(1) << p_line_shift), .i_carry(1'b0),
    .o_sum(four_state_address), .o_carry(four_state_carry)
  );
`endif
  always_comb begin
    {o_carry, o_address} = {next_carry, next_address};
`ifndef SYNTHESIS
    if ((^i_address) === 1'bx)
      {o_carry, o_address} = {four_state_carry, four_state_address};
`endif
  end
endmodule

// 每个进位归约独立综合，地址位之间不串联组合计算。
module conv_cache_increment_bit #(
  parameter int p_lower_width = 1
) (
  input wire logic i_bit,
  input wire logic [p_lower_width-1:0] i_lower,
  output logic o_bit
);
  assign o_bit = i_bit ^ (&i_lower);
endmodule

// 正常读取和复位读取均使用预先计算的比较值，来源控制只经过一层布尔选择。
module conv_cache_offer_match_select #(
  parameter bit p_capture_matches = 1'b1
) (
  input wire logic rst_n,
  input wire logic i_capture, i_current_match,
  input wire logic i_reset_captured_match, i_reset_held_match,
  output logic o_match
);
  assign o_match = rst_n ?
      ((i_capture == p_capture_matches) || i_current_match) :
      (i_capture ? i_reset_captured_match : i_reset_held_match);
endmodule

// 两位哈希组号在同一比较项中形成，索引模式在完整比较后选择。
module conv_cache_input_set_match #(
  parameter int p_set_width = 4,
  parameter int p_line_shift = 7
) (
  input wire logic [31:0] i_address, i_index,
  input wire logic i_indexed,
  input wire logic [p_set_width-1:0] i_fill_set,
  output logic o_match
);
  localparam int p_groups = (p_set_width + 1) / 2;
  logic [p_set_width-1:0] address_low, address_high;
  logic [p_groups-1:0] hashed_matches, indexed_matches;
  assign address_low = p_set_width'(i_address >> p_line_shift);
  assign address_high = p_set_width'(i_address >> (p_line_shift+p_set_width));
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_low = group_index * 2;
    localparam int p_width = p_set_width-p_low < 2 ? p_set_width-p_low : 2;
    assign hashed_matches[group_index] =
        (address_low[p_low+:p_width] ^ address_high[p_low+:p_width]) == i_fill_set[p_low+:p_width];
    assign indexed_matches[group_index] = i_index[p_low+:p_width] == i_fill_set[p_low+:p_width];
  end
  always_comb begin
    if (i_indexed) o_match = &indexed_matches;
    else o_match = &hashed_matches;
  end
endmodule

// 已保存来源与预读来源分别完成计算，较晚的预读比较只进入这一层资格选择。
module conv_cache_lookup_qualification (
  input wire logic i_stored_conflict, i_stored_valid, i_preview_selected,
  input wire logic i_preview_set_match, i_preview_word_match,
  input wire logic i_data_write, i_metadata_write,
  output logic o_conflict, o_valid
);
  assign o_conflict = i_stored_conflict ||
      (i_preview_selected && i_preview_set_match && i_preview_word_match && i_data_write);
  assign o_valid = i_stored_valid ||
      (i_preview_selected && !(i_preview_set_match &&
        (i_metadata_write || (i_data_write && i_preview_word_match))));
endmodule

// 标签与有效位独立完成读取，命中资格只合并运行和填充状态。
(* keep_hierarchy = "yes" *)
module conv_cache_tag_qualification (
  input wire logic i_cache_active, i_valid, i_tag_match,
  input wire logic i_fill_active, i_fill_selected, i_fill_set_match,
  output logic o_hit
);
  assign o_hit = i_cache_active && i_valid && i_tag_match &&
      !(i_fill_active && i_fill_selected && i_fill_set_match);
endmodule

// 已完成响应与当前命中并行生成有效位，返回资格只选择最终传输条件。
module conv_cache_direct_response #(
  parameter int p_ways = 2
) (
  input wire logic i_saved_valid, i_hit_eligible,
  input wire logic [p_ways-1:0] i_hits,
  output logic o_valid
);
  assign o_valid = i_saved_valid || (i_hit_eligible && (|i_hits));
endmodule

// 容量资格提前形成，字地址匹配只参与最终请求接收条件。
module conv_cache_request_qualification (
  input wire logic i_available, i_bypass, i_snapshot_valid, i_snapshot_match,
  output logic o_fire
);
  assign o_fire = i_available && (i_bypass || (i_snapshot_valid && i_snapshot_match));
endmodule

// 旁路和普通查询分别提供匹配条件，有效状态只参与最终读取资格。
module conv_cache_work_lookup (
  input wire logic i_valid, i_bypass, i_set_match, i_word_match, i_snapshot_match,
  output logic o_ready
);
  assign o_ready = i_valid &&
      (i_bypass ? (i_set_match && i_word_match) : i_snapshot_match);
endmodule

// 响应状态、字地址和范围结果并行归并，保持同步查询后的直接返回。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_response #(
  parameter int p_ways = 2
) (
  input wire logic i_saved_valid, i_control_ready, i_snapshot_match, i_range,
  input wire logic [p_ways-1:0] i_hits,
  output logic o_valid
);
  assign o_valid = i_saved_valid ||
      (i_control_ready && i_snapshot_match && i_range && (|i_hits));
endmodule

// 每路完整响应已经准备，较高编号的命中路在末级保持选择优先级。
module conv_cache_response_data_select #(
  parameter int p_ways = 2,
  parameter int p_width = 128
) (
  input wire logic [p_ways-1:0] i_hits,
  input wire logic [p_ways-1:0][p_width-1:0] i_data,
  output logic [p_width-1:0] o_data
);
  always_comb begin
    o_data = i_data[0];
    for (int way = 1; way < p_ways; way++) begin
      if (i_hits[way]) o_data = i_data[way];
    end
  end
endmodule

// 地址和运行条件提前准备，替换路命中只参与最终冲突资格。
module conv_cache_victim_qualification #(
  parameter int p_ways = 2
) (
  input wire logic i_demand_eligible, i_bypass_eligible,
  input wire logic [p_ways-1:0] i_selected_hits,
  output logic o_conflict
);
  assign o_conflict = i_bypass_eligible || (i_demand_eligible && (|i_selected_hits));
endmodule

// 工作请求和缺失请求分别选择优先命中路，元数据写入资格在末级归并。
module conv_cache_metadata_hit_select #(
  parameter int p_ways = 2,
  parameter int p_selected_way = 0
) (
  input wire logic i_work_eligible, i_demand_eligible, i_bypass_eligible,
  input wire logic [p_ways-1:0] i_work_hits, i_demand_hits,
  output logic o_hit
);
  logic work_selected, demand_selected;
  if (p_selected_way == p_ways-1) begin : g_last
    assign work_selected = i_work_hits[p_selected_way];
    assign demand_selected = i_demand_hits[p_selected_way];
  end else begin : g_lower
    assign work_selected = i_work_hits[p_selected_way] && !(|i_work_hits[p_ways-1:p_selected_way+1]);
    assign demand_selected = i_demand_hits[p_selected_way] && !(|i_demand_hits[p_ways-1:p_selected_way+1]);
  end
  conv_cache_metadata_hit_finish u_finish (
    .i_bypass_eligible(i_bypass_eligible), .i_work_eligible(i_work_eligible),
    .i_demand_eligible(i_demand_eligible), .i_work_selected(work_selected),
    .i_demand_selected(demand_selected), .o_hit(o_hit)
  );
endmodule

// 工作请求与缺失请求的优先命中位先行形成，写入资格只进行单比特归并。
module conv_cache_metadata_hit_finish (
  input wire logic i_bypass_eligible, i_work_eligible, i_demand_eligible,
  input wire logic i_work_selected, i_demand_selected,
  output logic o_hit
);
  assign o_hit = i_bypass_eligible ||
      (i_work_eligible && i_work_selected) || (i_demand_eligible && i_demand_selected);
endmodule

// 请求、范围、运行模式和快照就绪条件分别形成后一次归并。
module conv_cache_metadata_eligibility #(
  parameter int p_conditions = 5
) (
  input wire logic [p_conditions-1:0] i_conditions,
  output logic o_eligible
);
  assign o_eligible = &i_conditions;
endmodule

// 预取代次分别完成相等比较，请求接收仅选择当前槽位应保存的一位结果。
module conv_cache_prefetch_epoch_value (
  input wire logic i_push, i_fire, i_offer_work, i_offer_demand, i_slot_work,
  output logic o_value
);
  always_comb begin
    o_value = i_slot_work;
    if (i_push) o_value = i_fire ? i_offer_work : i_offer_demand;
  end
endmodule

// 提示占用、请求接收和组号冲突并行计算，候选种类保持各自的阻塞条件。
module conv_cache_select_busy #(
  parameter bit p_prefetch = 1'b1
) (
  input wire logic i_hint_busy, i_fire, i_set_match, i_hit,
  output logic o_busy
);
  if (p_prefetch) begin : g_prefetch
    assign o_busy = i_hint_busy || (i_fire && (i_set_match || !i_hit));
  end else begin : g_demand
    assign o_busy = i_hint_busy || (i_fire && i_set_match);
  end
endmodule

// 缺失请求和工作请求分别形成命中结果，工作快照只参与末级归并。
module conv_cache_lookup_hit #(
  parameter int p_ways = 2
) (
  input wire logic i_bypass, i_miss, i_filled, i_demand_ready, i_work_ready,
  input wire logic [p_ways-1:0] i_demand_hits, i_work_hits,
  output logic o_hit
);
  logic demand_hit, parallel_hit;
  conv_cache_demand_hit #(.p_ways(p_ways)) u_demand (
    .i_bypass(i_bypass), .i_miss(i_miss), .i_filled(i_filled),
    .i_ready(i_demand_ready), .i_hits(i_demand_hits), .o_hit(demand_hit)
  );
  conv_cache_snapshot_response #(.p_ways(p_ways)) u_work (
    .i_saved_valid(demand_hit), .i_control_ready(!i_bypass && !i_miss),
    .i_snapshot_match(i_work_ready), .i_range(1'b1), .i_hits(i_work_hits), .o_valid(parallel_hit)
  );
  always_comb begin
    o_hit = parallel_hit;
`ifndef SYNTHESIS
    if ((^i_bypass) === 1'bx)
      o_hit = i_bypass ? i_filled && i_miss && i_demand_ready :
          ((i_miss && i_demand_ready && (|i_demand_hits)) ||
           (!i_miss && i_work_ready && (|i_work_hits)));
`endif
  end
endmodule

// 旁路填充与普通标签命中共享缺失请求的状态和快照资格。
module conv_cache_demand_hit #(
  parameter int p_ways = 2
) (
  input wire logic i_bypass, i_miss, i_filled, i_ready,
  input wire logic [p_ways-1:0] i_hits,
  output logic o_hit
);
  assign o_hit = i_miss && i_ready && (i_bypass ? i_filled : (|i_hits));
endmodule

`default_nettype wire
