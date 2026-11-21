// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
`default_nettype none

// VCE 独占任务期间使用既有 IA 存储权重，使用四个 PS 端口存储完整的 INT32 结果行。
// 读取在请求上升沿后返回有效数据；返回数据由物理 RAM 保持，直到下一次读取。
module vector_shared_store #(
    parameter int p_bank_bytes = 2048,
    parameter int p_total_bytes = 14336,
    parameter int p_addr_width = $clog2(p_total_bytes / 16),
    parameter int p_bank_count_width = $clog2(p_total_bytes / p_bank_bytes + 1),
    parameter bit p_fixed_ps_channels = 1'b1
) (
    input  logic clk,
    input  logic rst_n,
    input  logic i_cfg_valid,
    input  logic [p_bank_count_width-1:0] i_cfg_ia_banks,
    input  logic i_enable,
    input  logic i_flush,
    output logic o_idle,
    output logic o_error,

    input  logic i_weight_read_en,
    input  logic [p_addr_width-1:0] i_weight_read_addr,
    output logic o_weight_read_valid,
    output logic [127:0] o_weight_read_data,
    input  logic i_weight_write_en,
    input  logic [p_addr_width-1:0] i_weight_write_addr,
    input  logic [127:0] i_weight_write_data,
    input  logic [15:0] i_weight_write_mask,

    input  logic i_ps_read_en,
    input  logic [p_addr_width-1:0] i_ps_read_addr,
    output logic o_ps_read_valid,
    output logic [511:0] o_ps_read_data,
    input  logic i_ps_write_en,
    input  logic [p_addr_width-1:0] i_ps_write_addr,
    input  logic [511:0] i_ps_write_data,

    output logic [1:0] o_ia_read_en,
    output logic [1:0] o_ia_write_en,
    output logic [p_addr_width-1:0] o_ia_read_addr [2],
    output logic [p_addr_width-1:0] o_ia_write_addr [2],
    input  logic [127:0] i_ia_read_data [2],
    output logic [127:0] o_ia_write_data [2],
    output logic [15:0] o_ia_write_mask [2],
    output logic [127:0] o_ia_shared_write_data,
    output logic [3:0] o_ps_read_en,
    output logic [3:0] o_ps_write_en,
    output logic [p_addr_width-1:0] o_ps_read_addr [4],
    output logic [p_addr_width-1:0] o_ps_write_addr [4],
    input  logic [127:0] i_ps_read_data [4],
    output logic [127:0] o_ps_write_data [4]
);
    //! 0. 存储尺寸与内部状态
    //! ----------------------

    localparam int p_banks = p_total_bytes / p_bank_bytes;
    localparam int p_rows = p_bank_bytes / 16;
    localparam int p_row_bits = $clog2(p_rows);

    logic configured;
    logic [p_addr_width-1:0] ia_word_limit;
    logic cfg_legal, access_en, access_err_fire;
    logic weight_write_req, any_req;
    logic weight_read_range, weight_write_range;
    logic ps_read_range, ps_write_range;
    logic weight_collision, ps_collision;
    logic weight_access_err, ps_access_err;
    logic weight_read_fire, weight_write_fire, ps_read_fire, ps_write_fire;
    logic weight_return_vld, ps_return_vld;
    logic unused_ia_read_data;

    //! 1. 配置检查与访问判定
    //! ----------------------

    // PS 固定使用四个独立端口，因此每种分配都必须保留至少四个 PS 存储块。
    assign cfg_legal = (i_cfg_ia_banks == p_bank_count_width'(1) ||
        i_cfg_ia_banks == p_bank_count_width'(2) || i_cfg_ia_banks == p_bank_count_width'(4)) &&
        i_cfg_ia_banks <= p_bank_count_width'(p_banks - 4);
    assign access_en = i_enable && configured && !i_cfg_valid && !i_flush && !o_error;
    assign weight_write_req = i_weight_write_en && (|i_weight_write_mask);
    assign any_req = i_weight_read_en || weight_write_req || i_ps_read_en || i_ps_write_en;
    assign weight_read_range = i_weight_read_addr < ia_word_limit;
    assign weight_write_range = i_weight_write_addr < ia_word_limit;
    assign ps_read_range = i_ps_read_addr < p_addr_width'(p_rows);
    assign ps_write_range = i_ps_write_addr < p_addr_width'(p_rows);

    // 同地址读写由调用方分到不同周期。发生冲突时，相关空间的读写均不提交到 RAM。
    assign weight_collision = i_weight_read_en && weight_write_req && (i_weight_read_addr == i_weight_write_addr);
    assign ps_collision = i_ps_read_en && i_ps_write_en && (i_ps_read_addr == i_ps_write_addr);
    assign weight_access_err = (i_weight_read_en && !weight_read_range) ||
        (weight_write_req && !weight_write_range) || weight_collision;
    assign ps_access_err = (i_ps_read_en && !ps_read_range) ||
        (i_ps_write_en && !ps_write_range) || ps_collision;
    assign access_err_fire = i_enable && !i_cfg_valid && !i_flush && !o_error &&
        ((!configured && any_req) || (configured && (weight_access_err || ps_access_err)));
    assign weight_read_fire = access_en && i_weight_read_en && !weight_access_err;
    assign weight_write_fire = access_en && weight_write_req && !weight_access_err;
    assign ps_read_fire = access_en && i_ps_read_en && !ps_access_err;
    assign ps_write_fire = access_en && i_ps_write_en && !ps_access_err;

    //! 2. 配置保存与同步返回
    //! ----------------------

    // flush 结束当前访问上下文，下一次任务必须重新配置；合法配置清除本地错误。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configured <= 1'b0;
            ia_word_limit <= '0;
            o_error <= 1'b0;
        end else if (i_flush) begin
            configured <= 1'b0;
            o_error <= 1'b0;
        end else if (i_cfg_valid) begin
            configured <= cfg_legal;
            ia_word_limit <= p_addr_width'(i_cfg_ia_banks) << p_row_bits;
            o_error <= !cfg_legal;
        end else if (access_err_fire) begin
            o_error <= 1'b1;
        end
    end

    // 有效信号与 RAM 原生同步输出同拍返回，不复制权重或部分和数据。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            weight_return_vld <= 1'b0;
            ps_return_vld <= 1'b0;
        end else if (i_flush || i_cfg_valid || !i_enable) begin
            weight_return_vld <= 1'b0;
            ps_return_vld <= 1'b0;
        end else begin
            weight_return_vld <= weight_read_fire;
            ps_return_vld <= ps_read_fire;
        end
    end

    //! 3. 物理端口映射与输出
    //! ----------------------

    assign o_weight_read_valid = weight_return_vld && i_enable && !i_flush && !i_cfg_valid;
    assign o_ps_read_valid = ps_return_vld && i_enable && !i_flush && !i_cfg_valid;
    assign o_weight_read_data = i_ia_read_data[0];
    assign o_idle = !(weight_return_vld || ps_return_vld || weight_read_fire ||
        weight_write_fire || ps_read_fire || ps_write_fire);

    // 权重只使用 IA 端口零；共享写数据也来自同一个请求，适配已有写数据流水。
    assign o_ia_read_en = {1'b0, weight_read_fire};
    assign o_ia_write_en = {1'b0, weight_write_fire};
    assign o_ia_read_addr[0] = i_weight_read_addr;
    assign o_ia_write_addr[0] = i_weight_write_addr;
    assign o_ia_write_data[0] = i_weight_write_data;
    assign o_ia_write_mask[0] = i_weight_write_mask;
    assign o_ia_read_addr[1] = '0;
    assign o_ia_write_addr[1] = '0;
    assign o_ia_write_data[1] = '0;
    assign o_ia_write_mask[1] = '0;
    assign o_ia_shared_write_data = i_weight_write_data;
    assign unused_ia_read_data = ^i_ia_read_data[1];

    // VCE 的 PS 地址始终表示 512 位行。固定通道共享行号，轮转映射选择前四个 PS 块。
    assign o_ps_read_en = {4{ps_read_fire}};
    assign o_ps_write_en = {4{ps_write_fire}};
    for (genvar port_index = 0; port_index < 4; port_index++) begin : g_ps_port
        if (p_fixed_ps_channels) begin : g_fixed
            assign o_ps_read_addr[port_index] = i_ps_read_addr;
            assign o_ps_write_addr[port_index] = i_ps_write_addr;
        end else begin : g_rotating
            assign o_ps_read_addr[port_index] = p_addr_width'(port_index * p_rows) |
                p_addr_width'(i_ps_read_addr[p_row_bits-1:0]);
            assign o_ps_write_addr[port_index] = p_addr_width'(port_index * p_rows) |
                p_addr_width'(i_ps_write_addr[p_row_bits-1:0]);
        end
        assign o_ps_write_data[port_index] = i_ps_write_data[128*port_index +: 128];
        assign o_ps_read_data[128*port_index +: 128] = i_ps_read_data[port_index];
    end
endmodule

`default_nettype wire
