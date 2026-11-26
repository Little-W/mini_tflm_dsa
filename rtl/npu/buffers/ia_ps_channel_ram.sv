// SPDX-License-Identifier: Apache-2.0
`default_nettype none
`timescale 1ns/1ps

// 部分和的四个固定通道共享 IA 可分配空间，每个通道保存一个 128 位数据段。
// 同一配置内，拥有共享块的通路在首次读取后持续保持返回数据，直到下一次读取。
module ia_ps_channel_ram #(
    parameter bit p_shared_write_stage = 1'b0,
    // 写入来源保证有效命令至少包含一个字节时，可直接使用写使能检查碰撞。
    parameter bit p_ia_nonempty_writes = 1'b0,
    // 两块 IA 行布局中，第二端口的有效命令只访问物理块 1。
    parameter bit p_paired_ia_ports = 1'b0,
    // 允许写入更新未拥有共享块的通路返回值；配置切换后由首次读取建立有效数据。
    parameter bit p_allow_inactive_return_updates = 1'b0,
    parameter int p_bank_bytes = 8192,
    parameter int p_total_bytes = 57344,
    parameter int p_addr_width = $clog2(p_total_bytes/16),
    parameter int p_bank_count_width = $clog2(p_total_bytes/p_bank_bytes+1)
) (
    input  wire logic clk /* 工作时钟 */,
    input  wire logic rst_n /* 低有效复位 */,
    input  wire logic i_access_enable = 1'b1 /* 允许当前计算通路访问共享存储 */,
    input  wire logic i_cfg_valid /* 接收本次共享存储空间分配配置 */,
    input  wire logic [p_bank_count_width-1:0] i_cfg_ia_banks /* 分配给输入数据的物理共享存储块数 */,
    output logic o_capacity_fault /* 存储分配或访问发生越界及端口冲突 */,
    input  wire logic [1:0] i_ia_read_en /* 两个输入数据通道的读使能 */,
    input  wire logic [1:0] i_ia_write_en /* 两个输入数据通道的写使能 */,
    input  wire logic [p_addr_width-1:0] i_ia_read_addr [2] /* 两个输入数据通道的存储字读取地址 */,
    input  wire logic [p_addr_width-1:0] i_ia_write_addr [2] /* 两个输入数据通道的存储字写入地址 */,
    output logic [127:0] o_ia_read_data [2] /* 两个输入数据通道同步返回的各128 位数据 */,
    input  wire logic [127:0] i_ia_write_data [2] /* 两个输入数据通道的各128 位写数据 */,
    input  wire logic [127:0] i_ia_shared_write_data = 128'd0 /* 预先选择的共享物理存储块写数据 */,
    input  wire logic [15:0] i_ia_write_mask [2] /* 两个输入数据通道的逐字节写使能 */,
    input  wire logic [3:0] i_ps_read_en /* 四个部分和存储通道的读使能 */,
    input  wire logic [3:0] i_ps_write_en /* 四个部分和存储通道的写使能 */,
    input  wire logic [p_addr_width-1:0] i_ps_read_addr [4] /* 四个部分和通道的存储字读取地址 */,
    input  wire logic [p_addr_width-1:0] i_ps_write_addr [4] /* 四个部分和通道的存储字写入地址 */,
    output logic [127:0] o_ps_read_data [4] /* 四个部分和通道同步返回的各128 位数据 */,
    input  wire logic [127:0] i_ps_write_data [4] /* 四个部分和通道的各128 位写数据 */
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
    localparam bit p_independent_read_data =
`ifdef XILINX_FPGA
        p_allow_inactive_return_updates;
`else
        1'b0;
`endif

    logic configured_q;
    logic [p_bank_count_width-1:0] ia_banks_q, ia_layout_banks;
    logic valid_configuration, access_enabled, memory_access_enabled, access_fault;
    logic [p_addr_width-1:0] ps_limit;
    logic [1:0] ia_read_range, ia_write_range;
    logic [3:0] ps_read_range, ps_write_range, ps_collision, ps_address_equal;
    logic [p_max_ia_banks-1:0] ia_bank_fault;
    logic [3:0] ps_request_fault;
    logic [1:0] ia_request_fault;
    logic ps_fault_summary;
    (* keep = 1 *) logic ia_fault_summary;
    logic [3:0] ps_read_fault_ready, ps_write_fault;
    logic capacity_next, capacity_next_selected;


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
        case (ia_layout_banks)
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
        // 每个请求先独立检查许可、范围和碰撞，统一访问条件在故障汇总后生效。
        case (^{i_access_enable, access_enabled, i_ia_read_en, i_ia_write_en,
                i_ps_read_en, i_ps_write_en, ia_read_range, ia_write_range,
                ps_read_range, ps_write_range, ps_address_equal, ia_bank_fault})
            1'b0, 1'b1: access_fault = i_access_enable && (ps_fault_summary || ia_fault_summary);
            default: begin end
        endcase
    end
    assign ps_fault_summary = |ps_request_fault;
    assign ia_fault_summary = (|ia_request_fault) || (|ia_bank_fault);
    for (genvar channel = 0; channel < 4; channel++) begin : g_prepared_ps_fault
        // 写入错误独立于读取请求；同地址冲突由读取请求在末级参与。
        assign ps_read_fault_ready[channel] = !access_enabled || !ps_read_range[channel] ||
            (i_ps_write_en[channel] && ps_address_equal[channel]);
        assign ps_write_fault[channel] =
            i_ps_write_en[channel] && (!access_enabled || !ps_write_range[channel]);
    end
    shared_ram_capacity_next u_capacity_next (
        .i_access_enable(i_access_enable), .i_cfg_valid(i_cfg_valid),
        .i_configuration_valid(valid_configuration), .i_current_fault(o_capacity_fault),
        .i_other_fault(ia_fault_summary || (|ps_write_fault)),
        .i_read_request(i_ps_read_en), .i_read_fault_ready(ps_read_fault_ready),
        .o_next_fault(capacity_next_selected)
    );
    always_comb begin
        capacity_next = o_capacity_fault;
        if (i_cfg_valid) capacity_next = !valid_configuration || access_fault;
        else if (access_fault) capacity_next = 1'b1;
        // 未知值仍通过原有条件更新语义处理，正常请求直接使用分组结果。
        case (^{i_cfg_valid, valid_configuration, o_capacity_fault, i_access_enable,
                access_enabled, i_ia_read_en, i_ia_write_en, i_ps_read_en, i_ps_write_en,
                ia_read_range, ia_write_range, ps_read_range, ps_write_range,
                ps_address_equal, ia_bank_fault})
            1'b0, 1'b1: capacity_next = capacity_next_selected;
            default: ;
        endcase
    end
    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_request_fault
        ps_channel_request_fault u_request_fault (
            .i_read_request(i_ia_read_en[port_index]), .i_write_request(i_ia_write_en[port_index]),
            .i_read_valid(ia_read_range[port_index]), .i_write_valid(ia_write_range[port_index]),
            .i_address_equal(1'b0), .i_access_enabled(access_enabled),
            .o_request_fault(ia_request_fault[port_index])
        );
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configured_q <= 1'b0;
            o_capacity_fault <= 1'b0;
        end else begin
            if (i_cfg_valid) begin
                configured_q <= valid_configuration;
            end
            o_capacity_fault <= capacity_next;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ia_banks_q <= p_bank_count_width'(1);
        end else if (i_cfg_valid && valid_configuration) begin
            ia_banks_q <= i_cfg_ia_banks;
        end
    end
    if (p_max_ia_banks == 2 && p_bank_count_width >= 3) begin : g_two_bank_layout
        logic two_banks_q;
        // 两块物理 IA 存储只接收一块或两块布局，用单个状态位保存选择。
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                two_banks_q <= 1'b0;
            end else if (i_cfg_valid && valid_configuration) begin
                two_banks_q <= i_cfg_ia_banks[1];
            end
        end
        always_comb begin
            ia_layout_banks = ia_banks_q;
            // 尚未建立有效状态时保留完整配置寄存器的四态传播。
            case (^ia_banks_q)
                1'b0, 1'b1: ia_layout_banks = two_banks_q ?
                    p_bank_count_width'(2) : p_bank_count_width'(1);
                default: ;
            endcase
        end
    end else begin : g_general_bank_layout
        assign ia_layout_banks = ia_banks_q;
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
    (* keep = "true" *) logic ia_row_address_equal [2][2];

    // 各对行地址独立比较，晚到的端口请求仅选择匹配结果。
    for (genvar read_port = 0; read_port < 2; read_port++) begin : g_ia_row_compare
        for (genvar write_port = 0; write_port < 2; write_port++) begin : g_write
            // 配对布局的两个端口分属不同块，交叉行比较可随使用逻辑共同优化。
            (* keep = !(p_paired_ia_ports && p_max_ia_banks == 2 && read_port != write_port) *)
            logic [2:0] layout_row_equal;
            for (genvar shift=0;shift<3;shift++) begin : g_layout
                // 各种地址排列分别比较原始行号，配置只选择已经形成的一位结果。
                if (p_max_ia_banks == 2 && p_bank_count_width >= 3 && shift == 2) begin : g_unused_layout
                    assign layout_row_equal[shift] = 1'b0;
                end else begin : g_supported_layout
                    assign layout_row_equal[shift] =
                        p_row_bits'(i_ia_read_addr[read_port] >> shift) ==
                        p_row_bits'(i_ia_write_addr[write_port] >> shift);
                end
            end
            always_comb begin
                case (ia_layout_banks)
                    p_bank_count_width'(2): ia_row_address_equal[read_port][write_port] = layout_row_equal[1];
                    p_bank_count_width'(4): ia_row_address_equal[read_port][write_port] = layout_row_equal[2];
                    default: ia_row_address_equal[read_port][write_port] = layout_row_equal[0];
                endcase
            end
        end
    end

    for (genvar port_index = 0; port_index < 2; port_index++) begin : g_ia_address
        logic [p_addr_width-1:0] read_row_full, write_row_full;
        always_comb begin
            ia_read_bank[port_index] = '0;
            ia_write_bank[port_index] = '0;
            read_row_full = i_ia_read_addr[port_index];
            write_row_full = i_ia_write_addr[port_index];
            case (ia_layout_banks)
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
        if (p_paired_ia_ports && p_max_ia_banks == 2 && port_index == 1) begin : g_paired_return
            // 第二端口用于宽行的后半段，消费者仅在对应读取有效时使用返回值。
            assign o_ia_read_data[port_index] = ia_bank_read_data[1];
        end else begin : g_general_return
            assign o_ia_read_data[port_index] = ia_bank_read_data[ia_return_bank_q[port_index]];
        end
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ia_return_bank_q[port_index] <= '0;
            end else if (memory_access_enabled && i_ia_read_en[port_index]) begin
                ia_return_bank_q[port_index] <= ia_read_bank[port_index];
            end
        end
    end

    logic [1:0] ia_read_requests [p_max_ia_banks], ia_write_requests [p_max_ia_banks];
    logic [p_max_ia_banks-1:0] ia_write_permitted;
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
        if (p_paired_ia_ports && p_max_ia_banks == 2 && bank == 0) begin : g_paired_write
            // 宽行后半段写入块 1，紧凑行和向量写入只使用第一端口。
            assign ia_bank_write_data[bank] = i_ia_write_data[0];
        end else begin : g_general_write
            assign ia_bank_write_data[bank] = write_port_one ? i_ia_write_data[1] : i_ia_write_data[0];
        end
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
        assign ia_read_requests[bank] = read_request;
        assign ia_write_requests[bank] = write_request;
        assign ia_write_permitted[bank] = !collision;
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
    (* keep = !p_independent_read_data *) logic [p_max_ia_banks-1:0] ps_read_selection_eligible [4];
    (* keep = 1 *) logic [p_max_ia_banks-1:0] ps_write_selection_eligible [4];
    logic [3:0] ps_fixed_read_match, ps_fixed_write_match;
    logic [p_addr_width-1:0] ps_fixed_read_addr [4], ps_fixed_write_addr [4];
    logic [p_max_ia_banks-1:0] ps_read_select [4], ps_write_select [4];
    (* keep = 1 *) logic [p_max_ia_banks-1:0] ps_read_bank_match [4];
    logic [p_max_ia_banks-1:0] ps_write_bank_match [4], ps_write_access_eligible [4];
    logic [p_ia_bank_bits-1:0] ps_return_select_q [4];
    logic [127:0] ps_segment_read_data [4][p_max_ia_banks];

    // 通道编号隐含最低两位字序号，端口地址只包含 512 位部分和行号。
    // 可配置的 IA 块分成四段，每段接入一个部分和通道；IA 的物理字位置保持固定。
    for (genvar channel = 0; channel < 4; channel++) begin : g_ps_address
        assign ps_read_range[channel] = i_ps_read_addr[channel] < ps_limit;
        assign ps_write_range[channel] = i_ps_write_addr[channel] < ps_limit;
        assign ps_read_eligible[channel] = i_ps_read_en[channel] && ps_read_range[channel];
        assign ps_write_eligible[channel] = i_ps_write_en[channel] && ps_write_range[channel] && !ps_collision[channel];
        ps_channel_read_enable u_read_fire (
            .i_read_request(i_ps_read_en[channel]), .i_address_valid(ps_read_range[channel]),
            .i_bank_match(1'b1), .i_access_enabled(access_enabled),
            .i_path_enable(i_access_enable), .o_enable(ps_read_fire[channel])
        );
        assign ps_write_fire[channel] = memory_access_enabled && ps_write_eligible[channel];
        ps_channel_request_fault u_request_fault (
            .i_read_request(i_ps_read_en[channel]), .i_write_request(i_ps_write_en[channel]),
            .i_read_valid(ps_read_range[channel]), .i_write_valid(ps_write_range[channel]),
            .i_address_equal(ps_address_equal[channel]), .i_access_enabled(access_enabled),
            .o_request_fault(ps_request_fault[channel])
        );
        assign ps_address_equal[channel] = i_ps_read_addr[channel] == i_ps_write_addr[channel];
        assign ps_collision[channel] = i_ps_read_en[channel] && i_ps_write_en[channel] &&
            ps_read_range[channel] && ps_write_range[channel] &&
            ps_address_equal[channel];

        always_comb begin
            ps_fixed_read_addr[channel] = i_ps_read_addr[channel];
            ps_fixed_write_addr[channel] = i_ps_write_addr[channel];
            ps_fixed_read_match[channel] = 1'b1;
            ps_fixed_write_match[channel] = 1'b1;
            case (ia_layout_banks)
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
            // 返回存储块编号由配置和地址独立确定，访问资格只控制接收使能。
            assign ps_read_bank_match[channel][bank] =
                (ia_layout_banks == p_bank_count_width'(1) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                (bank >= 2 && ia_layout_banks == p_bank_count_width'(2) && (i_ps_read_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2));
            assign ps_read_selection_eligible[channel][bank] =
                ps_read_eligible[channel] && ps_read_bank_match[channel][bank];
            assign ps_write_bank_match[channel][bank] =
                ((ia_layout_banks == p_bank_count_width'(1) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-1)) ||
                 (bank >= 2 && ia_layout_banks == p_bank_count_width'(2) && (i_ps_write_addr[channel] >> p_chunk_bits) == p_addr_width'(bank-2)));
        end
        assign ps_read_bank_match[channel][0] = ps_fixed_read_match[channel];
        assign ps_read_selection_eligible[channel][0] = ps_read_eligible[channel] && ps_fixed_read_match[channel];
        for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_read_selection_enable
            // 请求、配置许可和已准备的地址资格共同形成物理端口读取使能。
            ps_channel_read_enable u_read_enable (
                .i_read_request(i_ps_read_en[channel]), .i_address_valid(ps_read_range[channel]),
                .i_bank_match(ps_read_bank_match[channel][bank]), .i_access_enabled(access_enabled),
                .i_path_enable(i_access_enable), .o_enable(ps_read_select[channel][bank])
            );
        end
        assign ps_write_bank_match[channel][0] = ps_fixed_write_match[channel];
        for (genvar bank = 0; bank < p_max_ia_banks; bank++) begin : g_write_selection_enable
            logic destination_valid, selection_eligible, access_eligible;
            // 地址范围、目标银行和读写地址相等关系在请求到达前并行形成。
            // 小型组合模块使请求仅经过最终资格选择与物理存储端口使能。
            assign destination_valid = ps_write_range[channel] && ps_write_bank_match[channel][bank];
            ps_channel_write_enable u_write_enable (
                .i_write_request(i_ps_write_en[channel]), .i_read_request(i_ps_read_en[channel]),
                .i_read_valid(ps_read_range[channel]), .i_address_equal(ps_address_equal[channel]),
                .i_destination_valid(destination_valid), .i_access_enabled(access_enabled),
                .o_selection_eligible(selection_eligible), .o_access_eligible(access_eligible)
            );
            always_comb begin
                ps_write_selection_eligible[channel][bank] = ps_write_eligible[channel] && ps_write_bank_match[channel][bank];
                ps_write_access_eligible[channel][bank] = access_enabled && ps_write_selection_eligible[channel][bank];
                case (^{i_ps_write_en[channel], i_ps_read_en[channel], ps_read_range[channel],
                        ps_write_range[channel], ps_address_equal[channel],
                        ps_write_bank_match[channel][bank], access_enabled})
                    1'b0, 1'b1: begin
                        ps_write_selection_eligible[channel][bank] = selection_eligible;
                        ps_write_access_eligible[channel][bank] = access_eligible;
                    end
                    default: begin end
                endcase
            end
            assign ps_write_select[channel][bank] = i_access_enable && ps_write_access_eligible[channel][bank];
        end
        assign o_ps_read_data[channel] = ps_segment_read_data[channel][ps_return_select_q[channel]];
        always_ff @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                ps_return_select_q[channel] <= '0;
            end else if (ps_read_fire[channel]) begin
                ps_return_select_q[channel] <= '0;
                for (int bank = 1; bank < p_max_ia_banks; bank++) begin
                    if (ps_read_bank_match[channel][bank]) begin
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
        assign ia_selected = p_bank_count_width'(bank) < ia_layout_banks;
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
            (* keep = !p_independent_read_data *) logic ram_write_eligible, ram_read_eligible;
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
            if (p_independent_read_data) begin : g_qualified_response
                (* keep = "true" *) logic ia_read_qualified, ia_write_qualified;
                logic port_a_enable, port_a_read_allowed, port_b_enable;
                logic [1:0] ia_read_segment, ia_write_segment;
                logic selected_ia_read, selected_ia_write;
                logic [p_chunk_bits-1:0] port_a_addr, port_b_addr;
                logic [127:0] ia_write_data;
                // 两个端口先独立检查分段，端口优先选择只参与最终访问资格。
                for (genvar port_index = 0; port_index < 2; port_index++) begin : g_segment
                    assign ia_read_segment[port_index] =
                        ia_read_row[port_index][p_row_bits-1:p_chunk_bits] == 2'(channel);
                    assign ia_write_segment[port_index] =
                        ia_write_row[port_index][p_row_bits-1:p_chunk_bits] == 2'(channel);
                end
                ia_channel_segment_enable u_read_segment (
                    .i_first_request(ia_read_requests[bank][0]), .i_second_request(ia_read_requests[bank][1]),
                    .i_first_segment(ia_read_segment[0]), .i_second_segment(ia_read_segment[1]),
                    .i_permitted(1'b1), .i_access_enabled(access_enabled), .o_enable(selected_ia_read)
                );
                ia_channel_segment_enable u_write_segment (
                    .i_first_request(ia_write_requests[bank][0]), .i_second_request(ia_write_requests[bank][1]),
                    .i_first_segment(ia_write_segment[0]), .i_second_segment(ia_write_segment[1]),
                    .i_permitted(ia_write_permitted[bank]), .i_access_enabled(access_enabled),
                    .o_enable(selected_ia_write)
                );
                always_comb begin
                    ia_read_qualified = access_enabled && ia_bank_read_eligible[bank] &&
                        ia_bank_read_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel);
                    case (^{access_enabled, ia_read_requests[bank], ia_read_segment})
                        1'b0, 1'b1: ia_read_qualified = selected_ia_read;
                        default: begin end
                    endcase
                    ia_write_qualified = access_enabled && ia_bank_write_eligible[bank] &&
                        ia_bank_write_addr[bank][p_row_bits-1:p_chunk_bits] == 2'(channel);
                    case (^{access_enabled, ia_write_requests[bank], ia_write_segment, ia_write_permitted[bank]})
                        1'b0, 1'b1: ia_write_qualified = selected_ia_write;
                        default: begin end
                    endcase
                end
                // IA 与部分和按空间分配互斥使用该段，两个端口各有独立地址。
                // 当前拥有者的写入只更新另一通路的读输出，自己的读输出持续保持。
                // 部分和地址资格独立准备，读取请求在 RAM 端口的末级参与使能。
                assign port_a_enable = i_ps_read_en[channel];
                assign port_a_read_allowed = access_enabled && ps_read_range[channel] &&
                    ps_read_bank_match[channel][bank];
                assign port_b_enable = ia_read_qualified;
                assign port_a_addr = ia_selected ? ia_bank_write_addr[bank][p_chunk_bits-1:0] :
                    i_ps_read_addr[channel][p_chunk_bits-1:0];
                assign port_b_addr = ia_selected ? ia_bank_read_addr[bank][p_chunk_bits-1:0] :
                    i_ps_write_addr[channel][p_chunk_bits-1:0];
                if (p_shared_write_stage && p_max_ia_banks == 2) begin : g_shared_data
                    assign ia_write_data = i_ia_shared_write_data;
                end else begin : g_port_data
                    assign ia_write_data = ia_bank_write_data[bank];
                end
                ia_ps_role_ram #(.p_depth(p_chunk_rows), .p_addr_width(p_chunk_bits)) u_ram (
                    .clk(clk), .i_access_enable(i_access_enable),
                    .i_a_enable(port_a_enable), .i_a_read_allowed(port_a_read_allowed), .i_a_write(ia_write_qualified),
                    .i_a_addr(port_a_addr), .i_a_data(ia_write_data), .i_a_mask(ia_bank_write_mask[bank]),
                    .o_a_data(ps_segment_read_data[channel][bank]),
                    .i_b_enable(port_b_enable),
                    .i_b_write(ps_write_access_eligible[channel][bank]),
                    .i_b_addr(port_b_addr), .i_b_data(i_ps_write_data[channel]),
                    .o_b_data(chunk_read_data[channel])
                );
            end else begin : g_held_response
                assign chunk_read_data[channel] = ram_o_rd_data;
                assign ps_segment_read_data[channel][bank] = ram_o_rd_data;
                regfile #(.p_data_width(128), .p_depth(p_chunk_rows), .p_addr_width(p_chunk_bits), .p_write_unit(8)) u_ram (
                    .clk(clk), .i_wr_en(ram_i_wr_en), .i_wr_addr(ram_i_wr_addr),
                    .i_wr_data(ram_i_wr_data), .i_wr_mask(ram_i_wr_mask),
                    .i_rd_en(ram_i_rd_en), .i_rd_addr(ram_i_rd_addr), .o_rd_data(ram_o_rd_data)
                );
            end
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
    if (p_paired_ia_ports && p_max_ia_banks == 2) begin : g_paired_port_check
        always_ff @(posedge clk) begin
            if (rst_n && memory_access_enabled) begin
                if (i_ia_read_en[1]) begin
                    assert (ia_layout_banks == p_bank_count_width'(2) && i_ia_read_addr[1][0])
                        else $fatal(1, "Paired IA read port requires physical bank 1");
                end
                if (i_ia_write_en[1]) begin
                    assert (ia_layout_banks == p_bank_count_width'(2) && i_ia_write_addr[1][0])
                        else $fatal(1, "Paired IA write port requires physical bank 1");
                end
            end
        end
    end
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
