// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查一个存储通道的请求许可、地址范围和同地址读写冲突。
// 未访问的通道不产生错误，请求到来时直接汇总所有独立准备的检查结果。
(* keep_hierarchy = "yes" *)
module ps_channel_request_fault (
    input wire logic i_read_request, // 当前通道的读取请求
    input wire logic i_write_request, // 当前通道的写入请求
    input wire logic i_read_valid, // 读取地址位于已分配空间内
    input wire logic i_write_valid, // 写入地址位于已分配空间内
    input wire logic i_address_equal, // 读写请求指向同一存储字
    input wire logic i_access_enabled, // 当前配置允许接受存储访问
    output logic o_request_fault // 当前通道存在许可、越界或同地址冲突错误
);
    assign o_request_fault = (i_read_request && (!i_access_enabled || !i_read_valid)) ||
        (i_write_request && (!i_access_enabled || !i_write_valid)) ||
        (i_read_request && i_write_request && i_address_equal);
endmodule

`default_nettype wire
