// 输入向量同时进入第零行，随后每行接收上一行的右邻列，列零环形连接到最后一列。
// 驻留权重采用 B[(row+column)%SIZE][column] 排列，部分和沿行方向传递。
module ws_systolic_array #(
    parameter int unsigned SIZE          = 16,
    parameter int unsigned DATA_IN_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH  = 16,
    parameter int unsigned ACC_WIDTH     = 32,
    parameter bit p_exchange_weights = 1'b1
) (
    input  wire                              clk, // 模块工作时钟。
    input  wire                              rst_n, // 低有效复位输入。
    input  wire                              weight_commit, // 提交已装入的权重块供计算使用。
    input  wire                              store_weight_req, // 使能本周期的权重装载。
    input  wire signed [WEIGHT_WIDTH-1:0]    weight_in [SIZE], // 本周期装入的逐列有符号权重。
    input  wire signed [DATA_IN_WIDTH-1:0]   data_in [SIZE], // 送入计算单元的有符号输入数据。
    input  wire signed [ACC_WIDTH-1:0]       sum_in [SIZE], // 各计算通道的累加初值。
    output wire signed [ACC_WIDTH-1:0]       sum_out [SIZE] // 各计算通道的乘加结果。
);
    wire signed [DATA_IN_WIDTH-1:0] data_pipe [SIZE][SIZE];
    wire signed [WEIGHT_WIDTH-1:0] weight_pipe [SIZE][SIZE];
    wire signed [ACC_WIDTH-1:0] sum_pipe [SIZE][SIZE];
    wire store_weight_req_col [SIZE];
    logic [SIZE-1:0] row_weight_select;
    logic [SIZE-1:0] row_buffer_phase;
    wire input_weight_select = row_weight_select[0] ^ weight_commit;
    wire weight_load_select = !input_weight_select;
    wire [SIZE-1:0] incoming_buffer_phase;
    assign incoming_buffer_phase[0] = input_weight_select;
    for(genvar phase_row=1;phase_row<SIZE;phase_row++)begin:g_buffer_phase
        assign incoming_buffer_phase[phase_row] = row_weight_select[phase_row-1];
    end
    // 保存各行的缓冲相位，复位后在下次分块装载前恢复缓冲顺序。
    always_ff @(posedge clk) begin
        if (!rst_n) row_buffer_phase <= '0;
        else row_buffer_phase <= incoming_buffer_phase;
    end

    // 选择信号与数据及部分和经过相同的逐行寄存，
    // 提交时选择第零行新输入使用的完整权重块。
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) row_weight_select <= '0;
        else begin
            row_weight_select[0] <= input_weight_select;
            for (int row=1; row<SIZE; row++)
                row_weight_select[row] <= row_weight_select[row-1];
        end
    end

    generate
        for (genvar column=0; column<SIZE; column++) begin : gen_store_weight_buf
            assign store_weight_req_col[column] = store_weight_req;
        end
        for (genvar row=0; row<SIZE; row++) begin : gen_row
            wire incoming_weight_select;
            if (row == 0) begin : g_select_input
                assign incoming_weight_select = input_weight_select;
            end else begin : g_select_pipeline
                assign incoming_weight_select = row_weight_select[row-1];
            end
            // 该行在提交边沿获得加载使能，自底行开始装入的权重逐行传播。
            // 已完成提交的行可接收下一块权重，同时保留前一输入流所需的活动权重。
            wire row_load_enable = rst_n && (incoming_weight_select != weight_load_select);
            wire row_commit_weight = rst_n ?
                incoming_weight_select != row_buffer_phase[row] : row_buffer_phase[row];
            for (genvar column=0; column<SIZE; column++) begin : gen_col
                wire signed [DATA_IN_WIDTH-1:0] input_value;
                wire signed [WEIGHT_WIDTH-1:0] stationary_value;
                wire signed [ACC_WIDTH-1:0] partial_sum;
                if (row == 0) begin : g_input
                    assign input_value = data_in[column];
                    assign stationary_value = weight_in[column];
                    assign partial_sum = sum_in[column];
                end else begin : g_diagonal
                    assign input_value = data_pipe[row-1][(column+1)%SIZE];
                    assign stationary_value = weight_pipe[row-1][column];
                    assign partial_sum = sum_pipe[row-1][column];
                end
                ws_systolic_cell #(
                    .DATA_IN_WIDTH(DATA_IN_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
                    .ACC_WIDTH(ACC_WIDTH), .p_exchange_weights(p_exchange_weights)
                ) ws_cell (
                    .clk(clk), .commit_weight(row_commit_weight),
                    .store_weight_req(store_weight_req_col[column] && row_load_enable),
                    .weight_in(stationary_value), .data_in(input_value),
                    .sum_in(partial_sum), .data_out(data_pipe[row][column]),
                    .weight_out(weight_pipe[row][column]), .sum_out(sum_pipe[row][column])
                );
            end
        end
        for (genvar column=0; column<SIZE; column++) begin : gen_sum_out
            assign sum_out[column] = sum_pipe[SIZE-1][column];
        end
    endgenerate

endmodule
