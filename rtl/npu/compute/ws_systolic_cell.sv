`default_nettype none

// 计算单元保留独立综合边界，逐行权重寄存与本单元乘加共同实现。
`ifdef XILINX_FPGA
(* KEEP_HIERARCHY = "yes" *)
`endif
module ws_systolic_cell #(
    parameter int unsigned DATA_IN_WIDTH = 16,  // s16 输入数据
    parameter int unsigned WEIGHT_WIDTH  = 8,   // s8  权重
    parameter int unsigned ACC_WIDTH     = 32,  // 累加/输出位宽，默认32位
    parameter bit p_exchange_weights = 1'b1
) (
    input  logic                            clk,
    input  logic                            commit_weight,
    input  logic                            store_weight_req,  // 置位时加载新权重
    input  logic signed [ WEIGHT_WIDTH-1:0] weight_in,
    input  logic signed [DATA_IN_WIDTH-1:0] data_in,
    input  logic signed [    ACC_WIDTH-1:0] sum_in,
    output logic signed [DATA_IN_WIDTH-1:0] data_out,
    output logic signed [ WEIGHT_WIDTH-1:0] weight_out,
    output logic signed [    ACC_WIDTH-1:0] sum_out
);

    // 工作权重和预取权重分别寄存，数据及部分和按原有周期传递。
    logic signed [DATA_IN_WIDTH-1:0] data_reg;
    logic signed [WEIGHT_WIDTH-1:0] weight_active;
    // 权重输出保留寄存节点，各行只在装载边沿接收上一行的权重。
`ifdef XILINX_FPGA
    (* KEEP = "true" *)
`endif
    logic signed [WEIGHT_WIDTH-1:0] weight_prefetch;
    logic signed [ACC_WIDTH-1:0] sum_reg;
    logic [WEIGHT_WIDTH-1:0] weight_prefetch_data;
    logic weight_prefetch_enable;

    logic signed [WEIGHT_WIDTH-1:0] selected_weight;

    // 预取写入优先于权重交换，覆盖模式只接收外部权重。
    assign weight_prefetch_enable = store_weight_req || (p_exchange_weights && commit_weight);
    if (p_exchange_weights) begin : g_prefetch_selection
        assign weight_prefetch_data = store_weight_req ? weight_in : weight_active;
    end else begin : g_overwrite_selection
        assign weight_prefetch_data = weight_in;
    end

    (* use_dsp = "yes" *) logic signed [ACC_WIDTH-1:0] mac_result;
    assign selected_weight = weight_active;
    assign mac_result = data_reg * selected_weight + sum_reg;

    always_ff @(posedge clk) begin
        if (commit_weight) begin
            weight_active <= weight_prefetch;
        end
        if (weight_prefetch_enable) begin
            weight_prefetch <= weight_prefetch_data;
        end
        data_reg <= data_in;
        sum_reg  <= sum_in;
    end

    // 输出透传到相邻单元
    assign data_out = data_reg;
    assign weight_out = weight_prefetch;

    // 累加结果保留完整乘加运算的低 ACC_WIDTH 位。
    assign sum_out = mac_result;

endmodule

`default_nettype wire
