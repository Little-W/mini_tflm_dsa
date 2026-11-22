// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_windowed_cache_observer #(
  parameter int TB_F_DATA=0,
  parameter int TB_FG_MISS=0,
  parameter int TB_F_IDLE=0,
  parameter int TB_LB=0,
  parameter int TB_SETS=0,
  parameter int TB_SI=0,
  parameter int TB_WAYS=0
);


logic prefetched[TB_WAYS][TB_SETS];
logic observed_valid[TB_WAYS][TB_SETS];
logic [31:TB_LB] observed_tags[TB_WAYS][TB_SETS];
for(genvar way=0;way<TB_WAYS;way++)begin:g_way
 for(genvar set_id=0;set_id<TB_SETS;set_id++)begin:g_set
  wire lookup_target=32'(conv_windowed_cache.lookup_way)==way && 32'(conv_windowed_cache.lookup_set)==set_id;
  wire select_target=32'(conv_windowed_cache.select_way)==way && 32'(conv_windowed_cache.select_set)==set_id;
  wire fill_target=32'(conv_windowed_cache.fill_way)==way && 32'(conv_windowed_cache.fill_set)==set_id;
  wire consumed=(conv_windowed_cache.req_fire && conv_windowed_cache.lookup_range && conv_windowed_cache.lookup_hit) ||
                (32'(conv_windowed_cache.fg_state)==TB_FG_MISS && conv_windowed_cache.lookup_hit);
  // 统计使用独立的有效位模型，保持复位与配置清除期间的统计定义。
  always @(posedge conv_windowed_cache.clk or negedge conv_windowed_cache.rst_n) begin
    if (!conv_windowed_cache.rst_n) observed_valid[way][set_id] <= 1'b0;
    else if (conv_windowed_cache.metadata_enable) begin
      if ((conv_windowed_cache.clearing && 32'(conv_windowed_cache.clear_set)==set_id) ||
          (conv_windowed_cache.select_launch && select_target) ||
          (conv_windowed_cache.metadata_fill &&
           (conv_windowed_cache.fill_bad || conv_windowed_cache.span_error) && fill_target))
        observed_valid[way][set_id] <= 1'b0;
      if (conv_windowed_cache.metadata_fill_good && fill_target)
        observed_valid[way][set_id] <= !conv_windowed_cache.bypass_q;
    end
  end
  always @(posedge conv_windowed_cache.clk) begin
    if (conv_windowed_cache.metadata_enable && conv_windowed_cache.metadata_fill_good && fill_target)
      observed_tags[way][set_id] <= conv_windowed_cache.fill_addr[31:TB_LB];
  end
  always @(posedge conv_windowed_cache.clk or negedge conv_windowed_cache.rst_n)begin
   if(!conv_windowed_cache.rst_n)prefetched[way][set_id]<=0;
   else if(conv_windowed_cache.metadata_enable)begin
    if((conv_windowed_cache.clearing && 32'(conv_windowed_cache.clear_set)==set_id) ||
       (consumed && lookup_target) || (conv_windowed_cache.select_launch && select_target))prefetched[way][set_id]<=0;
    if(conv_windowed_cache.metadata_fill_good && fill_target)prefetched[way][set_id]<=conv_windowed_cache.fill_prefetch;
   end
  end
 end
end

logic [31:0] stat_hits,stat_misses,stat_read_bytes;
logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted;
logic [31:0] stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
logic [31:0] stat_peak_outstanding,stat_lookup_hits,stat_lookup_misses;
logic [TB_SI-1:0] accepted_set;
logic accepted_hit,accepted_range;
always_comb begin
  accepted_set=conv_windowed_cache.cache_set(conv_windowed_cache.req_addr,conv_windowed_cache.windowed_q && conv_windowed_cache.req_window_index_valid,conv_windowed_cache.req_window_index);
  accepted_range=conv_windowed_cache.req_addr>=conv_windowed_cache.base_q && conv_windowed_cache.req_addr<conv_windowed_cache.end_q;
  accepted_hit=0;
  for(int w=0;w<TB_WAYS;w++)
    if(!conv_windowed_cache.bypass_q && observed_valid[w][accepted_set] && observed_tags[w][accepted_set]==conv_windowed_cache.req_addr[31:TB_LB])accepted_hit=1;
  stat_prefetch_unused=0;
  for(int w=0;w<TB_WAYS;w++)for(int s=0;s<TB_SETS;s++)
    if(observed_valid[w][s] && prefetched[w][s])stat_prefetch_unused++;
end
always @(posedge conv_windowed_cache.clk or negedge conv_windowed_cache.rst_n) begin
  if(!conv_windowed_cache.rst_n)begin
    stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;
    stat_prefetch_lines<=0;stat_prefetch_used<=0;stat_prefetch_wasted<=0;
    stat_prefetch_bytes<=0;stat_prefetch_late<=0;
    stat_peak_outstanding<=0;stat_lookup_hits<=0;stat_lookup_misses<=0;
  end else if(conv_windowed_cache.cfg_valid && conv_windowed_cache.cfg_ready)begin
    stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;
    stat_prefetch_lines<=0;stat_prefetch_used<=0;stat_prefetch_wasted<=0;
    stat_prefetch_bytes<=0;stat_prefetch_late<=0;
    stat_peak_outstanding<=0;stat_lookup_hits<=0;stat_lookup_misses<=0;
  end else begin
    if(conv_windowed_cache.accepted_request && !conv_windowed_cache.consumed_response && 32'(conv_windowed_cache.outstanding_count)+1>stat_peak_outstanding)
      stat_peak_outstanding<=32'(conv_windowed_cache.outstanding_count)+1;
    if(conv_windowed_cache.accepted_request && accepted_range)begin
      if(accepted_hit)stat_hits<=stat_hits+1;
      else begin
        stat_misses<=stat_misses+1;
        if(32'(conv_windowed_cache.fill_state)!=TB_F_IDLE && conv_windowed_cache.fill_prefetch && conv_windowed_cache.fill_addr[31:TB_LB]==conv_windowed_cache.req_addr[31:TB_LB])
          stat_prefetch_late<=stat_prefetch_late+1;
      end
    end
    if(conv_windowed_cache.req_fire && conv_windowed_cache.lookup_range)begin
      if(conv_windowed_cache.lookup_hit)stat_lookup_hits<=stat_lookup_hits+1;
      else stat_lookup_misses<=stat_lookup_misses+1;
    end
    if(((conv_windowed_cache.req_fire && conv_windowed_cache.lookup_range && conv_windowed_cache.lookup_hit) || (32'(conv_windowed_cache.fg_state)==TB_FG_MISS && conv_windowed_cache.lookup_hit)) && prefetched[conv_windowed_cache.lookup_way][conv_windowed_cache.lookup_set])stat_prefetch_used<=stat_prefetch_used+1;
    if(conv_windowed_cache.select_launch && prefetched[conv_windowed_cache.select_way][conv_windowed_cache.select_set] && observed_valid[conv_windowed_cache.select_way][conv_windowed_cache.select_set])
      stat_prefetch_wasted<=stat_prefetch_wasted+1;
    if(32'(conv_windowed_cache.fill_state)==TB_F_DATA && conv_windowed_cache.span_rsp_valid && conv_windowed_cache.span_rsp_ready)begin
      stat_read_bytes<=stat_read_bytes+32'($countones(conv_windowed_cache.span_strb));
      if(conv_windowed_cache.fill_prefetch)stat_prefetch_bytes<=stat_prefetch_bytes+32'($countones(conv_windowed_cache.span_strb));
      if(conv_windowed_cache.span_last && !(conv_windowed_cache.fill_bad || conv_windowed_cache.span_error) && conv_windowed_cache.fill_prefetch)stat_prefetch_lines<=stat_prefetch_lines+1;
    end
  end
end

endmodule
bind conv_windowed_cache conv_windowed_cache_observer #(
  .TB_F_DATA(32'(F_DATA)),
  .TB_FG_MISS(32'(FG_MISS)),
  .TB_F_IDLE(32'(F_IDLE)),
  .TB_LB(32'(LB)),
  .TB_SETS(32'(SETS)),
  .TB_SI(32'(SI)),
  .TB_WAYS(32'(WAYS))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
