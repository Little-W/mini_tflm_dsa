`timescale 1ns / 1ps

module tb_compute_core;
    import test_params_pkg::*;
    localparam int unsigned NUM_SEG = (NUM_K + SIZE - 1) / SIZE;
`ifdef GEMPACT_PS_COMPRESS
    localparam bit COMPRESSED_STORE = SIZE == 16;
`else
    localparam bit COMPRESSED_STORE = 1'b0;
`endif
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    always #5 clk = ~clk;
    tb_compute_core_if tb_if(clk);

    logic signed [15:0] weight_mem_raw [SIZE * NUM_K];
    logic signed [15:0] ia_mem_raw [SIZE * NUM_K];
    logic signed [31:0] bias_mem [SIZE];
    logic signed [31:0] exp_mem [SIZE * SIZE];
    logic signed [31:0] expected_tile [NUM_SEG][SIZE][SIZE];
    int input_rows [NUM_SEG], partial_rows [NUM_SEG];
    int completions [NUM_SEG], frame_completions [NUM_SEG];
    int active_seg = -1, final_rows = 0;
    longint unsigned partial_checks = 0, replay_checks = 0, output_checks = 0;
    string data_dir;
    bit finished = 1'b0;
    integer force_raw_arg;

    compute_core_test #(.SIZE(SIZE)) dut (
        .clk, .rst_n,
        .weight_commit(tb_if.weight_commit), .store_weight_req(tb_if.store_weight_req),
        .weight_in(tb_if.weight_in), .ia_vec_in(tb_if.ia_vec_in),
        .ia_row_valid(tb_if.ia_row_valid), .ia_tile_start(tb_if.ia_tile_start),
        .ia_calc_done(tb_if.ia_calc_done), .ia_is_init_data(tb_if.ia_is_init_data),
        .ia_l1_switch(tb_if.ia_l1_switch), .ia_sending_done(tb_if.ia_sending_done),
        .send_ia_trigger(tb_if.send_ia_trigger),
        .ps_store_cfg_valid(tb_if.ps_store_cfg_valid), .ps_frame_request(tb_if.ps_frame_request),
        .ps_frame_init(tb_if.ps_frame_init), .ps_frame_final(tb_if.ps_frame_final),
        .ps_force_raw(tb_if.ps_force_raw), .bias_sleep(tb_if.bias_sleep), .bias_in(tb_if.bias_in),
        .acc_data_out(tb_if.acc_data_out), .acc_data_valid(tb_if.acc_data_valid),
        .partial_sum_calc_over(tb_if.partial_sum_calc_over), .tile_calc_over(tb_if.tile_calc_over),
        .ps_frame_ready(tb_if.ps_frame_ready), .ps_frame_complete(tb_if.ps_frame_complete),
        .ps_capacity_fault(tb_if.ps_capacity_fault)
    );

    function automatic logic signed [15:0] activation(input int row, input int k);
        return k < NUM_K ? ia_mem_raw[row * NUM_K + k] : 16'sd0;
    endfunction

    function automatic logic signed [15:0] coefficient(input int k, input int column);
        return k < NUM_K ? weight_mem_raw[column * NUM_K + k] : 16'sd0;
    endfunction

    task automatic reference_values();
        logic signed [31:0] accumulator;
        for (int row = 0; row < SIZE; row++) begin
            for (int column = 0; column < SIZE; column++) begin
                accumulator = bias_mem[column];
                for (int segment = 0; segment < NUM_SEG; segment++) begin
                    for (int k = 0; k < SIZE; k++)
                        accumulator += 32'(activation(row, segment * SIZE + k)) *
                                       32'(coefficient(segment * SIZE + k, column));
                    expected_tile[segment][row][column] = accumulator;
                end
                if (accumulator !== exp_mem[row * SIZE + column])
                    $fatal(1, "Reference file differs at row %0d column %0d", row, column);
            end
        end
    endtask

    task automatic idle_inputs();
        tb_if.weight_commit = 0;
        tb_if.store_weight_req = 0;
        tb_if.ia_row_valid = 0;
        tb_if.ia_tile_start = 0;
        tb_if.ia_calc_done = 0;
        tb_if.ia_is_init_data = 0;
        tb_if.ia_l1_switch = 0;
        tb_if.ia_sending_done = 0;
        tb_if.send_ia_trigger = 0;
        tb_if.ps_store_cfg_valid = 0;
        tb_if.ps_frame_request = 0;
        tb_if.ps_frame_init = 0;
        tb_if.ps_frame_final = 0;
        tb_if.ps_force_raw = 0;
        tb_if.bias_sleep = 0;
        foreach (tb_if.weight_in[lane]) begin
            tb_if.weight_in[lane] = 0;
            tb_if.ia_vec_in[lane] = 0;
            tb_if.bias_in[lane] = 0;
        end
    endtask

    task automatic load_weights(input int segment);
        // The physical row stores B[(row + column) % SIZE][column].
        // Loading starts with the last physical row and shifts downward.
        @(negedge clk);
        tb_if.store_weight_req = 1;
        for (int row = SIZE - 1; row >= 0; row--) begin
            for (int column = 0; column < SIZE; column++)
                tb_if.weight_in[column] = coefficient(segment * SIZE + (row + column) % SIZE, column);
            @(negedge clk);
        end
        tb_if.store_weight_req = 0;
        tb_if.weight_commit = 1;
        @(negedge clk);
        tb_if.weight_commit = 0;
        foreach (tb_if.weight_in[lane]) tb_if.weight_in[lane] = 0;
    endtask

    task automatic stream_rows(input int segment);
        int waits;
        @(negedge clk);
        tb_if.bias_sleep = segment != 0;
        foreach (tb_if.bias_in[lane]) tb_if.bias_in[lane] = segment == 0 ? bias_mem[lane] : 0;
        tb_if.ps_frame_init = segment == 0;
        tb_if.ps_frame_final = segment == NUM_SEG - 1;
        tb_if.ps_frame_request = 1;
        waits = 0;
        while (!tb_if.ps_frame_ready) begin
            @(negedge clk);
            if (waits++ >= 10000) $fatal(1, "PS frame preparation timed out");
        end
        tb_if.send_ia_trigger = 1;
        tb_if.ia_tile_start = 1;
        @(negedge clk);
        tb_if.send_ia_trigger = 0;
        tb_if.ia_tile_start = 0;
        tb_if.ps_frame_request = 0;
        // Synchronous PS RAM and replay registers supply the first row two
        // rising edges after ia_tile_start, matching the production IA reader.
        @(negedge clk);
        for (int row = 0; row < SIZE; row++) begin
            tb_if.ia_row_valid = 1;
            tb_if.ia_is_init_data = segment == 0;
            tb_if.ia_calc_done = segment == NUM_SEG - 1;
            tb_if.ia_l1_switch = row == SIZE - 1;
            tb_if.ia_sending_done = row == SIZE - 1;
            for (int lane = 0; lane < SIZE; lane++)
                tb_if.ia_vec_in[lane] = activation(row, segment * SIZE + lane);
            @(negedge clk);
        end
        tb_if.ia_row_valid = 0;
        tb_if.ia_is_init_data = 0;
        tb_if.ia_calc_done = 0;
        tb_if.ia_l1_switch = 0;
        tb_if.ia_sending_done = 0;
        foreach (tb_if.ia_vec_in[lane]) tb_if.ia_vec_in[lane] = 0;
        waits = 0;
        while (completions[segment] == 0 || (COMPRESSED_STORE && frame_completions[segment] == 0)) begin
            @(negedge clk);
            if (waits++ >= 10000) $fatal(1, "PS frame completion timed out");
        end
        repeat (2) @(negedge clk);
        if (input_rows[segment] != SIZE || partial_rows[segment] != SIZE || completions[segment] != 1)
            $fatal(1, "Unexpected row or completion count in segment %0d", segment);
        if (COMPRESSED_STORE && frame_completions[segment] != 1)
            $fatal(1, "Unexpected PS frame completion count in segment %0d", segment);
    endtask

    always @(posedge clk) begin
        if (rst_n && !finished && active_seg >= 0 && tb_if.ia_row_valid) begin
            if (input_rows[active_seg] >= SIZE) $fatal(1, "Extra input row");
            if (active_seg > 0) begin
                for (int lane = 0; lane < SIZE; lane++) begin
                    if (dut.u_core.ps_data_out[lane] !== expected_tile[active_seg-1][input_rows[active_seg]][lane])
                        $fatal(1, "PS replay differs at segment %0d row %0d lane %0d: got %0d expected %0d",
                            active_seg, input_rows[active_seg], lane, dut.u_core.ps_data_out[lane],
                            expected_tile[active_seg-1][input_rows[active_seg]][lane]);
                    replay_checks++;
                end
            end
            input_rows[active_seg]++;
        end
        #1;
        if (rst_n && !finished) begin
            if (tb_if.ps_capacity_fault) $fatal(1, "Unexpected PS capacity fault");
            if (dut.u_core.ps_stream_valid_d) begin
                if (active_seg < 0 || partial_rows[active_seg] >= SIZE)
                    $fatal(1, "Unexpected complete matrix row");
                for (int lane = 0; lane < SIZE; lane++) begin
                    if (dut.u_core.systolic_sum[lane] !== expected_tile[active_seg][partial_rows[active_seg]][lane])
                        $fatal(1, "Partial sum differs at segment %0d row %0d lane %0d: got %0d expected %0d",
                            active_seg, partial_rows[active_seg], lane, dut.u_core.systolic_sum[lane],
                            expected_tile[active_seg][partial_rows[active_seg]][lane]);
                    partial_checks++;
                end
                partial_rows[active_seg]++;
            end
            if (tb_if.acc_data_valid) begin
                if (active_seg != NUM_SEG - 1 || final_rows >= SIZE)
                    $fatal(1, "Final output appeared outside its reduction segment");
                for (int lane = 0; lane < SIZE; lane++) begin
                    if (tb_if.acc_data_out[lane] !== exp_mem[final_rows * SIZE + lane])
                        $fatal(1, "Final output differs at row %0d lane %0d", final_rows, lane);
                    output_checks++;
                end
                if (tb_if.tile_calc_over !== (final_rows == SIZE - 1))
                    $fatal(1, "Final tile completion has an incorrect row position");
                final_rows++;
            end else if (tb_if.tile_calc_over) $fatal(1, "Tile completion requires a valid output row");
            if (tb_if.partial_sum_calc_over) begin
                if (active_seg < 0 || partial_rows[active_seg] != SIZE)
                    $fatal(1, "Stream completion preceded the complete output rows");
                completions[active_seg]++;
            end
            if (tb_if.ps_frame_complete && active_seg >= 0) frame_completions[active_seg]++;
        end
    end

    initial begin
        idle_inputs();
        data_dir = ".";
        if (!$value$plusargs("DATA_DIR=%s", data_dir)) data_dir = ".";
        force_raw_arg = 0;
        if (!$value$plusargs("PS_FORCE_RAW=%d", force_raw_arg)) force_raw_arg = 0;
        tb_if.ps_force_raw = force_raw_arg != 0;
        $readmemh({data_dir, "/weight_mem.hex"}, weight_mem_raw);
        $readmemh({data_dir, "/ia_mem.hex"}, ia_mem_raw);
        $readmemh({data_dir, "/bias_mem.hex"}, bias_mem);
        $readmemh({data_dir, "/expected_out.hex"}, exp_mem);
        reference_values();
        repeat (3) @(negedge clk);
        rst_n = 1;
        tb_if.ps_store_cfg_valid = 1;
        @(negedge clk);
        tb_if.ps_store_cfg_valid = 0;
        for (int segment = 0; segment < NUM_SEG; segment++) begin
            active_seg = segment;
            load_weights(segment);
            stream_rows(segment);
        end
        repeat (SIZE + 2) @(negedge clk);
        if (final_rows != SIZE || output_checks != 64'(SIZE) * SIZE ||
            replay_checks != 64'(NUM_SEG - 1) * SIZE * SIZE ||
            partial_checks != 64'(NUM_SEG) * SIZE * SIZE)
            $fatal(1, "Incomplete matrix or replay comparison");
        finished = 1;
        $display("PASS: compute_core matched expected final output and control timing");
        $display("COMPUTE_CORE_RESULT {\"size\":%0d,\"k\":%0d,\"segments\":%0d,\"compressed_store\":%0d,\"force_raw\":%0d,\"partial_values\":%0d,\"replay_values\":%0d,\"output_values\":%0d}",
            SIZE, NUM_K, NUM_SEG, COMPRESSED_STORE, tb_if.ps_force_raw, partial_checks, replay_checks, output_checks);
        $finish;
    end

    initial begin
        #5000000;
        $fatal(1, "Compute core test timed out");
    end

    initial if ($test$plusargs("DUMP")) begin
        $dumpfile("tb_compute_core.vcd");
        $dumpvars(0, tb_compute_core);
    end
endmodule
