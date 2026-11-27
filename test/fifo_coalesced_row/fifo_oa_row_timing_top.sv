`default_nettype none

// 联合实例化完整输出写回与 INT8 FIFO，保留全部公开控制和数据用于资源及时序测量。
module fifo_oa_row_timing_top #(
    parameter int unsigned VLEN       = 16,
    parameter int unsigned DATA_WIDTH = 8,
    parameter int unsigned REG_WIDTH  = 32,
    parameter int unsigned BUS_WIDTH  = 32,
    parameter int unsigned COUNT_WIDTH = REG_WIDTH,
    parameter int unsigned ENABLE_IS_MODE = 1
) (
    input logic in_valid, // 输入结果行有效
    input logic in_tile_done, // 输入结果行结束当前矩阵块
    input logic [VLEN*8-1:0] in_vec_s8, // 当前输入结果行的数据
    input logic [31:0] reserve_banks, // 下一计算分组预留的存储体数量
    input logic [31:0] i_ready_bank_threshold, // 允许继续接收的完成存储体数量上限
    output logic fifo_full_flag, // FIFO 容量不足以接收下一分组
    input logic clk, // 模块工作时钟
    input logic rst_n, // 低有效复位

    input  logic init_cfg, // 装载本次写回配置
    output logic write_oa_req, // 输出写回请求
    input  logic write_oa_granted, // 输出写回获得授权

    input logic [REG_WIDTH-1:0] dst_base, // 输出矩阵起始字节地址
    input logic [REG_WIDTH-1:0] dst_row_stride_b, // 输出矩阵行字节跨度
    input logic [REG_WIDTH-1:0] k, // 输出矩阵列数
    input logic [REG_WIDTH-1:0] m, // 输出矩阵行数
    input logic [REG_WIDTH-1:0] ia_reuse_num, // 输入复用分组数量
    input logic                 is_mode, // 启用输入驻留转置布局
    input logic                 output_16bits, // 输出采用十六位数据格式
    input logic                 coalesce_enable, // 启用多矩阵块行合并
    input logic [4:0]           coalesce_cols, // 每个合并分组的矩阵块列数
    output logic                coalesce_group_start, // 开始当前合并分组
    output logic [4:0]          coalesce_row_tiles, // 当前合并分组的矩阵块行数

    output  logic                    oa_fifo_req, // FIFO 已准备可写回的结果
    output logic [$clog2(VLEN)-1:0] vec_valid_num_col, // 当前矩阵块最后一个有效列编号
    output logic [$clog2(VLEN)-1:0] vec_valid_num_row, // 当前矩阵块最后一个有效行编号

    output  logic                   output_valid, // FIFO 返回数据拍有效
    output  logic                   switch_row, // 当前数据拍结束输出行
    output logic                   output_ready, // 写回模块接收当前 FIFO 数据拍
    output  logic [BUS_WIDTH/8-1:0] output_mask, // 当前输出拍的有效字节掩码
    output  logic [BUS_WIDTH-1:0]   output_data, // 当前 FIFO 输出的数据拍

    output logic                        dma_start, // 发起 DMA 写回命令
    output logic                        dma_is_write, // DMA 命令为写入操作
    output logic                        dma_linear_read_mode, // DMA 采用线性读取布局
    output logic [REG_WIDTH-1:0]        dma_base_addr, // DMA 访问起始字节地址
    output logic [REG_WIDTH-1:0]        dma_row_stride, // DMA 行跨度
    output logic [REG_WIDTH-1:0]        dma_rows_to_read, // DMA 访问的行数
    output logic [7:0]                  dma_burst_len_m1, // DMA 突发传输拍数减一
    output logic                        dma_slot_id, // DMA 命令对应的存储位置
    output logic                        dma_use_16bits, // DMA 数据采用十六位格式
    output logic signed [REG_WIDTH-1:0] dma_lhs_zp, // DMA 数据转换的有符号零点
    output logic [BUS_WIDTH-1:0]        dma_src_wdata, // 送往 DMA 的写入数据
    output logic [BUS_WIDTH/8-1:0]      dma_src_wmask, // 送往 DMA 的写入字节掩码
    output logic                        dma_src_wvalid, // 送往 DMA 的数据有效
    input  logic                        dma_src_wready, // DMA 可接收写入数据
    input  logic                        dma_busy, // DMA 正在执行传输
    input  logic                        dma_done, // DMA 当前传输完成

    output logic write_done, // 当前输出矩阵写回完成
    output logic oa_calc_over // 当前计算分组的输出处理完成
);

    logic [31:0] fifo_rows, fifo_cols;
    assign fifo_rows = 32'(coalesce_row_tiles);
    assign fifo_cols = 32'(coalesce_cols);
    oa_writer #(.VLEN(VLEN), .DATA_WIDTH(DATA_WIDTH), .REG_WIDTH(REG_WIDTH),
                .BUS_WIDTH(BUS_WIDTH), .COUNT_WIDTH(COUNT_WIDTH), .ENABLE_IS_MODE(ENABLE_IS_MODE)) u_writer (
        .clk(clk),
        .rst_n(rst_n),
        .init_cfg(init_cfg),
        .write_oa_req(write_oa_req),
        .write_oa_granted(write_oa_granted),
        .dst_base(dst_base),
        .dst_row_stride_b(dst_row_stride_b),
        .k(k),
        .m(m),
        .ia_reuse_num(ia_reuse_num),
        .is_mode(is_mode),
        .output_16bits(output_16bits),
        .coalesce_enable(coalesce_enable),
        .coalesce_cols(coalesce_cols),
        .coalesce_group_start(coalesce_group_start),
        .coalesce_row_tiles(coalesce_row_tiles),
        .oa_fifo_req(oa_fifo_req),
        .vec_valid_num_col(vec_valid_num_col),
        .vec_valid_num_row(vec_valid_num_row),
        .output_valid(output_valid),
        .switch_row(switch_row),
        .output_ready(output_ready),
        .output_mask(output_mask),
        .output_data(output_data),
        .dma_start(dma_start),
        .dma_is_write(dma_is_write),
        .dma_linear_read_mode(dma_linear_read_mode),
        .dma_base_addr(dma_base_addr),
        .dma_row_stride(dma_row_stride),
        .dma_rows_to_read(dma_rows_to_read),
        .dma_burst_len_m1(dma_burst_len_m1),
        .dma_slot_id(dma_slot_id),
        .dma_use_16bits(dma_use_16bits),
        .dma_lhs_zp(dma_lhs_zp),
        .dma_src_wdata(dma_src_wdata),
        .dma_src_wmask(dma_src_wmask),
        .dma_src_wvalid(dma_src_wvalid),
        .dma_src_wready(dma_src_wready),
        .dma_busy(dma_busy),
        .dma_done(dma_done),
        .write_done(write_done),
        .oa_calc_over(oa_calc_over)
    );
    vec_s8_to_fifo #(.VLEN(VLEN), .BANKS(32), .BUS_WIDTH(BUS_WIDTH),
                         .ENABLE_TRANSPOSE(ENABLE_IS_MODE), .p_cyclic_storage(1'b1),
                         .p_precomputed_watermark(1'b1)) u_fifo (
        .clk(clk), .rst_n(rst_n),
        .in_valid(in_valid), .in_tile_done(in_tile_done), .in_vec_s8(in_vec_s8),
        .oa_fifo_req(oa_fifo_req), .transpose_mode(is_mode), .coalesce_enable(coalesce_enable),
        .coalesce_group_start(coalesce_group_start), .coalesce_rows(fifo_rows),
        .coalesce_cols(fifo_cols), .reserve_banks(reserve_banks),
        .i_ready_bank_threshold(i_ready_bank_threshold),
        .vec_valid_num_col(vec_valid_num_col), .vec_valid_num_row(vec_valid_num_row),
        .output_valid(output_valid), .output_ready(output_ready), .output_row_switch(switch_row),
        .output_mask(output_mask), .output_data(output_data), .fifo_full_flag(fifo_full_flag)
    );
endmodule
`default_nettype wire
