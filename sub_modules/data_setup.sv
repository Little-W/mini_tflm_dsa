module data_setup #(
    parameter DATA_WIDTH = 16,
    parameter DATA_NUM   = 16
) (
    input  wire                  clk,
    input  wire [DATA_WIDTH-1:0] data_in [DATA_NUM],
    output wire [DATA_WIDTH-1:0] data_out[DATA_NUM],

    // 控制信号延迟链
    input  wire input_valid_i,  // 输入有效信号
    input  wire calc_done_i,    // 计算完成信号
    input  wire is_init_data_i, // 初始化信号
    output wire input_valid_o,  // 输出有效信号（延迟SIZE-1周期）
    output wire calc_done_o,    // 输出计算完成信号（延迟SIZE-1周期）
    output wire is_init_data_o  // 输出初始化信号（延迟SIZE-1周期）
);
    genvar i, j;
    generate
        if (DATA_NUM > 0) begin
            // 数据延迟链
            for (i = 1; i < DATA_NUM; i = i + 1) begin : gen_shift_chain
                // 定义移位寄存器
                reg [DATA_WIDTH-1:0] shift_reg[0:i-1];
                assign data_out[i] = shift_reg[i-1];

                integer k;
                always @(posedge clk) begin
                    shift_reg[0] <= data_in[i];
                    for (k = 1; k <= i; k = k + 1) begin
                        shift_reg[k] <= shift_reg[k-1];
                    end
                end
            end

            // 控制信号延迟链（延迟SIZE-1周期）
            if (DATA_NUM > 1) begin : gen_control_delay
                reg input_valid_shift[0:DATA_NUM-2];
                reg calc_done_shift  [0:DATA_NUM-2];
                reg is_init_data_shift[0:DATA_NUM-2];

                always @(posedge clk) begin
                    input_valid_shift[0]   <= input_valid_i;
                    calc_done_shift[0]     <= calc_done_i;
                    is_init_data_shift[0]  <= is_init_data_i;
                    for (integer m = 1; m < DATA_NUM - 1; m = m + 1) begin
                        input_valid_shift[m]   <= input_valid_shift[m-1];
                        calc_done_shift[m]     <= calc_done_shift[m-1];
                        is_init_data_shift[m]  <= is_init_data_shift[m-1];
                    end
                end

                assign input_valid_o   = input_valid_shift[DATA_NUM-2];
                assign calc_done_o     = calc_done_shift[DATA_NUM-2];
                assign is_init_data_o  = is_init_data_shift[DATA_NUM-2];
            end else begin
                // 如果SIZE=1，直接输出
                assign input_valid_o   = input_valid_i;
                assign calc_done_o     = calc_done_i;
                assign is_init_data_o  = is_init_data_i;
            end
        end
        assign data_out[0] = data_in[0];
    endgenerate
endmodule
