// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
module soc_axil_ctrl_observer;
logic progress_trace_en;
longint unsigned cycle_q;
initial progress_trace_en=$test$plusargs("SOC_PROGRESS_TRACE");
always @(posedge soc_axil_ctrl.clk or negedge soc_axil_ctrl.rst_n)begin
 if(!soc_axil_ctrl.rst_n)cycle_q<=0;
 else begin
  cycle_q<=cycle_q+1;
  if(progress_trace_en && soc_axil_ctrl.wr_ready)begin
   case(soc_axil_ctrl.aw_seen_q ? soc_axil_ctrl.awaddr_q[3:2] : soc_axil_ctrl.s_axil_awaddr[3:2])
    2'b00:$display("[SOC_PROGRESS_TRACE] cycle=%0d finish status=%08x progress=%08x",cycle_q,soc_axil_ctrl.soc_status_next,soc_axil_ctrl.soc_progress);
    2'b11:$display("[SOC_PROGRESS_TRACE] cycle=%0d progress=%08x",cycle_q,soc_axil_ctrl.soc_progress_next);
    default:;
   endcase
  end
 end
end

endmodule
bind soc_axil_ctrl soc_axil_ctrl_observer tb_observer();
`endif
