// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算部分和帧的下一行地址，结果按地址位宽自然回绕。
(* keep_hierarchy = "yes" *)
module ps_frame_address_increment #(
    parameter int unsigned p_width = 12
) (
    input wire logic [p_width-1:0] i_address, // 当前行地址。
    output logic [p_width-1:0] o_next // 递增一行后的模地址。
);
    assign o_next = i_address + p_width'(1);
endmodule

`default_nettype wire
