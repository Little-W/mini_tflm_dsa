module shift_accumulator #(
    parameter STAGE_NUM  = 16,
    parameter DATA_WIDTH = 32,
    parameter OUTPUT_POS = STAGE_NUM - 1  // 输出数据在移位寄存器中的位置
) (
    input  wire                         clk,
    input  wire signed [DATA_WIDTH-1:0] data_in,
    input  wire                         calc_done_i, // 当前输入已经是tile最后的数据，累加该数据后部分和将得到最终结果
    input  wire                         input_valid_i,  // 新增输入有效信号
    input  wire [$clog2(STAGE_NUM)-1:0] valid_depth_i, // 有效深度输入，表示当前移位寄存器的有效数据深度
    input  wire                         is_init_data_i, // 新增初始化数据输入信号
    output wire signed [DATA_WIDTH-1:0] data_out,
    output wire                         calc_done_o,
    output wire                         input_valid_o,   // 新增输出端口
    output wire                         is_init_data_o,  // 新增输出端口
    output wire [$clog2(STAGE_NUM)-1:0] valid_depth_o // 新增输出端口
);

    reg signed [DATA_WIDTH-1:0] shift_reg[0:STAGE_NUM-1];
    reg                         calc_done_reg;
    reg [STAGE_NUM-1:0]         input_valid_shift_reg;  // input_valid移位寄存器
    reg [STAGE_NUM-1:0]         is_init_data_shift_reg; // is_init_data移位寄存器
    reg [$clog2(STAGE_NUM)-1:0] valid_depth_shift_reg[STAGE_NUM-1:0]; // 新增valid_depth移位寄存器
    integer i;

    always @(posedge clk) begin
        if (input_valid_i) begin  // 仅在输入有效时更新
            // 移位寄存器
            for (i = STAGE_NUM - 1; i > 0; i = i - 1) begin
                shift_reg[i] <= shift_reg[i-1];
                valid_depth_shift_reg[i] <= valid_depth_shift_reg[i-1];
            end
            // 新增初始化数据逻辑
            if (is_init_data_i) begin
                shift_reg[0] <= data_in;
            end else begin
                reg signed [DATA_WIDTH:0] sum;
                sum = shift_reg[valid_depth_i] + data_in;
                // 对加法结果进行限幅
                if (sum > (1 << DATA_WIDTH - 1) - 1) begin
                    shift_reg[0] <= ((1 << DATA_WIDTH - 1) - 1);
                end else if (sum < -(1 << DATA_WIDTH - 1)) begin
                    shift_reg[0] <= -(1 << DATA_WIDTH - 1);
                end else begin
                    shift_reg[0] <= sum[DATA_WIDTH-1:0];
                end
            end
            valid_depth_shift_reg[0] <= valid_depth_i;
            // calc_done信号寄存
            calc_done_reg <= calc_done_i;
            // input_valid信号移位
            input_valid_shift_reg <= {input_valid_shift_reg[STAGE_NUM-2:0], input_valid_i};
            // is_init_data信号移位
            is_init_data_shift_reg <= {is_init_data_shift_reg[STAGE_NUM-2:0], is_init_data_i};
        end
    end

    assign data_out        = shift_reg[OUTPUT_POS];
    assign calc_done_o     = calc_done_reg;
    assign input_valid_o   = input_valid_shift_reg[0];  // 串行传递input_valid信号
    assign is_init_data_o  = is_init_data_shift_reg[0]; // 串行传递is_init_data信号
    assign valid_depth_o   = valid_depth_shift_reg[0]; // 串行传递valid_depth信号

endmodule
