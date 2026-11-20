module dip_weight_tb #(
    parameter int SIZE = 16,
    parameter int WEIGHT_WIDTH = 16
) (
    input logic clk, rst_n, cache_flush, discard_head,
    input logic load_start, row_valid, load_done, send_start,
    input logic [$clog2(SIZE)-1:0] row_idx,
    input logic signed [WEIGHT_WIDTH-1:0] row_data [SIZE],
    output logic load_ready, load_commit, discard_ready,
    output logic weight_data_valid, weight_sending_done, store_weight_req,
    output logic signed [WEIGHT_WIDTH-1:0] weight_out [SIZE],
    input logic weight_commit, input_valid,
    input logic signed [15:0] input_row [SIZE],
    input logic signed [31:0] initial_sum [SIZE],
    output logic output_valid,
    output wire signed [31:0] output_row [SIZE],
    output wire signed [WEIGHT_WIDTH-1:0] resident_weight [SIZE*SIZE],
    output wire [SIZE-1:0] row_select,
    output logic [SIZE-1:0] valid_pipe
);
    logic load_slot_id, response_slot;
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) response_slot <= 1'b0;
        else if (load_start && load_ready) response_slot <= load_slot_id;
    end
    kernel_loader_buffer #(.DATA_WIDTH(WEIGHT_WIDTH), .SIZE(SIZE)) dut (
        .clk(clk), .rst_n(rst_n), .cache_flush(cache_flush), .discard_head(discard_head),
        .load_start(load_start), .load_slot_id(load_slot_id),
        .row_valid(row_valid), .row_slot(response_slot), .row_idx(row_idx), .row_data(row_data),
        .load_done(load_done), .done_slot(response_slot), .send_start(send_start), .load_ready(load_ready),
        .load_commit(load_commit), .load_commit_slot(), .discard_ready(discard_ready),
        .weight_data_valid(weight_data_valid), .weight_sending_done(weight_sending_done),
        .store_weight_req(store_weight_req), .weight_out(weight_out)
    );
    always_ff @(posedge clk) begin
        if (!rst_n) valid_pipe <= '0;
        else valid_pipe <= (valid_pipe << 1) | SIZE'(input_valid);
    end
    assign output_valid = valid_pipe[SIZE-1];
    ws_systolic_array #(.SIZE(SIZE), .DATA_IN_WIDTH(16), .WEIGHT_WIDTH(WEIGHT_WIDTH), .p_exchange_weights(1'b0)) u_array (
        .clk, .rst_n, .weight_commit, .store_weight_req,
        .weight_in(weight_out), .data_in(input_row), .sum_in(initial_sum), .sum_out(output_row)
    );
    wire signed [31:0] reference_row [SIZE];
    ws_systolic_array #(.SIZE(SIZE), .DATA_IN_WIDTH(16), .WEIGHT_WIDTH(WEIGHT_WIDTH),
                       .p_exchange_weights(1'b1)) u_reference (
        .clk(clk), .rst_n(rst_n), .weight_commit(weight_commit), .store_weight_req(store_weight_req),
        .weight_in(weight_out), .data_in(input_row), .sum_in(initial_sum), .sum_out(reference_row)
    );
    integer loaded_rows;
    always_ff @(posedge clk) begin
        if (!rst_n) loaded_rows <= 0;
        else if (weight_commit) begin
            assert(loaded_rows == SIZE);
            loaded_rows <= store_weight_req ? 1 : 0;
        end else if (store_weight_req) begin
            assert(loaded_rows < SIZE);
            loaded_rows <= loaded_rows + 1;
        end
    end
    for (genvar column=0; column<SIZE; column++) begin : g_output_check
        always_ff @(posedge clk) if (rst_n && output_valid)
            assert(output_row[column] == reference_row[column]);
    end
    assign row_select = u_array.row_weight_select;
    for (genvar r=0; r<SIZE; ++r) begin : g_row
        for (genvar c=0; c<SIZE; ++c) begin : g_col
            assign resident_weight[r*SIZE+c] = u_array.gen_row[r].gen_col[c].ws_cell.selected_weight;
            always_ff @(posedge clk) if (rst_n && valid_pipe[r])
                assert(u_array.gen_row[r].gen_col[c].ws_cell.selected_weight ==
                       u_reference.gen_row[r].gen_col[c].ws_cell.selected_weight);
        end
    end
endmodule
