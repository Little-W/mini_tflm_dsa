// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 单写端口存储器；读端口和写入分段由参数决定，存储资源由综合工具选择。
module regfile #(
    parameter int p_data_width = 32,
    parameter int p_depth = 64,
    parameter int p_addr_width = (p_depth <= 1) ? 1 : $clog2(p_depth),
    parameter int p_write_unit = 8,
    parameter int p_read_ports = 1,
    parameter bit p_sync_read = 1'b1,
    parameter string p_ram_style = "auto"
) (
    input  wire logic clk,
    input  wire logic i_wr_en,
    input  wire logic [p_addr_width-1:0] i_wr_addr,
    input  wire logic [p_data_width-1:0] i_wr_data,
    input  wire logic [p_data_width/p_write_unit-1:0] i_wr_mask,
    input  wire logic [p_read_ports-1:0] i_rd_en,
    input  wire logic [p_read_ports-1:0][p_addr_width-1:0] i_rd_addr,
    output logic [p_read_ports-1:0][p_data_width-1:0] o_rd_data
);

    // 存储类型由参数给出综合建议，端口行为和读取周期保持一致。
    (* ram_style = p_ram_style *) logic [p_data_width-1:0] mem [0:p_depth-1];

    // 写入掩码独立控制每个分段，未选中的分段保留原值。
    always_ff @(posedge clk) begin
        if (i_wr_en) begin
            for (int segment = 0; segment < p_data_width/p_write_unit; segment++) begin
                if (i_wr_mask[segment]) begin
                    mem[i_wr_addr][segment*p_write_unit +: p_write_unit] <=
                        i_wr_data[segment*p_write_unit +: p_write_unit];
                end
            end
        end
    end

    for (genvar port_index = 0; port_index < p_read_ports; port_index++) begin : g_read_port
        if (p_sync_read) begin : g_sync
            // 同步读取保持未使能时的输出，同周期同地址读写返回写入前的内容。
            always_ff @(posedge clk) begin
                if (i_rd_en[port_index]) begin
                    o_rd_data[port_index] <= mem[i_rd_addr[port_index]];
                end
            end
        end else begin : g_async
            // 异步读取持续反映所选地址；i_rd_en 仅用于同步读取模式。
            assign o_rd_data[port_index] = mem[i_rd_addr[port_index]];
        end
    end
endmodule

`default_nettype wire
