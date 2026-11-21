// 配置比较与预读距离的完整参考表达式，输入覆盖全部固定位宽值。
module group_reference #(parameter int LANES=8)(
input logic [31:0] stimulus,output logic [(LANES>4 ? 8 : 4):0] result);
localparam int p_saved_group_lanes=LANES>4 ? 8 : 4;
logic [15:0] cfg_group_c,ch_q;
logic [p_saved_group_lanes:0] group_range_cfg;
assign {cfg_group_c,ch_q}=stimulus;
  if (LANES <= 8) begin : g_short_group_lane
    logic [p_saved_group_lanes-1:0][15:0] cfg_group_last;
    logic cfg_has_channel;
    logic [p_saved_group_lanes-1:0] cfg_short_group;

    assign cfg_has_channel = cfg_group_c != ch_q;
    for (genvar offset = 0; offset < p_saved_group_lanes; offset++) begin : g_cfg_offset
      assign cfg_group_last[offset] = cfg_group_c - 16'(offset + 1);
      assign cfg_short_group[offset] = cfg_group_c >= 16'(offset + 1) &&
        ch_q == cfg_group_last[offset];
    end
    for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_cfg_lane
      if (lane == 0) begin : g_any_channel
        assign group_range_cfg[lane] = cfg_has_channel;
      end else begin : g_remaining
        assign group_range_cfg[lane] = cfg_has_channel && !(|cfg_short_group[lane-1:0]);
      end
    end
  end

assign result=group_range_cfg;
endmodule

module prefetch_reference #(parameter int LINE_BYTES=16)(
input logic [64:0] stimulus,output logic [95:0] result);
logic [15:0] cfg_input_c,cfg_kernel_w,cfg_stride_w,cfg_dilation_w;
logic cfg_input_s16;
logic [31:0] cfg_pixel_bytes,cfg_line_pixels,cfg_pf_step;
assign {cfg_input_c,cfg_kernel_w,cfg_stride_w,cfg_dilation_w,cfg_input_s16}=stimulus;
  logic [LINE_BYTES:0] cfg_line_threshold, cfg_line_select;
  assign cfg_pixel_bytes = 32'(cfg_input_c) << cfg_input_s16;
  assign cfg_line_threshold[0] = 1'b1;
  for (genvar count = 1; count <= LINE_BYTES; count++) begin : g_line_threshold
    // 两种元素宽度分别与常量比较，输入位宽选择只作用于最终标志。
    assign cfg_line_threshold[count] = cfg_input_s16 ?
      32'(cfg_input_c) <= 32'(((LINE_BYTES-1)/count)/2) :
      32'(cfg_input_c) <= 32'((LINE_BYTES-1)/count);
  end
  for (genvar count = 0; count <= LINE_BYTES; count++) begin : g_line_select
    if (count == LINE_BYTES) begin : g_last
      assign cfg_line_select[count] = cfg_line_threshold[count];
    end else begin : g_has_next
      assign cfg_line_select[count] = cfg_line_threshold[count] && !cfg_line_threshold[count+1];
    end
  end
  logic [31:0] cfg_base_step;
  assign cfg_base_step = cfg_kernel_w == 16'd1 ? 32'(cfg_stride_w) : 32'(cfg_dilation_w);
  // 每种行内像素数先与步长比较，独热选择直接归并最终预读步长。
  always_comb begin
    cfg_line_pixels = 32'd0;
    cfg_pf_step = 32'd0;
    for (int count = 0; count <= LINE_BYTES; count++) begin
      cfg_line_pixels |= {32{cfg_line_select[count]}} & 32'(count+1);
      cfg_pf_step |= {32{cfg_line_select[count]}} &
        (cfg_base_step < 32'(count+1) ? 32'(count+1) : cfg_base_step);
    end
  end

assign result={cfg_pixel_bytes,cfg_line_pixels,cfg_pf_step};
endmodule
