module kernel_asic_storage_synth_top (
    input logic clk, rst_n, cache_flush, discard_head, load_start,
    output logic load_slot_id,
    input logic row_valid, row_slot,
    input logic [3:0] row_idx,
    input logic signed [15:0] row_data [16],
    input logic load_done, done_slot, send_start,
    output logic load_ready, load_commit, load_commit_slot, discard_ready,
    output logic weight_data_valid, weight_sending_done, store_weight_req,
    output logic signed [15:0] weight_out [16]
);
    kernel_loader_buffer #(.DATA_WIDTH(16), .SIZE(16)) u_buffer (.*);
endmodule
