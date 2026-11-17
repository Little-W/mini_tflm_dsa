// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module conv_window_queue_observer;


logic [31:0] stat_requests,stat_completions,stat_peak_outstanding;
logic [31:0] stat_response_beats,stat_consecutive_responses,stat_request_response_overlap;
logic previous_response;
always @(posedge conv_window_queue.clk or negedge conv_window_queue.rst_n) begin
  if(!conv_window_queue.rst_n)begin
    stat_requests<=0;stat_completions<=0;stat_peak_outstanding<=0;
    stat_response_beats<=0;stat_consecutive_responses<=0;stat_request_response_overlap<=0;previous_response<=0;
  end else if(conv_window_queue.configure)begin
    stat_requests<=0;stat_completions<=0;stat_peak_outstanding<=0;
    stat_response_beats<=0;stat_consecutive_responses<=0;stat_request_response_overlap<=0;previous_response<=0;
  end else begin
    if(32'(conv_window_queue.next_count)>stat_peak_outstanding)stat_peak_outstanding<=32'(conv_window_queue.next_count);
    previous_response<=conv_window_queue.response_fire && !conv_window_queue.rsp_error;
    if(conv_window_queue.accept)stat_requests<=stat_requests+1;
    if(conv_window_queue.retire)stat_completions<=stat_completions+1;
    if(conv_window_queue.response_fire && !conv_window_queue.rsp_error)begin
      stat_response_beats<=stat_response_beats+1;
      if(previous_response)stat_consecutive_responses<=stat_consecutive_responses+1;
    end
    if(conv_window_queue.accept && conv_window_queue.response_fire)stat_request_response_overlap<=stat_request_response_overlap+1;
  end
end

endmodule
bind conv_window_queue conv_window_queue_observer tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
