// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并偏置同步读取资格与同址写入条件，后续标量地址比较直接参与末级使能。
(* keep_hierarchy = "yes" *)
module bias_read_enable_select (
    input wire logic i_enable, // 当前周期请求同步读取偏置数据。
    input wire logic i_write, // 当前周期存在实际被接受的存储写入。
    input wire logic i_scalar_next, // 当前读取采用已保存分组的后续标量地址。
    input wire logic i_scalar_collision, // 后续标量字地址与写入地址相同。
    input wire logic i_other_collision, // 其他已选读取分支与写入地址相同。
    output logic o_enable // 同拍碰撞检查后允许实际执行读取。
);
    assign o_enable = i_enable &&
        !(i_write && (i_other_collision || (i_scalar_next && i_scalar_collision)));
endmodule

`default_nettype wire
