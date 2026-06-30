`timescale 1ns / 1ps

module tb_compute_core;
    import test_params_pkg::*;

    localparam int unsigned DATA_WIDTH       = 16;
    localparam int unsigned WEIGHT_WIDTH     = 16;
    localparam int unsigned NUM_SEG          = NUM_K / SIZE;
    localparam int unsigned STAIR_STEPS      = (2 * SIZE) - 1;
    localparam int unsigned VALID_START_STEP = SIZE - 1;
    localparam int unsigned VALID_CYCLES     = SIZE;
    localparam int unsigned POST_TILE_DRAIN  = (2 * SIZE) + 4;

    localparam string C_GREEN = "\033[0;32m";
    localparam string C_RED   = "\033[0;31m";
    localparam string C_RESET = "\033[0m";

    logic rst_n = 1'b1;
    logic clk;

    initial clk = 1'b0;
    always #5 clk <= ~clk;

    tb_compute_core_if tb_if(clk);

    logic signed [WEIGHT_WIDTH-1:0] weight_mem_raw [SIZE * NUM_K];
    logic signed [15:0]  ia_mem_raw     [SIZE * NUM_K];
    logic signed [31:0]  bias_mem       [SIZE];
    logic signed [31:0]  exp_mem        [SIZE * SIZE];

    logic signed [31:0] expected_tile [NUM_SEG][SIZE][SIZE];
    logic signed [31:0] captured_final_rows [SIZE][SIZE];

    integer errors;
    int     final_rows_count;
    bit     final_tile_over_seen;
    string  data_dir;

    compute_core_test #(
        .SIZE        (SIZE),
        .DATA_WIDTH  (DATA_WIDTH),
        .WEIGHT_WIDTH(WEIGHT_WIDTH)
    ) dut (
        .clk             (clk),
        .rst_n           (rst_n),
        .store_weight_req(tb_if.store_weight_req),
        .weight_in       (tb_if.weight_in),
        .ia_vec_in       (tb_if.ia_vec_in),
        .ia_row_valid    (tb_if.ia_row_valid),
        .ia_tile_start   (tb_if.send_ia_trigger),
        .ia_calc_done    (tb_if.ia_calc_done),
        .ia_is_init_data (tb_if.ia_is_init_data),
        .ia_l1_switch    (tb_if.ia_l1_switch),
        .send_ia_trigger (tb_if.send_ia_trigger),
        .bias_sleep      (tb_if.bias_sleep),
        .bias_in         (tb_if.bias_in),
        .acc_data_out    (tb_if.acc_data_out),
        .acc_data_valid  (tb_if.acc_data_valid),
        .tile_calc_over  (tb_if.tile_calc_over)
    );

    function automatic logic signed [31:0] get_ia_value(
        input int row_idx,
        input int k_idx
    );
        return $signed(ia_mem_raw[row_idx * NUM_K + k_idx]);
    endfunction

    function automatic logic signed [31:0] get_weight_value(
        input int k_idx,
        input int col_idx
    );
        return $signed(weight_mem_raw[col_idx * NUM_K + k_idx]);
    endfunction

    function automatic logic signed [DATA_WIDTH-1:0] make_stair_tile_value(
        input int seg,
        input int step_idx,
        input int lane_idx
    );
        int row_idx;
        begin
            row_idx = step_idx - lane_idx;
            if (row_idx < 0 || row_idx >= SIZE) begin
                return '0;
            end

            return $signed(ia_mem_raw[row_idx * NUM_K + seg * SIZE + lane_idx]);
        end
    endfunction

    function automatic logic signed [31:0] expected_diag_value(
        input int seg,
        input int diag_step,
        input int lane_idx
    );
        int row_idx;
        begin
            row_idx = diag_step - lane_idx;
            if (row_idx < 0 || row_idx >= SIZE) begin
                return 32'sd0;
            end

            return expected_tile[seg][row_idx][lane_idx];
        end
    endfunction

    task automatic compute_expected_tiles();
        logic signed [31:0] running_acc [SIZE][SIZE];
        begin
            for (int r = 0; r < SIZE; r++) begin
                for (int c = 0; c < SIZE; c++) begin
                    running_acc[r][c] = '0;
                end
            end

            for (int seg = 0; seg < NUM_SEG; seg++) begin
                for (int r = 0; r < SIZE; r++) begin
                    for (int c = 0; c < SIZE; c++) begin
                        logic signed [31:0] partial;
                        partial = '0;

                        for (int k = 0; k < SIZE; k++) begin
                            partial += get_ia_value(r, seg * SIZE + k) *
                                       get_weight_value(seg * SIZE + k, c);
                        end

                        if (seg == 0) begin
                            running_acc[r][c] = bias_mem[c] + partial;
                        end else begin
                            running_acc[r][c] += partial;
                        end

                        expected_tile[seg][r][c] = running_acc[r][c];
                    end
                end
            end
        end
    endtask

    task automatic drive_idle();
        begin
            tb_if.store_weight_req = 1'b0;
            tb_if.ia_row_valid     = 1'b0;
            tb_if.ia_calc_done     = 1'b0;
            tb_if.ia_is_init_data  = 1'b0;
            tb_if.ia_l1_switch     = 1'b0;
            tb_if.send_ia_trigger  = 1'b0;
            tb_if.bias_sleep       = 1'b1;

            for (int i = 0; i < SIZE; i++) begin
                tb_if.bias_in[i]   = '0;
                tb_if.weight_in[i] = '0;
                tb_if.ia_vec_in[i] = '0;
            end
        end
    endtask

    task automatic load_weight_tile(input int seg);
        begin
            @(negedge clk);
            tb_if.store_weight_req = 1'b1;

            // Keep the original top-down load order used by the systolic array.
            for (int k = SIZE - 1; k >= 0; k--) begin
                for (int j = 0; j < SIZE; j++) begin
                    tb_if.weight_in[j] = $signed(weight_mem_raw[(seg * SIZE + k) + j * NUM_K]);
                end
                @(posedge clk);
                @(negedge clk);
            end

            tb_if.store_weight_req = 1'b0;
            for (int j = 0; j < SIZE; j++) begin
                tb_if.weight_in[j] = '0;
            end
        end
    endtask

    task automatic load_bias(input int seg);
        begin
            for (int c = 0; c < SIZE; c++) begin
                tb_if.bias_in[c] = (seg == 0) ? bias_mem[c] : 32'sd0;
            end
        end
    endtask

    task automatic pulse_send_ia_trigger(input int seg);
        begin
            @(negedge clk);
            tb_if.send_ia_trigger = 1'b1;
            @(posedge clk);
            #1;
            $display("[TB] seg=%0d send_ia_trigger pulse", seg);
            @(negedge clk);
            tb_if.send_ia_trigger = 1'b0;
        end
    endtask

    task automatic pulse_l1_switch(input int seg);
        begin
            @(negedge clk);
            tb_if.ia_l1_switch = 1'b1;
            @(posedge clk);
            #1;
            $display("[TB] seg=%0d ia_l1_switch pulse", seg);
            @(negedge clk);
            tb_if.ia_l1_switch = 1'b0;
        end
    endtask

    task automatic check_no_early_output(
        input int seg,
        input int step_idx
    );
        begin
            if (seg == NUM_SEG - 1) begin
                return;
            end

            if (tb_if.acc_data_valid !== 1'b0) begin
                $display("[TB] EARLY OUTPUT ERROR seg=%0d step=%0d acc_data_valid asserted before final segment",
                         seg, step_idx);
                errors++;
            end

            if (tb_if.tile_calc_over !== 1'b0) begin
                $display("[TB] EARLY OUTPUT ERROR seg=%0d step=%0d tile_calc_over asserted before final segment",
                         seg, step_idx);
                errors++;
            end
        end
    endtask

    task automatic capture_final_if_valid(input int seg, input string phase, input int cycle_idx);
        begin
            if (tb_if.tile_calc_over && !tb_if.acc_data_valid) begin
                $display("[TB] FINAL ERROR seg=%0d %s cycle=%0d tile_calc_over without acc_data_valid",
                         seg, phase, cycle_idx);
                errors++;
            end

            if (tb_if.acc_data_valid === 1'b1) begin
                if (seg != NUM_SEG - 1) begin
                    $display("[TB] FINAL ERROR seg=%0d %s cycle=%0d acc_data_valid asserted before final segment",
                             seg, phase, cycle_idx);
                    errors++;
                    return;
                end

                if (final_rows_count >= SIZE) begin
                    $display("[TB] FINAL ERROR observed extra valid row at %s cycle=%0d", phase, cycle_idx);
                    errors++;
                    return;
                end

                for (int lane = 0; lane < SIZE; lane++) begin
                    captured_final_rows[final_rows_count][lane] = tb_if.acc_data_out[lane];

                    if (tb_if.acc_data_out[lane] !== expected_tile[NUM_SEG-1][final_rows_count][lane]) begin
                        $display("[TB] FINAL DATA ERROR row=%0d lane=%0d got=%0d exp=%0d",
                                 final_rows_count, lane,
                                 tb_if.acc_data_out[lane],
                                 expected_tile[NUM_SEG-1][final_rows_count][lane]);
                        errors++;
                    end
                end

                if (final_rows_count == SIZE - 1) begin
                    if (tb_if.tile_calc_over !== 1'b1) begin
                        $display("[TB] FINAL ERROR last row should assert tile_calc_over");
                        errors++;
                    end else begin
                        final_tile_over_seen = 1'b1;
                    end
                end else begin
                    if (tb_if.tile_calc_over !== 1'b0) begin
                        $display("[TB] FINAL ERROR early tile_calc_over at row=%0d", final_rows_count);
                        errors++;
                    end
                end

                $display("[TB] FINAL CAPTURE row=%0d data=[%0d,%0d,%0d,%0d] over=%0b",
                         final_rows_count,
                         tb_if.acc_data_out[0], tb_if.acc_data_out[1],
                         tb_if.acc_data_out[2], tb_if.acc_data_out[3],
                         tb_if.tile_calc_over);

                final_rows_count++;
            end
        end
    endtask

    task automatic stream_tile(input int seg);
        bit row_valid_window;
        begin
            load_bias(seg);

            // First tile uses bias as initial sum; later tiles use ps_buffer replay.
            tb_if.bias_sleep = (seg == 0) ? 1'b0 : 1'b1;

            // ps_buffer replay starts one cycle after send_ia_trigger. The
            // stair-stepped IA input also starts in that next cycle.
            pulse_send_ia_trigger(seg);

            for (int step = 0; step < STAIR_STEPS; step++) begin
                row_valid_window = (step >= VALID_START_STEP) &&
                                   (step <  VALID_START_STEP + VALID_CYCLES);

                @(negedge clk);
                for (int lane = 0; lane < SIZE; lane++) begin
                    tb_if.ia_vec_in[lane] = make_stair_tile_value(seg, step, lane);
                end

                tb_if.ia_row_valid    = row_valid_window;
                tb_if.ia_is_init_data = row_valid_window && (seg == 0);
                tb_if.ia_calc_done    = row_valid_window && (seg == NUM_SEG - 1);

                @(posedge clk);
                #1;

                $display("[TB] seg=%0d step=%0d row_valid=%0b init=%0b calc_done=%0b bias_sleep=%0b acc_valid=%0b over=%0b out0=%0d out1=%0d out2=%0d out3=%0d",
                         seg, step,
                         tb_if.ia_row_valid,
                         tb_if.ia_is_init_data,
                         tb_if.ia_calc_done,
                         tb_if.bias_sleep,
                         tb_if.acc_data_valid,
                         tb_if.tile_calc_over,
                         tb_if.acc_data_out[0], tb_if.acc_data_out[1],
                         tb_if.acc_data_out[2], tb_if.acc_data_out[3]);

                check_no_early_output(seg, step);
                capture_final_if_valid(seg, "stream", step);
            end

            @(negedge clk);
            tb_if.ia_row_valid    = 1'b0;
            tb_if.ia_calc_done    = 1'b0;
            tb_if.ia_is_init_data = 1'b0;
            for (int lane = 0; lane < SIZE; lane++) begin
                tb_if.ia_vec_in[lane] = '0;
            end

            // Allow possible output drain and verify that tile_calc_over is a
            // one-cycle pulse aligned with the last valid final row.
            for (int d = 0; d < POST_TILE_DRAIN; d++) begin
                bit over_seen_before_cycle;
                over_seen_before_cycle = final_tile_over_seen;

                @(posedge clk);
                #1;
                capture_final_if_valid(seg, "drain", d);

                if ((seg == NUM_SEG - 1) && over_seen_before_cycle &&
                    (tb_if.tile_calc_over === 1'b1)) begin
                    $display("[TB] FINAL ERROR tile_calc_over stayed high after final-row pulse, drain=%0d", d);
                    errors++;
                end
            end
        end
    endtask

    initial begin
        rst_n = 1'b0;
        errors = 0;
        final_rows_count = 0;
        final_tile_over_seen = 1'b0;
        data_dir = ".";

        for (int r = 0; r < SIZE; r++) begin
            for (int c = 0; c < SIZE; c++) begin
                captured_final_rows[r][c] = '0;
            end
        end

        if (!$value$plusargs("DATA_DIR=%s", data_dir)) begin
            data_dir = ".";
        end

        drive_idle();

        $display("[TB] Loading data from DATA_DIR=%s", data_dir);
        $readmemh({data_dir, "/weight_mem.hex"},   weight_mem_raw);
        $readmemh({data_dir, "/ia_mem.hex"},       ia_mem_raw);
        $readmemh({data_dir, "/expected_out.hex"}, exp_mem);
        $readmemh({data_dir, "/bias_mem.hex"},     bias_mem);

        compute_expected_tiles();

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        for (int seg = 0; seg < NUM_SEG; seg++) begin
            $display("[TB] Loading weight tile seg=%0d", seg);
            load_weight_tile(seg);
            repeat (2) @(posedge clk);

            $display("[TB] Streaming IA tile seg=%0d", seg);
            stream_tile(seg);
            repeat (1) @(posedge clk);
        end

        if (final_rows_count != SIZE) begin
            $display("[TB] FINAL ERROR captured %0d final rows, expected %0d",
                     final_rows_count, SIZE);
            errors++;
        end

        if (!final_tile_over_seen) begin
            $display("[TB] FINAL ERROR tile_calc_over was not observed on the final valid row");
            errors++;
        end

        for (int r = 0; r < SIZE; r++) begin
            for (int c = 0; c < SIZE; c++) begin
                if (captured_final_rows[r][c] !== exp_mem[r * SIZE + c]) begin
                    $display("[TB] FINAL MEM ERROR r=%0d c=%0d got=%0d exp=%0d",
                             r, c, captured_final_rows[r][c], exp_mem[r * SIZE + c]);
                    errors++;
                end
            end
        end

        if (errors == 0) begin
            $display("%sPASS: compute_core matched expected final output and control timing%s", C_GREEN, C_RESET);
        end else begin
            $display("%sFAIL: %0d mismatches%s", C_RED, errors, C_RESET);
        end

        #20;
        $finish;
    end

    initial begin
        #5000000;
        $display("[TB] FATAL: timeout");
        $finish;
    end

    initial begin
        $dumpfile("tb_compute_core.vcd");
        $dumpvars(0, tb_compute_core);
    end
endmodule
