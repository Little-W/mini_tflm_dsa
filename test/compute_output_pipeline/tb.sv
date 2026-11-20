`timescale 1ns/1ps
`default_nettype none

module compute_output_pipeline_tb #(
    parameter int SIZE = 16,
    parameter int DATA_WIDTH = 16,
    parameter int WEIGHT_WIDTH = 16,
    parameter int CYCLES = 4096
);
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic weight_commit, store_weight_req;
    logic signed [WEIGHT_WIDTH-1:0] weight_in [SIZE];
    logic signed [DATA_WIDTH-1:0] ia_vec_in [SIZE];
    logic signed [31:0] bias_in [SIZE];
    logic ia_row_valid, final_output_overlap, direct_final_stream;
    logic ia_tile_start, ia_calc_done, ia_is_init_data, ia_l1_switch;
    logic ia_sending_done, send_ia_trigger, bias_sleep;
    logic signed [31:0] reference_data [SIZE], current_data [SIZE];
    logic reference_valid, current_valid, reference_tile, current_tile;
    logic reference_complete, current_complete;
    logic reference_advance, current_advance;
    logic reference_ready, current_ready, reference_pressure, current_pressure;
    logic reference_frame_complete, current_frame_complete;
    logic reference_fault, current_fault;
    logic signed [31:0] expected_data [SIZE];
    logic expected_valid, expected_tile, expected_final_complete;
    logic reference_final_component, reference_nonfinal_component;
    longint unsigned checked_values = 0;
    longint unsigned valid_rows = 0;
    longint unsigned final_completions = 0;
    longint unsigned intermediate_completions = 0;
    int unsigned random_state = 32'h5a37c18d;

    compute_core_reference #(
        .SIZE(SIZE), .DATA_WIDTH(DATA_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .PS_FRAME_COUNT(4), .MAX_IA_REUSE(2), .PS_POOL_BYTES(4096)
    ) u_reference (
        .clk(clk), .rst_n(rst_n), .weight_commit(weight_commit),
        .store_weight_req(store_weight_req), .weight_in(weight_in), .ia_vec_in(ia_vec_in),
        .ia_row_valid(ia_row_valid), .final_output_overlap(final_output_overlap),
        .direct_final_stream(direct_final_stream), .ia_tile_start(ia_tile_start),
        .ia_calc_done(ia_calc_done), .ia_is_init_data(ia_is_init_data),
        .ia_l1_switch(ia_l1_switch), .ia_sending_done(ia_sending_done),
        .send_ia_trigger(send_ia_trigger), .bias_sleep(bias_sleep), .bias_in(bias_in),
        .acc_data_out(reference_data), .acc_data_valid(reference_valid),
        .partial_sum_calc_over(reference_complete), .partial_sum_advance_ready(reference_advance),
        .tile_calc_over(reference_tile), .ps_frame_ready(reference_ready),
        .ps_frame_pressure(reference_pressure), .ps_frame_complete(reference_frame_complete),
        .ps_capacity_fault(reference_fault),
        .ps_ram_read_en(), .ps_ram_read_addr(), .ps_ram_write_en(),
        .ps_ram_write_addr(), .ps_ram_write_data()
    );

    compute_core #(
        .SIZE(SIZE), .DATA_WIDTH(DATA_WIDTH), .WEIGHT_WIDTH(WEIGHT_WIDTH),
        .PS_FRAME_COUNT(4), .MAX_IA_REUSE(2), .PS_POOL_BYTES(4096)
    ) u_current (
        .clk(clk), .rst_n(rst_n), .weight_commit(weight_commit),
        .store_weight_req(store_weight_req), .weight_in(weight_in), .ia_vec_in(ia_vec_in),
        .ia_row_valid(ia_row_valid), .final_output_overlap(final_output_overlap),
        .direct_final_stream(direct_final_stream), .ia_tile_start(ia_tile_start),
        .ia_calc_done(ia_calc_done), .ia_is_init_data(ia_is_init_data),
        .ia_l1_switch(ia_l1_switch), .ia_sending_done(ia_sending_done),
        .send_ia_trigger(send_ia_trigger), .bias_sleep(bias_sleep), .bias_in(bias_in),
        .acc_data_out(current_data), .acc_data_valid(current_valid),
        .partial_sum_calc_over(current_complete), .partial_sum_advance_ready(current_advance),
        .tile_calc_over(current_tile), .ps_frame_ready(current_ready),
        .ps_frame_pressure(current_pressure), .ps_frame_complete(current_frame_complete),
        .ps_capacity_fault(current_fault),
        .ps_ram_read_en(), .ps_ram_read_addr(), .ps_ram_write_en(),
        .ps_ram_write_addr(), .ps_ram_write_data()
    );

    assign reference_nonfinal_component =
        u_reference.ps_group_switch_d && !u_reference.ps_calc_done_d;
    assign reference_final_component = u_reference.final_group_complete_q ||
        (u_reference.ps_group_switch_d && u_reference.ps_calc_done_d && final_output_overlap);

    function automatic int unsigned random_word();
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        return random_state;
    endfunction

    task automatic tick;
        #1;
        for (int lane = 0; lane < SIZE; lane++) expected_data[lane] = reference_data[lane];
        expected_valid = rst_n && reference_valid;
        expected_tile = rst_n && reference_tile;
        expected_final_complete = rst_n && reference_final_component;
        if (rst_n) begin
            assert(reference_complete == (reference_final_component || reference_nonfinal_component));
        end
        clk = 1'b1;
        #1;
        assert(current_valid == expected_valid) else $fatal(1, "Output valid latency differs");
        assert(current_tile == expected_tile) else $fatal(1, "Tile completion latency differs");
        assert(current_complete == (expected_final_complete || reference_nonfinal_component))
            else $fatal(1, "Group completion latency differs");
        assert({current_advance, current_ready, current_pressure, current_frame_complete, current_fault} ==
               {reference_advance, reference_ready, reference_pressure, reference_frame_complete, reference_fault})
            else $fatal(1, "Partial-sum interface changed");
        for (int lane = 0; lane < SIZE; lane++) begin
            assert(current_data[lane] == expected_data[lane]) else $fatal(1, "Output payload latency differs");
            assert(u_current.ps_data_out[lane] == u_reference.ps_data_out[lane])
                else $fatal(1, "Partial-sum replay changed");
            assert(u_current.systolic_sum[lane] == u_reference.systolic_sum[lane])
                else $fatal(1, "Systolic arithmetic changed");
            checked_values++;
        end
        valid_rows += 64'(current_valid);
        final_completions += 64'(expected_final_complete);
        intermediate_completions += 64'(reference_nonfinal_component);
        clk = 1'b0;
        #1;
    endtask

    initial begin
        weight_commit = 0;
        store_weight_req = 0;
        ia_row_valid = 0;
        final_output_overlap = 0;
        direct_final_stream = 0;
        ia_tile_start = 0;
        ia_calc_done = 0;
        ia_is_init_data = 0;
        ia_l1_switch = 0;
        ia_sending_done = 0;
        send_ia_trigger = 0;
        bias_sleep = 0;
        for (int lane = 0; lane < SIZE; lane++) begin
            weight_in[lane] = '0;
            ia_vec_in[lane] = '0;
            bias_in[lane] = '0;
        end
        tick();
        tick();
        for (int cycle = 0; cycle < CYCLES; cycle++) begin
            rst_n = (cycle % 257) != 0;
            weight_commit = (random_word() % 23) == 0;
            store_weight_req = (random_word() % 4) != 0;
            ia_row_valid = (random_word() % 4) != 0;
            final_output_overlap = 1'(cycle / 127);
            direct_final_stream = 1'(cycle / 509);
            ia_tile_start = (random_word() % 17) == 0;
            ia_calc_done = 1'(random_word());
            ia_is_init_data = 1'(random_word());
            ia_l1_switch = ia_row_valid && ((cycle % SIZE) == SIZE-1);
            ia_sending_done = ia_row_valid && ((cycle % (2*SIZE)) == 2*SIZE-1);
            send_ia_trigger = (random_word() % 37) == 0;
            bias_sleep = 1'(random_word());
            for (int lane = 0; lane < SIZE; lane++) begin
                weight_in[lane] = WEIGHT_WIDTH'(random_word());
                ia_vec_in[lane] = DATA_WIDTH'(random_word());
                bias_in[lane] = 32'(random_word());
            end
            tick();
        end
        assert(valid_rows != 0 && final_completions != 0 && intermediate_completions != 0);
        $display("{\"passed\":true,\"size\":%0d,\"data_width\":%0d,\"weight_width\":%0d,\"cycles\":%0d,\"checked_values\":%0d,\"valid_rows\":%0d,\"final_completions\":%0d,\"intermediate_completions\":%0d}",
            SIZE, DATA_WIDTH, WEIGHT_WIDTH, CYCLES, checked_values, valid_rows,
            final_completions, intermediate_completions);
        $finish;
    end
endmodule

`default_nettype wire
