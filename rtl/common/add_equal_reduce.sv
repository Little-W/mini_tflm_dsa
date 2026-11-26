// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 归并同一比较组内各位的一致性结果。
module add_equal_reduce #(
    parameter int unsigned p_width = 6
) (
    input wire logic [p_width-1:0] i_equal, // 各比较位或比较组的相等结果
    output logic o_equal // 全部比较组均相等
);
    assign o_equal = &i_equal;
endmodule

`default_nettype wire
