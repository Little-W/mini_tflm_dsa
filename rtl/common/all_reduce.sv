// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按位归并一组布尔条件，全部有效时输出有效。
(* keep_hierarchy = "yes" *)
module all_reduce #(parameter int unsigned p_width = 6) (
    input wire logic [p_width-1:0] i_value, // 同时检查的布尔条件
    output logic o_all // 全部输入条件有效
);
    assign o_all = &i_value;
endmodule

`default_nettype wire
