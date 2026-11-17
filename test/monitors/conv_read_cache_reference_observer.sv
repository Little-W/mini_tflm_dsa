// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_read_cache_reference_observer #(
  parameter int TB_FILL=0,
  parameter int TB_HINT_WAIT=0,
  parameter int TB_IDLE=0,
  parameter int TB_TAG_EVAL=0
);


logic [31:0] stat_hits,stat_misses,stat_read_bytes;

always @(posedge conv_read_cache_reference.clk or negedge conv_read_cache_reference.rst_n)begin
 if(!conv_read_cache_reference.rst_n)begin stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;end
 else if(conv_read_cache_reference.cfg_valid && conv_read_cache_reference.cfg_ready)begin stat_hits<=0;stat_misses<=0;stat_read_bytes<=0;end
 else begin
  if(32'(conv_read_cache_reference.state)==TB_IDLE && conv_read_cache_reference.req_valid && conv_read_cache_reference.req_ready && conv_read_cache_reference.req_addr>=conv_read_cache_reference.base_q && conv_read_cache_reference.req_addr<conv_read_cache_reference.end_q)begin
   if(conv_read_cache_reference.bypass_q)stat_misses<=stat_misses+1;
   else if(conv_read_cache_reference.geometry_q && conv_read_cache_reference.req_geometry && conv_read_cache_reference.transient_valid && conv_read_cache_reference.transient_tag==conv_read_cache_reference.req_addr[31:4])stat_hits<=stat_hits+1;
  end
  if(32'(conv_read_cache_reference.state)==TB_TAG_EVAL || 32'(conv_read_cache_reference.state)==TB_HINT_WAIT)begin
   if(conv_read_cache_reference.hit)stat_hits<=stat_hits+1;
   else if(!(conv_read_cache_reference.request_geometry_q && !conv_read_cache_reference.has_invalid && !conv_read_cache_reference.effective_hint_valid))stat_misses<=stat_misses+1;
  end
  if(32'(conv_read_cache_reference.state)==TB_FILL && conv_read_cache_reference.span_rsp_valid && conv_read_cache_reference.span_rsp_ready)stat_read_bytes<=stat_read_bytes+32'($countones(conv_read_cache_reference.span_strb));
 end
end

endmodule
bind conv_read_cache_reference conv_read_cache_reference_observer #(
  .TB_FILL(32'(FILL)),
  .TB_HINT_WAIT(32'(HINT_WAIT)),
  .TB_IDLE(32'(IDLE)),
  .TB_TAG_EVAL(32'(TAG_EVAL))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
