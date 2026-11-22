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
  parameter bit p_defer_retire_shift=1'b0
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
  output logic [READ_WIDTH-1:0] rsp_data,
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
  logic lookup_hit;
  (* keep = "true" *) logic [WAYS-1:0] work_tag_hits, demand_tag_hits;
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
   logic [32:0] fill_candidate_end_wide;
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
  logic fill_end_exceeds_tensor, unused_fill_end_equal;
  logic [31:0] select_line_base, select_first;
  logic [31:0] fill_candidate_line_base, fill_candidate_end;
  logic ram_ren, ram_wen, spec_read_conflict;
`ifdef NPU_SIM_ASSERT
  logic [DA-1:0] ram_raddr, ram_waddr;
`endif
  logic [READ_WIDTH-1:0] ram_rdata;
  logic span_req_ready, span_rsp_valid, span_rsp_ready, span_last, span_error;
  logic [31:0] span_addr;
  (* keep = "true" *) logic [32:0] span_request_bytes_wide;
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
    logic geometry, event_first, in_range;
  } demand_t;
  demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request, lookup_read_request;
  logic [1:0][31:0] retire_decode_input, retire_decode_output;
  logic [SI-1:0] lookup_read_set, lookup_snapshot_set;
  logic [31:2] lookup_read_word;
  logic lookup_snapshot_valid, lookup_ready;
  logic work_lookup_ready, demand_lookup_ready;
  logic work_word_matches_q, demand_word_matches_q, work_snapshot_matches_q;
  logic lookup_idle_set_match;
  logic [1:0] lookup_head_matches, lookup_input_matches;
  logic lookup_next_work_match;
  logic lookup_idle_demand_match, lookup_pop_work_match;
  logic [READ_WIDTH-1:0] response_queue_data[DEMAND_DEPTH];
  logic response_queue_error[DEMAND_DEPTH];
  logic [DQ_AW-1:0] request_head, request_tail, response_head, response_tail;
  logic [DQ_CW-1:0] request_count, response_count, outstanding_count;
  logic accepted_request, consumed_response, request_push, request_pop;
  logic response_push, response_pop, work_valid, work_ready;
  logic core_rsp_valid, core_rsp_ready, core_rsp_error, fast_hit_response;
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
  always_ff @(posedge clk) begin
    offer_read_set_match_q[0] <= offer_read_next_set[0] == offer_next_set[0];
    offer_read_set_match_q[1] <= offer_read_next_set[1] == offer_next_set[1];
    offer_read_set_match_q[2] <= offer_read_next_set[2] == offer_next_set[0];
    offer_read_set_match_q[3] <= offer_read_next_set[3] == offer_next_set[1];
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
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_reference_next (
    .i_a(reference_addr), .i_b(32'(LINE_BYTES)), .i_carry(1'b0),
    .o_sum(reference_next_address), .o_carry(unused_reference_next_carry)
  );
  unsigned_compare #(.p_width(33)) u_fill_end_limit (
    .i_a({1'b0, end_q}), .i_b(fill_candidate_end_wide),
    .o_less(fill_end_exceeds_tensor), .o_equal(unused_fill_end_equal)
  );

  localparam int p_cfg_idle_width = 6 + PF_CW + 3*DQ_CW;
  logic [p_cfg_idle_width-1:0] cfg_idle_state;
  assign cfg_idle_state = {fg_state, clearing, pf_count, pf_active_valid, offer_valid,
                           outstanding_count, request_count, response_count, select_stage_valid};
  // 缓存各状态并行检查，填充状态独立参与最终接收条件。
  assign cfg_ready = fill_state == F_IDLE && !(|cfg_idle_state);
  assign req_ready=configured && !clearing && !cfg_valid &&
                   (outstanding_count<DQ_CW'(DEMAND_DEPTH) || consumed_response) &&
                   (windowed_q || outstanding_count==0 || consumed_response);
  assign accepted_request=req_valid && req_ready;
  assign consumed_response=rsp_valid && rsp_ready;
  assign incoming_range = !range_below[0] && range_below[1];
  assign incoming_request={req_addr,req_window_epoch,req_window_retire,req_window_progress,
                           cache_set(req_addr, windowed_q && req_window_index_valid, req_window_index),
                           req_geometry,req_event_first,incoming_range};
  assign retire_decode_input[0] = work_request.retire;
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
  assign lookup_input_matches = {incoming_request.address[31:2] == work_request.address[31:2],
                                 incoming_request.address[31:2] == demand_addr[31:2]};
  assign lookup_idle_demand_match = request_count == 0 ? lookup_input_matches[0] : lookup_head_matches[0];
  assign lookup_idle_set_match =
      (bypass_q ? demand_fill_set : demand_set) == lookup_read_request.set_index;
  assign lookup_pop_work_match = (request_count == 0 && lookup_input_matches[1]) ||
      (request_count == DQ_CW'(1) && ((req_valid && lookup_input_matches[1]) ||
                                     (!req_valid && lookup_head_matches[1]))) ||
      (request_count > DQ_CW'(1) && lookup_next_work_match);
  // 地址范围结果随接收描述保存，出队时只选择已保存的一位状态。
  // 队首描述与标签、数据预读同步更新，命中控制使用同一周期的寄存信息。
  always_ff @(posedge clk) begin
    work_request <= lookup_read_request;
    // 工作请求与预读字地址在同一边沿更新，比较结果同时保存。
    work_word_matches_q <= fg_state != FG_MISS || lookup_idle_demand_match;
    // 组地址与字地址在相同边沿保存，工作请求直接使用完整的快照匹配状态。
    work_snapshot_matches_q <= fg_state != FG_MISS ||
        (lookup_idle_demand_match && lookup_idle_set_match);
    // 缺失状态只使用需求字地址，普通请求按出队状态选择匹配结果。
    demand_word_matches_q <= fg_state == FG_MISS ?
        (!req_fire || demand_addr[31:2] == work_request.address[31:2]) :
        (req_fire ? lookup_pop_work_match : lookup_idle_demand_match);
  end
  assign work_range = work_request.in_range;
  assign work_valid=request_count!=0;
  (* keep = "true" *) logic work_capacity_ready, work_snapshot_ready;
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
  assign req_fire=work_valid && work_ready;
  assign request_push=accepted_request;
  assign request_pop=request_count!=0 && req_fire;
  // 标签读取与地址匹配共用原有寄存边沿，返回控制读取已保存的匹配结果。
  // 缺失请求可能在同一边沿更新，两种地址并行比较后选择一位结果。
  if (DEMAND_DEPTH > 1) begin : g_registered_tag_compare
    // 返回队列提供寄存边界，标签先同步读取，再与同拍保存的请求地址比较。
    for (genvar hit_way = 0; hit_way < WAYS; hit_way++) begin : g_way
      localparam int p_tag_groups = (32 - LB + 2) / 3;
      (* keep = 1 *) logic [p_tag_groups-1:0] work_group_matches, demand_group_matches;
      (* keep = "true" *) logic work_tag_matches, demand_tag_matches;
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
  for (genvar hit_way = 0; hit_way < WAYS; hit_way++) begin : g_lookup_tag
    logic work_tag_matches_q, demand_tag_matches_q;
    logic work_tag_matches, demand_tag_matches, accepted_tag_matches;

    assign work_tag_matches = lookup_tag_raw[hit_way] == lookup_read_request.address[31:LB];
    assign demand_tag_matches = lookup_tag_raw[hit_way] == demand_addr[31:LB];
    assign accepted_tag_matches = lookup_tag_raw[hit_way] == work_request.address[31:LB];
    always_ff @(posedge clk) begin
      work_tag_matches_q <= work_tag_matches;
      if (req_fire) demand_tag_matches_q <= accepted_tag_matches;
      else demand_tag_matches_q <= demand_tag_matches;
    end
    assign work_tag_hits[hit_way] = valid_lookup[hit_way] && work_tag_matches_q;
    assign demand_tag_hits[hit_way] = valid_lookup[hit_way] && demand_tag_matches_q;
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
    (* keep = 1 *) logic fast_control_ready, fast_snapshot_ready;
    // 普通命中直接使用工作请求的快照，旁路选择只参与最终返回条件。
    assign fast_snapshot_ready = lookup_snapshot_valid && work_snapshot_matches_q;
    assign fast_control_ready = fg_state == FG_IDLE && configured && !clearing &&
        work_valid && response_count < DQ_CW'(DEMAND_DEPTH);
    assign fast_hit_response = fast_control_ready && fast_snapshot_ready &&
        work_range && !bypass_q && (|work_tag_hits);
    // 空闲阶段的有效响应使用命中数据，数据选择与命中接收资格并行。
    assign core_rsp_data=fg_state == FG_IDLE ? fast_hit_data :
                         response_error ? '0 : ram_rdata;
  end else begin : g_queued_response_lookup
    (* keep = "true" *) logic fast_control_ready, fast_snapshot_ready;
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
  end else begin : g_single_response
    // 单个在途名额保持同步读出后的直接返回，以维持每周期一个字的吞吐率。
    assign rsp_valid = response_count != 0 || core_rsp_valid;
    assign rsp_data = response_count != 0 ? response_queue_data[response_head] : core_rsp_data;
    assign rsp_error = response_count != 0 ? response_queue_error[response_head] : core_rsp_error;
    assign response_push = core_rsp_valid && core_rsp_ready && (response_count != 0 || !rsp_ready);
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
  assign completing_demand=fill_success && fg_state==FG_MISS &&
    demand_addr[31:LB]==fill_addr[31:LB] && (bypass_q || demand_set==fill_set);

  // 逻辑位置保留预取优先次序；物理位置只在接收新描述时写入数据。
  // 移除非队首项时交换位置映射，整个描述不经过复制多路选择器。
  assign pf_push_slot = pf_slot_map_q[pf_tail];
  assign pf_pop_slot = pf_slot_map_q[pf_pick];
  // 代次比较与需求接收及预取写入同时保存，选择活动项时直接读取比较结果。
  assign pf_offer_matches_work = pf_offer_epoch == work_request.epoch;
  assign pf_offer_matches_demand = pf_offer_epoch == demand_epoch;
  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_prefetch_valid
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
          pf_epoch_matches[slot] <= req_fire ? pf_offer_matches_work : pf_offer_matches_demand;
        else if (req_fire)
          pf_epoch_matches[slot] <= prefetch_keys_o_rd_data[slot][31:0] == work_request.epoch;
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
  logic [3:0][SI-1:0] lookup_candidate_set;
  logic [3:0][31:2] lookup_candidate_word;
  logic [3:0] lookup_candidate_fill_match, lookup_candidate_conflict;
  logic lookup_fill_match;
  logic [1:0] lookup_candidate_select;
  // 四个位置独立读取有效位，出队状态只选择已经形成的单比特结果。
  assign lookup_candidate_set[0] = request_queue[request_head].set_index;
  assign lookup_candidate_set[1] = request_queue[DQ_AW'(request_head + DQ_AW'(1))].set_index;
  assign lookup_candidate_set[2] = incoming_request.set_index;
  assign lookup_candidate_set[3] = bypass_q ? demand_fill_set : demand_set;
  assign lookup_candidate_word[0] = request_queue[request_head].address[31:2];
  assign lookup_candidate_word[1] = request_queue[DQ_AW'(request_head + DQ_AW'(1))].address[31:2];
  assign lookup_candidate_word[2] = incoming_request.address[31:2];
  assign lookup_candidate_word[3] = demand_addr[31:2];
  always_comb begin
    lookup_candidate_select = request_count == 0 ? 2'd2 : 2'd0;
    if (fg_state != FG_MISS && req_fire && request_count != 0) begin
      if (request_count > DQ_CW'(1)) lookup_candidate_select = 2'd1;
      else if (req_valid) lookup_candidate_select = 2'd2;
    end
    if (fg_state == FG_MISS) lookup_candidate_select = 2'd3;
  end
  // 填充组号与查询快照在各自更新边沿同时形成匹配状态。
  // 返回阶段直接使用这一位结果，保持填充切换与快照暂停的原有周期关系。
  if (DEMAND_DEPTH == 1) begin : g_saved_fill_match
    logic [SI-1:0] next_fill_set, next_lookup_set;
    logic lookup_fill_set_match_q;
    always_comb begin
      next_fill_set = fill_set;
      if (fill_state == F_IDLE || fill_success)
        next_fill_set = bypass_q ? SI'(0) : select_set;
      next_lookup_set = lookup_read_set;
      if (!rst_n) next_lookup_set = lookup_snapshot_set;
      else if (cfg_valid && cfg_ready) next_lookup_set = lookup_snapshot_set;
    end
    always_ff @(posedge clk)
      lookup_fill_set_match_q <= next_fill_set == next_lookup_set;
  end
  // 两种请求分别匹配已有快照，队首出队直接使用工作请求的匹配结果。
  assign work_lookup_ready = lookup_snapshot_valid &&
      (bypass_q ? (lookup_snapshot_set == demand_fill_set && work_word_matches_q) :
                  work_snapshot_matches_q);
  assign demand_lookup_ready = lookup_snapshot_valid &&
      lookup_snapshot_set == (bypass_q ? demand_fill_set : demand_set) &&
      demand_word_matches_q;
  assign lookup_ready = fg_state == FG_MISS ? demand_lookup_ready : work_lookup_ready;

  assign lookup_hit = bypass_q ? demand_filled && fg_state == FG_MISS && demand_lookup_ready :
      ((fg_state == FG_MISS && demand_lookup_ready && (|demand_tag_hits)) ||
       (fg_state != FG_MISS && work_lookup_ready && (|work_tag_hits)));
  always_comb begin
    lookup_way = '0;
    for (int way = 0; way < WAYS; way++)
      if (lookup_ready && (fg_state == FG_MISS ? demand_tag_hits[way] : work_tag_hits[way]))
        lookup_way = WI'(way);
    if (bypass_q) lookup_way = demand_fill_way;
  end

  always_comb begin
    pf_hit_raw=0;
    for (int w=0;w<WAYS;w++)
      if (pf_lookup_ready && valid_prefetch[w] && pf_tag[w]==pf_addr[31:LB]) pf_hit_raw=1;
    pf_in_flight=fill_state!=F_IDLE && fill_addr[31:LB]==pf_addr[31:LB];
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
  (* keep = "true" *) logic [p_address_compare_groups-1:0] select_demand_address_match;
  (* keep = "true" *) logic [p_address_compare_groups-1:0] select_prefetch_address_match;
  // 请求身份按固定小组并行比较，状态资格在完整比较之后合并。
  for (genvar group_index = 0; group_index < p_address_compare_groups; group_index++) begin : g_select_address
    localparam int p_low = group_index * 3;
    localparam int p_width = 32 - p_low < 3 ? 32 - p_low : 3;
    assign select_demand_address_match[group_index] =
        demand_addr[p_low +: p_width] == select_addr[p_low +: p_width];
    assign select_prefetch_address_match[group_index] =
        pf_addr[p_low +: p_width] == select_addr[p_low +: p_width];
  end
  (* keep = "true" *) logic select_fill_capacity_ready, select_prefetch_ready, select_demand_ready;
  (* keep = "true" *) logic select_victim_conflict;
  logic select_request_set_match, select_hint_busy;
  logic select_prefetch_blocked, select_demand_blocked;

  // 请求组号、提示冲突和命中结果并行准备，需求接收只在最后一级参与选择。
  // 预取同时检查同组访问和需求缺失，普通填充只检查同组访问。
  assign select_request_set_match = lookup_set == select_set;
  assign select_hint_busy = hint_pending_q && hint_effective_valid && hint_set == select_set;
  assign select_prefetch_blocked = select_hint_busy ||
      (req_fire && (select_request_set_match || !lookup_hit));
  assign select_demand_blocked = select_hint_busy || (req_fire && select_request_set_match);
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
  (* keep = "true" *) logic select_demand_snapshot_ready, select_demand_request_ready;
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
  always_comb begin
    select_victim_conflict = fg_state == FG_MISS && demand_lookup_ready &&
        (bypass_q ? (demand_filled && select_set == demand_fill_set && select_way == demand_fill_way) :
                    (select_set == demand_set && (|demand_selected_victim)));
`ifndef SYNTHESIS
    // 未知地址与命中结果使用逐路选择的四态结果。
    if ((^{fg_state, bypass_q, demand_tag_hits, demand_lookup_ready,
           select_way, demand_fill_way, select_set, lookup_set}) === 1'bx) begin
      select_victim_conflict = fg_state == FG_MISS && lookup_hit &&
          select_set == lookup_set && select_way == lookup_way;
    end
`endif
  end
  always_comb begin
    select_launch = select_fill_capacity_ready &&
        (select_prefetch ? (select_prefetch_ready && !select_prefetch_blocked) :
                           (select_demand_ready && !lookup_hit && !select_demand_blocked));
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
    // 工作请求与填充的同组冲突已包含在元数据占用条件中。
    // 预取替换还需避开缺失请求当前命中的存储路。
    if (select_launch && select_victim_conflict) begin
      select_launch = 1'b0;
    end
    ram_ren=(req_fire && lookup_range && lookup_hit) ||
            (fg_state==FG_MISS && lookup_hit);
  end
  // 缺失请求与预取分别准备完整填充地址，状态只选择对应地址。
  assign select_line_base=bypass_q ? {select_addr[31:p_read_shift],{p_read_shift{1'b0}}} : {select_addr[31:LB],{LB{1'b0}}};
  assign select_first=range_below[10] ? base_q : select_line_base;
  // 两种填充方式在同一边沿采样，共用相同的上界计算。
  assign fill_candidate_line_base = bypass_q ?
        {demand_addr[31:p_read_shift], {p_read_shift{1'b0}}} : {select_addr[31:LB], {LB{1'b0}}};
  assign fill_candidate_end_wide = {1'b0, fill_candidate_line_base} +
        33'(bypass_q ? p_read_bytes : LINE_BYTES);
  assign fill_candidate_end = fill_end_exceeds_tensor ?
        end_q : fill_candidate_end_wide[31:0];
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
  // 四个读取位置独立检查填充冲突，请求出队只选择单比特比较结果。
  // 原始地址仍驱动存储器端口，冲突状态与地址采用相同的位置选择。
  for (genvar candidate = 0; candidate < 4; candidate++) begin : g_lookup_conflict
    logic [WAY_AW-1:0] candidate_address;
    assign candidate_address = WAY_AW'((32'(lookup_candidate_set[candidate]) * (LINE_BYTES/4)) +
        (32'(lookup_candidate_word[candidate]) & (LINE_BYTES/4-1)));
    assign lookup_candidate_conflict[candidate] =
        (candidate_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
    assign lookup_candidate_fill_match[candidate] = lookup_candidate_set[candidate] == fill_set;
  end
  always_comb begin
    case (^{fg_state, req_fire, req_valid, request_count})
      1'b0, 1'b1: begin
        spec_read_conflict = ram_wen && lookup_candidate_conflict[lookup_candidate_select];
        lookup_fill_match = lookup_candidate_fill_match[lookup_candidate_select];
      end
      default: begin
        spec_read_conflict = ram_wen &&
            (speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
        lookup_fill_match = fill_set == lookup_read_set;
      end
    endcase
  end
  for (genvar data_way=0; data_way<WAYS; data_way++) begin : g_data_way
    conv_sdp_ram #(.DEPTH(WAY_DEPTH),.AW(WAY_AW),.WRITE_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH)) u_data (
      .clk, .rd_en(!spec_read_conflict), .rd_addr(speculative_address), .rd_data(speculative_data[data_way]),
      .wr_en(ram_wen && fill_way==WI'(data_way)), .wr_addr(fill_word_address),
      .wr_data(span_data), .wr_strb(span_strb));
  end
  always_ff @(posedge clk) if (ram_ren) ram_rdata <= speculative_data[lookup_way];
  wire bypass_launch = bypass_q && fg_state==FG_MISS && !demand_filled && lookup_range &&
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

  wire metadata_enable=!(cfg_valid && cfg_ready);
  wire metadata_hit=req_fire && lookup_range && lookup_hit;
  wire metadata_fill=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  wire metadata_fill_good=metadata_fill && !(fill_bad || span_error);
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
      lookup_snapshot_valid <= !(metadata_enable && metadata_fill_good && lookup_fill_match) &&
                               !spec_read_conflict;
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
  // 每路元数据通过独立模块维护，调度器提供访问事件和对应地址。
  for (genvar metadata_way = 0; metadata_way < WAYS; metadata_way++) begin : g_metadata_way
    logic lookup_saved_fill_match;
    logic [31:LB] unused_lookup_tag_raw;
    if (DEMAND_DEPTH == 1) begin : g_direct_lookup
      assign lookup_saved_fill_match = g_saved_fill_match.lookup_fill_set_match_q;
      assign g_direct_tag_compare.lookup_tag_raw[metadata_way] = unused_lookup_tag_raw;
    end else begin : g_queued_lookup
      assign lookup_saved_fill_match = 1'b0;
    end
    conv_cache_metadata_way #(
      .p_sets(SETS), .p_demand_depth(DEMAND_DEPTH), .p_set_width(SI),
      .p_line_shift(LB), .p_epoch_width(EPOCH_W)
    ) u_metadata (
      .clk(clk), .rst_n(rst_n),
      .i_cfg_accept(cfg_valid && cfg_ready), .i_configured(configured),
      .i_clearing(clearing), .i_bypass(bypass_q), .i_windowed(windowed_q),
      .i_metadata_enable(metadata_enable), .i_metadata_fill(metadata_fill),
      .i_metadata_fill_good(metadata_fill_good), .i_metadata_hit(metadata_hit),
      .i_fill_active(fill_state != F_IDLE),
      .i_fill_selected(fill_way == WI'(metadata_way)),
      .i_hit_selected(lookup_way == WI'(metadata_way)),
      .i_clear_set(clear_set), .i_fill_set(fill_set),
      .i_lookup_set(lookup_set), .i_candidate_set(candidate_set),
      .i_read_set({hint_set, select_set, offer_next_set_q, offer_set_q, pf_set, lookup_read_set}),
      .i_offer_tag_set({offer_capture ? next_pf_set : offer_next_set_q,
                        offer_capture ? initial_pf_set : offer_set_q}),
      .i_lookup_snapshot_set(lookup_snapshot_set),
      .i_lookup_candidate_set(lookup_candidate_set),
      .i_lookup_candidate_select(lookup_candidate_select),
      .i_lookup_saved_fill_match(lookup_saved_fill_match),
      .i_fill_tag(fill_addr[31:LB]), .i_hint_tag(hint_tag),
      .i_fill_epoch(EPOCH_W'(fill_epoch)), .i_hit_epoch(EPOCH_W'(work_request.epoch)),
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
    if (req_fire && work_request.geometry && work_request.event_first && hint_valid &&
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
          demand_epoch<=work_request.epoch;demand_retire<=retire_decode_output[0];
          demand_progress<=work_request.progress;demand_filled<=0;response_error<=0;
          if (!lookup_range) begin response_error<=1;fg_state<=FG_RESP;end
          else if (lookup_hit) begin
            fg_state<=fast_hit_response ? FG_IDLE : FG_RESP;
          end else begin
            fg_state<=FG_MISS;
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
    if (consumed_response) assert(outstanding_count!=0);
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

`default_nettype wire
