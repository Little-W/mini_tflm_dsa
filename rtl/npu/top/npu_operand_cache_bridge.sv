`default_nettype none

// 任务范围寄存、操作数读取缓存和 AXI 读取接口。
module npu_operand_cache_bridge #(
    parameter int unsigned p_bus_width = 32'd64,
    parameter int unsigned p_operand_cache_enable = 32'd0,
    parameter int unsigned p_operand_stream_bytes = 32'd65536,
    parameter int unsigned p_reg_width = 32'd32,
    parameter int unsigned p_size_shift = 32'd4
) (
    input wire logic [p_reg_width-1:0] i_cache_axi_araddr, // 操作数请求侧的 AXI 接口：读事务起始字节地址。
    input wire logic [1:0] i_cache_axi_arburst, // 操作数请求侧的 AXI 接口：读事务的突发类型。
    input wire logic [7:0] i_cache_axi_arlen, // 操作数请求侧的 AXI 接口：读突发的传输拍数减一。
    input wire logic [2:0] i_cache_axi_arsize, // 操作数请求侧的 AXI 接口：每拍读取字节数的二进制对数。
    input wire logic i_cache_axi_arvalid, // 操作数请求侧的 AXI 接口：读地址请求有效。
    input wire logic i_cache_axi_rready, // 操作数请求侧的 AXI 接口：能够接收读取响应。
    input wire logic i_calc_start, // 开始接收新的计算任务。
    input wire logic i_cfg_16x8_q [0:2], // 各配置阶段采用十六位乘八位格式的标志。
    input wire logic i_cfg_conv_enable, // 启用卷积窗口展开。
    input wire logic i_cfg_dataflow_mode_eff, // 经过能力配置筛选的数据流模式。
    input wire logic [p_reg_width-1:0] i_cfg_ia_reuse_q [0:2], // 各配置阶段保存的输入分块复用数量。
    input wire logic i_cfg_lhs_tile_packed, // 左操作数采用分块打包存储。
    input wire logic i_cfg_operand_fetch64, // 启用操作数范围预读。
    input wire logic i_cfg_rhs_tile_packed, // 右操作数采用分块打包存储。
    input wire logic i_cfg_stage2_fire, // 配置准备的第三阶段完成事件。
    input wire logic [p_reg_width-1:0] i_cfg_stream_k_q [0:2], // 各配置阶段的流式维度长度，WS 为输出行数，IS 为输出列数。
    input wire logic [p_reg_width-1:0] i_cfg_stream_m_q [0:2], // 各配置阶段的驻留维度长度，WS 为输出列数，IS 为输出行数。
    input wire logic i_cfg_use16_q [0:2], // 各配置阶段采用十六位输入的标志。
    input wire logic i_cfg_vector_enable, // 启用向量计算任务。
    input wire logic [p_reg_width-1:0] i_cfg_w_reuse_q [0:2], // 各配置阶段保存的驻留分块复用数量。
    input wire logic clk, // 模块工作时钟。
    input wire logic rst_n, // 低有效复位输入。
    input wire logic [p_reg_width-1:0] i_k, // 矩阵计算的输出行数。
    input wire logic i_legacy_axi_arready, // 外部读取侧的 AXI 接口：能够接收读地址请求。
    input wire logic [p_bus_width-1:0] i_legacy_axi_rdata, // 外部读取侧的 AXI 接口：读取响应的数据。
    input wire logic i_legacy_axi_rlast, // 外部读取侧的 AXI 接口：当前读突发的最后一拍。
    input wire logic [1:0] i_legacy_axi_rresp, // 外部读取侧的 AXI 接口：读取响应的状态编码。
    input wire logic i_legacy_axi_rvalid, // 外部读取侧的 AXI 接口：返回的读取数据有效。
    input wire logic [p_reg_width-1:0] i_lhs_base, // 左操作数矩阵的字节基址。
    input wire logic [p_reg_width-1:0] i_lhs_row_stride_b, // 左操作数相邻行的字节间隔。
    input wire logic [p_reg_width-1:0] i_m, // 矩阵计算的输出列数。
    input wire logic [p_reg_width-1:0] i_rhs_base, // 右操作数矩阵的字节基址。
    input wire logic [p_reg_width-1:0] i_rhs_col_stride_b, // 右操作数相邻列的字节间隔。
    input wire logic i_run_conv, // 当前已接收任务采用卷积模式。
    input wire logic i_run_lhs_tile_packed, // 当前任务的左操作数采用分块打包存储。
    input wire logic i_run_rhs_tile_packed, // 当前任务的右操作数采用分块打包存储。
    input wire logic i_sa_ready, // 计算阵列及其控制逻辑允许接收任务。
    output logic o_cache_axi_arready, // 操作数请求侧的 AXI 接口：能够接收读地址请求。
    output logic [p_bus_width-1:0] o_cache_axi_rdata, // 操作数请求侧的 AXI 接口：读取响应的数据。
    output logic o_cache_axi_rlast, // 操作数请求侧的 AXI 接口：当前读突发的最后一拍。
    output logic [1:0] o_cache_axi_rresp, // 操作数请求侧的 AXI 接口：读取响应的状态编码。
    output logic o_cache_axi_rvalid, // 操作数请求侧的 AXI 接口：返回的读取数据有效。
    output logic [p_reg_width-1:0] o_legacy_axi_araddr, // 外部读取侧的 AXI 接口：读事务起始字节地址。
    output logic [1:0] o_legacy_axi_arburst, // 外部读取侧的 AXI 接口：读事务的突发类型。
    output logic [7:0] o_legacy_axi_arlen, // 外部读取侧的 AXI 接口：读突发的传输拍数减一。
    output logic [2:0] o_legacy_axi_arsize, // 外部读取侧的 AXI 接口：每拍读取字节数的二进制对数。
    output logic o_legacy_axi_arvalid, // 外部读取侧的 AXI 接口：读地址请求有效。
    output logic o_legacy_axi_rready, // 外部读取侧的 AXI 接口：能够接收读取响应。
    output logic o_operand_cache_idle // 操作数缓存及其读取事务均已空闲。
);

    generate if (p_operand_cache_enable != 0) begin : g_operand_cache
        // 保存任务范围，分阶段计算尺寸乘积和起始地址。
        localparam int HALF = (p_reg_width + 1) / 2;
        logic [3:0] range_stage;
        logic range_ready, fetch64_q;
        logic [p_reg_width-1:0] a_base_cfg, b_base_cfg;
        logic [p_reg_width-1:0] ax, ay, bx, by;
        logic [p_reg_width-1:0] a_ll, a_lh, a_hl, b_ll, b_lh, b_hl;
        logic [p_reg_width-1:0] a_bytes_cfg, b_bytes_cfg;
        logic cache_request_ready;
        logic single_group_bypass;
        wire retained_arvalid, retained_rvalid, retained_rready, retained_rlast;
        wire [p_reg_width-1:0] retained_araddr;
        wire [7:0] retained_arlen;
        wire [2:0] retained_arsize;
        wire [1:0] retained_arburst, retained_rresp;
        wire [p_bus_width-1:0] retained_rdata;
        wire accept_cache_task = i_calc_start && i_sa_ready;
        // 完整输出工作组由 IA/PS 调度保存所需的归约分块，任务开始时选择读取方式。
        // 卷积的原始图像复用由共享 DMA 管理，矩阵任务按范围选择操作数缓存。
        always_ff @(posedge clk) begin
            if (!rst_n) single_group_bypass <= 1'b0;
            else begin
                if (accept_cache_task) single_group_bypass <= i_cfg_conv_enable || i_cfg_vector_enable ||
                    i_cfg_lhs_tile_packed || i_cfg_rhs_tile_packed;
                if (i_cfg_stage2_fire)
                    single_group_bypass <= i_run_conv || i_run_lhs_tile_packed || i_run_rhs_tile_packed ||
                        (!fetch64_q && !i_cfg_use16_q[2] && !i_cfg_16x8_q[2] &&
                        i_cfg_stream_k_q[2] != 0 && i_cfg_stream_m_q[2] != 0 &&
                        i_cfg_stream_k_q[2] <= (i_cfg_ia_reuse_q[2] << p_size_shift) &&
                        i_cfg_stream_m_q[2] <= (i_cfg_w_reuse_q[2] << p_size_shift));
            end
        end
        always_ff @(posedge clk) begin
            if (!rst_n) begin
                range_stage <= 0; range_ready <= 0; fetch64_q <= 0;
                a_base_cfg <= 0; b_base_cfg <= 0;
                ax <= 0; ay <= 0; bx <= 0; by <= 0;
                a_ll <= 0; a_lh <= 0; a_hl <= 0;
                b_ll <= 0; b_lh <= 0; b_hl <= 0;
                a_bytes_cfg <= 0; b_bytes_cfg <= 0;
            end else begin
                range_stage <= {range_stage[2:0],accept_cache_task};
                if (accept_cache_task) begin
                    range_ready <= 0;
                    fetch64_q <= i_cfg_operand_fetch64;
                    a_base_cfg <= i_cfg_dataflow_mode_eff ? i_rhs_base : i_lhs_base;
                    b_base_cfg <= i_cfg_dataflow_mode_eff ? i_lhs_base : i_rhs_base;
                    ax <= i_cfg_dataflow_mode_eff ? i_m : i_k;
                    ay <= i_cfg_dataflow_mode_eff ? i_rhs_col_stride_b : i_lhs_row_stride_b;
                    bx <= i_cfg_dataflow_mode_eff ? i_k : i_m;
                    by <= i_cfg_dataflow_mode_eff ? i_lhs_row_stride_b : i_rhs_col_stride_b;
                end
                if (range_stage[0]) begin
                    a_ll <= ax[HALF-1:0] * ay[HALF-1:0];
                    a_lh <= ax[HALF-1:0] * ay[p_reg_width-1:HALF];
                    a_hl <= ax[p_reg_width-1:HALF] * ay[HALF-1:0];
                    b_ll <= bx[HALF-1:0] * by[HALF-1:0];
                    b_lh <= bx[HALF-1:0] * by[p_reg_width-1:HALF];
                    b_hl <= bx[p_reg_width-1:HALF] * by[HALF-1:0];
                end
                if (range_stage[1]) begin
                    a_bytes_cfg <= a_ll + ((a_lh + a_hl) << HALF);
                    b_bytes_cfg <= b_ll + ((b_lh + b_hl) << HALF);
                end
                if (range_stage[3]) range_ready <= 1;
            end
        end
        assign o_cache_axi_arready = (single_group_bypass ? i_legacy_axi_arready : cache_request_ready) && range_ready;
        assign o_legacy_axi_arvalid = single_group_bypass ? (i_cache_axi_arvalid && range_ready) : retained_arvalid;
        assign o_legacy_axi_araddr = single_group_bypass ? i_cache_axi_araddr : retained_araddr;
        assign o_legacy_axi_arlen = single_group_bypass ? i_cache_axi_arlen : retained_arlen;
        assign o_legacy_axi_arsize = single_group_bypass ? i_cache_axi_arsize : retained_arsize;
        assign o_legacy_axi_arburst = single_group_bypass ? i_cache_axi_arburst : retained_arburst;
        assign o_cache_axi_rvalid = single_group_bypass ? i_legacy_axi_rvalid : retained_rvalid;
        assign o_cache_axi_rdata = single_group_bypass ? i_legacy_axi_rdata : retained_rdata;
        assign o_cache_axi_rresp = single_group_bypass ? i_legacy_axi_rresp : retained_rresp;
        assign o_cache_axi_rlast = single_group_bypass ? i_legacy_axi_rlast : retained_rlast;
        assign o_legacy_axi_rready = single_group_bypass ? i_cache_axi_rready : retained_rready;
        operand_read_cache #(.AW(p_reg_width), .DW(p_bus_width), .A_BYTES(p_operand_stream_bytes)) u_cache (
            .clk(clk), .rst_n(rst_n), .flush(range_stage[2]),
            .idle(o_operand_cache_idle),
            .prefetch_enable(fetch64_q),
            // 保留缓存跟随流式输入操作数：WS 保存 A，IS 保存转置计算所用的物理 B。
            .a_base(a_base_cfg), .a_bytes(a_bytes_cfg),
            .b_base(b_base_cfg), .b_bytes(b_bytes_cfg),
            .s_arvalid(i_cache_axi_arvalid && range_ready && !single_group_bypass), .m_arvalid(retained_arvalid),
            .s_arready(cache_request_ready), .m_arready(i_legacy_axi_arready),
            .s_araddr(i_cache_axi_araddr), .m_araddr(retained_araddr),
            .s_arlen(i_cache_axi_arlen), .m_arlen(retained_arlen),
            .s_arsize(i_cache_axi_arsize), .m_arsize(retained_arsize),
            .s_arburst(i_cache_axi_arburst), .m_arburst(retained_arburst),
            .s_rvalid(retained_rvalid), .m_rvalid(i_legacy_axi_rvalid && !single_group_bypass),
            .s_rready(i_cache_axi_rready && !single_group_bypass), .m_rready(retained_rready),
            .s_rdata(retained_rdata), .m_rdata(i_legacy_axi_rdata),
            .s_rresp(retained_rresp), .m_rresp(i_legacy_axi_rresp),
            .s_rlast(retained_rlast), .m_rlast(i_legacy_axi_rlast)
        );
    end else begin : g_no_operand_cache
        assign o_operand_cache_idle=1'b1;
        assign o_legacy_axi_arvalid=i_cache_axi_arvalid;
        assign o_cache_axi_arready=i_legacy_axi_arready;
        assign o_legacy_axi_araddr=i_cache_axi_araddr;
        assign o_legacy_axi_arlen=i_cache_axi_arlen;
        assign o_legacy_axi_arsize=i_cache_axi_arsize;
        assign o_legacy_axi_arburst=i_cache_axi_arburst;
        assign o_cache_axi_rvalid=i_legacy_axi_rvalid;
        assign o_legacy_axi_rready=i_cache_axi_rready;
        assign o_cache_axi_rdata=i_legacy_axi_rdata;
        assign o_cache_axi_rresp=i_legacy_axi_rresp;
        assign o_cache_axi_rlast=i_legacy_axi_rlast;
    end endgenerate

endmodule

`default_nettype wire
