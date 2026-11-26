// SPDX-License-Identifier: Apache-2.0
// Shared input cache. Policy 3 uses convolution-window lifetime and geometric
// lookahead; policies 0-2 provide fixed-capacity replacement comparisons.
`default_nettype none

/* 按所选替换策略组织共享输入缓存，提供窗口预取和正式读取响应。 */ module conv_read_cache #(
  parameter int SETS=128,
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
  input wire logic clk /* 工作时钟 */, rst_n /* 低有效复位 */,
  input wire logic cfg_valid /* 缓存任务配置有效 */,
  output logic cfg_ready /* 缓存可接收任务配置 */,
  input wire logic [31:0] cfg_base /* 输入区域首字节地址 */, cfg_bytes /* 输入区域的字节数 */,
  input wire logic cfg_bypass /* 启用直接读取旁路 */,
  input wire logic cfg_geometry = 1'b0 /* 启用卷积几何事件信息 */,
  input wire logic req_valid /* 正式缓存读取请求有效 */,
  output logic req_ready /* 缓存可接收正式读取请求 */,
  input wire logic preview_valid = 1'b0 /* 用于提前查询元数据的请求有效 */,
  input wire logic [31:0] preview_addr = 32'd0 /* 提前查询请求的字节地址 */,
  input wire logic preview_index_valid = 1'b0 /* 提前查询请求携带有效窗口索引 */,
  input wire logic [31:0] preview_index = 32'd0 /* 提前查询请求的窗口索引 */,
  input wire logic [31:0] req_addr /* 正式请求的字节地址 */,
  input wire logic req_geometry = 1'b0 /* 当前请求携带卷积几何事件信息 */,
  input wire logic req_event_first = 1'b0 /* 当前请求是几何事件的首个数据拍 */,
  input wire logic hint_valid = 1'b0 /* 下一次使用顺序提示有效 */,
  input wire logic [31:0] hint_next = 32'hffff_ffff /* 当前缓存行的下一次使用顺序 */,
  output logic hint_pending /* 当前缓存行仍等待下一次使用顺序提示 */,
  output logic rsp_valid /* 缓存读取响应有效 */,
  input wire logic rsp_ready /* 请求端可接收缓存读取响应 */,
  output logic [READ_WIDTH-1:0] rsp_data /* 返回请求端的读取数据 */,
  output logic rsp_error /* 当前读取响应携带错误 */,
  output logic rsp_success /* 当前读取响应成功完成事件 */,
  output logic rsp_failure /* 当前读取响应失败事件 */,
  output logic arvalid /* AXI：读地址请求有效 */,
  input wire logic arready /* AXI：可接收读地址请求 */,
  output logic [31:0] araddr /* AXI：读突发首字节地址 */,
  output logic [7:0] arlen /* AXI：读突发传输拍数减一 */,
  output logic [2:0] arsize /* AXI：每个读数据拍字节数的二进制对数 */,
  output logic [1:0] arburst /* AXI：读突发地址递增类型 */,
  input wire logic rvalid /* AXI：读响应数据有效 */,
  output logic rready /* AXI：可接收读响应数据 */,
  input wire logic [BUS_WIDTH-1:0] rdata /* AXI：读响应数据 */,
  input wire logic [1:0] rresp /* AXI：读响应状态码 */,
  input wire logic rlast /* AXI：当前读突发的最后一个数据拍 */,
  input wire logic cfg_windowed = 1'b0 /* 启用基于窗口索引的缓存管理 */,
  input wire logic cfg_prefetch_enable = 1'b0 /* 允许当前任务发起预取 */,
  input wire logic req_window_index_valid = 1'b0 /* 正式请求携带有效窗口索引 */,
  input wire logic [31:0] req_window_index = 32'd0 /* 正式请求的窗口索引 */,
  input wire logic [31:0] req_window_epoch = 32'd0 /* 正式请求的窗口代次 */,
  input wire logic [31:0] req_window_retire = 32'hffff_ffff /* 正式请求对应缓存行的释放顺序 */,
  input wire logic [31:0] req_window_progress = 32'd0 /* 当前窗口遍历的执行进度 */,
  input wire logic prefetch_valid = 1'b0 /* 预取请求有效 */,
  output logic prefetch_ready /* 缓存可接收预取请求 */,
  input wire logic [31:0] prefetch_addr = 32'd0 /* 预取目标的字节地址 */,
  input wire logic prefetch_window_index_valid = 1'b0 /* 预取请求携带有效窗口索引 */,
  input wire logic [31:0] prefetch_window_index = 32'd0 /* 预取目标的窗口索引 */,
  input wire logic [31:0] prefetch_window_epoch = 32'd0 /* 预取目标的窗口代次 */,
  input wire logic [31:0] prefetch_window_retire = 32'hffff_ffff /* 预取缓存行的释放顺序 */,
  input wire logic prefetch_next_fragment = 1'b0 /* 预取候选为当前数据的后续片段 */,
  input wire logic prefetch_ref_valid = 1'b0 /* 预取参考位置有效 */,
  input wire logic [31:0] prefetch_ref_addr = 32'd0 /* 预取参考位置的字节地址 */,
  input wire logic prefetch_ref_index_valid = 1'b0 /* 预取参考位置携带有效窗口索引 */,
  input wire logic [31:0] prefetch_ref_index = 32'd0 /* 预取参考位置的窗口索引 */,
  input wire logic [31:0] prefetch_ref_epoch = 32'd0 /* 预取参考位置的窗口代次 */);
  generate if (CACHE_POLICY==3) begin : g_window
    conv_windowed_cache #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .DEMAND_DEPTH(DEMAND_DEPTH),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES),
      .p_defer_retire_shift(p_defer_retire_shift),
      .p_preview_request(p_preview_request)) u_window (.*);
  end else begin : g_reference
    conv_read_cache_reference #(.SETS(SETS),.WAYS(WAYS),.LINE_BYTES(LINE_BYTES),
      .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_reference (.*);
    assign prefetch_ready=1'b0;
    assign rsp_success = rsp_valid && !rsp_error;
    assign rsp_failure = rsp_valid && rsp_error;
  end endgenerate
endmodule

`default_nettype wire
