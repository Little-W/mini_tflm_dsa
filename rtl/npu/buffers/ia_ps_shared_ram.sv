`timescale 1ns/1ps
`default_nettype none

// 每个物理存储块提供一个同步读端口和一个带字节掩码的写端口。
module ia_ps_shared_ram #(
    parameter int BANK_BYTES = 2048,
    parameter int TOTAL_BYTES = 14336,
    parameter int IA_ADDR_BITS = $clog2(TOTAL_BYTES/16),
    parameter int PS_ADDR_BITS = $clog2(TOTAL_BYTES/16),
    parameter int BANK_COUNT_BITS = $clog2(TOTAL_BYTES/BANK_BYTES+1)
) (
    input  wire logic clk,
    input  wire logic rst_n,
    input  wire logic cfg_valid,
    input  wire logic [BANK_COUNT_BITS-1:0] cfg_ia_banks,
    output logic capacity_fault,
    input  wire logic [1:0] ia_read_en,
    input  wire logic [1:0] ia_write_en,
    input  wire logic [IA_ADDR_BITS-1:0] ia_read_addr [0:1],
    input  wire logic [IA_ADDR_BITS-1:0] ia_write_addr [0:1],
    output logic [127:0] ia_read_data [0:1],
    input  wire logic [127:0] ia_write_data [0:1],
    input  wire logic [15:0] ia_write_mask [0:1],
    input  wire logic [3:0] ps_read_en,
    input  wire logic [3:0] ps_write_en,
    input  wire logic [PS_ADDR_BITS-1:0] ps_read_addr [0:3],
    input  wire logic [PS_ADDR_BITS-1:0] ps_write_addr [0:3],
    output logic [127:0] ps_read_data [0:3],
    input  wire logic [127:0] ps_write_data [0:3]
);
    //! 0. 常量与内部信号
    //! --------------------

    localparam int p_banks = TOTAL_BYTES / BANK_BYTES;
    localparam int p_rows = BANK_BYTES / 16;
    localparam int p_row_bits = $clog2(p_rows);
    localparam int p_bank_bits = (p_banks <= 1) ? 1 : $clog2(p_banks);

    logic configured;
    logic [BANK_COUNT_BITS-1:0] ia_banks_q;
    logic valid_configuration, access_enabled, access_fault;
    logic [p_banks-1:0] read_en, write_en, bank_fault;
    logic [p_row_bits-1:0] read_addr [p_banks], write_addr [p_banks];
    logic [127:0] write_data [p_banks], read_data [p_banks];
    logic [15:0] write_mask [p_banks];
    logic [p_row_bits-1:0] ia_read_row [2], ia_write_row [2];
    logic [1:0] ia_read_bank [2], ia_write_bank [2];
    logic [1:0] ia_read_range, ia_write_range;
    logic [3:0] ps_read_range, ps_write_range;
    logic [p_banks-1:0] ps_read_selected [4];
    logic [p_bank_bits-1:0] ia_read_bank_hold [2], ps_read_bank_hold [4];
    logic [p_bank_bits-1:0] ps_return_bank [4];
    logic ia_address_collision [2][2];
    logic ps_address_collision [4][4];

    //! 1. 地址译码与端口仲裁
    //! ------------------------

    assign valid_configuration = (cfg_ia_banks == BANK_COUNT_BITS'(1) ||
        cfg_ia_banks == BANK_COUNT_BITS'(2) || cfg_ia_banks == BANK_COUNT_BITS'(4)) && int'(cfg_ia_banks) < p_banks;
    assign access_enabled = configured && !capacity_fault && !cfg_valid;

    // IA 按 1、2、4 个存储块交织，低位选择存储块，其余位选择行。
    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_address
        logic [IA_ADDR_BITS-1:0] read_row_full, write_row_full;
        always_comb begin
            ia_read_bank[port_index] = '0;
            ia_write_bank[port_index] = '0;
            read_row_full = ia_read_addr[port_index];
            write_row_full = ia_write_addr[port_index];
            case (ia_banks_q)
                BANK_COUNT_BITS'(2): begin
                    ia_read_bank[port_index] = {1'b0, ia_read_addr[port_index][0]};
                    ia_write_bank[port_index] = {1'b0, ia_write_addr[port_index][0]};
                    read_row_full = ia_read_addr[port_index] >> 1;
                    write_row_full = ia_write_addr[port_index] >> 1;
                end
                BANK_COUNT_BITS'(4): begin
                    ia_read_bank[port_index] = ia_read_addr[port_index][1:0];
                    ia_write_bank[port_index] = ia_write_addr[port_index][1:0];
                    read_row_full = ia_read_addr[port_index] >> 2;
                    write_row_full = ia_write_addr[port_index] >> 2;
                end
                default: begin end
            endcase
        end
        assign ia_read_row[port_index] = p_row_bits'(read_row_full);
        assign ia_write_row[port_index] = p_row_bits'(write_row_full);
        assign ia_read_range[port_index] = int'(read_row_full) < p_rows;
        assign ia_write_range[port_index] = int'(write_row_full) < p_rows;
    end

    for (genvar port_index = 0; port_index < 4; port_index++) begin : g_ps_range
        assign ps_read_range[port_index] =
            (ia_banks_q == BANK_COUNT_BITS'(1) && (int'(ps_read_addr[port_index]) >> p_row_bits) < p_banks-1) ||
            (ia_banks_q == BANK_COUNT_BITS'(2) && (int'(ps_read_addr[port_index]) >> p_row_bits) < p_banks-2) ||
            (ia_banks_q == BANK_COUNT_BITS'(4) && (int'(ps_read_addr[port_index]) >> p_row_bits) < p_banks-4);
        assign ps_write_range[port_index] =
            (ia_banks_q == BANK_COUNT_BITS'(1) && (int'(ps_write_addr[port_index]) >> p_row_bits) < p_banks-1) ||
            (ia_banks_q == BANK_COUNT_BITS'(2) && (int'(ps_write_addr[port_index]) >> p_row_bits) < p_banks-2) ||
            (ia_banks_q == BANK_COUNT_BITS'(4) && (int'(ps_write_addr[port_index]) >> p_row_bits) < p_banks-4);
    end

    // IA 和 PS 分别占用不同的存储块，同类逻辑地址的比较结果由各块共用。
    for (genvar read_port = 0; read_port < 2; read_port++) begin : g_ia_collision
        for (genvar write_port = 0; write_port < 2; write_port++) begin : g_write
            assign ia_address_collision[read_port][write_port] = ia_read_addr[read_port] == ia_write_addr[write_port];
        end
    end
    for (genvar read_port = 0; read_port < 4; read_port++) begin : g_ps_collision
        for (genvar write_port = 0; write_port < 4; write_port++) begin : g_write
            assign ps_address_collision[read_port][write_port] = ps_read_addr[read_port] == ps_write_addr[write_port];
        end
    end

    // 每个存储块独立选择编号最小的请求端口；同块多请求和同地址读写会记录容量错误。
    for (genvar bank = 0; bank < p_banks; bank++) begin : g_port_route
        logic [5:0] read_request, write_request, read_grant, write_grant, read_hit, write_hit;
        logic [19:0] collision_terms;
        logic collision, ia_bank;
        logic [1:0] ps_write_port;
        logic [5:0][p_row_bits-1:0] read_row_terms, write_row_terms;
        logic [5:0][15:0] mask_terms;

        for (genvar read_port = 0; read_port < 2; read_port++) begin : g_ia_collision
            for (genvar write_port = 0; write_port < 2; write_port++) begin : g_write
                assign collision_terms[2*read_port+write_port] = read_grant[read_port] && write_grant[write_port] &&
                    (|ia_write_mask[write_port]) && ia_address_collision[read_port][write_port];
            end
        end
        for (genvar read_port = 0; read_port < 4; read_port++) begin : g_ps_collision
            for (genvar write_port = 0; write_port < 4; write_port++) begin : g_write
                assign collision_terms[4+4*read_port+write_port] = read_grant[read_port+2] && write_grant[write_port+2] &&
                    ps_address_collision[read_port][write_port];
            end
        end
        assign collision = |collision_terms;
        for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_port
            assign read_hit[port_index] = (bank < 4) && ia_read_bank[port_index] == 2'(bank);
            assign write_hit[port_index] = (bank < 4) && ia_write_bank[port_index] == 2'(bank);
            assign read_request[port_index] = access_enabled && ia_read_en[port_index] && ia_read_range[port_index] && read_hit[port_index];
            assign write_request[port_index] = access_enabled && ia_write_en[port_index] && ia_write_range[port_index] && write_hit[port_index];
            assign read_row_terms[port_index] = ia_read_row[port_index] & {p_row_bits{read_grant[port_index]}};
            assign write_row_terms[port_index] = ia_write_row[port_index] & {p_row_bits{write_grant[port_index]}};
            assign mask_terms[port_index] = ia_write_mask[port_index] & {16{write_grant[port_index]}};
        end
        for (genvar port_index = 0; port_index < 4; port_index++) begin : g_ps_port
            // 固定物理块偏移分别译码，避免请求路径上的可变加法。
            assign read_hit[port_index+2] =
                (ia_banks_q == BANK_COUNT_BITS'(1) && bank >= 1 && (int'(ps_read_addr[port_index]) >> p_row_bits) == bank-1) ||
                (ia_banks_q == BANK_COUNT_BITS'(2) && bank >= 2 && (int'(ps_read_addr[port_index]) >> p_row_bits) == bank-2) ||
                (ia_banks_q == BANK_COUNT_BITS'(4) && bank >= 4 && (int'(ps_read_addr[port_index]) >> p_row_bits) == bank-4);
            assign write_hit[port_index+2] =
                (ia_banks_q == BANK_COUNT_BITS'(1) && bank >= 1 && (int'(ps_write_addr[port_index]) >> p_row_bits) == bank-1) ||
                (ia_banks_q == BANK_COUNT_BITS'(2) && bank >= 2 && (int'(ps_write_addr[port_index]) >> p_row_bits) == bank-2) ||
                (ia_banks_q == BANK_COUNT_BITS'(4) && bank >= 4 && (int'(ps_write_addr[port_index]) >> p_row_bits) == bank-4);
            assign ps_read_selected[port_index][bank] = read_hit[port_index+2];
            assign read_request[port_index+2] = access_enabled && ps_read_en[port_index] && read_hit[port_index+2];
            assign write_request[port_index+2] = access_enabled && ps_write_en[port_index] && write_hit[port_index+2];
            assign read_row_terms[port_index+2] = ps_read_addr[port_index][p_row_bits-1:0] & {p_row_bits{read_grant[port_index+2]}};
            assign write_row_terms[port_index+2] = ps_write_addr[port_index][p_row_bits-1:0] & {p_row_bits{write_grant[port_index+2]}};
            assign mask_terms[port_index+2] = {16{write_grant[port_index+2]}};
        end
        assign read_grant[0] = read_request[0];
        assign write_grant[0] = write_request[0];
        for (genvar port_index = 1; port_index < 6; port_index++) begin : g_priority
            assign read_grant[port_index] = read_request[port_index] && !(|read_request[port_index-1:0]);
            assign write_grant[port_index] = write_request[port_index] && !(|write_request[port_index-1:0]);
        end
        assign read_addr[bank] = read_row_terms[0] | read_row_terms[1] | read_row_terms[2] |
            read_row_terms[3] | read_row_terms[4] | read_row_terms[5];
        assign write_addr[bank] = write_row_terms[0] | write_row_terms[1] | write_row_terms[2] |
            write_row_terms[3] | write_row_terms[4] | write_row_terms[5];
        assign write_mask[bank] = collision ? 16'd0 :
            (mask_terms[0] | mask_terms[1] | mask_terms[2] | mask_terms[3] | mask_terms[4] | mask_terms[5]);

        // 第零块始终属于 IA，编号不小于四的块始终属于 PS；中间块按配置选择数据源。
        // 写使能独立控制存储更新，闲置端口的宽数据无需逐位清零。
        assign ps_write_port = {write_grant[4] || write_grant[5], write_grant[3] || write_grant[5]};
        assign ia_bank = (bank < 1) || ((bank < 2) && ia_banks_q == BANK_COUNT_BITS'(2)) ||
            ((bank < 4) && ia_banks_q == BANK_COUNT_BITS'(4));
        if (bank == 0) begin : g_ia_only
            assign write_data[bank] = write_grant[1] ? ia_write_data[1] : ia_write_data[0];
        end else if (bank >= 4) begin : g_ps_only
            assign write_data[bank] = ps_write_data[ps_write_port];
        end else begin : g_shared_role
            assign write_data[bank] = ia_bank ? (write_grant[1] ? ia_write_data[1] : ia_write_data[0]) : ps_write_data[ps_write_port];
        end
        assign read_en[bank] = |read_request;
        assign write_en[bank] = (|write_request) && !collision;
        assign bank_fault[bank] = collision || (|(read_request & ~read_grant)) || (|(write_request & ~write_grant));
    end
    always_comb begin
        access_fault = |bank_fault;
        if (access_enabled) begin
            access_fault = (|bank_fault) || (|(ia_read_en & ~ia_read_range)) || (|(ia_write_en & ~ia_write_range)) ||
                (|(ps_read_en & ~ps_read_range)) || (|(ps_write_en & ~ps_write_range));
        end else if (|ia_read_en || |ia_write_en || |ps_read_en || |ps_write_en) begin
            access_fault = 1'b1;
        end
    end
    for (genvar port_index = 0; port_index < 4; port_index++) begin : g_return_address
        // 返回选择只在有效请求时保存，空闲期间继续输出对应物理存储块的读寄存器。
        for (genvar bit_index = 0; bit_index < p_bank_bits; bit_index++) begin : g_bit
            logic [p_banks-1:0] selected_bits;
            for (genvar bank = 0; bank < p_banks; bank++) begin : g_bank
                assign selected_bits[bank] = 1'(bank >> bit_index) && ps_read_selected[port_index][bank];
            end
            assign ps_return_bank[port_index][bit_index] = |selected_bits;
        end
    end

    //! 2. 配置与返回位置寄存
    //! ------------------------

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configured <= 1'b0;
            ia_banks_q <= BANK_COUNT_BITS'(1);
            capacity_fault <= 1'b0;
            for (int port_index = 0; port_index < 2; port_index++) begin
                ia_read_bank_hold[port_index] <= '0;
            end
            for (int port_index = 0; port_index < 4; port_index++) begin
                ps_read_bank_hold[port_index] <= '0;
            end
        end else begin
            if (cfg_valid) begin
                configured <= valid_configuration;
                if (valid_configuration) begin
                    ia_banks_q <= cfg_ia_banks;
                end
                capacity_fault <= !valid_configuration || access_fault;
            end else if (access_fault) begin
                capacity_fault <= 1'b1;
            end
            if (access_enabled) begin
                for (int port_index = 0; port_index < 2; port_index++) begin
                    if (ia_read_en[port_index]) begin
                        ia_read_bank_hold[port_index] <= p_bank_bits'(ia_read_bank[port_index]);
                    end
                end
                for (int port_index = 0; port_index < 4; port_index++) begin
                    if (ps_read_en[port_index] && ps_read_range[port_index]) begin
                        ps_read_bank_hold[port_index] <= ps_return_bank[port_index];
                    end
                end
            end
        end
    end

    //! 3. 读数据选择与物理存储
    //! --------------------------

    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_return
        assign ia_read_data[port_index] = read_data[ia_read_bank_hold[port_index]];
    end
    for (genvar port_index = 0; port_index < 4; port_index++) begin : g_ps_return
        logic [127:0] return_i_data [p_banks];
        logic [p_bank_bits-1:0] return_i_select;
        logic [127:0] return_o_data;
        assign return_i_data = read_data;
        assign return_i_select = ps_read_bank_hold[port_index];
        assign ps_read_data[port_index] = return_o_data;
        shared_ram_read_mux #(.p_width(128), .p_inputs(p_banks), .p_select_width(p_bank_bits)) u_return (
            .i_data(return_i_data), .i_select(return_i_select), .o_data(return_o_data)
        );
    end
    for (genvar bank = 0; bank < p_banks; bank++) begin : g_bank
        logic ram_i_wr_en, ram_i_rd_en;
        logic [p_row_bits-1:0] ram_i_wr_addr, ram_i_rd_addr;
        logic [127:0] ram_i_wr_data, ram_o_rd_data;
        logic [15:0] ram_i_wr_mask;
        assign ram_i_wr_en = write_en[bank];
        assign ram_i_wr_addr = write_addr[bank];
        assign ram_i_wr_data = write_data[bank];
        assign ram_i_wr_mask = write_mask[bank];
        assign ram_i_rd_en = read_en[bank];
        assign ram_i_rd_addr = read_addr[bank];
        assign read_data[bank] = ram_o_rd_data;
`ifdef ASIC_SRAM
        logic [127:0] ram_i_bit_write_mask;
        for (genvar byte_index = 0; byte_index < 16; byte_index++) begin : g_mask
            assign ram_i_bit_write_mask[byte_index*8+:8] = {8{ram_i_wr_mask[byte_index]}};
        end
        smic40_sram_1r1w #(.DATA_WIDTH(128), .DEPTH(p_rows), .ADDR_WIDTH(p_row_bits), .MACRO_DEPTH(128)) u_ram (
            .clk(clk), .write_enable(ram_i_wr_en), .write_address(ram_i_wr_addr),
            .write_data(ram_i_wr_data), .write_mask(ram_i_bit_write_mask),
            .read_enable(ram_i_rd_en), .read_address(ram_i_rd_addr), .read_data(ram_o_rd_data)
        );
`else
        regfile #(.p_data_width(128), .p_depth(p_rows), .p_addr_width(p_row_bits), .p_write_unit(8)) u_ram (
            .clk(clk), .i_wr_en(ram_i_wr_en), .i_wr_addr(ram_i_wr_addr),
            .i_wr_data(ram_i_wr_data), .i_wr_mask(ram_i_wr_mask),
            .i_rd_en(ram_i_rd_en), .i_rd_addr(ram_i_rd_addr), .o_rd_data(ram_o_rd_data)
        );
`endif
    end
`ifdef NPU_SIM_ASSERT
    initial begin
        if (BANK_BYTES < 32 || (BANK_BYTES & (BANK_BYTES-1)) != 0 || TOTAL_BYTES % BANK_BYTES != 0 || p_banks < 4) begin
            $fatal(1, "Invalid shared SRAM dimensions");
        end
    end
`endif
endmodule

// 按低位选择组内数据，再由高位选择对应组。
module shared_ram_read_mux #(
    parameter int p_width = 128,
    parameter int p_inputs = 7,
    parameter int p_select_width = $clog2(p_inputs)
) (
    input  wire logic [p_width-1:0] i_data [p_inputs],
    input  wire logic [p_select_width-1:0] i_select,
    output logic [p_width-1:0] o_data
);
    //! 0. 辅助定义
    //! -----------

    localparam int p_groups = (p_inputs <= 8) ? 2 : 4;

    //! 1. 选择存储返回数据
    //! -------------------

    if (p_inputs > 4 && p_inputs <= 16) begin : g_grouped
        logic [p_width-1:0] group_data [p_groups];
        logic [p_width-1:0] padded_data [4*p_groups];
        for (genvar bank = 0; bank < 4*p_groups; bank++) begin : g_pad
            if (bank < p_inputs) begin : g_present
                assign padded_data[bank] = i_data[bank];
            end else begin : g_unused
                assign padded_data[bank] = '0;
            end
        end
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            // 二级二选一表达组内选择，组间只读取已选中的数据。
            assign group_data[group_index] = i_select[1] ?
                (i_select[0] ? padded_data[4*group_index+3] : padded_data[4*group_index+2]) :
                (i_select[0] ? padded_data[4*group_index+1] : padded_data[4*group_index]);
        end
        if (p_inputs <= 8) begin : g_eight
            assign o_data = group_data[i_select[2]];
        end else begin : g_sixteen
            assign o_data = group_data[i_select[3:2]];
        end
    end else begin : g_direct
        assign o_data = i_data[i_select];
    end
endmodule

// 部分和的四个固定通道共享 IA 可分配空间，每个通道保存一个 128 位数据段。
module ia_ps_channel_ram #(
    parameter bit p_shared_write_stage = 1'b0,
    parameter int p_bank_bytes = 8192,
    parameter int p_total_bytes = 57344,
    parameter int p_addr_width = $clog2(p_total_bytes/16),
    parameter int p_bank_count_width = $clog2(p_total_bytes/p_bank_bytes+1)
) (
    input  wire logic clk,
    input  wire logic rst_n,
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
    logic valid_configuration, access_enabled, access_fault;
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
        access_fault = (|ia_bank_fault) || (|ps_collision);
        if (access_enabled) begin
            access_fault = access_fault ||
                (|(i_ia_read_en & ~ia_read_range)) || (|(i_ia_write_en & ~ia_write_range)) ||
                (|(i_ps_read_en & ~ps_read_range)) || (|(i_ps_write_en & ~ps_write_range));
        end else if ((|i_ia_read_en) || (|i_ia_write_en) || (|i_ps_read_en) || (|i_ps_write_en)) begin
            access_fault = 1'b1;
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
            end else if (access_enabled && i_ia_read_en[port_index]) begin
                ia_return_bank_q[port_index] <= ia_read_bank[port_index];
            end
        end
    end

    for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_ia_route
        logic [1:0] read_request, write_request;
        logic read_port_one, write_port_one, collision;
        logic [3:0] collision_terms;
        for (genvar port_index = 0; port_index < 2; port_index++) begin : g_request
            assign read_request[port_index] = access_enabled && i_ia_read_en[port_index] &&
                ia_read_range[port_index] && ia_read_bank[port_index] == p_ia_bank_bits'(bank);
            assign write_request[port_index] = access_enabled && i_ia_write_en[port_index] &&
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
                    (|i_ia_write_mask[write_port]) && ia_row_address_equal[read_port][write_port];
            end
        end
        assign collision = |collision_terms;
        assign ia_bank_read_en[bank] = |read_request;
        assign ia_bank_write_en[bank] = (|write_request) && !collision;
        assign ia_bank_fault[bank] = collision || (&read_request) || (&write_request);
    end

    //! 2. 固定部分和通道地址
    //! -----------------------

    logic [3:0] ps_read_fire, ps_write_fire;
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
        assign ps_read_fire[channel] = access_enabled && i_ps_read_en[channel] && ps_read_range[channel];
        assign ps_write_fire[channel] = access_enabled && i_ps_write_en[channel] && ps_write_range[channel] &&
            !ps_collision[channel];
        assign ps_collision[channel] = access_enabled && i_ps_read_en[channel] && i_ps_write_en[channel] &&
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
            assign ps_read_select[channel][bank] = ps_read_fire[channel] &&
                ((ia_banks_q == p_bank_count_width'(1) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                 (bank >= 2 && ia_banks_q == p_bank_count_width'(2) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2)));
            assign ps_write_select[channel][bank] = ps_write_fire[channel] &&
                ((ia_banks_q == p_bank_count_width'(1) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                 (bank >= 2 && ia_banks_q == p_bank_count_width'(2) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2)));
        end
        assign ps_read_select[channel][0] = ps_read_fire[channel] && ps_fixed_read_match[channel];
        assign ps_write_select[channel][0] = ps_write_fire[channel] && ps_fixed_write_match[channel];
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
            logic [p_chunk_bits-1:0] ram_i_wr_addr, ram_i_rd_addr;
            logic [127:0] ram_i_wr_data, ram_o_rd_data;
            logic [15:0] ram_i_wr_mask;
            assign ram_i_wr_en = (ia_bank_write_en[bank] &&
                ia_bank_write_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel)) || ps_write_select[channel][bank];
            assign ram_i_rd_en = (ia_bank_read_en[bank] &&
                ia_bank_read_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel)) || ps_read_select[channel][bank];
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
endmodule

`default_nettype wire
