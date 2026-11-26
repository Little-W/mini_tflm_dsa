// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 部分和写入资格同时检查目标地址、读取碰撞和当前访问状态。
// 各项地址关系独立计算，请求信号在本模块内直接形成最终写入条件。
(* keep_hierarchy = "yes" *)
module ps_channel_write_enable (
    input wire logic i_write_request, // 当前通道的部分和写入请求
    input wire logic i_read_request, // 当前通道的部分和读取请求
    input wire logic i_read_valid, // 当前读取地址位于已分配空间内
    input wire logic i_address_equal, // 读写地址指向同一个部分和字
    input wire logic i_destination_valid, // 写入地址位于当前目标银行的有效范围
    input wire logic i_access_enabled, // 当前配置允许接受存储访问
    output logic o_selection_eligible, // 已通过目标银行与读写冲突检查的写入请求
    output logic o_access_eligible // 同时满足当前配置访问条件的写入请求
);
    assign o_selection_eligible = i_write_request && i_destination_valid &&
        !(i_read_request && i_read_valid && i_address_equal);
    assign o_access_eligible = i_access_enabled && i_write_request && i_destination_valid &&
        !(i_read_request && i_read_valid && i_address_equal);
endmodule

`default_nettype wire
