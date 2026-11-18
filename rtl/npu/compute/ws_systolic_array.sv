// Diagonal-input, permuted-stationary array. A complete input vector enters
// row zero in one cycle. Each subsequent row receives the previous row's
// next column, including the wrap from column zero to column SIZE-1.
// The stationary tile is B[(row+column)%SIZE][column]; sums move vertically.
module ws_systolic_array #(
    parameter int unsigned SIZE          = 16,
    parameter int unsigned DATA_IN_WIDTH = 16,
    parameter int unsigned WEIGHT_WIDTH  = 16,
    parameter int unsigned ACC_WIDTH     = 32
) (
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              weight_commit,
    input  wire                              store_weight_req,
    input  wire signed [WEIGHT_WIDTH-1:0]    weight_in [SIZE],
    input  wire signed [DATA_IN_WIDTH-1:0]   data_in [SIZE],
    input  wire signed [ACC_WIDTH-1:0]       sum_in [SIZE],
    output wire signed [ACC_WIDTH-1:0]       sum_out [SIZE]
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
    // Preserve the physical bank order across reset before the next tile load.
    always_ff @(posedge clk) begin
        if (!rst_n) row_buffer_phase <= '0;
        else row_buffer_phase <= incoming_buffer_phase;
    end

    // The selector follows the same registers as data and partial sums.
    // A commit selects the completed tile for the next row entering row zero.
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
`ifdef SYNTHESIS
`ifndef ASIC_SYNTHESIS
            (* DONT_TOUCH = "TRUE" *)
            LUT1 #(.INIT(2'b10)) u_store_weight_buf (
                .I0(store_weight_req), .O(store_weight_req_col[column])
            );
`else
            assign store_weight_req_col[column] = store_weight_req;
`endif
`else
            assign store_weight_req_col[column] = store_weight_req;
`endif
        end
        for (genvar row=0; row<SIZE; row++) begin : gen_row
            wire incoming_weight_select;
            if (row == 0) begin : g_select_input
                assign incoming_weight_select = input_weight_select;
            end else begin : g_select_pipeline
                assign incoming_weight_select = row_weight_select[row-1];
            end
            // A bank becomes writable on the edge that selects the other bank.
            // Bottom-first loading needs only the final SIZE-row shifts here;
            // earlier shifts may wait for the preceding input stream to leave.
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
                    .ACC_WIDTH(ACC_WIDTH)
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
