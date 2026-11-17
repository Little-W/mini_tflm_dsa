// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module vector_engine_observer #(
  parameter int TB_WB_REQ=0,
  parameter int TB_WB_IDLE=0,
  parameter int TB_FAILED=0,
  parameter int TB_ADD_MULT=0,
  parameter int TB_ADD_ROUND=0,
  parameter int TB_ADD_STORE=0,
  parameter int TB_ADD_SUM=0,
  parameter int TB_CONFIGURE=0,
  parameter int TB_DONE=0,
  parameter int TB_EXECUTE=0,
  parameter int TB_IDLE=0,
  parameter int TB_LOAD_WAIT=0,
  parameter int TB_POOL_LOAD_WAIT=0,
  parameter int TB_SOFT_LUT_WAIT=0,
  parameter int TB_SOFT_RUN=0,
  parameter int TB_WB_DATA=0,
  parameter int TB_WB_WAIT=0
)(
  input wire hw_clk,
  input wire hw_dma_cfg_ready,
  input wire hw_rd_granted,
  input wire hw_rd_req,
  input wire hw_rst_n,
  input wire hw_soft_done,
  input wire hw_soft_lut_req_valid,
  input wire hw_start,
  input wire [31:0] hw_state,
  input wire [31:0] hw_wb_state,
  input wire hw_win_busy,
  input wire hw_wr_granted,
  input wire hw_wr_req
);


wire is_EXECUTE=hw_state==TB_EXECUTE;
wire is_FAILED=hw_state==TB_FAILED;
wire is_WB_IDLE=hw_wb_state==TB_WB_IDLE;
wire is_WB_REQ=hw_wb_state==TB_WB_REQ;
logic [31:0] stat_cycles,stat_compute,stat_dma_wait;
always @(posedge hw_clk or negedge hw_rst_n) begin
  if(!hw_rst_n)begin stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;end
  else if(32'(hw_state)==TB_IDLE && hw_start)begin stat_cycles<=0;stat_compute<=0;stat_dma_wait<=0;end
  else begin
    if(32'(hw_state)!=TB_IDLE && 32'(hw_state)!=TB_DONE)stat_cycles<=stat_cycles+1;
    if(32'(hw_state)==TB_EXECUTE || 32'(hw_state)==TB_ADD_MULT || 32'(hw_state)==TB_ADD_ROUND || 32'(hw_state)==TB_ADD_SUM || 32'(hw_state)==TB_ADD_STORE ||
       (32'(hw_state)==TB_SOFT_RUN && !hw_soft_lut_req_valid && !hw_soft_done))stat_compute<=stat_compute+1;
    if(32'(hw_state)==TB_LOAD_WAIT || hw_win_busy || 32'(hw_state)==TB_POOL_LOAD_WAIT || 32'(hw_wb_state)==TB_WB_DATA || 32'(hw_wb_state)==TB_WB_WAIT ||
       32'(hw_state)==TB_SOFT_LUT_WAIT || (hw_rd_req && !hw_rd_granted) || (hw_wr_req && !hw_wr_granted) ||
       (32'(hw_state)==TB_CONFIGURE && !hw_dma_cfg_ready))stat_dma_wait<=stat_dma_wait+1;
  end
end

endmodule
bind vector_engine vector_engine_observer #(
  .TB_WB_REQ(32'(WB_REQ)),
  .TB_WB_IDLE(32'(WB_IDLE)),
  .TB_FAILED(32'(FAILED)),
  .TB_ADD_MULT(32'(ADD_MULT)),
  .TB_ADD_ROUND(32'(ADD_ROUND)),
  .TB_ADD_STORE(32'(ADD_STORE)),
  .TB_ADD_SUM(32'(ADD_SUM)),
  .TB_CONFIGURE(32'(CONFIGURE)),
  .TB_DONE(32'(DONE)),
  .TB_EXECUTE(32'(EXECUTE)),
  .TB_IDLE(32'(IDLE)),
  .TB_LOAD_WAIT(32'(LOAD_WAIT)),
  .TB_POOL_LOAD_WAIT(32'(POOL_LOAD_WAIT)),
  .TB_SOFT_LUT_WAIT(32'(SOFT_LUT_WAIT)),
  .TB_SOFT_RUN(32'(SOFT_RUN)),
  .TB_WB_DATA(32'(WB_DATA)),
  .TB_WB_WAIT(32'(WB_WAIT))
) tb_observer(
  .hw_clk(clk),
  .hw_dma_cfg_ready(dma_cfg_ready),
  .hw_rd_granted(rd_granted),
  .hw_rd_req(rd_req),
  .hw_rst_n(rst_n),
  .hw_soft_done(soft_done),
  .hw_soft_lut_req_valid(soft_lut_req_valid),
  .hw_start(start),
  .hw_state(32'(state)),
  .hw_wb_state(32'(wb_state)),
  .hw_win_busy(win_busy),
  .hw_wr_granted(wr_granted),
  .hw_wr_req(wr_req)
);
/* verilator lint_on DECLFILENAME */
`endif
