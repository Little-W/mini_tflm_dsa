// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 合并保存的读取请求与完成页边界检查的直通请求。
(* keep_hierarchy = "yes" *)
module conv_guard_read_valid (
 input wire logic i_stored, // 保存状态产生的地址请求
 input wire logic i_direct, // 直通请求满足模式和格式条件
 input wire logic i_page, // 直通突发全部位于当前页
 output logic o_valid // 外部读取地址请求有效
);
 assign o_valid = i_stored || (i_direct && i_page);
endmodule
`default_nettype wire
