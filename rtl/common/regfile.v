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
    // 使用定宽字符串兼容 Vivado 的存储类型属性。
    parameter [8*16-1:0] p_ram_style = "auto",
    // 同址写入时保持整个读输出，适用于读写分别使用独立存储区域的缓冲区。
    parameter bit p_no_change_collision = 1'b0
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

    //! 0. 常量与内部信号
    //! --------------------

    localparam int p_segments = p_data_width / p_write_unit;
    logic [p_segments-1:0] accepted_write_mask;
    logic accepted_write;
    logic [p_read_ports-1:0] read_accept;

`ifdef ASIC_SRAM
    // 同步存储按写入分段选择 SRAM，每个分段保存完整的逻辑地址范围。
    // 容量条件计入分段填充和读端复制，避免小数组占用低利用率的宏。
    localparam int p_asic_macro_depth = (p_depth <= 384) ? 128 : 1024;
    localparam int p_asic_segment_width = p_no_change_collision ? p_data_width : p_write_unit;
    localparam longint p_asic_macros_per_segment = ((64'(p_asic_segment_width) + 15) / 16) *
        ((64'(p_depth) + 64'(p_asic_macro_depth) - 1) / 64'(p_asic_macro_depth));
    // 较深的宏每位面积更低，允许其采用较低的容量利用率。
    localparam int p_asic_min_bits_per_macro = (p_asic_macro_depth == 128) ? 1024 : 4096;
    localparam bit p_asic_eligible = p_sync_read && p_depth >= 32 &&
        64'(p_depth) * p_asic_segment_width >=
            64'(p_read_ports) * p_asic_macros_per_segment * p_asic_min_bits_per_macro &&
        p_data_width % p_write_unit == 0;

`endif

    //! 1. 读写请求处理
    //! ------------------

    // 只接收合法地址和明确有效的写入分段，未知控制与行为数组的 if 语义相同。
    always_comb begin
        accepted_write_mask = '0;
        if (i_wr_en) begin
            if ({1'b0, i_wr_addr} < (p_addr_width+1)'(p_depth)) begin
                for (int segment = 0; segment < p_segments; segment++) begin
                    if (i_wr_mask[segment]) begin
                        accepted_write_mask[segment] = 1'b1;
                    end
                end
            end
        end
    end
    assign accepted_write = |accepted_write_mask;

    for (genvar port_index = 0; port_index < p_read_ports; port_index++) begin : g_read_accept
        // 保持模式只关闭发生实际写入的同址读取，零掩码写入不会阻止读取。
        always_comb begin
            read_accept[port_index] = i_rd_en[port_index];
            if (p_no_change_collision && p_sync_read && accepted_write) begin
                if (i_rd_addr[port_index] == i_wr_addr) begin
                    read_accept[port_index] = 1'b0;
                end
            end
        end
    end

    //! 2. 存储更新与读出
    //! --------------------

`ifdef ASIC_SRAM
    if (p_asic_eligible && p_no_change_collision) begin : g_asic_masked_storage
        logic storage_i_wr_en;
        logic [p_addr_width-1:0] storage_i_wr_addr;
        logic [p_data_width-1:0] storage_i_wr_data, storage_i_wr_mask;
        assign storage_i_wr_en = accepted_write;
        assign storage_i_wr_addr = i_wr_addr;
        assign storage_i_wr_data = i_wr_data;
        for (genvar segment = 0; segment < p_segments; segment++) begin : g_write_mask
            assign storage_i_wr_mask[segment*p_write_unit +: p_write_unit] =
                {p_write_unit{accepted_write_mask[segment]}};
        end
        for (genvar port_index = 0; port_index < p_read_ports; port_index++) begin : g_read_port
            logic invalid_address;
            logic storage_i_rd_en;
            logic [p_addr_width-1:0] storage_i_rd_addr;
            logic [p_data_width-1:0] storage_o_rd_data;

            // 全字共享位写掩码，同址读取已由 read_accept 关闭，宏端口不会冲突。
            always_comb begin
                storage_i_rd_en = 1'b0;
                if (read_accept[port_index]) begin
                    if ({1'b0, i_rd_addr[port_index]} < (p_addr_width+1)'(p_depth)) begin
                        storage_i_rd_en = 1'b1;
                    end
                end
            end
            always_ff @(posedge clk) begin
                if (read_accept[port_index]) begin
                    if ({1'b0, i_rd_addr[port_index]} < (p_addr_width+1)'(p_depth)) begin
                        invalid_address <= 1'b0;
                    end else begin
                        invalid_address <= 1'b1;
                    end
                end
            end
            assign storage_i_rd_addr = i_rd_addr[port_index];
            assign o_rd_data[port_index] = invalid_address ? 'x : storage_o_rd_data;
            smic40_sram_1r1w #(
                .DATA_WIDTH(p_data_width), .DEPTH(p_depth), .ADDR_WIDTH(p_addr_width),
                .MACRO_DEPTH(p_asic_macro_depth)
            ) u_storage (
                .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
                .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
                .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr),
                .read_data(storage_o_rd_data)
            );
        end
    end else if (p_asic_eligible) begin : g_asic_storage
        logic [p_addr_width-1:0] pending_address_q;
        logic [p_data_width-1:0] pending_data_q;
        logic [p_segments-1:0] pending_mask_q;

        // 写入在下一个边沿提交到宏；读端转发已接收的写入，保持原有读取周期。
        // 各分段独立提交，部分写入时其他分段仍可安全读取。
        always_ff @(posedge clk) begin
            pending_mask_q <= '0;
            if (i_wr_en) begin
                pending_address_q <= i_wr_addr;
                pending_data_q <= i_wr_data;
                if ({1'b0, i_wr_addr} < (p_addr_width+1)'(p_depth)) begin
                    for (int segment = 0; segment < p_segments; segment++) begin
                        if (i_wr_mask[segment]) pending_mask_q[segment] <= 1'b1;
                    end
                end
            end
        end

        for (genvar port_index = 0; port_index < p_read_ports; port_index++) begin : g_read_port
            logic invalid_address_q;
            always_ff @(posedge clk) begin
                if (i_rd_en[port_index]) begin
                    if ({1'b0, i_rd_addr[port_index]} < (p_addr_width+1)'(p_depth))
                        invalid_address_q <= 1'b0;
                    else
                        invalid_address_q <= 1'b1;
                end
            end
            for (genvar segment = 0; segment < p_segments; segment++) begin : g_write_segment
                logic macro_read_enable;
                logic forward_q;
                logic [p_write_unit-1:0] forward_data_q, macro_read_data;
                wire same_address = pending_mask_q[segment] &&
                    i_rd_addr[port_index] == pending_address_q;

                // 同地址访问由写入缓冲提供数据，关闭该宏读取以避免物理端口冲突。
                always_comb begin
                    macro_read_enable = 1'b0;
                    if (i_rd_en[port_index]) begin
                        if ({1'b0, i_rd_addr[port_index]} < (p_addr_width+1)'(p_depth)) begin
                            if (!same_address) macro_read_enable = 1'b1;
                        end
                    end
                end
                always_ff @(posedge clk) begin
                    if (i_rd_en[port_index]) begin
                        forward_q <= same_address;
                        if (same_address)
                            forward_data_q <= pending_data_q[segment*p_write_unit +: p_write_unit];
                    end
                end
                assign o_rd_data[port_index][segment*p_write_unit +: p_write_unit] =
                    invalid_address_q ? 'x : forward_q ? forward_data_q : macro_read_data;

                smic40_sram_1r1w #(
                    .DATA_WIDTH(p_write_unit), .DEPTH(p_depth), .ADDR_WIDTH(p_addr_width),
                    .MACRO_DEPTH(p_asic_macro_depth)
                ) u_storage (
                    .clk(clk), .write_enable(pending_mask_q[segment]),
                    .write_address(pending_address_q),
                    .write_data(pending_data_q[segment*p_write_unit +: p_write_unit]),
                    .write_mask({p_write_unit{1'b1}}),
                    .read_enable(macro_read_enable), .read_address(i_rd_addr[port_index]),
                    .read_data(macro_read_data)
                );
            end
        end
    end else begin : g_rtl_storage
`endif
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
            // 同步读取保持未使能时的输出，同址写入按所选读取模式处理。
            always_ff @(posedge clk) begin
                if (read_accept[port_index]) begin
                    o_rd_data[port_index] <= mem[i_rd_addr[port_index]];
                end
            end
        end else begin : g_async
            // 异步读取持续反映所选地址；i_rd_en 仅用于同步读取模式。
            assign o_rd_data[port_index] = mem[i_rd_addr[port_index]];
        end
    end
`ifdef ASIC_SRAM
    end
`endif

endmodule

`default_nettype wire
