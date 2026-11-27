// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 窗口缓存管理正式请求、同拍预读、缺失填充及预取，响应保持接收顺序。
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
  input wire logic clk /* 工作时钟 */, rst_n /* 低有效复位 */ , // 工作时钟；低有效复位
  input wire logic cfg_valid, // 配置有效
  output logic cfg_ready, // 配置可接收
  input wire logic [31:0] cfg_base /* 输入区域首地址 */, cfg_bytes /* 输入区域字节数 */ , // 输入区域首地址；输入区域字节数
  input wire logic cfg_bypass, // 启用缓存旁路
  input wire logic cfg_geometry = 1'b0, // 启用几何布局
  input wire logic req_valid, // 正式请求有效
  output logic req_ready, // 正式请求可接收
  input wire logic preview_valid = 1'b0, // 预读请求有效
  input wire logic [31:0] preview_addr = 32'd0, // 预读字节地址
  input wire logic preview_index_valid = 1'b0, // 预读窗口索引有效
  input wire logic [31:0] preview_index = 32'd0, // 预读窗口索引
  input wire logic [31:0] req_addr, // 正式请求字节地址
  input wire logic req_geometry = 1'b0, // 请求采用几何布局
  input wire logic req_event_first = 1'b0, // 请求为几何事件首拍
  input wire logic hint_valid = 1'b0, // 下一次使用提示有效
  input wire logic [31:0] hint_next = 32'hffff_ffff, // 下一次使用顺序
  output logic hint_pending, // 等待下一次使用提示
  output logic rsp_valid, // 响应有效
  input wire logic rsp_ready, // 下游可接收响应
  output logic [READ_WIDTH-1:0] rsp_data, // 响应数据
  output logic rsp_error, // 响应错误
  output logic rsp_success, // 成功响应事件
  output logic rsp_failure, // 失败响应事件
  output logic arvalid, // AXI读取地址有效
  input wire logic arready, // AXI读取地址可接收
  output logic [31:0] araddr, // AXI读取首地址
  output logic [7:0] arlen, // AXI突发长度减一
  output logic [2:0] arsize, // AXI每拍字节数编码
  output logic [1:0] arburst, // AXI突发类型
  input wire logic rvalid, // AXI读取数据有效
  output logic rready, // AXI读取数据可接收
  input wire logic [BUS_WIDTH-1:0] rdata, // AXI读取数据
  input wire logic [1:0] rresp, // AXI读取响应状态
  input wire logic rlast, // AXI突发最后一拍
  input wire logic cfg_windowed = 1'b0, // 启用窗口索引
  input wire logic cfg_prefetch_enable = 1'b0, // 允许预取
  input wire logic req_window_index_valid = 1'b0, // 正式请求窗口索引有效
  input wire logic [31:0] req_window_index = 32'd0, // 正式请求窗口索引
  input wire logic [31:0] req_window_epoch = 32'd0, // 正式请求窗口代次
  input wire logic [31:0] req_window_retire = 32'hffff_ffff, // 正式请求释放顺序
  input wire logic [31:0] req_window_progress = 32'd0, // 正式请求进度
  input wire logic prefetch_valid = 1'b0, // 预取请求有效
  output logic prefetch_ready, // 预取请求可接收
  input wire logic [31:0] prefetch_addr = 32'd0, // 预取字节地址
  input wire logic prefetch_window_index_valid = 1'b0, // 预取窗口索引有效
  input wire logic [31:0] prefetch_window_index = 32'd0, // 预取窗口索引
  input wire logic [31:0] prefetch_window_epoch = 32'd0, // 预取窗口代次
  input wire logic [31:0] prefetch_window_retire = 32'hffff_ffff, // 预取释放顺序
  input wire logic prefetch_next_fragment = 1'b0, // 预取的下一片段有效
  input wire logic prefetch_ref_valid = 1'b0, // 预取参考位置有效
  input wire logic [31:0] prefetch_ref_addr = 32'd0, // 预取参考字节地址
  input wire logic prefetch_ref_index_valid = 1'b0, // 预取参考窗口索引有效
  input wire logic [31:0] prefetch_ref_index = 32'd0, // 预取参考窗口索引
  input wire logic [31:0] prefetch_ref_epoch = 32'd0 /* 预取参考位置的窗口代次 */); // 预取参考窗口代次
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
  // 单比特命中结果供填充和替换控制共同使用。
  (* keep = "true" *) logic lookup_hit;
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
  logic select_prefetch_launch;
  logic [PF_DEPTH-1:0] pf_slot_valid, pf_current_by_slot;
  // 保留并行独热选择结果，使逻辑位置编码与物理读取地址分别归并。
  (* keep = "true" *) logic [PF_DEPTH-1:0] pf_pick_by_slot;
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
  demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request;
  demand_t   processing_request;
  logic lookup_input_valid, preview_active, preview_source_select;

  logic [1:0][31:0]  retire_decode_output;
  logic [SI-1:0] lookup_read_set, lookup_snapshot_set;
  logic [31:2] lookup_read_word;
  logic lookup_snapshot_valid, lookup_ready;
  logic work_lookup_ready, demand_lookup_ready;
  logic  demand_word_matches_q;

  logic [READ_WIDTH-1:0] response_queue_data[DEMAND_DEPTH];
  logic response_queue_error[DEMAND_DEPTH];
  logic [DQ_AW-1:0] request_head, request_tail, response_head, response_tail;
  logic [DQ_CW-1:0] request_count, response_count, outstanding_count;
  logic accepted_request, consumed_response, request_push, request_pop;
  logic response_push, response_pop;
  logic  core_rsp_ready, core_rsp_error, fast_hit_response;
  logic bypass_launch;

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
  // 缓存占用状态按六位分组检查，完整空闲结果只需合并各组标志。
  localparam int p_idle_width = p_cfg_idle_width + 2;
  localparam int p_idle_groups = (p_idle_width + 5) / 6;
  logic [p_idle_width-1:0] complete_idle_state;
  logic [p_idle_groups-1:0] idle_group_zero;
  assign complete_idle_state = {fill_state, cfg_idle_state};
  for (genvar group_index = 0; group_index < p_idle_groups; group_index++) begin : g_idle_group
    localparam int p_first = group_index * 6;
    localparam int p_bits = p_idle_width - p_first < 6 ? p_idle_width - p_first : 6;
    zero_reduce #(.p_width(p_bits)) u_zero (
      .i_value(complete_idle_state[p_first+:p_bits]), .o_zero(idle_group_zero[group_index])
    );
  end
  assign cfg_ready = &idle_group_zero;
  localparam int WAY_DEPTH = SETS * (LINE_BYTES/4);
  localparam int WAY_AW = $clog2(WAY_DEPTH);
  localparam int RAM_BANK_SHIFT = $clog2((BUS_WIDTH > READ_WIDTH ? BUS_WIDTH : READ_WIDTH)/32);
  wire [WAY_AW-1:0] speculative_address = WAY_AW'((32'(lookup_read_set) * (LINE_BYTES/4)) +
      (32'(lookup_read_word) & (LINE_BYTES/4-1)));
  wire [WAY_AW-1:0] fill_word_address = WAY_AW'((32'(fill_set) * (LINE_BYTES/4)) +
      ((span_addr >> 2) & (LINE_BYTES/4-1)));

  logic [WAYS-1:0] metadata_lookup_valid_next;
  logic lookup_saved_fill_set_match;
  logic [1:0] lookup_candidate_select;
  logic metadata_enable, metadata_fill_good;
  // 请求查询与响应独立于填充调度，所有数组保持原来的位置和采样边沿。
  conv_cache_request_path #(
    .p_sets(SETS), .p_ways(WAYS), .p_line_bytes(LINE_BYTES),
    .p_bus_width(BUS_WIDTH), .p_read_width(READ_WIDTH), .p_demand_depth(DEMAND_DEPTH),
    .p_set_width(SI), .p_line_shift(LB), .p_word_width(WB), .p_way_width(WI),
    .p_defer_retire_shift(p_defer_retire_shift), .p_preview_request(p_preview_request)
  ) u_request_path (
    .clk(clk), .rst_n(rst_n),
    .i_cfg_valid(cfg_valid), .i_cfg_ready(cfg_ready),
    .i_req_valid(req_valid), .o_req_ready(req_ready),
    .i_preview_valid(preview_valid), .i_preview_addr(preview_addr),
    .i_preview_index_valid(preview_index_valid), .i_preview_index(preview_index),
    .i_req_addr(req_addr), .i_req_geometry(req_geometry),
    .i_req_event_first(req_event_first), .o_rsp_valid(rsp_valid),
    .i_rsp_ready(rsp_ready), .o_rsp_data(rsp_data),
    .o_rsp_error(rsp_error), .o_rsp_success(rsp_success),
    .o_rsp_failure(rsp_failure), .i_req_window_index_valid(req_window_index_valid),
    .i_req_window_index(req_window_index), .i_req_window_epoch(req_window_epoch),
    .i_req_window_retire(req_window_retire), .i_req_window_progress(req_window_progress),
    .i_fg_state(fg_state), .i_fill_state(fill_state),
    .i_configured(configured), .i_clearing(clearing),
    .i_clear_set(clear_set), .i_base_q(base_q),
    .i_end_q(end_q), .i_bypass_q(bypass_q),
    .i_windowed_q(windowed_q), .i_lookup_tag(lookup_tag),
    .i_valid_lookup(valid_lookup), .i_demand_addr(demand_addr),
    .i_demand_set(demand_set), .i_response_error(response_error),
    .i_demand_filled(demand_filled), .i_demand_fill_set(demand_fill_set),
    .i_demand_fill_way(demand_fill_way), .o_lookup_addr(lookup_addr),
    .o_lookup_set(lookup_set), .o_lookup_candidate_set(lookup_candidate_set),
    .o_lookup_input_set(lookup_input_set), .o_lookup_hit(lookup_hit),
    .o_work_tag_hits(work_tag_hits), .o_demand_tag_hits(demand_tag_hits),
    .o_lookup_way(lookup_way), .o_req_fire(req_fire),
    .o_lookup_range(lookup_range), .o_work_range(work_range),
    .i_demand_range(demand_range), .i_offer_retire_q(offer_retire_q),
    .i_fill_set(fill_set), .i_fill_way(fill_way),
    .i_select_launch(select_launch), .i_range_below(range_below),
    .i_ram_wen(ram_wen), .o_spec_read_conflict(spec_read_conflict),
    .i_ram_rdata(ram_rdata), .i_span_rsp_valid(span_rsp_valid),
    .i_span_rsp_ready(span_rsp_ready), .i_span_last(span_last),
    .i_span_addr(span_addr), .i_request_queue(request_queue),
    .o_incoming_request(incoming_request), .o_work_request(work_request),
    .o_processing_request(processing_request), .o_lookup_input_valid(lookup_input_valid),
    .o_preview_active(preview_active), .o_preview_source_select(preview_source_select),
    .o_retire_decode_output(retire_decode_output), .o_lookup_read_set(lookup_read_set),
    .o_lookup_snapshot_set(lookup_snapshot_set), .o_lookup_read_word(lookup_read_word),
    .o_lookup_snapshot_valid(lookup_snapshot_valid), .o_lookup_ready(lookup_ready),
    .o_work_lookup_ready(work_lookup_ready), .o_demand_lookup_ready(demand_lookup_ready),
    .o_demand_word_matches_q(demand_word_matches_q), .i_saved_response_data(response_queue_data[response_head]),
    .i_saved_response_error(response_queue_error[response_head]), .i_request_head(request_head),
    .i_request_count(request_count),
    .i_response_count(response_count), .i_outstanding_count(outstanding_count),
    .o_accepted_request(accepted_request), .o_consumed_response(consumed_response),
    .o_request_push(request_push), .o_request_pop(request_pop),
    .o_response_push(response_push), .o_response_pop(response_pop),
    .o_core_rsp_ready(core_rsp_ready), .o_core_rsp_error(core_rsp_error),
    .o_fast_hit_response(fast_hit_response), .i_bypass_launch(bypass_launch),
    .o_core_rsp_data(core_rsp_data), .i_speculative_data(speculative_data),
    .i_speculative_address(speculative_address), .i_fill_word_address(fill_word_address),
    .i_metadata_enable(metadata_enable), .i_metadata_fill_good(metadata_fill_good),
    .o_lookup_candidate_select(lookup_candidate_select), .i_lookup_valid_next(metadata_lookup_valid_next),
    .o_lookup_saved_fill_set_match(lookup_saved_fill_set_match)
  );

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
                              select_prefetch_launch);
  assign pf_pop=pf_pending && pf_retire_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pf_retire_q <= 1'b0;
    else if (cfg_valid && cfg_ready) pf_retire_q <= 1'b0;
    else pf_retire_q <= pf_retire_ready;
  end
  assign fill_complete=fill_state==F_DATA && span_rsp_valid && span_rsp_ready && span_last;
  assign fill_success=fill_complete && !fill_bad && !span_error;
  logic completion_tag_matches;
  // 完整标签按三位形成相等结果，填充资格只在末级合并。
  conv_cache_snapshot_equal #(.p_width(32-LB)) u_completion_tag (
    .i_a(demand_addr[31:LB]), .i_b(fill_addr[31:LB]),
    .o_equal(completion_tag_matches)
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
  logic [PF_DEPTH-1:0] prefetch_priority_i_match, prefetch_priority_o_select;
  logic [PF_AW-1:0] prefetch_priority_i_head;
  // 队首以后的首个匹配项和全队列首个匹配项并行计算，末级决定循环次序。
  assign prefetch_priority_i_match = pf_current_by_slot;
  assign prefetch_priority_i_head = pf_head;
  assign pf_pick_by_slot = prefetch_priority_o_select;
  conv_cache_prefetch_priority #(.p_depth(PF_DEPTH), .p_address_width(PF_AW)) u_prefetch_priority (
    .i_match(prefetch_priority_i_match), .i_head(prefetch_priority_i_head),
    .o_select(prefetch_priority_o_select)
  );
  for (genvar bit_index = 0; bit_index < PF_AW; bit_index++) begin : g_prefetch_encode
    logic [PF_DEPTH-1:0] logical_bits, physical_bits;
    for (genvar slot = 0; slot < PF_DEPTH; slot++) begin : g_slot
      localparam logic [PF_AW-1:0] p_slot = PF_AW'(slot);
      assign logical_bits[slot] = pf_pick_by_slot[slot] && p_slot[bit_index];
      assign physical_bits[slot] = pf_pick_by_slot[slot] && pf_slot_map_q[slot][bit_index];
    end
    localparam int p_groups = (PF_DEPTH+2)/3;
    (* keep = 1 *) logic [p_groups-1:0] physical_groups;
    // 每组最多合并三个候选，物理槽号经过两级归并进入存储器读地址。
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_physical
      localparam int p_low = 3*group_index;
      localparam int p_count = PF_DEPTH-p_low<3 ? PF_DEPTH-p_low : 3;
      assign physical_groups[group_index] = |physical_bits[p_low+:p_count];
    end
    assign pf_pick_comb[bit_index] = |logical_bits;
    assign pf_read_slot[bit_index] = |physical_groups;
  end

  assign pf_set = cache_set(pf_addr, windowed_q && pf_index_valid, pf_index);

  logic prefetch_fill_tag_match;
  // 预取地址和在途填充地址按独立分组比较，末级只合并相等结果。
  conv_cache_snapshot_equal #(.p_width(32-LB)) u_prefetch_fill_tag (
    .i_a(pf_addr[31:LB]), .i_b(fill_addr[31:LB]), .o_equal(prefetch_fill_tag_match)
  );
  always_comb begin
    pf_hit_raw=0;
    for (int w=0;w<WAYS;w++)
      if (pf_lookup_ready && valid_prefetch[w] && pf_tag[w]==pf_addr[31:LB]) pf_hit_raw=1;
    pf_in_flight=fill_state!=F_IDLE && prefetch_fill_tag_match;
  end
  logic [1:0][WAYS+PF_DEPTH-1:0] offer_duplicate_valid;
  logic [1:0][WAYS+PF_DEPTH-1:0][31-LB:0] offer_duplicate_tag;
  for (genvar way=0; way<WAYS; way++) begin : g_offer_duplicate_way
    assign offer_duplicate_valid[0][way] = valid_incoming[way];
    assign offer_duplicate_valid[1][way] = valid_next[way];
    assign offer_duplicate_tag[0][way] = incoming_tag[way];
    assign offer_duplicate_tag[1][way] = next_tag[way];
  end
  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_offer_duplicate_slot
    assign offer_duplicate_valid[0][WAYS+slot] = pf_physical_valid_q[slot];
    assign offer_duplicate_valid[1][WAYS+slot] = pf_physical_valid_q[slot];
    assign offer_duplicate_tag[0][WAYS+slot] = prefetch_keys_o_rd_data[slot][63:32+LB];
    assign offer_duplicate_tag[1][WAYS+slot] = prefetch_keys_o_rd_data[slot][63:32+LB];
  end
  // 两个片段分别完成标签归并，选择条件只参与最终一位重复标志。
  conv_cache_offer_duplicate #(.p_tag_width(32-LB), .p_entries(WAYS+PF_DEPTH)) u_offer_duplicate (
    .i_fill_active(fill_state != F_IDLE), .i_fill_tag(fill_addr[31:LB]),
    .i_offer_tag({offer_next_addr_q[31:LB], offer_addr_q[31:LB]}),
    .i_valid(offer_duplicate_valid), .i_tag(offer_duplicate_tag),
    .i_next_fragment(offer_next_fragment_q),
    .o_choose_next(offer_choose_next), .o_duplicate(pf_duplicate)
  );

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

  logic select_demand_address_matches, select_prefetch_address_matches;
  // 完整地址分别形成比较结果，快照保持和发送控制共用单比特身份匹配。
  conv_cache_snapshot_equal #(.p_width(32)) u_demand_address (
    .i_a(demand_addr), .i_b(select_addr), .o_equal(select_demand_address_matches)
  );
  conv_cache_snapshot_equal #(.p_width(32)) u_prefetch_address (
    .i_a(pf_addr), .i_b(select_addr), .o_equal(select_prefetch_address_matches)
  );
  logic select_fill_capacity_ready, select_prefetch_ready, select_demand_ready;
  logic select_victim_conflict;
  (* keep = 1 *) logic select_request_set_match, select_hint_busy;
  (* keep = 1 *) logic select_fill_busy;
  wire metadata_fill;

  // 请求组号、提示冲突和命中结果并行准备，需求接收只在最后一级参与选择。
  // 预取同时检查同组访问和需求缺失，普通填充只检查同组访问。
  conv_cache_lookup_set_match #(.p_set_width(SI)) u_selected_request_set (
    .i_bypass(bypass_q), .i_miss(fg_state == FG_MISS),
    .i_fill_set(demand_fill_set), .i_demand_set(demand_set),
    .i_work_set(work_request.set_index), .i_select_set(select_set),
    .o_match(select_request_set_match)
  );
  assign select_hint_busy = hint_pending_q && hint_effective_valid && hint_set == select_set;
  always_comb begin
    select_fill_capacity_ready = select_stage_valid && select_decision_valid &&
        (fill_state == F_IDLE || (fill_success && fill_set != select_set));
`ifndef SYNTHESIS
    if ((^{fill_state, fill_success}) === 1'bx)
      select_fill_capacity_ready = select_stage_valid && select_decision_valid &&
          !(metadata_fill && fill_set == select_set) && (fill_state == F_IDLE || fill_success);
`endif
  end
  (* keep_hierarchy = "yes" *) conv_cache_metadata_eligibility u_prefetch_launch_ready (
    .i_conditions({pf_pending, pf_match_ready, select_prefetch_address_matches,
        !pf_hit, !pf_in_flight}), .o_eligible(select_prefetch_ready)
  );
  logic select_demand_snapshot_ready, select_demand_request_ready;
  // 替换需求直接检查保存的需求字段，前台状态在末级选择是否使用该结果。
  assign select_demand_snapshot_ready = bypass_q ||
      (lookup_snapshot_valid && lookup_snapshot_set == demand_set && demand_word_matches_q);
  assign select_demand_request_ready = fg_state == FG_MISS &&
      select_demand_address_matches && demand_range;
  always_comb begin
    select_demand_ready = select_demand_request_ready &&
        select_demand_snapshot_ready && !completing_demand;
`ifndef SYNTHESIS
    if ((^{fg_state, bypass_q}) === 1'bx)
      select_demand_ready = fg_state == FG_MISS && select_demand_address_matches &&
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
    .i_conditions({fg_state == FG_MISS, 1'b1, !bypass_q,
        select_set == demand_set, 1'b1}), .o_eligible(demand_victim_eligible)
  );
  conv_cache_metadata_eligibility #(.p_conditions(6)) u_bypass_victim (
    .i_conditions({fg_state == FG_MISS, 1'b1, bypass_q, demand_filled,
        select_set == demand_fill_set, select_way == demand_fill_way}),
    .o_eligible(bypass_victim_eligible)
  );
  conv_cache_victim_qualification #(.p_ways(WAYS)) u_victim_qualification (
    .i_demand_eligible(demand_victim_eligible), .i_bypass_eligible(bypass_victim_eligible),
    .i_selected_hits(demand_selected_victim), .i_lookup_ready(demand_lookup_ready),
    .o_conflict(victim_conflict_parallel)
  );
  // 受影响缓存行的身份预先归并，查询就绪只控制最终冲突结果。
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
  // 两类请求独立合并资格，工作请求占用条件只在末级参与发送选择。
  conv_cache_select_launch u_select_launch (
    .i_capacity_ready(select_fill_capacity_ready), .i_victim_conflict(select_victim_conflict),
    .i_prefetch(select_prefetch), .i_prefetch_ready(select_prefetch_ready),
    .i_demand_ready(select_demand_ready), .i_hint_busy(select_hint_busy),
    .i_fire(req_fire), .i_set_match(select_request_set_match), .i_hit(lookup_hit),
    .o_launch(select_launch), .o_prefetch_launch(select_prefetch_launch)
  );
  always_comb begin
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
    parallel_unsigned_compare #(
      .p_width(p_index_width), .p_preserve_groups(1'b1), .p_infer_arithmetic(1'b0)
    ) u_line_limit (
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
  // 地址相等与提示、填充冲突并行准备，正式请求只参与末级冲突归并。
  assign select_fill_busy = metadata_fill && fill_set == select_set;
  conv_cache_select_busy #(.p_prefetch(1'b0)) u_snapshot_busy (
    .i_hint_busy(select_fill_busy || select_hint_busy), .i_fire(req_fire),
    .i_set_match(select_request_set_match), .i_hit(1'b0), .o_busy(select_metadata_busy)
  );
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
  logic pf_hit_checked_next;
  // 活动预取保持到退休；已准备的查询资格与本周期替换发送分别控制有效位。
  conv_cache_prefetch_check u_prefetch_check (
    .i_configure(cfg_valid && cfg_ready), .i_pending(pf_pending),
    .i_lookup_ready(pf_lookup_ready), .i_fill_busy(metadata_enable && metadata_fill),
    .i_fill_set_match(fill_set == pf_set), .i_launch(select_launch),
    .i_launch_set_match(select_set == pf_set), .o_next_checked(pf_hit_checked_next)
  );
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pf_hit_checked <= 1'b0;
    else pf_hit_checked <= pf_hit_checked_next;
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
      logic valid_select_i_cfg_accept;
      logic [1:0] valid_select_i_foreground_state;
      logic valid_select_i_request_occupied, valid_select_i_request_fire;
      logic valid_select_i_input_valid, valid_select_i_preview_selected;
      logic [3:0] valid_select_i_source_valid;
      logic valid_select_i_address_valid, valid_select_i_saved_valid;
      assign lookup_saved_fill_match = lookup_saved_fill_set_match;
      assign valid_select_i_cfg_accept = cfg_valid && cfg_ready;
      assign valid_select_i_foreground_state = fg_state;
      assign valid_select_i_request_occupied = request_count[0];
      assign valid_select_i_request_fire = req_fire;
      assign valid_select_i_input_valid = lookup_input_valid;
      assign valid_select_i_preview_selected = preview_source_select;
      assign valid_select_i_source_valid = lookup_source_valid;
      assign valid_select_i_address_valid = lookup_valid_raw;
      assign valid_select_i_saved_valid = lookup_valid_saved;
      // 元数据的四个来源并行读取及转发，队列控制仅选择单比特结果。
      conv_cache_lookup_valid_select u_valid_select (
        .rst_n(rst_n), .i_cfg_accept(valid_select_i_cfg_accept),
        .i_foreground_state(valid_select_i_foreground_state),
        .i_request_occupied(valid_select_i_request_occupied),
        .i_request_fire(valid_select_i_request_fire),
        .i_input_valid(valid_select_i_input_valid),
        .i_preview_selected(valid_select_i_preview_selected),
        .i_source_valid(valid_select_i_source_valid),
        .i_address_valid(valid_select_i_address_valid),
        .i_saved_valid(valid_select_i_saved_valid), .o_valid(lookup_valid_next)
      );
      // 运行状态在同一边沿清除；未启用期间的读取结果由运行状态统一屏蔽。
      always_comb begin
        source_valid_next = lookup_source_valid;
        case (^{rst_n, cfg_valid && cfg_ready})
          1'b0, 1'b1: begin end
          default: begin
            source_valid_next = {4{lookup_valid_saved}};
          end
        endcase
      end
      assign metadata_lookup_valid_next[metadata_way] = lookup_valid_next;
    end else begin : g_queued_lookup
      assign lookup_saved_fill_match = 1'b0;
      assign metadata_lookup_valid_next[metadata_way] = lookup_valid_saved;
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
      .i_lookup_preview_selected(preview_source_select),
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
  // 标签比较先形成寄存结果，再控制队列内容的接收使能。
  // 候选字段保存在当前条目中，直到该条目被消费。
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

  logic select_stage_next_valid;
  // 两类请求分别准备快照保持与结束资格，命中结果只参与最终选择。
  conv_cache_snapshot_hold u_snapshot_hold (
    .i_configure(cfg_valid && cfg_ready), .i_valid(select_stage_valid),
    .i_metadata_busy(select_metadata_busy), .i_prefetch(select_prefetch),
    .i_prefetch_snapshot(pf_pending && select_prefetch_address_matches && !pf_hit && !pf_in_flight),
    .i_demand_snapshot(fg_state == FG_MISS && select_demand_address_matches && lookup_range),
    .i_retire_eligible(select_decision_valid && (fill_state == F_IDLE || fill_success)),
    .i_prefetch_ready(pf_match_ready), .i_victim_conflict(select_victim_conflict),
    .i_demand_retire((bypass_q || lookup_ready) && !completing_demand),
    .i_fire(req_fire), .i_hit(lookup_hit), .i_launch(select_launch_candidate),
    .i_candidate_busy(candidate_metadata_busy), .o_next_valid(select_stage_next_valid)
  );
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) select_stage_valid <= 1'b0;
    else select_stage_valid <= select_stage_next_valid;
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

`default_nettype wire
