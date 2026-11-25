`timescale 1ns/1ps
module tb_kernel_buffer_equivalence #(
    parameter int SIZE = 16,
    parameter int DATA_WIDTH = 16,
    parameter int RANDOM_CYCLES = 100000,
    parameter bit FOUR_STATE = 1'b0
);
    localparam int INDEX_WIDTH = $clog2(SIZE);
    logic clk = 1'b0;
    always #5 clk = ~clk;
    logic rst_n, cache_flush, discard_head, load_start, row_valid, row_slot;
    logic load_done, done_slot, send_start;
    logic [INDEX_WIDTH-1:0] row_idx;
    logic signed [DATA_WIDTH-1:0] row_data [SIZE];
    logic load_slot_id, load_ready, load_commit, load_commit_slot, discard_ready;
    logic weight_data_valid, weight_sending_done, store_weight_req;
    logic ref_load_slot_id, ref_load_ready, ref_load_commit, ref_load_commit_slot, ref_discard_ready;
    logic ref_weight_data_valid, ref_weight_sending_done, ref_store_weight_req;
    wire signed [DATA_WIDTH-1:0] weight_out [SIZE], ref_weight_out [SIZE];
    logic [INDEX_WIDTH-1:0] forced_column;
    integer known_weight_samples = 0;
    bit response_active [2];
    int response_row [2], response_rows [2], completion_delay [2];
    int cycles, loaded, sends, discards, flushes, resets, overlap;
    int seed = 32'h71d5a214;

    kernel_loader_buffer #(.SIZE(SIZE), .DATA_WIDTH(DATA_WIDTH)) dut (
        .clk, .rst_n, .cache_flush, .discard_head, .load_start, .load_slot_id,
        .row_valid, .row_slot, .row_idx, .row_data, .load_done, .done_slot,
        .send_start, .load_ready, .load_commit, .load_commit_slot, .discard_ready,
        .weight_data_valid, .weight_sending_done, .store_weight_req, .weight_out
    );
    kernel_loader_buffer_ref #(.SIZE(SIZE), .DATA_WIDTH(DATA_WIDTH)) reference (
        .clk, .rst_n, .cache_flush, .discard_head, .load_start, .load_slot_id(ref_load_slot_id),
        .row_valid, .row_slot, .row_idx, .row_data, .load_done, .done_slot,
        .send_start, .load_ready(ref_load_ready), .load_commit(ref_load_commit),
        .load_commit_slot(ref_load_commit_slot), .discard_ready(ref_discard_ready),
        .weight_data_valid(ref_weight_data_valid), .weight_sending_done(ref_weight_sending_done),
        .store_weight_req(ref_store_weight_req), .weight_out(ref_weight_out)
    );

    task automatic clear_inputs;
        cache_flush = 0;
        discard_head = 0;
        load_start = 0;
        row_valid = 0;
        row_slot = 0;
        row_idx = 0;
        load_done = 0;
        done_slot = 0;
        send_start = 0;
        for (int column = 0; column < SIZE; column++) row_data[column] = '0;
    endtask

    task automatic clear_responses;
        for (int slot = 0; slot < 2; slot++) begin
            response_active[slot] = 0;
            response_row[slot] = 0;
            response_rows[slot] = 0;
            completion_delay[slot] = 0;
        end
    endtask

    task automatic tick;
        @(posedge clk);
        #1;
        cycles++;
        if ({load_slot_id, load_ready, load_commit, load_commit_slot, discard_ready,
             weight_data_valid, weight_sending_done, store_weight_req} !==
            {ref_load_slot_id, ref_load_ready, ref_load_commit, ref_load_commit_slot, ref_discard_ready,
             ref_weight_data_valid, ref_weight_sending_done, ref_store_weight_req}) begin
            $fatal(1, "Control mismatch cycle=%0d size=%0d", cycles, SIZE);
        end
        for (int column = 0; column < SIZE; column++) begin
            if (FOUR_STATE && !$isunknown(weight_out[column]) && weight_out[column] != 0)
                known_weight_samples++;
            if (weight_out[column] !== ref_weight_out[column]) begin
                $fatal(1, "Weight mismatch cycle=%0d lane=%0d actual=%0d expected=%0d",
                    cycles, column, weight_out[column], ref_weight_out[column]);
            end
        end
        if (row_valid && store_weight_req) overlap++;
        @(negedge clk);
        #1;
    endtask

    initial begin
        int slot;
        int random_value;
        random_value = $urandom(seed);
        rst_n = 0;
        clear_inputs();
        clear_responses();
        repeat (3) tick();
        rst_n = 1;
        for (int iteration = 0; iteration < RANDOM_CYCLES; iteration++) begin
            clear_inputs();
            rst_n = 1;
            random_value = $urandom_range(0, 2047);
            if (random_value < 3) begin
                rst_n = 0;
                resets++;
                clear_responses();
            end else if (random_value < 13) begin
                cache_flush = 1;
                flushes++;
                clear_responses();
            end else begin
                if (load_ready && $urandom_range(0, 3) != 0) begin
                    load_start = 1;
                    slot = int'(load_slot_id);
                    if (response_active[slot]) $fatal(1, "Reused active response slot");
                    response_active[slot] = 1;
                    response_row[slot] = 0;
                    response_rows[slot] = $urandom_range(1, SIZE);
                    completion_delay[slot] = $urandom_range(0, 6);
                    loaded++;
                end
                slot = $urandom_range(0, 1);
                if (!response_active[slot]) slot = 1 - slot;
                if (response_active[slot] && $urandom_range(0, 3) != 0) begin
                    if (response_row[slot] < response_rows[slot]) begin
                        row_valid = 1;
                        row_slot = 1'(slot);
                        row_idx = INDEX_WIDTH'(response_row[slot]);
                        for (int column = 0; column < SIZE; column++) begin
                            row_data[column] = DATA_WIDTH'($urandom());
                            if (FOUR_STATE && iteration % 11 == 0) row_data[column][iteration % DATA_WIDTH] = 1'bx;
                            if (FOUR_STATE && iteration % 13 == 0) row_data[column][iteration % DATA_WIDTH] = 1'bz;
                        end
                        response_row[slot]++;
                    end
                    if (response_row[slot] == response_rows[slot]) begin
                        if (completion_delay[slot] == 0) begin
                            load_done = 1;
                            done_slot = 1'(slot);
                            response_active[slot] = 0;
                        end else begin
                            completion_delay[slot]--;
                        end
                    end
                end
                if (weight_data_valid) begin
                    random_value = $urandom_range(0, 15);
                    if (random_value == 0) begin
                        discard_head = 1;
                        discards++;
                    end else if (random_value < 12) begin
                        send_start = 1;
                        sends++;
                    end
                end
            end
            tick();
        end
        if (FOUR_STATE) begin
            for (int sample = 0; sample < 20000; sample++) begin
                rst_n = (sample % 257 != 0);
                cache_flush = (sample % 137 == 0);
                discard_head = $urandom_range(0,3)==0;
                load_start = $urandom;
                row_valid = $urandom;
                row_slot = $urandom;
                row_idx = INDEX_WIDTH'($urandom);
                load_done = $urandom;
                done_slot = $urandom;
                send_start = $urandom;
                for (int column = 0; column < SIZE; column++) begin
                    row_data[column] = DATA_WIDTH'($urandom);
                    if (sample % 7 == 0) row_data[column][sample % DATA_WIDTH] = 1'bx;
                    if (sample % 11 == 0) row_data[column][sample % DATA_WIDTH] = 1'bz;
                end
                case (sample % 41)
                    0: row_valid = 1'bx;
                    1: load_start = 1'bz;
                    2: row_idx[sample % INDEX_WIDTH] = 1'bx;
                    3: row_idx[sample % INDEX_WIDTH] = 1'bz;
                    4: load_done = 1'bx;
                    5: send_start = 1'bz;
                    6: rst_n = 1'bx;
                    7: cache_flush = 1'bz;
                    default: ;
                endcase
                forced_column = INDEX_WIDTH'($urandom);
                if (sample % 3 == 0) forced_column[sample % INDEX_WIDTH] = 1'bx;
                if (sample % 5 == 0) forced_column[sample % INDEX_WIDTH] = 1'bz;
                if (sample == 10000) begin
                    force dut.output_column_q = forced_column;
                    force reference.output_column_q = forced_column;
                end
                tick();
            end
            if (known_weight_samples < 10000) $fatal(1, "Insufficient known weight data");
            $display("KERNEL_BUFFER_FOUR_STATE_PASS known_weight_samples=%0d", known_weight_samples);
        end
        if (sends < 100 || discards < 10 || overlap < 100 || flushes < 10 || resets < 10)
            $fatal(1, "Insufficient scenario coverage");
        $display("KERNEL_BUFFER_EQ_PASS cycles=%0d loaded=%0d sends=%0d discards=%0d flushes=%0d resets=%0d overlap=%0d",
            cycles, loaded, sends, discards, flushes, resets, overlap);
        $finish;
    end
endmodule
