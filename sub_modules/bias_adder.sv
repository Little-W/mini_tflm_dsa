/*
 * bias_adder 偏置加法控制器设计说明
 * ------------------------------------------------------------
 * 1. 双缓冲区交替运行：
 *    - 设计采用双缓冲区（如 buffer0 和 buffer1），每次只允许一个缓冲区向加法器输出偏置数据，另一个缓冲区则用于接收新的偏置数据。
 *    - 当缓冲区A正在输出数据时，缓冲区B可以被外部写入新数据。输出完成后，缓冲区角色切换，实现无缝数据加载和输出，提高数据吞吐率。
 *
 * 2. init_bias_cfg 触发机制：
 *    - init_bias_cfg 是一个单拍有效的触发信号。每次有效时，模块应寄存当前的 valid_row_num（有效偏置行数）和 need_bias（是否需要偏置）。
 *    - 这些信息用于后续偏置输出和加法控制。
 *
 * 3. 偏置数据输出与有效信号：
 *    - 每当有一行偏置输出到加法器时，应同时拉高 bias_loading_done，表示当前偏置数据有效。
 *    - 输出数据通过内部逻辑传递。
 *
 * 4. 偏置加法处理：
 *    - 如果 need_bias 为高，则在数据输入时进行偏置加法，将 data_in 与偏置相加得到 data_out。
 *    - 如果 need_bias 为低，则直接输出 data_in。
 */

// 偏置加法控制器，双缓冲区交替加载偏置数据并进行加法运算
module bias_adder #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned BUS_WIDTH = 32     // 总线宽度
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 偏置加载控制
    input  wire                        init_bias_cfg,     // 触发加载偏置的相关参数
    input  wire [$clog2(SIZE)-1:0]     valid_row_num,     // 当前有效偏置行数
    input  wire                        need_bias,         // 是否需要偏置

    // 偏置写入接口，支持地址映射和写字节使能
    input  wire [$clog2(SIZE)-1:0]     bias_wr_addr,      // 偏置写入地址
    input  wire                        bias_wr_en,        // 偏置写使能
    input  wire [BUS_WIDTH-1:0]        bias_data_in,      // 外部偏置数据（总线位宽）

    // 输入数据
    input  wire [  DATA_WIDTH-1:0]     data_in       [SIZE],
    input  wire                        calc_done_i,
    input  wire [$clog2(SIZE)-1:0]     valid_depth_i,
    input  wire                        is_init_data_i,

    // 输出信号
    output reg                         bias_loading_done, // trigger后，一整个tile已经输出完毕
    output wire [  DATA_WIDTH-1:0]     data_out      [SIZE],
    output wire                        output_valid_o,
    output wire [$clog2(SIZE)-1:0]     valid_depth_o,
    output wire                        is_init_data_o
);

endmodule