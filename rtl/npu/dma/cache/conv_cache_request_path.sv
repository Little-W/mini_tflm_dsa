// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 请求读取通路并行准备正式请求、预读和缺失地址，保存查询快照并形成顺序响应。
// 所有快照沿用缓存现有采样边沿，缓存调度状态及请求队列更新由父模块管理。
module conv_cache_request_path #(
  parameter int p_sets = 32,
  parameter int p_ways = 2,
  parameter int p_line_bytes = 16,
  parameter int p_bus_width = 32,
  parameter int p_read_width = 32,
  parameter int p_demand_depth = 4,
  parameter int p_set_width = $clog2(p_sets),
  parameter int p_line_shift = $clog2(p_line_bytes),
  parameter int p_word_width = $clog2(p_line_bytes/4),
  parameter int p_way_width = p_ways == 1 ? 1 : $clog2(p_ways),
  parameter bit p_defer_retire_shift = 1'b0,
  parameter bit p_preview_request = 1'b0,
  localparam int p_queue_addr_width = p_demand_depth <= 1 ? 1 : $clog2(p_demand_depth),
  localparam int p_queue_count_width = $clog2(p_demand_depth+1),
  localparam int p_way_addr_width = $clog2(p_sets*(p_line_bytes/4)),
  localparam int p_request_width = 131+p_set_width
) (
  input wire logic clk, // 工作时钟
  input wire logic rst_n, // 低有效复位
  input wire logic i_cfg_valid, // 配置请求有效
  input wire logic i_cfg_ready, // 配置请求可接收
  input wire logic i_req_valid, // 正式读取请求有效
  output logic o_req_ready, // 正式读取请求可接收
  input wire logic i_preview_valid, // 同拍预读请求有效
  input wire logic [31:0] i_preview_addr, // 预读字节地址
  input wire logic i_preview_index_valid, // 预读窗口索引有效
  input wire logic [31:0] i_preview_index, // 预读窗口索引
  input wire logic [31:0] i_req_addr, // 正式请求字节地址
  input wire logic i_req_geometry, // 正式请求采用几何布局
  input wire logic i_req_event_first, // 正式请求为几何事件首拍
  output logic o_rsp_valid, // 返回数据有效
  input wire logic i_rsp_ready, // 下游可接收返回数据
  output logic [p_read_width-1:0] o_rsp_data, // 返回数据
  output logic o_rsp_error, // 返回错误状态
  output logic o_rsp_success, // 成功返回事件
  output logic o_rsp_failure, // 错误返回事件
  input wire logic i_req_window_index_valid, // 正式请求窗口索引有效
  input wire logic [31:0] i_req_window_index, // 正式请求窗口索引
  input wire logic [31:0] i_req_window_epoch, // 正式请求窗口代次
  input wire logic [31:0] i_req_window_retire, // 正式请求释放顺序
  input wire logic [31:0] i_req_window_progress, // 正式请求进度
  input wire logic [1:0] i_fg_state, // 前台请求处理状态
  input wire logic [1:0] i_fill_state, // 缓存行填充状态
  input wire logic i_configured, // 配置已完成
  input wire logic i_clearing, // 正在清除元数据
  input wire logic [p_set_width-1:0] i_clear_set, // 当前清除组号
  input wire logic [31:0] i_base_q, // 已配置输入区域首地址
  input wire logic [31:0] i_end_q, // 已配置输入区域结束地址
  input wire logic i_bypass_q, // 启用缓存旁路
  input wire logic i_windowed_q, // 启用窗口索引
  input wire logic [p_ways-1:0][31:p_line_shift] i_lookup_tag, // 各路同步读出的标签
  input wire logic [p_ways-1:0] i_valid_lookup, // 各路保存查询的有效位
  input wire logic [31:0] i_demand_addr, // 当前缺失请求字节地址
  input wire logic [p_set_width-1:0] i_demand_set, // 当前缺失请求组号
  input wire logic i_response_error, // 已保存普通响应的错误状态
  input wire logic i_demand_filled, // 当前缺失请求已完成填充
  input wire logic [p_set_width-1:0] i_demand_fill_set, // 旁路填充组号
  input wire logic [p_way_width-1:0] i_demand_fill_way, // 旁路填充路号
  output logic [31:0] o_lookup_addr, // 当前工作查询字节地址
  output logic [p_set_width-1:0] o_lookup_set, // 当前工作查询组号
  output logic [3:0][p_set_width-1:0] o_lookup_candidate_set, // 队首、下一项、输入和缺失请求的组号
  output logic [1:0][p_set_width-1:0] o_lookup_input_set, // 正式输入与预读输入的组号
  output logic o_lookup_hit, // 当前工作查询命中
  output logic [p_ways-1:0] o_work_tag_hits, // 各路工作请求命中
  output logic [p_ways-1:0] o_demand_tag_hits, // 各路缺失请求命中
  output logic [p_way_width-1:0] o_lookup_way, // 当前查询选择的缓存路号
  output logic o_req_fire, // 当前工作请求处理事件
  output logic o_lookup_range, // 当前工作查询位于输入区域
  output logic o_work_range, // 已保存工作请求位于输入区域
  input wire logic i_demand_range, // 当前缺失请求位于输入区域
  input wire logic [31:0] i_offer_retire_q, // 已保存预取描述的释放顺序
  input wire logic [p_set_width-1:0] i_fill_set, // 当前填充组号
  input wire logic [p_way_width-1:0] i_fill_way, // 当前填充路号
  input wire logic i_select_launch, // 替换选择发出新填充
  input wire logic [11:0] i_range_below, // 各地址范围比较结果
  input wire logic i_ram_wen, // 本周期写入缓存数据
  output logic o_spec_read_conflict, // 查询读取与填充写入存在冲突
  input wire logic [p_read_width-1:0] i_ram_rdata, // 已保存普通读取数据
  input wire logic i_span_rsp_valid, // 填充传输返回有效
  input wire logic i_span_rsp_ready, // 填充传输返回可接收
  input wire logic i_span_last, // 填充传输最后一拍
  input wire logic [31:0] i_span_addr, // 填充传输当前字节地址
  input wire logic [p_request_width-1:0] i_request_queue[p_demand_depth], // 按接收顺序保存的请求描述数组
  output logic [p_request_width-1:0] o_incoming_request, // 正式输入请求描述
  output logic [p_request_width-1:0] o_work_request, // 已保存工作请求描述
  output logic [p_request_width-1:0] o_processing_request, // 补充同拍元数据后的工作请求描述
  output logic o_lookup_input_valid, // 正式输入或预读输入可供查询
  output logic o_preview_active, // 当前工作项使用前一拍预读结果
  output logic o_preview_source_select, // 当前输入来源选择预读请求
  output logic [1:0][31:0] o_retire_decode_output, // 工作请求与预取描述的释放序号
  output logic [p_set_width-1:0] o_lookup_read_set, // 当前存储读取组号
  output logic [p_set_width-1:0] o_lookup_snapshot_set, // 已保存存储读取组号
  output logic [31:2] o_lookup_read_word, // 当前存储读取字地址
  output logic o_lookup_snapshot_valid, // 已保存查询结果有效
  output logic o_lookup_ready, // 当前工作查询具备有效快照
  output logic o_work_lookup_ready, // 已保存工作请求具备有效快照
  output logic o_demand_lookup_ready, // 缺失请求具备有效快照
  output logic o_demand_word_matches_q, // 已保存字地址与缺失请求相同
  input wire logic [p_read_width-1:0] i_saved_response_data, // 返回队列队首的数据
  input wire logic i_saved_response_error, // 返回队列队首的错误状态
  input wire logic [p_queue_addr_width-1:0] i_request_head, // 请求队列队首位置
  input wire logic [p_queue_count_width-1:0] i_request_count, // 请求队列占用数量
  input wire logic [p_queue_count_width-1:0] i_response_count, // 返回队列占用数量
  input wire logic [p_queue_count_width-1:0] i_outstanding_count, // 已接收且尚未返回的请求数量
  output logic o_accepted_request, // 正式请求接收事件
  output logic o_consumed_response, // 返回数据消费事件
  output logic o_request_push, // 正式请求进入请求队列
  output logic o_request_pop, // 队首请求处理完成
  output logic o_response_push, // 处理结果进入返回队列
  output logic o_response_pop, // 队首返回数据被消费
  output logic o_core_rsp_ready, // 返回队列可保存当前处理结果
  output logic o_core_rsp_error, // 当前处理结果的错误状态
  output logic o_fast_hit_response, // 当前命中可直接返回
  input wire logic i_bypass_launch, // 旁路请求发出新填充
  output logic [p_read_width-1:0] o_core_rsp_data, // 当前处理结果的数据
  input wire logic [p_read_width-1:0] i_speculative_data[p_ways], // 各路同步读出的缓存数据
  input wire logic [p_way_addr_width-1:0] i_speculative_address, // 当前存储读取的行内字地址
  input wire logic [p_way_addr_width-1:0] i_fill_word_address, // 当前填充写入的行内字地址
  input wire logic i_metadata_enable, // 当前周期允许元数据更新
  input wire logic i_metadata_fill_good, // 当前周期填充成功
  output logic [1:0] o_lookup_candidate_select, // 当前查询选择的候选编号
  input wire logic [p_ways-1:0] i_lookup_valid_next, // 各路当前查询需要保存的有效位
  output logic o_lookup_saved_fill_set_match // 已保存查询组号与当前填充组号相同
);
  localparam int SETS=p_sets, WAYS=p_ways, LINE_BYTES=p_line_bytes;
  localparam int BUS_WIDTH=p_bus_width, READ_WIDTH=p_read_width, DEMAND_DEPTH=p_demand_depth;
  localparam int SI=p_set_width, LB=p_line_shift, WB=p_word_width, WI=p_way_width;
  localparam int DQ_AW=p_queue_addr_width, DQ_CW=p_queue_count_width, WAY_AW=p_way_addr_width;
  localparam int RAM_BANK_SHIFT=$clog2((BUS_WIDTH > READ_WIDTH ? BUS_WIDTH : READ_WIDTH)/32);
  localparam logic [31:0] INF=32'hffff_ffff;
  localparam logic [1:0] FG_IDLE=2'd0, FG_MISS=2'd1, FG_RESP=2'd2;
  localparam logic [1:0] F_IDLE=2'd0, F_REQ=2'd1, F_DATA=2'd2;
  typedef struct packed {
    logic [31:0] address, epoch, retire, progress;
    logic [SI-1:0] set_index;
    logic geometry, event_first, in_range;
  } demand_t;

  //! 1. 接口字段与内部状态
  //! ---------------------
  logic cfg_valid;
  logic cfg_ready;
  logic req_valid;
  logic req_ready;
  logic preview_valid;
  logic [31:0] preview_addr;
  logic preview_index_valid;
  logic [31:0] preview_index;
  logic [31:0] req_addr;
  logic req_geometry;
  logic req_event_first;
  logic rsp_valid;
  logic rsp_ready;
  logic [READ_WIDTH-1:0] rsp_data;
  logic rsp_error;
  logic rsp_success;
  logic rsp_failure;
  logic req_window_index_valid;
  logic [31:0] req_window_index;
  logic [31:0] req_window_epoch;
  logic [31:0] req_window_retire;
  logic [31:0] req_window_progress;
  logic [1:0] fg_state;
  logic [1:0] fill_state;
  logic configured;
  logic clearing;
  logic [SI-1:0] clear_set;
  logic [31:0] base_q;
  logic [31:0] end_q;
  logic bypass_q;
  logic windowed_q;
  logic [WAYS-1:0][31:LB] lookup_tag;
  logic [WAYS-1:0] valid_lookup;
  logic [31:0] demand_addr;
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
  logic [WAYS-1:0] work_tag_hits;
  logic [WAYS-1:0] demand_tag_hits;
  logic [WI-1:0] lookup_way;
  logic req_fire;
  logic queued_read_fire;
  logic lookup_range;
  logic work_range;
  logic demand_range;
  logic [31:0] offer_retire_q;
  logic [SI-1:0] fill_set;
  logic [WI-1:0] fill_way;
  logic select_launch;
  logic [11:0] range_below;
  logic ram_wen;
  logic spec_read_conflict;
  logic [READ_WIDTH-1:0] ram_rdata;
  logic span_rsp_valid;
  logic span_rsp_ready;
  logic span_last;
  logic [31:0] span_addr;
  demand_t request_queue[DEMAND_DEPTH];
  demand_t incoming_request;
  demand_t work_request;
  demand_t lookup_read_request;
  demand_t preview_request;
  demand_t lookup_input_request;
  demand_t processing_request;
  logic lookup_input_valid;
  logic preview_selected_q;
  logic preview_active;
  logic preview_source_select;
  logic preview_below_base;
  logic preview_below_end;
  logic unused_preview_base_equal;
  logic unused_preview_end_equal;
  logic [1:0][31:0] retire_decode_input;
  logic [1:0][31:0] retire_decode_output;
  logic [SI-1:0] lookup_read_set;
  logic [SI-1:0] lookup_snapshot_set;
  logic [31:2] lookup_read_word;
  logic lookup_snapshot_valid;
  logic lookup_ready;
  logic work_lookup_ready;
  logic demand_lookup_ready;
  logic work_word_matches_q;
  logic demand_word_matches_q;
  logic work_snapshot_matches_q;
  logic work_word_matches_next;
  logic work_snapshot_matches_next;
  logic response_snapshot_ready;
  logic demand_word_matches_next;
  logic direct_response_snapshot_ready;
  logic lookup_idle_set_match;
  logic [1:0] lookup_head_matches;
  logic [1:0] lookup_input_matches;
  logic [1:0] lookup_preview_matches;
  logic [1:0] lookup_request_matches;
  logic lookup_next_work_match;
  logic lookup_idle_demand_match;
  logic lookup_pop_work_match;
  logic [READ_WIDTH-1:0] saved_response_data;
  logic saved_response_error;
  logic [DQ_AW-1:0] request_head;
  logic [DQ_CW-1:0] request_count;
  logic [DQ_CW-1:0] response_count;
  logic [DQ_CW-1:0] outstanding_count;
  logic accepted_request;
  logic consumed_response;
  logic request_push;
  logic request_pop;
  logic response_push;
  logic response_pop;
  logic work_valid;
  logic work_ready;
  logic core_rsp_valid;
  logic core_rsp_ready;
  logic core_rsp_error;
  logic fast_hit_response;
  logic bypass_launch;
  logic incoming_range;
  logic [READ_WIDTH-1:0] core_rsp_data;
  logic [READ_WIDTH-1:0] speculative_data[WAYS];
  wire [WAY_AW-1:0] speculative_address;
  wire [WAY_AW-1:0] fill_word_address;
  logic metadata_enable;
  logic metadata_fill_good;
  logic [1:0] lookup_candidate_select;
  logic [WAYS-1:0] lookup_valid_next;
  logic lookup_saved_fill_set_match;

  assign cfg_valid = i_cfg_valid;
  assign cfg_ready = i_cfg_ready;
  assign req_valid = i_req_valid;
  assign o_req_ready = req_ready;
  assign preview_valid = i_preview_valid;
  assign preview_addr = i_preview_addr;
  assign preview_index_valid = i_preview_index_valid;
  assign preview_index = i_preview_index;
  assign req_addr = i_req_addr;
  assign req_geometry = i_req_geometry;
  assign req_event_first = i_req_event_first;
  assign o_rsp_valid = rsp_valid;
  assign rsp_ready = i_rsp_ready;
  assign o_rsp_data = rsp_data;
  assign o_rsp_error = rsp_error;
  assign o_rsp_success = rsp_success;
  assign o_rsp_failure = rsp_failure;
  assign req_window_index_valid = i_req_window_index_valid;
  assign req_window_index = i_req_window_index;
  assign req_window_epoch = i_req_window_epoch;
  assign req_window_retire = i_req_window_retire;
  assign req_window_progress = i_req_window_progress;
  assign fg_state = i_fg_state;
  assign fill_state = i_fill_state;
  assign configured = i_configured;
  assign clearing = i_clearing;
  assign clear_set = i_clear_set;
  assign base_q = i_base_q;
  assign end_q = i_end_q;
  assign bypass_q = i_bypass_q;
  assign windowed_q = i_windowed_q;
  assign lookup_tag = i_lookup_tag;
  assign valid_lookup = i_valid_lookup;
  assign demand_addr = i_demand_addr;
  assign demand_set = i_demand_set;
  assign response_error = i_response_error;
  assign demand_filled = i_demand_filled;
  assign demand_fill_set = i_demand_fill_set;
  assign demand_fill_way = i_demand_fill_way;
  assign o_lookup_addr = lookup_addr;
  assign o_lookup_set = lookup_set;
  assign o_lookup_candidate_set = lookup_candidate_set;
  assign o_lookup_input_set = lookup_input_set;
  assign o_lookup_hit = lookup_hit;
  assign o_work_tag_hits = work_tag_hits;
  assign o_demand_tag_hits = demand_tag_hits;
  assign o_lookup_way = lookup_way;
  assign o_req_fire = req_fire;
  assign o_lookup_range = lookup_range;
  assign o_work_range = work_range;
  assign demand_range = i_demand_range;
  assign offer_retire_q = i_offer_retire_q;
  assign fill_set = i_fill_set;
  assign fill_way = i_fill_way;
  assign select_launch = i_select_launch;
  assign range_below = i_range_below;
  assign ram_wen = i_ram_wen;
  assign o_spec_read_conflict = spec_read_conflict;
  assign ram_rdata = i_ram_rdata;
  assign span_rsp_valid = i_span_rsp_valid;
  assign span_rsp_ready = i_span_rsp_ready;
  assign span_last = i_span_last;
  assign span_addr = i_span_addr;
  for (genvar request_slot = 0; request_slot < DEMAND_DEPTH; request_slot++) begin : g_request_input
    assign request_queue[request_slot] = demand_t'(i_request_queue[request_slot]);
  end
  assign o_incoming_request = incoming_request;
  assign o_work_request = work_request;
  assign o_processing_request = processing_request;
  assign o_lookup_input_valid = lookup_input_valid;
  assign o_preview_active = preview_active;
  assign o_preview_source_select = preview_source_select;
  assign o_retire_decode_output = retire_decode_output;
  assign o_lookup_read_set = lookup_read_set;
  assign o_lookup_snapshot_set = lookup_snapshot_set;
  assign o_lookup_read_word = lookup_read_word;
  assign o_lookup_snapshot_valid = lookup_snapshot_valid;
  assign o_lookup_ready = lookup_ready;
  assign o_work_lookup_ready = work_lookup_ready;
  assign o_demand_lookup_ready = demand_lookup_ready;
  assign o_demand_word_matches_q = demand_word_matches_q;
  assign saved_response_data = i_saved_response_data;
  assign saved_response_error = i_saved_response_error;
  assign request_head = i_request_head;
  assign request_count = i_request_count;
  assign response_count = i_response_count;
  assign outstanding_count = i_outstanding_count;
  assign o_accepted_request = accepted_request;
  assign o_consumed_response = consumed_response;
  assign o_request_push = request_push;
  assign o_request_pop = request_pop;
  assign o_response_push = response_push;
  assign o_response_pop = response_pop;
  assign o_core_rsp_ready = core_rsp_ready;
  assign o_core_rsp_error = core_rsp_error;
  assign o_fast_hit_response = fast_hit_response;
  assign bypass_launch = i_bypass_launch;
  assign o_core_rsp_data = core_rsp_data;
  assign speculative_data = i_speculative_data;
  assign speculative_address = i_speculative_address;
  assign fill_word_address = i_fill_word_address;
  assign metadata_enable = i_metadata_enable;
  assign metadata_fill_good = i_metadata_fill_good;
  assign o_lookup_candidate_select = lookup_candidate_select;
  assign lookup_valid_next = i_lookup_valid_next;
  assign o_lookup_saved_fill_set_match = lookup_saved_fill_set_match;

  function automatic logic [SI-1:0] cache_set(input logic [31:0] address,
      input logic indexed, input logic [31:0] index);
    if (indexed) return SI'(index);
    return SI'(address>>LB) ^ SI'(address>>(LB+SI));
  endfunction

  //! 2. 请求读取、匹配与响应
  //! -----------------------
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
    logic credit_returned;
    // 空闲直达响应不占用在途名额，接收资格只依赖已经保存响应的释放。
    assign credit_returned = p_preview_request ? response_pop : consumed_response;
    assign req_ready = configured && !clearing && !cfg_valid &&
        (outstanding_count < DQ_CW'(DEMAND_DEPTH) || credit_returned) &&
        (windowed_q || outstanding_count == 0 || credit_returned);
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
  if (DEMAND_DEPTH == 1) begin : g_single_preview_select
    assign preview_source_select = p_preview_request &&
        (!req_valid || (preview_active && req_fire));
  end else if (p_preview_request) begin : g_queued_preview_select
    // 空闲输入准备候选；当前预读内容可处理时，同时读取下一候选。
    // 地址选择只使用保存的匹配和读取容量，正式握手保持独立。
    always_comb begin
      preview_source_select = 1'b0;
      case (req_valid)
        1'b0: preview_source_select = 1'b1;
        1'b1: begin
          case ({g_queued_preview_active.preview_match, work_ready})
            2'b11: preview_source_select = 1'b1;
            default: begin end
          endcase
        end
        default: begin end
      endcase
    end
  end else begin : g_no_preview_select
    assign preview_source_select = 1'b0;
  end
  assign lookup_input_request = preview_source_select ? preview_request : incoming_request;
  assign lookup_input_valid = req_valid || p_preview_request;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) preview_selected_q <= 1'b0;
    else preview_selected_q <= preview_valid && preview_source_select && fg_state != FG_MISS &&
        (request_count == 0 || (queued_read_fire && request_count == DQ_CW'(1)));
  end
  // 空闲请求名额可直接消费前一边沿准备的快照，正式请求仍完整握手。
  if (DEMAND_DEPTH == 1) begin : g_single_preview_active
    assign preview_active = p_preview_request && req_valid && preview_selected_q &&
        request_count == 0 && outstanding_count == 0 && !cfg_valid;
  end else if (p_preview_request) begin : g_queued_preview_active
    // 预读只提前完成同步读取，返回数据仍写入原响应寄存器。
    // 完整地址及组号必须与前一拍保存内容一致，配置和容量由处理事件统一检查。
    // 地址相同且配置保持时，保存的范围结果与正式请求一致，范围运算不参与来源选择。
    logic preview_match, accepted_known;
    // 地址身份与正式接收并行计算，处理事件末级合并读取匹配和容量资格。
    conv_cache_queued_preview #(.p_set_width(SI)) u_active (
      .i_preview_selected(preview_selected_q),
      .i_queue_empty(request_count == 0), .i_foreground_idle(fg_state == FG_IDLE),
      .i_request_address(incoming_request.address), .i_saved_address(work_request.address),
      .i_request_set(incoming_request.set_index), .i_saved_set(work_request.set_index),
      .i_saved_range(work_request.in_range), .o_match(preview_match)
    );
    always_comb begin
      accepted_known = 1'b0;
      case (accepted_request)
        1'b1: accepted_known = 1'b1;
        default: begin end
      endcase
    end
    assign preview_active = preview_match && accepted_known;
  end else begin : g_no_preview_active
    assign preview_active = 1'b0;
  end
  // 队首位置直接选择元数据，较晚的处理资格只控制状态更新。
  // 空队列只有预读请求可以被处理，此时元数据来自正式输入。
  always_comb begin
    processing_request = work_request;
    if ((DEMAND_DEPTH > 1 && p_preview_request) ? request_count == 0 : preview_active) begin
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
  if (DEMAND_DEPTH > 1 && p_preview_request) begin : g_parallel_preview_fire
    (* keep = 1 *) logic preview_capacity_ready;
    (* keep = 1 *) logic queued_capacity_ready;
    // 保存请求与预读请求独立形成容量资格，地址匹配只参与最终归并。
    assign preview_capacity_ready = g_queued_preview_active.accepted_known && work_ready;
    assign queued_capacity_ready = request_count != 0 && work_ready;
    assign req_fire = queued_capacity_ready ||
        (g_queued_preview_active.preview_match && preview_capacity_ready);
  end else begin : g_regular_request_fire
    always_comb begin
      req_fire = work_fire_parallel;
`ifndef SYNTHESIS
      if ((^bypass_q) === 1'bx) req_fire = work_valid && work_ready;
`endif
    end
  end
  if (DEMAND_DEPTH > 1 && p_preview_request) begin : g_queued_read_event
    logic parallel_queued_fire;
    // 只有已经入队的请求才改变下一项读取位置，预读直接处理不参与读取地址反馈。
    conv_cache_request_qualification u_fire (
      .i_available(request_count != 0 && work_capacity_ready), .i_bypass(bypass_q),
      .i_snapshot_valid(lookup_snapshot_valid), .i_snapshot_match(work_snapshot_matches_q),
      .o_fire(parallel_queued_fire)
    );
    always_comb begin
      queued_read_fire = parallel_queued_fire;
`ifndef SYNTHESIS
      if ((^bypass_q) === 1'bx) queued_read_fire = request_count != 0 && work_ready;
`endif
    end
  end else begin : g_shared_read_event
    assign queued_read_fire = req_fire;
  end
  assign request_push=accepted_request && !(preview_active && req_fire);
  assign request_pop=request_count!=0 && req_fire;
  // 标签与请求字段共用原查询边沿，返回控制读取保存后的比较结果。
  // 工作地址与缺失地址分别匹配同拍标签，并独立形成命中资格。
  if (DEMAND_DEPTH > 1) begin : g_registered_tag_compare
    // 返回队列提供寄存边界，标签先同步读取，再与同拍保存的请求地址比较。
    for (genvar hit_way = 0; hit_way < WAYS; hit_way++) begin : g_way
      logic work_tag_matches, demand_tag_matches;
      conv_cache_snapshot_equal #(.p_width(32-LB)) u_work_tag (
        .i_a(lookup_tag[hit_way][31:LB]), .i_b(work_request.address[31:LB]),
        .o_equal(work_tag_matches)
      );
      conv_cache_snapshot_equal #(.p_width(32-LB)) u_demand_tag (
        .i_a(lookup_tag[hit_way][31:LB]), .i_b(demand_addr[31:LB]),
        .o_equal(demand_tag_matches)
      );
      assign work_tag_hits[hit_way] = valid_lookup[hit_way] && work_tag_matches;
      assign demand_tag_hits[hit_way] = valid_lookup[hit_way] && demand_tag_matches;
    end
  end else begin : g_direct_tag_compare
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
    // 返回队列保存普通完成结果和被下游停顿的预读结果。
    // 已准备命中且当前没有在途请求时，正式接收与成功返回可在同拍完成。
    logic preview_response;
    always_comb begin
      preview_response = 1'b0;
      if (p_preview_request) begin
        case (preview_active && req_fire && fast_hit_response &&
              response_count == 0 && outstanding_count == 0)
          1'b1: preview_response = 1'b1;
          default: begin end
        endcase
      end
    end
    // 正式接收且完整地址匹配时使用同步读取的数据，反压时原样保存到响应队列。
    assign rsp_valid = response_count != 0 || preview_response;
    assign rsp_data = preview_response ? core_rsp_data : saved_response_data;
    assign rsp_error = preview_response ? 1'b0 : saved_response_error;
    assign response_push = core_rsp_valid && core_rsp_ready && !(preview_response && rsp_ready);
    // 直达命中只产生成功响应，错误资格独立于直达选择。
    assign rsp_success = preview_response || (response_count != 0 && !saved_response_error);
    assign rsp_failure = response_count != 0 && saved_response_error;
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
          saved_response_data :
          (fg_state == FG_IDLE ? speculative_data[response_way] :
           (response_error ? '0 : ram_rdata));
    end
    conv_cache_response_data_select #(.p_ways(WAYS), .p_width(READ_WIDTH)) u_data (
      .i_hits(work_tag_hits), .i_data(response_data_by_way), .o_data(rsp_data)
    );
    assign rsp_error = response_count != 0 ? saved_response_error : core_rsp_error;
    assign response_push = core_rsp_valid && core_rsp_ready && (response_count != 0 || !rsp_ready);
    logic saved_success, parallel_success;
    assign saved_success = (response_count != 0 && !saved_response_error) ||
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
      rsp_failure = (response_count != 0 && saved_response_error) ||
          (response_count == 0 && fg_state == FG_RESP && response_error);
      case (^{response_count, fg_state, fast_hit_response, response_error,
               saved_response_error})
        1'b0, 1'b1: begin end
        default: begin
          rsp_success = rsp_valid && !rsp_error;
          rsp_failure = rsp_valid && rsp_error;
        end
      endcase
    end
  end
  assign response_pop=response_count!=0 && rsp_ready;

  assign lookup_addr = fg_state==FG_MISS ? demand_addr : work_request.address;
  assign lookup_set = bypass_q ? demand_fill_set :
      (fg_state==FG_MISS ? demand_set : work_request.set_index);
  assign lookup_range = fg_state == FG_MISS ? demand_range : work_range;

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
      if (fg_state != FG_MISS && queued_read_fire && request_count != 0) begin
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
    if (fg_state != FG_MISS && queued_read_fire && request_count != 0) begin
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
  (* keep = 1 *) logic demand_snapshot_set_match, fill_snapshot_set_match;
  logic parallel_demand_lookup_ready;
  // 两个保存组号分别完成比较，查询资格只归并已经形成的匹配结果。
  assign demand_snapshot_set_match = lookup_snapshot_set == demand_set;
  assign fill_snapshot_set_match = lookup_snapshot_set == demand_fill_set;
  conv_cache_demand_lookup u_demand_lookup (
    .i_valid(lookup_snapshot_valid), .i_word_match(demand_word_matches_q),
    .i_bypass(bypass_q), .i_demand_set_match(demand_snapshot_set_match),
    .i_fill_set_match(fill_snapshot_set_match), .o_ready(parallel_demand_lookup_ready)
  );
  // 旁路选择含未知值时保留先选择组号再比较的四态结果。
  always_comb begin
    case (bypass_q)
      1'b0, 1'b1: demand_lookup_ready = parallel_demand_lookup_ready;
      default: demand_lookup_ready = lookup_snapshot_valid && demand_word_matches_q &&
          (lookup_snapshot_set == (bypass_q ? demand_fill_set : demand_set));
    endcase
  end
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
    logic [3:0][1:0] candidate_result;
    logic read_select_i_miss, read_select_i_empty, read_select_i_many;
    logic read_select_i_fire, read_select_i_input_valid;
    logic [3:0][1:0] read_select_i_result;
    logic [1:0] read_select_o_result;
    for (genvar candidate=0; candidate<4; candidate++) begin : g_result
      if (candidate == 2 && DEMAND_DEPTH > 1 && p_preview_request) begin : g_formal
        // 正式输入与预读输入各自完成冲突检查，读取来源只选择最终资格。
        assign candidate_result[candidate][0] = ram_wen && input_conflict_results[0][0];
        assign candidate_result[candidate][1] =
            !(metadata_enable && metadata_fill_good && input_conflict_results[0][1]) &&
            !candidate_result[candidate][0];
      end else begin : g_regular
        assign candidate_result[candidate][0] = ram_wen && lookup_candidate_conflict[candidate];
        assign candidate_result[candidate][1] =
            !(metadata_enable && metadata_fill_good && lookup_candidate_fill_match[candidate]) &&
            !candidate_result[candidate][0];
      end
    end
    // 每个地址来源分别完成读取冲突和快照资格，需求接收只选择单比特结果。
    assign read_select_i_miss = fg_state == FG_MISS;
    assign read_select_i_empty = request_count == 0;
    assign read_select_i_many = request_count > DQ_CW'(1);
    assign read_select_i_fire = queued_read_fire;
    assign read_select_i_input_valid = lookup_input_valid;
    assign read_select_i_result = candidate_result;
    conv_cache_queued_read_select u_read_select (
      .i_miss(read_select_i_miss), .i_empty(read_select_i_empty),
      .i_many(read_select_i_many), .i_fire(read_select_i_fire),
      .i_input_valid(read_select_i_input_valid), .i_result(read_select_i_result),
      .o_result(read_select_o_result)
    );
    logic [1:0] selected_read_result;
    if (DEMAND_DEPTH > 1 && p_preview_request) begin : g_preview_result
      (* keep = 1 *) logic [1:0] prepared_result;
      logic read_uses_input;
      assign prepared_result[0] = ram_wen && input_conflict_results[1][0];
      assign prepared_result[1] =
          !(metadata_enable && metadata_fill_good && input_conflict_results[1][1]) &&
          !prepared_result[0];
      assign read_uses_input = !read_select_i_miss &&
          (read_select_i_empty ||
           (read_select_i_fire && !read_select_i_many && read_select_i_input_valid));
      assign selected_read_result = read_uses_input && preview_source_select ?
          prepared_result : read_select_o_result;
    end else begin : g_regular_result
      assign selected_read_result = read_select_o_result;
    end
    always_comb begin
      spec_read_conflict = selected_read_result[0];
      lookup_snapshot_good = selected_read_result[1];
      case (^{fg_state, req_fire, lookup_input_valid, request_count})
        1'b0, 1'b1: begin end
        default: begin
          spec_read_conflict = ram_wen &&
              (speculative_address >> RAM_BANK_SHIFT) == (fill_word_address >> RAM_BANK_SHIFT);
          lookup_snapshot_good = !(metadata_enable && metadata_fill_good && lookup_fill_match) &&
              !spec_read_conflict;
        end
      endcase
    end
  end

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

  if (DEMAND_DEPTH == 1) begin : g_saved_fill_output
    assign lookup_saved_fill_set_match = g_saved_fill_match.lookup_fill_set_match_q;
  end else begin : g_unused_fill_output
    assign lookup_saved_fill_set_match = 1'b0;
  end

endmodule

`default_nettype wire
