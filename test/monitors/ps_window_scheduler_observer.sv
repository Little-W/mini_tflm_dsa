// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module ps_window_scheduler_observer #(
  parameter int TB_COMPLETE=0,
  parameter int TB_DRAINING=0,
  parameter int TB_IDLE=0,
  parameter int TB_OPENING=0,
  parameter int TB_SWEEPING=0
);


logic [31:0] stat_commands,stat_pressure_events,stat_early_finish_frames;
always @(posedge ps_window_scheduler.clk or negedge ps_window_scheduler.rst_n)begin
  if(!ps_window_scheduler.rst_n)begin stat_commands<=0;stat_pressure_events<=0;stat_early_finish_frames<=0;end
  else if(32'(ps_window_scheduler.phase)==TB_IDLE && ps_window_scheduler.start)begin stat_commands<=0;stat_pressure_events<=0;stat_early_finish_frames<=0;end
  else if(32'(ps_window_scheduler.phase)==TB_COMPLETE && ps_window_scheduler.done_ready)begin end
  else if(ps_window_scheduler.command_valid && ps_window_scheduler.command_pressure)begin
    if(!ps_window_scheduler.frame_final && ps_window_scheduler.protected_valid && ps_window_scheduler.live[ps_window_scheduler.protected_id] && ps_window_scheduler.protected_id!=ps_window_scheduler.candidate_id &&
       (32'(ps_window_scheduler.phase)==TB_OPENING || 32'(ps_window_scheduler.phase)==TB_SWEEPING))stat_pressure_events<=stat_pressure_events+1;
  end else if(ps_window_scheduler.command_valid && ps_window_scheduler.command_ready)begin end
  else if(ps_window_scheduler.command_active && ps_window_scheduler.command_complete)begin
    stat_commands<=stat_commands+1;
    if(32'(ps_window_scheduler.phase)==TB_DRAINING && ps_window_scheduler.active_final)stat_early_finish_frames<=stat_early_finish_frames+1;
  end
end

endmodule
bind ps_window_scheduler ps_window_scheduler_observer #(
  .TB_COMPLETE(32'(COMPLETE)),
  .TB_DRAINING(32'(DRAINING)),
  .TB_IDLE(32'(IDLE)),
  .TB_OPENING(32'(OPENING)),
  .TB_SWEEPING(32'(SWEEPING))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
