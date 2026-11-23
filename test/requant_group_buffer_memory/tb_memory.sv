`timescale 1ns/1ps
`default_nettype none

module requant_group_buffer_memory_case #(
    parameter int p_rows = 512,
    parameter int p_lanes = 16,
    parameter int p_case = 0
) (
    input wire clk,
    output logic o_done
);
    localparam int p_width = p_lanes * 32 + 1;
    logic rst_n, i_clear, i_group_start, i_row_valid;
    logic i_row_tile_done, i_row_ready, i_output_valid;
    logic [31:0] i_group_rows;
    logic signed [31:0] i_row_data [p_lanes];
    wire ready_dut, ready_ref, valid_dut, valid_ref, tile_dut, tile_ref;
    wire signed [31:0] data_dut [p_lanes], data_ref [p_lanes];
    logic [p_width-1:0] expected_data [0:p_rows-1];
    logic [p_width-1:0] packed_input, packed_dut, packed_ref, previous_data;
    logic previous_data_known;
    logic [31:0] random_state;
    int queue_head, queue_tail, queue_count, expected_count, pending_count, issued_count;
    int writes, reads, retirements, holds, concurrent_accesses, cycles;
    int full_groups, clears, resets, max_pending;

    requant_group_buffer #(.p_lanes(p_lanes), .p_rows(p_rows)) dut (
        .clk(clk), .rst_n(rst_n), .i_clear(i_clear),
        .i_group_start(i_group_start), .i_group_rows(i_group_rows), .o_group_ready(ready_dut),
        .i_row_valid(i_row_valid), .i_row_tile_done(i_row_tile_done), .i_row_data(i_row_data),
        .o_row_valid(valid_dut), .o_row_tile_done(tile_dut), .o_row_data(data_dut),
        .i_row_ready(i_row_ready), .i_output_valid(i_output_valid)
    );
    requant_group_buffer_reference #(.p_lanes(p_lanes), .p_rows(p_rows)) reference (
        .clk(clk), .rst_n(rst_n), .i_clear(i_clear),
        .i_group_start(i_group_start), .i_group_rows(i_group_rows), .o_group_ready(ready_ref),
        .i_row_valid(i_row_valid), .i_row_tile_done(i_row_tile_done), .i_row_data(i_row_data),
        .o_row_valid(valid_ref), .o_row_tile_done(tile_ref), .o_row_data(data_ref),
        .i_row_ready(i_row_ready), .i_output_valid(i_output_valid)
    );
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_data
        assign packed_input[32*lane +: 32] = i_row_data[lane];
        assign packed_dut[32*lane +: 32] = data_dut[lane];
        assign packed_ref[32*lane +: 32] = data_ref[lane];
    end
    assign packed_input[p_width-1] = i_row_tile_done;
    assign packed_dut[p_width-1] = tile_dut;
    assign packed_ref[p_width-1] = tile_ref;

    // 独立队列记录每一行的全部位，并检查输出暂停期间的保持行为。
    always @(posedge clk) begin : p_scoreboard
        logic did_read;
        logic [p_width-1:0] held_data;
        did_read = dut.read_row;
        held_data = packed_dut;
        cycles++;
        if (!rst_n || i_clear) begin
            queue_head = 0;
            queue_tail = 0;
            queue_count = 0;
            expected_count = 0;
            pending_count = 0;
            issued_count = 0;
        end else begin
            if (valid_dut && i_row_ready) begin
                if (queue_count == 0 || packed_dut !== expected_data[queue_head])
                    $fatal(1, "Case %0d row consumption differs", p_case);
                queue_head = (queue_head + 1) % p_rows;
                queue_count--;
                issued_count++;
                reads++;
            end
            if (i_group_start) begin
                if (!ready_dut || pending_count != 0 || queue_count != 0 || issued_count != 0)
                    $fatal(1, "Case %0d group reservation differs", p_case);
                expected_count = int'(i_group_rows);
                pending_count = int'(i_group_rows);
                if (i_group_rows == p_rows) full_groups++;
            end
            if (i_row_valid) begin
                if (expected_count == 0 || queue_count >= p_rows)
                    $fatal(1, "Case %0d input capacity differs", p_case);
                expected_data[queue_tail] = packed_input;
                queue_tail = (queue_tail + 1) % p_rows;
                queue_count++;
                expected_count--;
                writes++;
            end
            if (i_output_valid) begin
                if (issued_count == 0 || pending_count == 0)
                    $fatal(1, "Case %0d output retirement differs", p_case);
                issued_count--;
                pending_count--;
                retirements++;
            end
            if (pending_count > max_pending) max_pending = pending_count;
            if (dut.push_row && did_read) concurrent_accesses++;
        end
        #1;
        if (valid_dut !== valid_ref || ready_dut !== ready_ref)
            $fatal(1, "Case %0d cycle control differs", p_case);
        if (ready_dut !== (pending_count == 0))
            $fatal(1, "Case %0d reservation count differs", p_case);
        if (valid_dut) begin
            if (queue_count == 0 || packed_dut !== expected_data[queue_head])
                $fatal(1, "Case %0d queue head differs", p_case);
            if (packed_dut !== packed_ref)
                $fatal(1, "Case %0d complete row differs", p_case);
            previous_data_known = 1'b1;
        end
        if (previous_data_known && !did_read) begin
            if (packed_dut !== held_data || packed_dut !== packed_ref)
                $fatal(1, "Case %0d output hold differs", p_case);
            holds++;
        end
        previous_data = packed_dut;
    end

    task automatic advance_random;
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
    endtask

    task automatic step(
        input logic clear_value,
        input logic start_value,
        input int group_rows,
        input logic push_value,
        input logic consume_value,
        input logic retire_value,
        input int pattern
    );
        @(negedge clk);
        i_clear = clear_value;
        i_group_start = start_value;
        i_group_rows = 32'(group_rows);
        i_row_valid = push_value;
        i_row_ready = consume_value;
        i_output_valid = retire_value;
        for (int lane = 0; lane < p_lanes; lane++) begin
            advance_random();
            if (pattern == 0) i_row_data[lane] = '0;
            else if (pattern == 1) i_row_data[lane] = '1;
            else i_row_data[lane] = $signed(random_state);
        end
        advance_random();
        i_row_tile_done = (pattern == 0) ? 1'b0 :
            (pattern == 1) ? 1'b1 : random_state[0];
        @(posedge clk);
        #2;
    endtask

    task automatic drain;
        int watchdog;
        watchdog = 0;
        while (!ready_dut) begin
            step(0, 0, 0, 0, 1, issued_count != 0, 2);
            watchdog++;
            if (watchdog > p_rows * 4 + 20) $fatal(1, "Case %0d drain timeout", p_case);
        end
    endtask

    task automatic full_group(input int pattern);
        step(0, 1, p_rows, 1, 0, 0, pattern);
        for (int row = 1; row < p_rows; row++) step(0, 0, 0, 1, 0, 0, pattern);
        repeat (8) step(0, 0, 0, 0, 0, 0, pattern);
        drain();
    endtask

    task automatic random_group(input int group_size);
        int watchdog;
        logic push_value, consume_value, retire_value;
        step(0, 1, group_size, 0, 0, 0, 2);
        watchdog = 0;
        while (!ready_dut) begin
            advance_random();
            push_value = expected_count != 0 && |random_state[1:0];
            consume_value = random_state[2];
            retire_value = issued_count != 0 && random_state[3];
            step(0, 0, 0, push_value, consume_value, retire_value, 2);
            watchdog++;
            if (watchdog > p_rows * 40 + 200) $fatal(1, "Case %0d random timeout", p_case);
        end
    endtask

    initial begin
        o_done = 0;
        rst_n = 0;
        i_clear = 0;
        i_group_start = 0;
        i_group_rows = 0;
        i_row_valid = 0;
        i_row_tile_done = 0;
        i_row_ready = 0;
        i_output_valid = 0;
        previous_data_known = 0;
        previous_data = '0;
        random_state = 32'h714a9305 ^ 32'(p_rows * 17 + p_lanes * 1023 + p_case);
        writes = 0;
        reads = 0;
        retirements = 0;
        holds = 0;
        concurrent_accesses = 0;
        cycles = 0;
        full_groups = 0;
        clears = 0;
        resets = 1;
        max_pending = 0;
        for (int lane = 0; lane < p_lanes; lane++) i_row_data[lane] = '0;
        repeat (2) step(0, 0, 0, 0, 0, 0, 2);
        @(negedge clk);
        rst_n = 1;
        // 两轮满容量读写分别覆盖每个逻辑存储位的零与一。
        full_group(0);
        full_group(1);
        for (int group_index = 0; group_index < 12; group_index++) begin
            advance_random();
            random_group(1 + int'(random_state % 32'(p_rows)));
        end
        // 清空同时禁止本周期的写入和读取，已有存储输出继续保持。
        step(0, 1, p_rows, 1, 0, 0, 2);
        for (int row = 1; row < ((p_rows < 17) ? p_rows : 17); row++)
            step(0, 0, 0, 1, 0, 0, 2);
        step(1, 1, p_rows, 1, 1, 1, 2);
        clears++;
        step(0, 0, 0, 0, 0, 0, 2);
        random_group(p_rows);
        // 中途复位只重置队列控制，下一组继续覆盖完整容量。
        step(0, 1, p_rows, 1, 0, 0, 2);
        step(0, 0, 0, 0, 0, 0, 2);
        @(negedge clk);
        rst_n = 0;
        repeat (2) step(0, 0, 0, 0, 0, 0, 2);
        resets++;
        @(negedge clk);
        rst_n = 1;
        full_group(2);
        repeat (4) step(0, 0, 0, 0, 0, 0, 2);
        if (max_pending != p_rows || full_groups < 3 || writes < 3*p_rows || reads < 3*p_rows)
            $fatal(1, "Case %0d capacity coverage incomplete", p_case);
        if (p_rows > 1 && concurrent_accesses == 0)
            $fatal(1, "Case %0d simultaneous access coverage incomplete", p_case);
        $display("RESULT {\"rows\":%0d,\"lanes\":%0d,\"logical_bits\":%0d,\"writes\":%0d,\"reads\":%0d,\"retirements\":%0d,\"holds\":%0d,\"simultaneous_accesses\":%0d,\"cycles\":%0d,\"full_groups\":%0d,\"clears\":%0d,\"resets\":%0d}",
            p_rows, p_lanes, p_rows*p_width, writes, reads, retirements, holds,
            concurrent_accesses, cycles, full_groups, clears, resets);
        o_done = 1;
    end
endmodule

module tb_requant_group_buffer_memory;
    logic clk = 0;
    wire [12:0] done;
    localparam int p_test_rows [13] = '{1, 3, 16, 127, 128, 129, 256, 384, 385, 511, 512, 513, 1024};
    always #5 clk = ~clk;
    for (genvar profile = 0; profile < 13; profile++) begin : g_case
        requant_group_buffer_memory_case #(
            .p_rows(p_test_rows[profile]), .p_lanes((p_test_rows[profile] == 256 || p_test_rows[profile] == 512) ? 16 : 1), .p_case(profile)
        ) u_case (.clk(clk), .o_done(done[profile]));
    end
    initial begin
        wait (&done);
        $display("PASS complete SRAM row comparison");
        $finish;
    end
    initial begin
        #20000000;
        $fatal(1, "Simulation timeout");
    end
endmodule

`default_nettype wire
