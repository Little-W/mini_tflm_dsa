`default_nettype none

module ws_systolic_cell #(
    parameter int unsigned DATA_IN_WIDTH = 16,  // s16 输入数据
    parameter int unsigned WEIGHT_WIDTH  = 8,   // s8  权重
    parameter int unsigned ACC_WIDTH     = 32,  // 累加/输出位宽，默认32位
    parameter bit p_exchange_weights = 1'b1
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

    // 工作权重和预取权重分别寄存，数据及部分和按原有周期传递。
    logic signed [DATA_IN_WIDTH-1:0] data_reg;
    logic signed [WEIGHT_WIDTH-1:0] weight_active;
    logic signed [WEIGHT_WIDTH-1:0] weight_prefetch;
    logic signed [ACC_WIDTH-1:0] sum_reg;
    logic [WEIGHT_WIDTH-1:0] weight_prefetch_data;
    logic weight_prefetch_enable;

`ifdef SYNTHESIS
`ifndef ASIC_SYNTHESIS
    localparam bit p_fpga_weight_mux = 1'b1;
`else
    localparam bit p_fpga_weight_mux = 1'b0;
`endif
`else
    localparam bit p_fpga_weight_mux = 1'b0;
`endif

    // 新权重写入优先于交换；相邻两个数据位共用查找表的两个输出。
    assign weight_prefetch_enable = store_weight_req || (p_exchange_weights && commit_weight);
    if (p_exchange_weights && p_fpga_weight_mux) begin : g_prefetch_selection
        for (genvar pair_index = 0; pair_index < WEIGHT_WIDTH/2; pair_index++) begin : g_pair
            logic [1:0] mux_i_active, mux_i_load;
            logic mux_i_select, mux_i_one;
            logic mux_o_lower, mux_o_upper;

            assign mux_i_active = weight_active[2*pair_index +: 2];
            assign mux_i_load = weight_in[2*pair_index +: 2];
            assign mux_i_select = store_weight_req;
            assign mux_i_one = 1'b1;
            assign weight_prefetch_data[2*pair_index] = mux_o_lower;
            assign weight_prefetch_data[2*pair_index+1] = mux_o_upper;
            LUT6_2 #(.INIT(64'hff00f0f0ccccaaaa)) u_mux (
                .I0(mux_i_active[0]), .I1(mux_i_load[0]),
                .I2(mux_i_active[1]), .I3(mux_i_load[1]),
                .I4(mux_i_select), .I5(mux_i_one),
                .O5(mux_o_lower), .O6(mux_o_upper)
            );
        end
        if ((WEIGHT_WIDTH % 2) != 0) begin : g_last_bit
            assign weight_prefetch_data[WEIGHT_WIDTH-1] = store_weight_req ?
                weight_in[WEIGHT_WIDTH-1] : weight_active[WEIGHT_WIDTH-1];
        end
    end else if (p_exchange_weights) begin : g_generic_selection
        assign weight_prefetch_data = store_weight_req ? weight_in : weight_active;
    end else begin : g_overwrite_selection
        // 完整装载模式直接覆盖预取寄存器，提交后仍保存刚装入的权重。
        assign weight_prefetch_data = weight_in;
    end

    (* use_dsp = "yes" *) wire signed [ACC_WIDTH-1:0] mac_result;
    wire signed [WEIGHT_WIDTH-1:0] selected_weight = weight_active;
    assign mac_result = data_reg * selected_weight + sum_reg;

    always_ff @(posedge clk) begin
        if (commit_weight) weight_active <= weight_prefetch;
        if (weight_prefetch_enable) weight_prefetch <= weight_prefetch_data;
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
