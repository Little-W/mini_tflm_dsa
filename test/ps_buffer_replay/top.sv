module ps_replay_top #(
    parameter int DEPTH = 17,
    parameter int FRAME_COUNT = 3,
    parameter int MAX_FRAME_LEN = 7
)(
    input logic clk, rst_n,
    input logic [63:0] data_in,
    input logic input_valid, frame_end, replay_trigger, replay_enable,
    output logic [63:0] data_out,
    output logic replay_ready, capacity_fault,
    output logic forward_hit, write_enable,
    output logic [31:0] write_address, frame_count, replay_count
);
    ps_buffer_wide_fifo #(
        .DEPTH(DEPTH), .DATA_WIDTH(64), .FRAME_COUNT(FRAME_COUNT),
        .MAX_FRAME_LEN(MAX_FRAME_LEN)
    ) dut (
        .clk, .rst_n, .data_in, .input_valid_i(input_valid),
        .ia_l1_switch_i(frame_end), .send_ia_trigger_i(replay_trigger),
        .replay_enable_i(replay_enable), .data_out, .capacity_fault,
        .replay_ready
    );
    assign forward_hit = dut.read_forward_valid && dut.replay_data_valid;
    assign write_enable = dut.ram_write_en_q;
    assign write_address = 32'(dut.ram_write_addr_q);
    assign frame_count = 32'(dut.frame_count);
    assign replay_count = 32'(dut.replay_count);
endmodule
