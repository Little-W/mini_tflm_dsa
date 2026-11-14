/*
 * ia_buffer_wrapper - 输入激活缓冲区包装器
 * 模拟 32位宽 × 128位深 的 Memory Compiler 生成的 SRAM 时序
 * 
 * 特性：
 * - 单端口读写（不支持同时读写）
 * - 写使能控制的同步写入
 * - 读取有1周期延迟（寄存器输出）
 * - 字节写使能支持
 */

module ia_buffer_wrapper #(
    parameter int unsigned DATA_WIDTH = 32,   // 数据宽度
    parameter int unsigned DEPTH = 128,       // 深度
    parameter int unsigned ADDR_WIDTH = $clog2(DEPTH)
) (
    input  wire                      clk,
    input  wire                      rst_n,
    
    // 写接口
    input  wire                      wr_en,
    input  wire [ADDR_WIDTH-1:0]     wr_addr,
    input  wire [DATA_WIDTH-1:0]     wr_data,
    input  wire [DATA_WIDTH/8-1:0]   wr_mask,  // 字节写使能
    
    // 读接口
    input  wire                      rd_en,
    input  wire [ADDR_WIDTH-1:0]     rd_addr,
    output reg  [DATA_WIDTH-1:0]     rd_data
);

`ifdef ASIC_SRAM
    wire [DATA_WIDTH-1:0] macro_data;
    wire [DATA_WIDTH-1:0] bit_mask;
    reg read_valid;
    for (genvar byte_index=0; byte_index<DATA_WIDTH/8; byte_index=byte_index+1) begin : g_write_mask
        assign bit_mask[byte_index*8 +: 8] = {8{wr_mask[byte_index]}};
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) read_valid <= 1'b0;
        else if (rd_en) read_valid <= 1'b1;
    end
    assign rd_data = read_valid ? macro_data : {DATA_WIDTH{1'b0}};
    smic40_sram_1r1w #(.DATA_WIDTH(DATA_WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(ADDR_WIDTH)) u_sram (
        .clk(clk), .write_enable(wr_en), .write_address(wr_addr), .write_data(wr_data),
        .write_mask(bit_mask), .read_enable(rd_en && rst_n), .read_address(rd_addr), .read_data(macro_data));
`else
    // 内部存储阵列：不做复位清零，便于 FPGA 推断同步读 BRAM。
    (* ram_style = "block" *) reg [DATA_WIDTH-1:0] mem [DEPTH];
    
    // 读数据寄存器（模拟1周期延迟）
    reg [DATA_WIDTH-1:0] rd_data_reg;
    
    // 写操作（同步）
    always_ff @(posedge clk) begin
        if (wr_en) begin
            for (int i = 0; i < DATA_WIDTH/8; i++) begin
                if (wr_mask[i]) begin
                    mem[wr_addr][i*8 +: 8] <= wr_data[i*8 +: 8];
                end
            end
        end
    end
    
    // 读操作（1周期延迟，模拟SRAM时序）
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_data_reg <= '0;
        end else if (rd_en) begin
            rd_data_reg <= mem[rd_addr];
        end
    end
    
    assign rd_data = rd_data_reg;

`endif

endmodule
