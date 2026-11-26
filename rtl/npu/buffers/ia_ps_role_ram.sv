// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 共享存储段采用两个独立地址端口，端口 A 写入 IA 或读取部分和，端口 B 执行相反职责。
// 写入会更新未拥有该段的通路输出；当前拥有者的读输出在相邻读取之间持续保持。
(* keep_hierarchy = "yes" *)
module ia_ps_role_ram #(
    parameter int p_depth = 128,
    parameter int p_addr_width = $clog2(p_depth)
) (
    input wire logic clk, // 工作时钟
    input wire logic i_access_enable = 1'b1, // 统一允许本周期的存储访问
    input wire logic i_a_enable, // 端口 A 的部分和读取请求
    input wire logic i_a_read_allowed = 1'b1, // 端口 A 读取地址及当前配置允许访问
    input wire logic i_a_write, // 端口 A 写入 IA 数据
    input wire logic [p_addr_width-1:0] i_a_addr, // 端口 A 的共享行地址
    input wire logic [127:0] i_a_data, // 端口 A 的 IA 写入数据
    input wire logic [15:0] i_a_mask, // 端口 A 的逐字节写入掩码
    output logic [127:0] o_a_data, // 端口 A 同步返回的部分和数据
    input wire logic i_b_enable, // 端口 B 的 IA 读取使能
    input wire logic i_b_write, // 端口 B 写入部分和数据
    input wire logic [p_addr_width-1:0] i_b_addr, // 端口 B 的共享行地址
    input wire logic [127:0] i_b_data, // 端口 B 的完整部分和写入数据
    output logic [127:0] o_b_data // 端口 B 同步返回的 IA 数据
);
    (* ram_style = "block" *) logic [127:0] memory [p_depth];

    always_ff @(posedge clk) begin
        for (int byte_index = 0; byte_index < 16; byte_index++) begin
            if (i_access_enable && i_a_write && i_a_mask[byte_index]) begin
                memory[i_a_addr][8*byte_index +: 8] <= i_a_data[8*byte_index +: 8];
            end
        end
        if (i_access_enable && ((i_a_enable && i_a_read_allowed) || i_a_write)) begin
            o_a_data <= memory[i_a_addr];
        end
    end
    always_ff @(posedge clk) begin
        if (i_access_enable && i_b_write) begin
            memory[i_b_addr] <= i_b_data;
        end
        if (i_access_enable && (i_b_enable || i_b_write)) begin
            o_b_data <= memory[i_b_addr];
        end
    end
endmodule

`default_nettype wire
