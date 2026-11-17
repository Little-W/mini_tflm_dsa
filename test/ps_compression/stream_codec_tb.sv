`timescale 1ns/1ps
module stream_codec_tb (
    input wire clk, rst_n,
    input wire encode_start, encode_first, encode_force_raw,
    input wire [511:0] encode_row,
    input wire [8:0] encode_slot,
    output wire encode_done,
    output wire [2:0] encode_opcode, encode_words,
    output wire [511:0] encode_packet,
    input wire read_start,
    input wire [8:0] read_slot,
    input wire inject_start, inject_first,
    input wire [2:0] inject_opcode,
    input wire [511:0] inject_packet,
    output wire decode_start,
    output wire decode_done, decode_fault,
    output wire [511:0] decode_row
);
    wire encoder_busy, decoder_busy;
    reg [8:0] slots [0:3];
    reg [3:0] first_pipe;
    reg [3:0] descriptors [0:511];
    reg [3:0] read_descriptor;
    reg read_valid;
    wire [511:0] stored_packet;
    ps_adaptive_encoder encoder (
        .clk(clk), .rst_n(rst_n), .start(encode_start), .row_first(encode_first), .force_raw(encode_force_raw),
        .row_data(encode_row), .busy(encoder_busy), .done(encode_done),
        .opcode(encode_opcode), .words(encode_words), .packet(encode_packet)
    );
    genvar bank;
    generate for (bank=0; bank<4; bank=bank+1) begin : g_memory
        reg [127:0] ram [0:511];
        reg [127:0] read_data;
        always @(posedge clk) begin
            if (encode_done) ram[slots[3]] <= encode_packet[bank*128 +: 128];
            if (read_start) read_data <= ram[read_slot];
        end
        assign stored_packet[bank*128 +: 128] = read_data;
    end endgenerate
    integer stage;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            first_pipe <= 0;
            read_valid <= 0;
            read_descriptor <= 0;
            for (stage=0; stage<4; stage=stage+1) slots[stage] <= 0;
        end else begin
            slots[0] <= encode_slot;
            for (stage=1; stage<4; stage=stage+1) slots[stage] <= slots[stage-1];
            first_pipe <= {first_pipe[2:0],encode_first};
            if (encode_done) descriptors[slots[3]] <= {first_pipe[3],encode_opcode};
            if (read_start) read_descriptor <= descriptors[read_slot];
            read_valid <= read_start;
        end
    end
    assign decode_start = inject_start || read_valid;
    ps_adaptive_decoder decoder (
        .clk(clk), .rst_n(rst_n), .start(decode_start),
        .row_first(inject_start ? inject_first : read_descriptor[3]),
        .opcode(inject_start ? inject_opcode : read_descriptor[2:0]),
        .packet(inject_start ? inject_packet : stored_packet),
        .busy(decoder_busy), .done(decode_done), .fault(decode_fault), .row_data(decode_row)
    );
endmodule
