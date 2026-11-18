module ws_systolic_cell #(
    parameter int unsigned DATA_IN_WIDTH = 16,  // s16 输入数据
    parameter int unsigned WEIGHT_WIDTH  = 8,   // s8  权重
    parameter int unsigned ACC_WIDTH     = 32   // 累加/输出位宽，默认32位
) (
    input  wire                            clk,
    input  wire                            commit_weight,
    input  wire                            store_weight_req,  // 置位时加载新权重
    input  wire signed [ WEIGHT_WIDTH-1:0] weight_in,
    input  wire signed [DATA_IN_WIDTH-1:0] data_in,
    input  wire signed [    ACC_WIDTH-1:0] sum_in,
    output wire signed [DATA_IN_WIDTH-1:0] data_out,
    output wire signed [ WEIGHT_WIDTH-1:0] weight_out,
    output wire signed [    ACC_WIDTH-1:0] sum_out
);

    // 寄存保持：权重驻留（WS），数据流水透传
    reg signed  [DATA_IN_WIDTH-1:0] data_reg;
    reg signed [WEIGHT_WIDTH-1:0] weight_active;
    reg signed [WEIGHT_WIDTH-1:0] weight_prefetch;
    reg signed  [    ACC_WIDTH-1:0] sum_reg;

    (* use_dsp = "yes" *) wire signed [ACC_WIDTH-1:0] mac_result;
    wire signed [WEIGHT_WIDTH-1:0] selected_weight = weight_active;
    assign mac_result = data_reg * selected_weight + sum_reg;

    always_ff @(posedge clk) begin
        if (commit_weight) weight_active <= weight_prefetch;
        if (store_weight_req) weight_prefetch <= weight_in;
        else if (commit_weight) weight_prefetch <= weight_active;
        data_reg <= data_in;
        sum_reg  <= sum_in;
    end

    // 输出透传到相邻单元
    assign data_out = data_reg;
    assign weight_out = weight_prefetch;

    // INT32 accumulation retains the low bits of the exact multiply-add.
    assign sum_out = mac_result;

endmodule
