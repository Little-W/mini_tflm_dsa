// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_im2col_frontend_observer #(parameter int p_state_width = 5);

// 观察器按状态寄存器宽度读取编码，统计编号保持与状态声明顺序一致。
localparam logic [p_state_width-1:0] OBS_IDLE = p_state_width'(p_state_width == 22 ? 1 : 0);
localparam logic [p_state_width-1:0] OBS_WAIT_WORD = p_state_width'(p_state_width == 22 ? (1 << 19) : 19);
localparam logic [p_state_width-1:0] OBS_ZERO_STREAM = p_state_width'(p_state_width == 22 ? (1 << 21) : 21);

function automatic int state_number(input logic [p_state_width-1:0] value);
  state_number = int'(value);
  if (p_state_width == 22) begin
    state_number = 0;
    for (int bit_index = 0; bit_index < p_state_width; bit_index++)
      if (value[bit_index]) state_number = bit_index;
  end
endfunction

wire [31:0] stat_hits=conv_im2col_frontend.u_cache.tb_observer.stat_hits;
wire [31:0] stat_misses=conv_im2col_frontend.u_cache.tb_observer.stat_misses;
wire [31:0] stat_read_bytes=conv_im2col_frontend.u_cache.tb_observer.stat_read_bytes;
wire [31:0] stat_prefetch_lines=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_lines;
wire [31:0] stat_prefetch_used=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_used;
wire [31:0] stat_prefetch_wasted=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_wasted;
wire [31:0] stat_prefetch_unused=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_unused;
wire [31:0] stat_prefetch_bytes=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_bytes;
wire [31:0] stat_prefetch_late=conv_im2col_frontend.u_cache.tb_observer.stat_prefetch_late;

// 可选仿真统计记录前端实际握手与状态驻留周期，不参与综合。
bit profile_enabled, trace_enabled;
longint unsigned profile_cycle, state_cycles[32];
longint unsigned descriptors, fast_same, fast_pixel, fast_tile, fast_skip, slow_descriptors;
longint unsigned cache_requests, request_stalls, response_waits, response_holds;
longint unsigned output_beats, consecutive_outputs, narrow_beats, padding_beats;
longint unsigned prefetch_busy, first_response_cycles, descriptor_start;
longint unsigned first_response_max;
longint unsigned idle_no_valid,idle_not_ready,idle_cache_hint,idle_predictor;
longint unsigned finish_no_valid,finish_not_ready;
bit previous_output, waiting_first_response;

initial begin
  profile_enabled=$test$plusargs("CONV_FRONTEND_PROFILE");
  trace_enabled=$test$plusargs("CONV_FRONTEND_TRACE");
end

always @(posedge conv_im2col_frontend.clk) begin
  if (!conv_im2col_frontend.rst_n) begin
    profile_cycle=0;
    descriptors=0;fast_same=0;fast_pixel=0;fast_tile=0;fast_skip=0;slow_descriptors=0;
    cache_requests=0;request_stalls=0;response_waits=0;response_holds=0;
    output_beats=0;consecutive_outputs=0;narrow_beats=0;padding_beats=0;
    prefetch_busy=0;first_response_cycles=0;first_response_max=0;descriptor_start=0;
    idle_no_valid=0;idle_not_ready=0;idle_cache_hint=0;idle_predictor=0;
    finish_no_valid=0;finish_not_ready=0;
    previous_output=0;waiting_first_response=0;
    for (int index=0;index<32;index++) state_cycles[index]=0;
  end else if (profile_enabled || trace_enabled) begin
    profile_cycle++;
    state_cycles[state_number(conv_im2col_frontend.state)]++;
    if (conv_im2col_frontend.state==OBS_IDLE) begin
      if (!conv_im2col_frontend.tile_valid) idle_no_valid++;
      if (!conv_im2col_frontend.tile_ready) idle_not_ready++;
      if (conv_im2col_frontend.cache_hint_pending) idle_cache_hint++;
      if (conv_im2col_frontend.pred_busy) idle_predictor++;
    end
    if (conv_im2col_frontend.finishing_tile) begin
      if (!conv_im2col_frontend.tile_valid) finish_no_valid++;
      if (!conv_im2col_frontend.tile_ready) finish_not_ready++;
    end
    if (conv_im2col_frontend.prefetch_phase!=0) prefetch_busy++;
    if (conv_im2col_frontend.cache_port_valid && conv_im2col_frontend.cache_port_ready)
      cache_requests++;
    if (conv_im2col_frontend.cache_port_valid && !conv_im2col_frontend.cache_port_ready)
      request_stalls++;
    if (conv_im2col_frontend.state==OBS_WAIT_WORD &&
        !conv_im2col_frontend.cache_rsp_valid) response_waits++;
    if (conv_im2col_frontend.wr_valid && !conv_im2col_frontend.wr_ready) response_holds++;
    if (conv_im2col_frontend.wr_valid && conv_im2col_frontend.wr_ready) begin
      output_beats++;
      if (previous_output) consecutive_outputs++;
      if (conv_im2col_frontend.narrow_output) narrow_beats++;
      if (conv_im2col_frontend.state==OBS_ZERO_STREAM) padding_beats++;
      if (waiting_first_response) begin
        first_response_cycles+=profile_cycle-descriptor_start;
        if (profile_cycle-descriptor_start>first_response_max)
          first_response_max=profile_cycle-descriptor_start;
        waiting_first_response=0;
      end
    end
    previous_output=conv_im2col_frontend.wr_valid && conv_im2col_frontend.wr_ready;
    if (conv_im2col_frontend.tile_valid && conv_im2col_frontend.tile_ready) begin
      descriptors++;
      descriptor_start=profile_cycle;
      waiting_first_response=1;
      if (conv_im2col_frontend.incoming_next_position_fast) fast_pixel++;
      else if (conv_im2col_frontend.incoming_next_tile_fast) fast_tile++;
      else if (conv_im2col_frontend.incoming_same_position_fast) begin
        if (conv_im2col_frontend.incoming_skip_tap) fast_skip++;
        else fast_same++;
      end
      else slow_descriptors++;
      if (trace_enabled && descriptors<=64)
        $display("CONV_FRONTEND_DESCRIPTOR cycle=%0d p=%0d q=%0d rows=%0d cols=%0d fast_same=%0d fast_pixel=%0d fast_tile=%0d narrow=%0d",
          profile_cycle,conv_im2col_frontend.tile_p0,conv_im2col_frontend.tile_q0,
          conv_im2col_frontend.tile_rows,conv_im2col_frontend.tile_cols,
          conv_im2col_frontend.incoming_same_position_fast,conv_im2col_frontend.incoming_next_position_fast,
          conv_im2col_frontend.incoming_next_tile_fast,conv_im2col_frontend.tile_narrow);
    end
  end
end

final begin
  if (profile_enabled || trace_enabled) begin
    $display("CONV_FRONTEND_PROFILE cycles=%0d descriptors=%0d fast_same=%0d fast_pixel=%0d fast_tile=%0d fast_skip=%0d slow=%0d requests=%0d request_stalls=%0d response_waits=%0d response_holds=%0d output_beats=%0d consecutive_outputs=%0d narrow_beats=%0d padding_beats=%0d prefetch_busy=%0d first_response_total=%0d first_response_max=%0d",
      profile_cycle,descriptors,fast_same,fast_pixel,fast_tile,fast_skip,slow_descriptors,
      cache_requests,request_stalls,response_waits,response_holds,output_beats,
      consecutive_outputs,narrow_beats,padding_beats,prefetch_busy,first_response_cycles,first_response_max);
    $display("CONV_FRONTEND_IDLE idle_no_valid=%0d idle_not_ready=%0d idle_cache_hint=%0d idle_predictor=%0d finish_no_valid=%0d finish_not_ready=%0d",
      idle_no_valid,idle_not_ready,idle_cache_hint,idle_predictor,finish_no_valid,finish_not_ready);
    for (int index=0;index<32;index++) begin
      if (state_cycles[index]!=0)
        $display("CONV_FRONTEND_STATE state=%0d cycles=%0d",index,state_cycles[index]);
    end
  end
end
endmodule
bind conv_im2col_frontend conv_im2col_frontend_observer #(.p_state_width($bits(state))) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
