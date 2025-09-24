// 权重加载控制器
// 模块内部权重按照列主序展平存放，输出时按照行输出
module kernel_loader #(
    parameter int unsigned DATA_WIDTH = 8,      // 权重数据宽度
    parameter int unsigned SIZE = 16,           // 阵列大小
    parameter int unsigned BUS_WIDTH = 32       // 总线宽度
) (
    // 时钟与复位
    input  wire clk,                            // 时钟信号
    input  wire rst_n,                          // 异步复位，低有效

    // 权重加载控制
    input  wire load_weight_trigger,            // 触发加载权重

    // 外部输入数据
    input  wire [BUS_WIDTH-1:0] weight_data_in, // 外部输入权重数据（总线位宽）

    // 有效权重/偏置尺寸
    input  wire [$clog2(SIZE)-1:0] valid_row_num, // 当前有效权重行数
    input  wire [$clog2(SIZE)-1:0] valid_col_num, // 当前有效权重列数

    // 权重写入接口
    input  wire [$clog2(SIZE*SIZE)-1:0] weight_wr_addr, // 权重写入地址
    input  wire weight_wr_en,                           // 权重写使能

    // 输出信号
    output reg  weight_loading_done,                    // 一次加载完成
    output reg  store_weight_req,                        // 控制脉动阵列权重加载
    output reg  signed [DATA_WIDTH-1:0] weight_out[SIZE] // 输出到脉动阵列的权重
);

endmodule
