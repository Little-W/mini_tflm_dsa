// SPDX-License-Identifier: Apache-2.0
`ifndef SYNTHESIS
/* verilator lint_off DECLFILENAME */
module ws_systolic_array_observer #(
  parameter int TB_SIZE=0
);
integer weight_rows_loaded;
always @(posedge ws_systolic_array.clk or negedge ws_systolic_array.rst_n)begin
if(!ws_systolic_array.rst_n)weight_rows_loaded<=0;
else if(ws_systolic_array.weight_commit)begin
assert(weight_rows_loaded==TB_SIZE)else $fatal(1,"Weight selection requires a complete inactive tile");
weight_rows_loaded<=ws_systolic_array.store_weight_req ? 1 : 0;
end else if(ws_systolic_array.store_weight_req)begin
assert(weight_rows_loaded<TB_SIZE)else $fatal(1,"Weight loading must select a completed tile before the next tile");
weight_rows_loaded<=weight_rows_loaded+1;
end
end

endmodule
bind ws_systolic_array ws_systolic_array_observer #(
  .TB_SIZE(32'(SIZE))
) tb_observer();
/* verilator lint_on DECLFILENAME */
`endif
