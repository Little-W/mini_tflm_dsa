// SPDX-License-Identifier: Apache-2.0
`default_nettype none
`timescale 1ns/1ps

// 部分和的四个固定通道共享 IA 可分配空间，每个通道保存一个 128 位数据段。
module ia_ps_channel_ram #(
    parameter bit p_shared_write_stage = 1'b0,
    // 写入来源保证有效命令至少包含一个字节时，可直接使用写使能检查碰撞。
    parameter bit p_ia_nonempty_writes = 1'b0,
    parameter int p_bank_bytes = 8192,
    parameter int p_total_bytes = 57344,
    parameter int p_addr_width = $clog2(p_total_bytes/16),
    parameter int p_bank_count_width = $clog2(p_total_bytes/p_bank_bytes+1)
) (
    input  wire logic clk,
    input  wire logic rst_n,
    input  wire logic i_access_enable = 1'b1,
    input  wire logic i_cfg_valid,
    input  wire logic [p_bank_count_width-1:0] i_cfg_ia_banks,
    output logic o_capacity_fault,
    input  wire logic [1:0] i_ia_read_en,
    input  wire logic [1:0] i_ia_write_en,
    input  wire logic [p_addr_width-1:0] i_ia_read_addr [2],
    input  wire logic [p_addr_width-1:0] i_ia_write_addr [2],
    output logic [127:0] o_ia_read_data [2],
    input  wire logic [127:0] i_ia_write_data [2],
    input  wire logic [127:0] i_ia_shared_write_data = 128'd0,
    input  wire logic [15:0] i_ia_write_mask [2],
    input  wire logic [3:0] i_ps_read_en,
    input  wire logic [3:0] i_ps_write_en,
    input  wire logic [p_addr_width-1:0] i_ps_read_addr [4],
    input  wire logic [p_addr_width-1:0] i_ps_write_addr [4],
    output logic [127:0] o_ps_read_data [4],
    input  wire logic [127:0] i_ps_write_data [4]
);
    //! 0. 存储尺寸与配置
    //! -------------------

    localparam int p_banks = p_total_bytes / p_bank_bytes;
    localparam int p_rows = p_bank_bytes / 16;
    localparam int p_row_bits = $clog2(p_rows);
    localparam int p_max_ia_banks = p_banks >= 8 ? 4 : 2;
    localparam int p_ia_bank_bits = $clog2(p_max_ia_banks);
    localparam int p_chunk_rows = p_rows / 4;
    localparam int p_chunk_bits = $clog2(p_chunk_rows);
    localparam int p_fixed_rows = (p_banks - p_max_ia_banks) * p_chunk_rows;
    localparam int p_fixed_bits = $clog2(p_fixed_rows);

    logic configured_q;
    logic [p_bank_count_width-1:0] ia_banks_q;
    logic valid_configuration, access_enabled, memory_access_enabled, access_fault;
    logic [p_addr_width-1:0] ps_limit;
    logic [1:0] ia_read_range, ia_write_range;
    logic [3:0] ps_read_range, ps_write_range, ps_collision;
    logic [p_max_ia_banks-1:0] ia_bank_fault;

    assign valid_configuration =
        (i_cfg_ia_banks == p_bank_count_width'(1) ||
         i_cfg_ia_banks == p_bank_count_width'(2) ||
         i_cfg_ia_banks == p_bank_count_width'(4)) &&
        i_cfg_ia_banks <= p_bank_count_width'(p_max_ia_banks);
    assign access_enabled = configured_q && !o_capacity_fault && !i_cfg_valid;
    // 全局访问条件在端口译码后统一生效，地址和碰撞判断并行准备。
    assign memory_access_enabled = access_enabled && i_access_enable;
    always_comb begin
        ps_limit = '0;
        case (ia_banks_q)
            p_bank_count_width'(1): ps_limit = p_addr_width'((p_banks-1)*p_chunk_rows);
            p_bank_count_width'(2): ps_limit = p_addr_width'((p_banks-2)*p_chunk_rows);
            p_bank_count_width'(4): ps_limit = p_addr_width'((p_banks-4)*p_chunk_rows);
            default: begin end
        endcase
    end

    always_comb begin
        access_fault = 1'b0;
        if (i_access_enable) begin
            access_fault = (|ia_bank_fault) || (|ps_collision);
            if (access_enabled) begin
                access_fault = access_fault ||
                    (|(i_ia_read_en & ~ia_read_range)) || (|(i_ia_write_en & ~ia_write_range)) ||
                    (|(i_ps_read_en & ~ps_read_range)) || (|(i_ps_write_en & ~ps_write_range));
            end else if ((|i_ia_read_en) || (|i_ia_write_en) || (|i_ps_read_en) || (|i_ps_write_en)) begin
                access_fault = 1'b1;
            end
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configured_q <= 1'b0;
            ia_banks_q <= p_bank_count_width'(1);
            o_capacity_fault <= 1'b0;
        end else begin
            if (i_cfg_valid) begin
                configured_q <= valid_configuration;
                if (valid_configuration) begin
                    ia_banks_q <= i_cfg_ia_banks;
                end
                o_capacity_fault <= !valid_configuration || access_fault;
            end else if (access_fault) begin
                o_capacity_fault <= 1'b1;
            end
        end
    end

    //! 1. IA 地址与同块请求仲裁
    //! --------------------------

    logic [p_ia_bank_bits-1:0] ia_read_bank [2], ia_write_bank [2];
    logic [p_ia_bank_bits-1:0] ia_return_bank_q [2];
    logic [p_row_bits-1:0] ia_read_row [2], ia_write_row [2];
    logic [p_max_ia_banks-1:0] ia_bank_read_en, ia_bank_write_en;
    (* keep = 1 *) logic [p_max_ia_banks-1:0] ia_bank_read_eligible, ia_bank_write_eligible;
    logic [p_row_bits-1:0] ia_bank_read_addr [p_max_ia_banks];
    logic [p_row_bits-1:0] ia_bank_write_addr [p_max_ia_banks];
    logic [127:0] ia_bank_write_data [p_max_ia_banks], ia_bank_read_data [p_max_ia_banks];
    logic [15:0] ia_bank_write_mask [p_max_ia_banks];
    logic ia_row_address_equal [2][2];

    // 各对行地址独立比较，晚到的端口请求仅选择匹配结果。
    for (genvar read_port = 0; read_port < 2; read_port++) begin : g_ia_row_compare
        for (genvar write_port = 0; write_port < 2; write_port++) begin : g_write
            assign ia_row_address_equal[read_port][write_port] =
                ia_read_row[read_port] == ia_write_row[write_port];
        end
    end

    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_address
        logic [p_addr_width-1:0] read_row_full, write_row_full;
        always_comb begin
            ia_read_bank[port_index] = '0;
            ia_write_bank[port_index] = '0;
            read_row_full = i_ia_read_addr[port_index];
            write_row_full = i_ia_write_addr[port_index];
            case (ia_banks_q)
                p_bank_count_width'(2): begin
                    ia_read_bank[port_index] = p_ia_bank_bits'(i_ia_read_addr[port_index][0]);
                    ia_write_bank[port_index] = p_ia_bank_bits'(i_ia_write_addr[port_index][0]);
                    read_row_full = i_ia_read_addr[port_index] >> 1;
                    write_row_full = i_ia_write_addr[port_index] >> 1;
                end
                p_bank_count_width'(4): begin
                    ia_read_bank[port_index] = p_ia_bank_bits'(i_ia_read_addr[port_index][1:0]);
                    ia_write_bank[port_index] = p_ia_bank_bits'(i_ia_write_addr[port_index][1:0]);
                    read_row_full = i_ia_read_addr[port_index] >> 2;
                    write_row_full = i_ia_write_addr[port_index] >> 2;
                end
                default: begin end
            endcase
        end
        assign ia_read_row[port_index] = p_row_bits'(read_row_full);
        assign ia_write_row[port_index] = p_row_bits'(write_row_full);
        assign ia_read_range[port_index] = read_row_full < p_addr_width'(p_rows);
        assign ia_write_range[port_index] = write_row_full < p_addr_width'(p_rows);
        assign o_ia_read_data[port_index] = ia_bank_read_data[ia_return_bank_q[port_index]];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ia_return_bank_q[port_index] <= '0;
            end else if (memory_access_enabled && i_ia_read_en[port_index]) begin
                ia_return_bank_q[port_index] <= ia_read_bank[port_index];
            end
        end
    end

    for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_ia_route
        (* keep = 1 *) logic [1:0] read_request, write_request;
        logic read_port_one, write_port_one, collision;
        logic [3:0] collision_terms;
        for (genvar port_index = 0; port_index < 2; port_index++) begin : g_request
            assign read_request[port_index] = i_ia_read_en[port_index] &&
                ia_read_range[port_index] && ia_read_bank[port_index] == p_ia_bank_bits'(bank);
            assign write_request[port_index] = i_ia_write_en[port_index] &&
                ia_write_range[port_index] && ia_write_bank[port_index] == p_ia_bank_bits'(bank);
        end
        assign read_port_one = read_request[1] && !read_request[0];
        assign write_port_one = write_request[1] && !write_request[0];
        assign ia_bank_read_addr[bank] = read_port_one ? ia_read_row[1] : ia_read_row[0];
        assign ia_bank_write_addr[bank] = write_port_one ? ia_write_row[1] : ia_write_row[0];
        assign ia_bank_write_data[bank] = write_port_one ? i_ia_write_data[1] : i_ia_write_data[0];
        assign ia_bank_write_mask[bank] = write_port_one ? i_ia_write_mask[1] : i_ia_write_mask[0];
        for (genvar read_port = 0; read_port < 2; read_port++) begin : g_collision_read
            for (genvar write_port = 0; write_port < 2; write_port++) begin : g_collision_write
                assign collision_terms[2*read_port+write_port] =
                    (read_port == 0 ? read_request[0] : read_port_one) &&
                    (write_port == 0 ? write_request[0] : write_port_one) &&
                    (p_ia_nonempty_writes || (|i_ia_write_mask[write_port])) &&
                    ia_row_address_equal[read_port][write_port];
            end
        end
        assign collision = |collision_terms;
        assign ia_bank_read_eligible[bank] = |read_request;
        assign ia_bank_write_eligible[bank] = (|write_request) && !collision;
        assign ia_bank_read_en[bank] = memory_access_enabled && ia_bank_read_eligible[bank];
        assign ia_bank_write_en[bank] = memory_access_enabled && ia_bank_write_eligible[bank];
        assign ia_bank_fault[bank] = collision || (&read_request) || (&write_request);
    end

    //! 2. 固定部分和通道地址
    //! -----------------------

    logic [3:0] ps_read_fire, ps_write_fire;
    logic [3:0] ps_read_eligible, ps_write_eligible;
    (* keep = 1 *) logic [p_max_ia_banks-1:0] ps_read_selection_eligible [4], ps_write_selection_eligible [4];
    logic [3:0] ps_fixed_read_match, ps_fixed_write_match;
    logic [p_addr_width-1:0] ps_fixed_read_addr [4], ps_fixed_write_addr [4];
    logic [p_max_ia_banks-1:0] ps_read_select [4], ps_write_select [4];
    logic [p_ia_bank_bits-1:0] ps_return_select_q [4];
    logic [127:0] ps_segment_read_data [4][p_max_ia_banks];

    // 通道编号隐含最低两位字序号，端口地址只包含 512 位部分和行号。
    // 可配置的 IA 块分成四段，每段接入一个部分和通道；IA 的物理字位置保持固定。
    for (genvar channel = 0; channel < 4; channel++) begin : g_ps_address
        assign ps_read_range[channel] = i_ps_read_addr[channel] < ps_limit;
        assign ps_write_range[channel] = i_ps_write_addr[channel] < ps_limit;
        assign ps_read_eligible[channel] = i_ps_read_en[channel] && ps_read_range[channel];
        assign ps_write_eligible[channel] = i_ps_write_en[channel] && ps_write_range[channel] && !ps_collision[channel];
        assign ps_read_fire[channel] = memory_access_enabled && ps_read_eligible[channel];
        assign ps_write_fire[channel] = memory_access_enabled && ps_write_eligible[channel];
        assign ps_collision[channel] = i_ps_read_en[channel] && i_ps_write_en[channel] &&
            ps_read_range[channel] && ps_write_range[channel] &&
            i_ps_read_addr[channel] == i_ps_write_addr[channel];

        always_comb begin
            ps_fixed_read_addr[channel] = i_ps_read_addr[channel];
            ps_fixed_write_addr[channel] = i_ps_write_addr[channel];
            ps_fixed_read_match[channel] = 1'b1;
            ps_fixed_write_match[channel] = 1'b1;
            case (ia_banks_q)
                p_bank_count_width'(1): begin
                    ps_fixed_read_addr[channel] = i_ps_read_addr[channel] - p_addr_width'((p_max_ia_banks-1)*p_chunk_rows);
                    ps_fixed_write_addr[channel] = i_ps_write_addr[channel] - p_addr_width'((p_max_ia_banks-1)*p_chunk_rows);
                    ps_fixed_read_match[channel] = i_ps_read_addr[channel] >= p_addr_width'((p_max_ia_banks-1)*p_chunk_rows);
                    ps_fixed_write_match[channel] = i_ps_write_addr[channel] >= p_addr_width'((p_max_ia_banks-1)*p_chunk_rows);
                end
                p_bank_count_width'(2): begin
                    ps_fixed_read_addr[channel] = i_ps_read_addr[channel] - p_addr_width'((p_max_ia_banks-2)*p_chunk_rows);
                    ps_fixed_write_addr[channel] = i_ps_write_addr[channel] - p_addr_width'((p_max_ia_banks-2)*p_chunk_rows);
                    ps_fixed_read_match[channel] = p_max_ia_banks == 2 || (|i_ps_read_addr[channel][p_addr_width-1:p_chunk_bits+1]);
                    ps_fixed_write_match[channel] = p_max_ia_banks == 2 || (|i_ps_write_addr[channel][p_addr_width-1:p_chunk_bits+1]);
                end
                default: begin end
            endcase
        end
        for (genvar bank = 1; bank < p_max_ia_banks; bank++) begin : g_shared_select
            assign ps_read_selection_eligible[channel][bank] = ps_read_eligible[channel] &&
                ((ia_banks_q == p_bank_count_width'(1) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                 (bank >= 2 && ia_banks_q == p_bank_count_width'(2) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2)));
            assign ps_write_selection_eligible[channel][bank] = ps_write_eligible[channel] &&
                ((ia_banks_q == p_bank_count_width'(1) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                 (bank >= 2 && ia_banks_q == p_bank_count_width'(2) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2)));
        end
        assign ps_read_selection_eligible[channel][0] = ps_read_eligible[channel] && ps_fixed_read_match[channel];
        for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_read_selection_enable
            assign ps_read_select[channel][bank] = memory_access_enabled && ps_read_selection_eligible[channel][bank];
        end
        assign ps_write_selection_eligible[channel][0] = ps_write_eligible[channel] && ps_fixed_write_match[channel];
        for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_write_selection_enable
            assign ps_write_select[channel][bank] = memory_access_enabled && ps_write_selection_eligible[channel][bank];
        end
        assign o_ps_read_data[channel] = ps_segment_read_data[channel][ps_return_select_q[channel]];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ps_return_select_q[channel] <= '0;
            end else if (ps_read_fire[channel]) begin
                ps_return_select_q[channel] <= '0;
                for (int bank = 1; bank < p_max_ia_banks; bank++) begin
                    if (ps_read_select[channel][bank]) begin
                        ps_return_select_q[channel] <= p_ia_bank_bits'(bank);
                    end
                end
            end
        end
    end

    //! 3. IA 专用存储块
    //! -------------------

    logic ia_ram_i_wr_en, ia_ram_i_rd_en;
    logic [p_row_bits-1:0] ia_ram_i_wr_addr, ia_ram_i_rd_addr;
    logic [127:0] ia_ram_i_wr_data, ia_ram_o_rd_data;
    logic [15:0] ia_ram_i_wr_mask;
    assign ia_ram_i_wr_en = ia_bank_write_en[0];
    assign ia_ram_i_rd_en = ia_bank_read_en[0];
    assign ia_ram_i_wr_addr = ia_bank_write_addr[0];
    assign ia_ram_i_rd_addr = ia_bank_read_addr[0];
    assign ia_ram_i_wr_data = ia_bank_write_data[0];
    assign ia_ram_i_wr_mask = ia_bank_write_mask[0];
    assign ia_bank_read_data[0] = ia_ram_o_rd_data;
    regfile #(.p_data_width(128), .p_depth(p_rows), .p_addr_width(p_row_bits), .p_write_unit(8)) u_ia_ram (
        .clk(clk), .i_wr_en(ia_ram_i_wr_en), .i_wr_addr(ia_ram_i_wr_addr),
        .i_wr_data(ia_ram_i_wr_data), .i_wr_mask(ia_ram_i_wr_mask),
        .i_rd_en(ia_ram_i_rd_en), .i_rd_addr(ia_ram_i_rd_addr), .o_rd_data(ia_ram_o_rd_data)
    );

    //! 4. 可分配存储块与部分和专用区域
    //! ---------------------------------

    for (genvar bank = 1; bank < p_max_ia_banks; bank++) begin : g_shared_bank
        logic ia_selected;
        logic [1:0] return_chunk_q;
        logic [127:0] chunk_read_data [4];
        assign ia_selected = p_bank_count_width'(bank) < ia_banks_q;
        assign ia_bank_read_data[bank] = chunk_read_data[return_chunk_q];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                return_chunk_q <= '0;
            end else if (ia_bank_read_en[bank]) begin
                return_chunk_q <= ia_bank_read_addr[bank][p_row_bits-1:p_chunk_bits];
            end
        end
        for (genvar channel = 0; channel < 4; channel++) begin : g_channel
            logic ram_i_wr_en, ram_i_rd_en;
            (* keep = 1 *) logic ram_write_eligible, ram_read_eligible;
            logic [p_chunk_bits-1:0] ram_i_wr_addr, ram_i_rd_addr;
            logic [127:0] ram_i_wr_data, ram_o_rd_data;
            logic [15:0] ram_i_wr_mask;
            // 地址分段和端口资格先并行计算，统一访问条件在物理 RAM 使能端合并。
            assign ram_write_eligible = (ia_bank_write_eligible[bank] &&
                ia_bank_write_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel)) ||
                ps_write_selection_eligible[channel][bank];
            assign ram_i_wr_en = memory_access_enabled && ram_write_eligible;
            assign ram_read_eligible = (ia_bank_read_eligible[bank] &&
                ia_bank_read_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel)) ||
                ps_read_selection_eligible[channel][bank];
            assign ram_i_rd_en = memory_access_enabled && ram_read_eligible;
            assign ram_i_wr_addr = ia_selected ? ia_bank_write_addr[bank][p_chunk_bits-1:0] :
                i_ps_write_addr[channel][p_chunk_bits-1:0];
            assign ram_i_rd_addr = ia_selected ? ia_bank_read_addr[bank][p_chunk_bits-1:0] :
                i_ps_read_addr[channel][p_chunk_bits-1:0];
            if (p_shared_write_stage && p_max_ia_banks == 2) begin : g_shared_write_stage
                // 两块 IA 布局的共享写数据已在缓存写命令边沿完成端口选择。
                assign ram_i_wr_data = ia_selected ? i_ia_shared_write_data : i_ps_write_data[channel];
            end else begin : g_general_write_stage
                assign ram_i_wr_data = ia_selected ? ia_bank_write_data[bank] : i_ps_write_data[channel];
            end
            assign ram_i_wr_mask = ia_selected ? ia_bank_write_mask[bank] : 16'hffff;
            assign chunk_read_data[channel] = ram_o_rd_data;
            assign ps_segment_read_data[channel][bank] = ram_o_rd_data;
            regfile #(.p_data_width(128), .p_depth(p_chunk_rows), .p_addr_width(p_chunk_bits), .p_write_unit(8)) u_ram (
                .clk(clk), .i_wr_en(ram_i_wr_en), .i_wr_addr(ram_i_wr_addr),
                .i_wr_data(ram_i_wr_data), .i_wr_mask(ram_i_wr_mask),
                .i_rd_en(ram_i_rd_en), .i_rd_addr(ram_i_rd_addr), .o_rd_data(ram_o_rd_data)
            );
        end
    end
    for (genvar channel = 0; channel < 4; channel++) begin : g_fixed_channel
        logic ram_i_wr_en, ram_i_rd_en;
        logic [p_fixed_bits-1:0] ram_i_wr_addr, ram_i_rd_addr;
        logic [127:0] ram_i_wr_data, ram_o_rd_data;
        logic ram_i_wr_mask;
        assign ram_i_wr_en = ps_write_select[channel][0];
        assign ram_i_rd_en = ps_read_select[channel][0];
        assign ram_i_wr_addr = p_fixed_bits'(ps_fixed_write_addr[channel]);
        assign ram_i_rd_addr = p_fixed_bits'(ps_fixed_read_addr[channel]);
        assign ram_i_wr_data = i_ps_write_data[channel];
        assign ram_i_wr_mask = 1'b1;
        assign ps_segment_read_data[channel][0] = ram_o_rd_data;
        regfile #(.p_data_width(128), .p_depth(p_fixed_rows), .p_addr_width(p_fixed_bits), .p_write_unit(128)) u_ram (
            .clk(clk), .i_wr_en(ram_i_wr_en), .i_wr_addr(ram_i_wr_addr),
            .i_wr_data(ram_i_wr_data), .i_wr_mask(ram_i_wr_mask),
            .i_rd_en(ram_i_rd_en), .i_rd_addr(ram_i_rd_addr), .o_rd_data(ram_o_rd_data)
        );
    end
`ifdef NPU_SIM_ASSERT
    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_write_mask_check
        always_ff @(posedge clk) begin
            if (rst_n && p_ia_nonempty_writes && i_ia_write_en[port_index]) begin
                assert (|i_ia_write_mask[port_index])
                    else $fatal(1, "IA write command requires at least one enabled byte");
            end
        end
    end
`endif

endmodule

`default_nettype wire
