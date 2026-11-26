// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 结合驻留装载状态、清除条件及范围比较生成偏置请求命中资格。
(* keep_hierarchy = "yes" *)
module bias_resident_qualify (
    input  wire logic i_clear, // 清除当前驻留数据有效状态
    input  wire logic i_loaded, // 当前驻留数据已装载完成
    input  wire logic i_below_start, // 请求起点低于驻留范围起点
    input  wire logic i_above_end, // 请求末端高于驻留范围终点
    output logic o_valid // 当前比较对象有效
);
    always_comb begin
        o_valid = i_loaded && !i_below_start && !i_above_end;
        if (i_clear) begin
            o_valid = 1'b0;
        end
    end
endmodule

`default_nettype wire
