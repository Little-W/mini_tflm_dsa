`timescale 1ns/1ps

module tb_ps_buffer;
    localparam int unsigned SIZE        = 4;
    localparam int unsigned DATA_WIDTH  = 32;
    localparam int unsigned STAIR_STEPS = (2 * SIZE) - 1;

    logic clk = 1'b0;
    logic rst_n;
    always #5 clk = ~clk;

    logic signed [DATA_WIDTH-1:0] data_in [0:SIZE-1];
    logic                         ia_row_valid;
    logic                         ia_calc_done;
    logic                         ia_l1_switch;
    logic                         send_ia_trigger;
    logic                         ia_is_init_data;

    logic signed [DATA_WIDTH-1:0] dut_data_out [0:SIZE-1];
    logic                         dut_acc_data_valid_o;
    logic                         dut_tile_calc_over_o;

    integer errors = 0;

    ps_buffer #(
        .SIZE      (SIZE),
        .DATA_WIDTH(DATA_WIDTH)
    ) u_dut (
        .clk            (clk),
        .rst_n          (rst_n),
        .data_in        (data_in),
        .ia_row_valid   (ia_row_valid),
        .ia_calc_done   (ia_calc_done),
        .ia_l1_switch   (ia_l1_switch),
        .send_ia_trigger(send_ia_trigger),
        .ia_is_init_data(ia_is_init_data),
        .data_out       (dut_data_out),
        .acc_data_valid (dut_acc_data_valid_o),
        .tile_calc_over (dut_tile_calc_over_o)
    );

    function automatic logic signed [DATA_WIDTH-1:0] make_value(
        input int tag,
        input int row_idx,
        input int lane_idx
    );
        return $signed(tag * 1000 + row_idx * 100 + lane_idx * 11 - 37);
    endfunction

    function automatic logic signed [DATA_WIDTH-1:0] make_stair_value(
        input int tag,
        input int step_idx,
        input int lane_idx
    );
        int row_idx;
        begin
            row_idx = step_idx - lane_idx;
            if (row_idx < 0 || row_idx >= SIZE) begin
                return '0;
            end
            return make_value(tag, row_idx, lane_idx);
        end
    endfunction

    task automatic clear_inputs();
        begin
            ia_row_valid    = 1'b0;
            ia_calc_done    = 1'b0;
            ia_l1_switch    = 1'b0;
            send_ia_trigger = 1'b0;
            ia_is_init_data = 1'b0;
            for (int lane = 0; lane < SIZE; lane++) begin
                data_in[lane] = '0;
            end
        end
    endtask

    task automatic apply_reset();
        begin
            rst_n = 1'b0;
            clear_inputs();
            repeat (3) @(posedge clk);
            rst_n = 1'b1;
            repeat (2) @(posedge clk);
        end
    endtask

    task automatic check_control_idle(input string label);
        begin
            if (dut_acc_data_valid_o !== 1'b0) begin
                $display("[TB] ERROR %s expected acc_data_valid_o=0 got=%0b", label, dut_acc_data_valid_o);
                errors++;
            end
            if (dut_tile_calc_over_o !== 1'b0) begin
                $display("[TB] ERROR %s expected tile_calc_over_o=0 got=%0b", label, dut_tile_calc_over_o);
                errors++;
            end
        end
    endtask

    task automatic check_diagonal_partial_sum_step(
        input string label,
        input int    tag,
        input int    step_idx
    );
        begin
            // FIFO replay only drives the stair-stepped partial-sum data.
            // acc_data_valid_o and tile_calc_over_o are managed only by
            // de_diagonalizer, so they must stay low during FIFO replay.
            check_control_idle($sformatf("%s step %0d", label, step_idx));

            for (int lane = 0; lane < SIZE; lane++) begin
                if (dut_data_out[lane] !== make_stair_value(tag, step_idx, lane)) begin
                    $display("[TB] ERROR %s step %0d lane %0d diagonal data mismatch: dut=%0d exp=%0d",
                             label, step_idx, lane, dut_data_out[lane],
                             make_stair_value(tag, step_idx, lane));
                    errors++;
                end
            end
        end
    endtask

    task automatic check_de_diagonalized_vector_row(
        input string label,
        input int    tag,
        input int    row_idx,
        input bit    expect_tile_over
    );
        begin
            if (dut_acc_data_valid_o !== 1'b1) begin
                $display("[TB] ERROR %s row %0d expected acc_data_valid_o=1 got=%0b",
                         label, row_idx, dut_acc_data_valid_o);
                errors++;
            end

            if (dut_tile_calc_over_o !== expect_tile_over) begin
                $display("[TB] ERROR %s row %0d expected tile_calc_over_o=%0b got=%0b",
                         label, row_idx, expect_tile_over, dut_tile_calc_over_o);
                errors++;
            end

            for (int lane = 0; lane < SIZE; lane++) begin
                if (dut_data_out[lane] !== make_value(tag, row_idx, lane)) begin
                    $display("[TB] ERROR %s row %0d lane %0d de-diagonalized data mismatch: dut=%0d exp=%0d",
                             label, row_idx, lane, dut_data_out[lane],
                             make_value(tag, row_idx, lane));
                    errors++;
                end
            end
        end
    endtask

    task automatic run_diagonal_partial_sum_fifo_test(input int tag);
        begin
            $display("[TB] diagonal partial-sum FIFO replay test start");
            apply_reset();

            // Normal partial sums enter ps_buffer_fifo. The replayed output must
            // remain in the original diagonal/stair-stepped form.
            for (int step = 0; step < STAIR_STEPS; step++) begin
                @(negedge clk);
                for (int lane = 0; lane < SIZE; lane++) begin
                    data_in[lane] = make_stair_value(tag, step, lane);
                end
                ia_row_valid    = (step < SIZE);
                ia_calc_done    = 1'b0;
                ia_l1_switch    = 1'b0;
                send_ia_trigger = 1'b0;
                ia_is_init_data = ia_row_valid;

                @(posedge clk);
                #1;
                check_control_idle($sformatf("fifo capture step %0d", step));
            end

            @(negedge clk);
            clear_inputs();
            ia_l1_switch = 1'b1;
            @(posedge clk);
            #1;
            check_control_idle("fifo l1 switch");

            @(negedge clk);
            ia_l1_switch    = 1'b0;
            send_ia_trigger = 1'b1;
            @(posedge clk);
            #1;
            check_control_idle("fifo send trigger edge");

            @(negedge clk);
            send_ia_trigger = 1'b0;

            for (int step = 0; step < STAIR_STEPS; step++) begin
                @(posedge clk);
                #1;
                check_diagonal_partial_sum_step("fifo diagonal replay", tag, step);
            end

            @(posedge clk);
            #1;
            check_control_idle("fifo replay done");
        end
    endtask

    task automatic run_calc_done_de_diagonalizer_test(input int tag);
        int row_idx;
        bit expect_tile_over;
        begin
            $display("[TB] calc_done de-diagonalization test start");
            apply_reset();

            // When ia_calc_done is high, the stair-stepped input bypasses FIFO
            // and enters de_diagonalizer. The final output must be normal vector
            // rows synchronized with acc_data_valid_o. tile_calc_over_o is high
            // only for the last valid vector row.
            for (int step = 0; step < STAIR_STEPS; step++) begin
                @(negedge clk);
                for (int lane = 0; lane < SIZE; lane++) begin
                    data_in[lane] = make_stair_value(tag, step, lane);
                end
                ia_row_valid    = 1'b1;  // high on purpose: calc_done must bypass FIFO
                ia_calc_done    = 1'b1;
                ia_l1_switch    = 1'b0;
                send_ia_trigger = 1'b0;
                ia_is_init_data = 1'b0;

                @(posedge clk);
                #1;

                if (step < SIZE - 1) begin
                    check_control_idle($sformatf("de_diagonalizer fill step %0d", step));
                end else begin
                    row_idx = step - (SIZE - 1);
                    expect_tile_over = (row_idx == SIZE - 1);
                    check_de_diagonalized_vector_row("de_diagonalizer output", tag,
                                                     row_idx, expect_tile_over);
                end
            end

            @(negedge clk);
            clear_inputs();
            @(posedge clk);
            #1;
            check_control_idle("de_diagonalizer after final row");

            // Prove that the calc_done burst was not stored into FIFO: after an
            // l1 switch and replay trigger, no de_diagonalizer control pulse
            // should appear and data_out should stay zero.
            @(negedge clk);
            ia_l1_switch = 1'b1;
            @(posedge clk);
            #1;
            check_control_idle("bypass fifo l1 switch");

            @(negedge clk);
            ia_l1_switch    = 1'b0;
            send_ia_trigger = 1'b1;
            @(posedge clk);
            #1;
            check_control_idle("bypass fifo trigger edge");

            @(negedge clk);
            send_ia_trigger = 1'b0;
            repeat (SIZE + 1) begin
                @(posedge clk);
                #1;
                check_control_idle("bypass fifo replay window");
                for (int lane = 0; lane < SIZE; lane++) begin
                    if (dut_data_out[lane] !== '0) begin
                        $display("[TB] ERROR bypass fifo replay lane %0d expected zero got=%0d",
                                 lane, dut_data_out[lane]);
                        errors++;
                    end
                end
            end
        end
    endtask

    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_ps_buffer);
    end

    initial begin
        run_diagonal_partial_sum_fifo_test(1);
        run_calc_done_de_diagonalizer_test(2);

        if (errors == 0) begin
            $display("PASS: diagonal partial-sum replay and calc_done de-diagonalized output validated");
        end else begin
            $display("FAIL: ps_buffer mismatches=%0d", errors);
        end

        #20;
        $finish;
    end

    initial begin
        #200000;
        $display("[TB] FATAL: timeout");
        $finish;
    end
endmodule
