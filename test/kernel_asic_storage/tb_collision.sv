`timescale 1ns/1ps
module tb_collision;
    localparam int SIZE = 16;
    localparam int DATA_WIDTH = 16;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, cache_flush = 0, discard_head = 0, load_start = 0;
    logic row_valid = 0, row_slot = 0, load_done = 0, done_slot = 0, send_start = 0;
    logic [3:0] row_idx = 0;
    logic signed [DATA_WIDTH-1:0] row_data [SIZE];
    logic load_slot_id, load_ready, load_commit, load_commit_slot, discard_ready;
    logic weight_data_valid, weight_sending_done, store_weight_req;
    logic signed [DATA_WIDTH-1:0] weight_out [SIZE];
    logic [SIZE*DATA_WIDTH-1:0] payload;

    kernel_loader_buffer #(.DATA_WIDTH(DATA_WIDTH), .SIZE(SIZE)) dut (.*);

    task automatic tick;
        @(posedge clk); #1;
        @(negedge clk); #1;
    endtask

    initial begin
        for (int i = 0; i < SIZE; i++) row_data[i] = '0;
        repeat (2) tick();
        rst_n = 1;
        force dut.row_slot_q = 0;
        force dut.row_idx_q = 0;
        force dut.active_storage = 0;
        force dut.slot_reserved = 2'b11;
        force dut.row_data_vec_q = payload;
        force dut.row_valid_q = 1;
        force dut.send_pending = 0;
        force dut.send_prefetch = 0;
        force dut.send_active = 0;
        force dut.emit_col_idx = 0;
        force dut.send_valid_cols = SIZE;
        payload = 'h35;
        tick();
        force dut.send_active = 1;
        payload = 'h65;
        tick();
        if (weight_out[0] !== 16'h35) $fatal(1, "collision did not return old data");
        force dut.row_valid_q = 0;
        tick();
        if (weight_out[0] !== 16'h65) $fatal(1, "subsequent read did not return new data");
        $display("KERNEL_COLLISION_PASS");
        $finish;
    end
endmodule
