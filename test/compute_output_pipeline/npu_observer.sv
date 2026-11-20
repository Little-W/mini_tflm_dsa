`default_nettype none

module compute_output_pipeline_observer #(parameter int SIZE=16)(
    input logic clk, rst_n,
    input logic signed [31:0] i_raw_data [SIZE], i_output_data [SIZE],
    input logic i_raw_valid, i_raw_tile_done, i_raw_group_last, i_raw_final,
    input logic i_final_wait, i_final_overlap,
    input logic i_output_valid, i_output_tile_done, i_group_complete
);
    logic signed [31:0] expected_data [SIZE];
    logic expected_valid, expected_tile_done, expected_final_complete;
    longint unsigned output_rows=0;
    longint unsigned checked_values=0;
    longint unsigned final_completions=0;
    longint unsigned intermediate_completions=0;

    always_ff @(posedge clk) expected_data <= i_raw_data;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            expected_valid <= 0;
            expected_tile_done <= 0;
            expected_final_complete <= 0;
        end else begin
            expected_valid <= i_raw_valid;
            expected_tile_done <= i_raw_tile_done;
            expected_final_complete <= i_final_wait ||
                (i_raw_group_last && i_raw_final && i_final_overlap);
        end
    end
    always @(posedge clk) begin
        if (rst_n) begin
            assert(i_output_valid == expected_valid);
            assert(i_output_tile_done == expected_tile_done);
            assert(i_group_complete ==
                (expected_final_complete || (i_raw_group_last && !i_raw_final)));
            if (i_output_valid) begin
                for (int lane=0;lane<SIZE;lane++) begin
                    assert(i_output_data[lane] == expected_data[lane]);
                    checked_values++;
                end
                output_rows++;
            end
            final_completions += 64'(expected_final_complete);
            intermediate_completions += 64'(i_raw_group_last && !i_raw_final);
        end
    end
    final $display("COMPUTE_OUTPUT_PIPELINE_PASS rows=%0d values=%0d final_completions=%0d intermediate_completions=%0d",
        output_rows, checked_values, final_completions, intermediate_completions);
endmodule

module compute_output_context_observer(
    input logic clk, rst_n, i_quant_init, i_output_valid, i_raw_valid
);
    longint unsigned initializations=0;
    always @(posedge clk) begin
        if (rst_n && i_quant_init) begin
            assert(!i_output_valid && !i_raw_valid);
            initializations++;
        end
    end
    final $display("COMPUTE_OUTPUT_CONTEXT_PASS initializations=%0d", initializations);
endmodule

bind compute_core compute_output_pipeline_observer #(.SIZE(SIZE)) u_output_pipeline_observer (
    .clk(clk), .rst_n(rst_n), .i_raw_data(ps_acc_out), .i_output_data(acc_data_out),
    .i_raw_valid(ps_acc_data_valid), .i_raw_tile_done(ps_tile_calc_over),
    .i_raw_group_last(ps_group_switch_d), .i_raw_final(ps_calc_done_d),
    .i_final_wait(final_group_complete_q), .i_final_overlap(final_output_overlap),
    .i_output_valid(acc_data_valid), .i_output_tile_done(tile_calc_over),
    .i_group_complete(partial_sum_calc_over)
);
bind npu_top compute_output_context_observer u_output_context_observer (
    .clk(clk), .rst_n(core_rst_n), .i_quant_init(exec_init_requant),
    .i_output_valid(acc_data_valid), .i_raw_valid(u_compute_core.ps_acc_data_valid)
);

`default_nettype wire
