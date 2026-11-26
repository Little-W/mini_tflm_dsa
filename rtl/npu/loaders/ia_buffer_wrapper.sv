`default_nettype none

/*
 * ia_buffer_wrapper - 输入激活缓冲区包装器
 * 默认提供 32 位宽、128 项的同步存储
 * 
 * 特性：
 * - 独立的写端口和同步读端口
 * - 写使能控制的同步写入
 * - 读取有1周期延迟（寄存器输出）
 * - 字节写使能支持
 */

module ia_buffer_wrapper #(
    parameter int unsigned DATA_WIDTH = 32,   // 数据宽度
    parameter int unsigned DEPTH = 128,       // 深度
    parameter int unsigned ADDR_WIDTH = $clog2(DEPTH)
) (
    input  wire logic                      clk /* 工作时钟 */,
    input  wire logic                      rst_n /* 低有效复位 */,
    
    // 写接口
    input  wire logic                      wr_en /* 使能输入缓存写入 */,
    input  wire logic [ADDR_WIDTH-1:0]     wr_addr /* 当前写入的输入缓存地址 */,
    input  wire logic [DATA_WIDTH-1:0]     wr_data /* 写入输入缓存的数据字 */,
    input  wire logic [DATA_WIDTH/8-1:0]   wr_mask,  // 字节写使能
    
    // 读接口
    input  wire logic                      rd_en /* 使能输入缓存同步读取 */,
    input  wire logic [ADDR_WIDTH-1:0]     rd_addr /* 当前读取的输入缓存地址 */,
    output logic [DATA_WIDTH-1:0]     rd_data /* 输入缓存最近一次有效读取结果 */
);

    // 复位清除读出有效状态；存储内容保留，首个同步读取后更新输出。
    logic read_valid;
    logic storage_i_wr_en, storage_i_rd_en;
    logic [ADDR_WIDTH-1:0] storage_i_wr_addr, storage_i_rd_addr;
    logic [DATA_WIDTH-1:0] storage_i_wr_data, storage_o_rd_data;
    assign storage_i_wr_en = wr_en;
    assign storage_i_wr_addr = wr_addr;
    assign storage_i_wr_data = wr_data;
    assign storage_i_rd_en = rd_en && rst_n;
    assign storage_i_rd_addr = rd_addr;
    assign rd_data = read_valid ? storage_o_rd_data : '0;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_valid <= 1'b0;
        end else if (rd_en) begin
            read_valid <= 1'b1;
        end
    end

`ifdef ASIC_SRAM
    logic [DATA_WIDTH-1:0] storage_i_wr_mask;
    for (genvar byte_index = 0; byte_index < DATA_WIDTH/8; byte_index++) begin : g_write_mask
        assign storage_i_wr_mask[byte_index*8 +: 8] = {8{wr_mask[byte_index]}};
    end
    smic40_sram_1r1w #(
        .DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)
    ) u_storage (
        .clk(clk), .write_enable(storage_i_wr_en), .write_address(storage_i_wr_addr),
        .write_data(storage_i_wr_data), .write_mask(storage_i_wr_mask),
        .read_enable(storage_i_rd_en), .read_address(storage_i_rd_addr), .read_data(storage_o_rd_data)
    );
`else
    logic [DATA_WIDTH/8-1:0] storage_i_wr_mask;
    assign storage_i_wr_mask = wr_mask;
    regfile #(
        .p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_addr_width(ADDR_WIDTH), .p_write_unit(8)
    ) u_storage (
        .clk(clk), .i_wr_en(storage_i_wr_en), .i_wr_addr(storage_i_wr_addr),
        .i_wr_data(storage_i_wr_data), .i_wr_mask(storage_i_wr_mask),
        .i_rd_en(storage_i_rd_en), .i_rd_addr(storage_i_rd_addr), .o_rd_data(storage_o_rd_data)
    );
`endif

endmodule

`default_nettype wire
