`default_nettype none

// 任务范围寄存、操作数读取缓存和 AXI 读取接口。
module npu_operand_cache_bridge #(
    parameter int unsigned p_bus_width = 32'd64,
    parameter int unsigned p_operand_cache_enable = 32'd0,
    parameter int unsigned p_operand_stream_bytes = 32'd65536,
    parameter int unsigned p_reg_width = 32'd32,
    parameter int unsigned p_size_shift = 32'd4
) (
    input logic [p_reg_width-1:0] i_cache_axi_araddr,
    input logic [1:0] i_cache_axi_arburst,
    input logic [7:0] i_cache_axi_arlen,
    input logic [2:0] i_cache_axi_arsize,
    input logic i_cache_axi_arvalid,
    input logic i_cache_axi_rready,
    input logic i_calc_start,
    input logic i_cfg_16x8_q [0:2],
    input logic i_cfg_conv_enable,
    input logic i_cfg_dataflow_mode_eff,
    input logic [p_reg_width-1:0] i_cfg_ia_reuse_q [0:2],
    input logic i_cfg_lhs_tile_packed,
    input logic i_cfg_operand_fetch64,
    input logic i_cfg_rhs_tile_packed,
    input logic i_cfg_stage2_fire,
    input logic [p_reg_width-1:0] i_cfg_stream_k_q [0:2],
    input logic [p_reg_width-1:0] i_cfg_stream_m_q [0:2],
    input logic i_cfg_use16_q [0:2],
    input logic i_cfg_vector_enable,
    input logic [p_reg_width-1:0] i_cfg_w_reuse_q [0:2],
    input logic clk,
    input logic rst_n,
    input logic [p_reg_width-1:0] i_k,
    input logic i_legacy_axi_arready,
    input logic [p_bus_width-1:0] i_legacy_axi_rdata,
    input logic i_legacy_axi_rlast,
    input logic [1:0] i_legacy_axi_rresp,
    input logic i_legacy_axi_rvalid,
    input logic [p_reg_width-1:0] i_lhs_base,
    input logic [p_reg_width-1:0] i_lhs_row_stride_b,
    input logic [p_reg_width-1:0] i_m,
    input logic [p_reg_width-1:0] i_rhs_base,
    input logic [p_reg_width-1:0] i_rhs_col_stride_b,
    input logic i_run_conv,
    input logic i_run_lhs_tile_packed,
    input logic i_run_rhs_tile_packed,
    input logic i_sa_ready,
    output logic o_cache_axi_arready,
    output logic [p_bus_width-1:0] o_cache_axi_rdata,
    output logic o_cache_axi_rlast,
    output logic [1:0] o_cache_axi_rresp,
    output logic o_cache_axi_rvalid,
    output logic [p_reg_width-1:0] o_legacy_axi_araddr,
    output logic [1:0] o_legacy_axi_arburst,
    output logic [7:0] o_legacy_axi_arlen,
    output logic [2:0] o_legacy_axi_arsize,
    output logic o_legacy_axi_arvalid,
    output logic o_legacy_axi_rready,
    output logic o_operand_cache_idle
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
