`timescale 1ns/1ps

module ps_stream_capture_tb;
    logic clk = 0, rst_n = 0;
    logic frame_request = 0, frame_accept = 0;
    logic [1:0] frame_id = 0;
    logic [31:0] frame_rows = 0;
    logic frame_init = 0, frame_final = 0;
    wire frame_ready, frame_pressure, capacity_fault, frame_complete;
    logic write_valid = 0, write_frame_end = 0, replay_trigger = 0;
    logic [511:0] write_data = 0;
    wire [511:0] replay_data;
    wire replay_valid;
    logic [63:0] cycle = 0;
    logic force_accept = 0, force_complete = 0;
    integer fault_case = 0;
    integer overlap_count = 0, overlap_commit_count = 0;
    logic [31:0] occupied_payload_bytes;

    ps_frame_store #(
        .MAX_FRAME_ROWS(256), .FRAME_COUNT(4), .POOL_BYTES(65536)
    ) dut (
        .clk, .rst_n, .frame_request, .frame_accept, .frame_id, .frame_rows,
        .frame_reserve_rows(frame_rows), .frame_word_cap(3'd4), .frame_init, .frame_final,
        .force_raw_i(1'b1), .frame_ready, .frame_pressure, .capacity_fault, .frame_complete,
        .write_valid, .write_data, .write_frame_end, .replay_trigger, .replay_data, .replay_valid
    );
    always_comb begin
        occupied_payload_bytes = 0;
        for (int id=0; id<4; id++)
            if (dut.frame_valid[id]) occupied_payload_bytes += 64 * 32'(dut.frame_lengths[id]);
    end
    ps_stream_capture #(.FRAME_COUNT(4), .MAX_FRAME_ROWS(256)) capture (
        .clk, .rst_n, .cycle, .job(64'd1),
        .frame_accept(frame_accept || force_accept),
        .frame_complete(dut.complete_now || force_complete),
        .frame_id(32'(frame_id)), .frame_rows, .frame_init, .frame_final,
        .write_valid(dut.encoder_start), .write_data,
        .replay_valid, .replay_data(replay_data ^ (fault_case == 1 ? 512'd1 : 512'd0)),
        .payload_write_en(dut.payload_ram_write_en), .payload_read_en(dut.payload_ram_read_en),
        .decoded_write_en(dut.decoded_write_en), .decoded_read_en(dut.decoded_read_en),
        .replay_bypass(dut.replay_bypass), .occupied_payload_bytes
    );
    always @(posedge clk) begin
        if (rst_n && frame_accept && dut.complete_now) begin
            overlap_count++;
            if (dut.last_commit_now) overlap_commit_count++;
        end
    end

    task automatic tick;
        cycle++;
        #1; clk = 1;
        #1; clk = 0;
        #1;
        assert(!capacity_fault) else $fatal(1, "PS store reported a capacity fault");
    endtask
    task automatic wait_ready;
        integer waited;
        waited = 0;
        #1;
        while (!frame_ready) begin
            tick();
            waited++;
            assert(waited < 1024) else $fatal(1, "PS descriptor did not become ready");
        end
    endtask
    task automatic accept_current(input bit replay);
        wait_ready();
        frame_accept = 1;
        replay_trigger = replay;
        tick();
        frame_accept = 0;
        frame_request = 0;
        replay_trigger = 0;
    endtask
    task automatic request_next(input integer id, input integer rows, input bit initial_frame, input bit final_frame);
        frame_id = 2'(id);
        frame_rows = 32'(rows);
        frame_init = initial_frame;
        frame_final = final_frame;
        frame_request = 1;
        tick();
        tick();
    endtask
    task automatic write_rows(input integer rows, input logic [31:0] seed);
        for (int row=0; row<rows; row++) begin
            for (int lane=0; lane<16; lane++) write_data[32*lane+:32] = seed + 32'(31*row + 17*lane);
            write_valid = 1;
            write_frame_end = row+1 == rows;
            tick();
        end
        write_valid = 0;
        write_frame_end = 0;
    endtask
    task automatic read_rows(input integer rows);
        integer received, waited;
        received = 0;
        waited = 0;
        while (received < rows) begin
            tick();
            waited++;
            if (replay_valid) received++;
            assert(waited < rows+1024) else $fatal(1, "PS replay did not finish");
        end
    endtask
    task automatic finish_frame;
        integer waited;
        write_frame_end = 1;
        tick();
        write_frame_end = 0;
        waited = 0;
        while (!frame_complete) begin
            tick();
            waited++;
            assert(waited < 1024) else $fatal(1, "PS frame did not finish");
        end
    endtask
    task automatic frame_sequence(input integer id, input integer rows);
        // 初始帧、更新帧和最终帧使用同一编号；后续单段帧使用另一编号。
        request_next(id, rows, 1, 0);
        accept_current(0);
        tick();
        if (fault_case == 2) begin force_accept = 1; tick(); end
        if (fault_case == 3) begin force_complete = 1; tick(); end
        request_next(id, rows, 0, 0);
        write_rows(rows, 32'h8000_0100 + 32'(id));
        accept_current(1);
        read_rows(rows);
        request_next(id, rows, 0, 1);
        write_rows(rows, 32'h7fff_1000 + 32'(id));
        accept_current(1);
        read_rows(rows);
        request_next((id+1)%4, rows, 1, 1);
        write_frame_end = 1;
        tick();
        write_frame_end = 0;
        accept_current(0);
        tick();
        finish_frame();
    endtask

    initial begin
        if (!$value$plusargs("FAULT_CASE=%d", fault_case)) fault_case = 0;
        tick(); tick(); rst_n = 1; tick();
        frame_sequence(0, 1);
        frame_sequence(1, 2);
        frame_sequence(2, 128);
        frame_sequence(3, 256);
        assert(overlap_count > 0 && overlap_commit_count > 0)
            else $fatal(1, "PS completion and acceptance overlap was not exercised");
        assert(capture.frames == 16 && capture.writes == 774 && capture.reads == 774)
            else $fatal(1, "PS observer event counts differ");
        $display("PS_CAPTURE_OVERLAP_PASS frames=%0d rows=%0d overlap=%0d commit_overlap=%0d",
            capture.frames, capture.reads, overlap_count, overlap_commit_count);
        $finish;
    end
endmodule
