// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 部分和读取使能合并当前请求、空间范围、目标银行和访问许可。
// 地址关系独立准备，晚到的读取请求在此直接参与最终端口使能。
(* keep_hierarchy = "yes" *)
module ps_channel_read_enable (
    input wire logic i_read_request, // 当前部分和通道的读取请求
    input wire logic i_address_valid, // 读取地址位于已分配空间内
    input wire logic i_bank_match, // 读取地址属于当前目标银行
    input wire logic i_access_enabled, // 当前配置和故障状态允许访问
    input wire logic i_path_enable, // 当前计算通路允许访问共享存储
    output logic o_enable // 同时满足全部条件的读取使能
);
    assign o_enable = i_read_request && i_address_valid && i_bank_match &&
        i_access_enabled && i_path_enable;
endmodule

`default_nettype wire
