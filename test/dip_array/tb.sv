module dip_array_tb #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned DATA_IN_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH = 16
) (
    input logic clk, rst_n, weight_commit, store_weight_req, input_valid,
    input logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE],
    input logic signed [DATA_IN_WIDTH-1:0] data_in [SIZE],
    input logic signed [31:0] sum_in [SIZE],
    output wire signed [31:0] sum_out [SIZE],
    output logic [SIZE-1:0] valid_rows,
    output wire [SIZE-1:0] row_select, row_load_enable,
    output wire signed [WEIGHT_WIDTH-1:0] selected_weight [SIZE*SIZE]
);
    ws_systolic_array #(
        .SIZE(SIZE), .DATA_IN_WIDTH(DATA_IN_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH)
    ) u_array (
        .clk, .rst_n, .weight_commit, .store_weight_req,
        .weight_in, .data_in, .sum_in, .sum_out
    );
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) valid_rows <= '0;
        else valid_rows <= (valid_rows << 1) | SIZE'(input_valid);
    end
    assign row_select = u_array.row_weight_select;
    for (genvar row=0; row<SIZE; row++) begin : g_row
        assign row_load_enable[row] = u_array.gen_row[row].row_load_enable;
        for (genvar column=0; column<SIZE; column++) begin : g_column
            assign selected_weight[row*SIZE+column] =
                u_array.gen_row[row].gen_col[column].ws_cell.selected_weight;
        end
    end
endmodule
