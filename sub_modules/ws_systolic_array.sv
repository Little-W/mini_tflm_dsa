// filepath: /home/etc/FPGA/tflm_ai_dsa/basic/ws_systolic_array.sv
module ws_systolic_array #(
    parameter int unsigned SIZE = 16
) (
    input  wire                              clk,
    input  wire                              store_weight_req,    // 权重加载请求，单个信号控制所有行
    input  wire signed [7:0]                 weight_in          [SIZE],
    input  wire signed [15:0]                data_in            [SIZE],
    input  wire signed [31:0]                sum_in             [SIZE],  // 累加器反馈输入
    output wire signed [31:0]                sum_out            [SIZE]
);

    // 中间信号
    wire signed [15:0] data_pipe   [SIZE][SIZE];
    wire signed [7:0]  weight_pipe [SIZE][SIZE];
    wire signed [31:0] sum_pipe    [SIZE][SIZE];

    genvar row, col;
    generate
        for (row = 0; row < SIZE; row++) begin : gen_row
            for (col = 0; col < SIZE; col++) begin : gen_col
                ws_systolic_cell ws_cell (
                    .clk(clk),
                    .store_weight_req(col == 0 ? store_weight_req : 1'b0),  // 所有行在第一列时都使用同一个信号
                    .weight_in(row == 0 ? weight_in[col] : weight_pipe[row-1][col]),
                    .data_in(col == 0 ? data_in[row] : data_pipe[row][col-1]),
                    .sum_in(row == 0 ? sum_in[col] : sum_pipe[row-1][col]),
                    .data_out(data_pipe[row][col]),
                    .weight_out(weight_pipe[row][col]),
                    .sum_out(sum_pipe[row][col])
                );
            end
        end
        for (genvar col = 0; col < SIZE; col++) begin : gen_sum_out
            assign sum_out[col] = sum_pipe[SIZE-1][col];
        end
    endgenerate

endmodule
