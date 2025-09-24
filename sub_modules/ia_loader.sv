/*
 * ia_loader 输入激活加载控制器设计说明
 * ------------------------------------------------------------
 * 1. 双缓冲区交替运行：
 *    - 设计采用双缓冲区（如 buffer0 和 buffer1），每次只允许一个缓冲区向脉动阵列输出数据，另一个缓冲区则用于接收新的输入激活数据。
 *    - 当缓冲区A正在输出数据时，缓冲区B可以被 mma_controller 写入新数据。输出完成后，缓冲区角色切换，实现无缝数据加载和输出，提高数据吞吐率。
 *
 * 2. load_ia_trigger 触发机制：
 *    - load_ia_trigger 是一个单拍有效的触发信号。每次有效时，模块应寄存当前的 valid_row_num（有效输入行数）和 is_last_tile（是否为最后一个tile）。
 *    - 这些信息用于后续数据输出和计算控制。
 *
 * 3. 行数据输出与有效信号：
 *    - 每当有一行向量输出到脉动阵列时，应同时拉高 ia_row_valid，表示当前行数据有效。
 *    - 输出数据通过 ia_out 总线传递。
 *
 * 4. 最后一行tile处理：
 *    - 如果当前输出的是最后一个tile（is_last_tile为高），则在输出行数据的同时，还需拉高 ia_calc_done，通知后续模块进行部分和累加，得到最终结果。
 */

// 输入激活加载控制器，双缓冲区交替向脉动阵列加载输入数据
module ia_loader #(
    parameter int unsigned DATA_WIDTH = 16,   // 单个输入数据宽度
    parameter int unsigned SIZE = 16,         // 输入阵列大小
    parameter int unsigned BUS_WIDTH = 32     // 总线宽度
) (
    // 时钟与复位
    input  wire                        clk,               // 时钟信号
    input  wire                        rst_n,             // 异步复位，低有效

    // 输入激活加载控制
    input  wire                        load_ia_trigger,   // 触发加载输入激活
    input  wire [$clog2(SIZE)-1:0]     valid_row_num,     // 当前有效输入行数
    input  wire                        is_last_tile,      // 当前输入的行已经是最后一个tile，部分和将累加得到最终结果

    // 输入写入接口，支持地址映射和写字节使能
    input  wire [$clog2(SIZE*SIZE)-1:0] ia_wr_addr,       // 输入写入地址
    input  wire                        ia_wr_en,          // 输入写使能
    input  wire [BUS_WIDTH-1:0]        ia_data_in,        // 外部输入激活数据（总线位宽）

    // 零点偏移相关
    input  wire signed [31:0]          lhs_offset,        // 输入激活零点偏移
    input  wire                        ia_use_offset,     // 输入激活零点偏移使能
    input  wire                        use_16bits,        // 输入数据类型指示，1为s16，0为s8

    // 输出信号
    output reg                         ia_loading_done,   // trigger后，一整个tile已经输出完毕
    output reg                         ia_row_valid,      // 当前行数据有效
    output reg                         ia_calc_done,      // 当前输入的行已经是最后一个tile，部分和将累加得到最终结果
    output reg signed [DATA_WIDTH-1:0] ia_out [SIZE]      // 输出到脉动阵列的输入数据
);

endmodule
