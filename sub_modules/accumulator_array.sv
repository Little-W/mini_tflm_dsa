module accumulator_array #(
    parameter SIZE = 16,
    parameter DATA_WIDTH = 32
) (
    input  wire                    clk,
    input  wire [  DATA_WIDTH-1:0] data_in       [0:SIZE-1],
    input  wire                    calc_done_i,
    input  wire                    input_valid_i,
    output wire [  DATA_WIDTH-1:0] data_out      [0:SIZE-1],
    output wire                    calc_done_o,
    input  wire [$clog2(SIZE)-1:0] valid_depth_i,
    input  wire                    is_init_data_i,
    output reg                     tile_calc_over_o
);

    wire [          SIZE:0] calc_done_chain;
    wire [          SIZE:0] input_valid_chain;
    wire [$clog2(SIZE)-1:0] valid_depth_chain  [0:SIZE];
    wire [          SIZE:0] is_init_data_chain;

    assign calc_done_chain[0]    = calc_done_i;
    assign calc_done_o           = calc_done_chain[SIZE];
    assign input_valid_chain[0]  = input_valid_i;
    assign valid_depth_chain[0]  = valid_depth_i;
    assign is_init_data_chain[0] = is_init_data_i;

    genvar i;
    generate
        for (i = 0; i < SIZE; i = i + 1) begin : accumulator_gen
            shift_accumulator #(
                .STAGE_NUM (SIZE),
                .DATA_WIDTH(DATA_WIDTH),
                .OUTPUT_POS(SIZE - 1 - i)
            ) acc_inst (
                .clk           (clk),
                .data_in       (data_in[i]),
                .calc_done_i   (calc_done_chain[i]),
                .input_valid_i (input_valid_chain[i]),
                .valid_depth   (valid_depth_chain[i]),
                .is_init_data_i(is_init_data_chain[i]),
                .data_out      (data_out[i]),
                .calc_done_o   (calc_done_chain[i+1]),
                .input_valid_o (input_valid_chain[i+1]),
                .valid_depth_o (valid_depth_chain[i+1]),
                .is_init_data_o(is_init_data_chain[i+1])
            );
        end
    endgenerate

    reg calc_done_o_d;
    always @(posedge clk) begin
        calc_done_o_d <= calc_done_o;
        tile_calc_over_o <= calc_done_o_d & ~calc_done_o; // 检测下降沿
    end

endmodule
