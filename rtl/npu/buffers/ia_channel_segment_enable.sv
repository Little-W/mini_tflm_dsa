// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两个端口分别检查目标分段，第一端口优先选择并同时合并访问及碰撞资格。
(* keep_hierarchy = "yes" *)
module ia_channel_segment_enable (
    input wire logic i_first_request, // 第一端口请求访问当前物理存储块
    input wire logic i_second_request, // 第二端口请求访问当前物理存储块
    input wire logic i_first_segment, // 第一端口地址属于当前存储分段
    input wire logic i_second_segment, // 第二端口地址属于当前存储分段
    input wire logic i_permitted, // 当前访问不存在阻止操作的端口碰撞
    input wire logic i_access_enabled, // 当前配置及故障状态允许存储访问
    output wire logic o_enable // 按端口优先顺序选择的分段访问资格
);
    assign o_enable = i_access_enabled && i_permitted &&
        ((i_first_request && i_first_segment) ||
         (i_second_request && !i_first_request && i_second_segment));
endmodule

`default_nettype wire
