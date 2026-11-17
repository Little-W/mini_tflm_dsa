`timescale 1ns/1ps
module frame_store_tb (
    input wire clk,rst_n,
    input wire frame_request,frame_accept,
    input wire [3:0] frame_id,
    input wire [31:0] frame_rows,
    input wire [31:0] frame_reserve_rows,
    input wire [2:0] frame_word_cap,
    input wire frame_init,frame_final,force_raw_i,
    output wire frame_ready,frame_pressure,capacity_fault,frame_complete,
    input wire write_valid,
    input wire [511:0] write_data,
    input wire write_frame_end,replay_trigger,
    output wire [511:0] replay_data,
    output wire replay_valid,
    output wire prepare_start,command_present,command_accepted,replay_armed,
    output wire encoder_start,commit_valid,
    output wire [2:0] commit_opcode,commit_words,
    output wire [511:0] commit_packet,
    output wire [31:0] selected_id,commit_row,read_row,captured_rows,
    output wire [3:0] payload_we,payload_re,
    output wire [127:0] allocated_addresses,read_addresses,free_counts,
    output wire [255:0] free_bits,
    output wire [383:0] frame_bank_counts,
    output wire [95:0] frame_lengths,
    output wire [47:0] frame_max_words,
    output wire [2:0] selected_word_cap,current_max_words,
    output wire [31:0] required_read_rows,
    output wire [15:0] frame_valid,
    output wire prefetch_fire,decoder_done,decoder_fault,decoder_first,
    output wire [2:0] prefetch_opcode,
    output wire [1:0] write_rotation,read_rotation,
    output wire [511:0] decoded_row,
    output wire decoded_write_en,decoded_read_en,replay_bypass,
    output wire [31:0] decoded_count,decoder_inflight,
    input wire [31:0] inspect_address,
    output wire [31:0] inspect_descriptor
);
    ps_frame_store #(.MAX_FRAME_ROWS(47),.FRAME_COUNT(16),.POOL_BYTES(4096),.DECODE_FIFO_ROWS(8)) dut (
        .clk(clk),.rst_n(rst_n),.frame_request(frame_request),.frame_accept(frame_accept),
        .frame_id(frame_id),.frame_rows(frame_rows),.frame_reserve_rows(frame_reserve_rows),
        .frame_word_cap(frame_word_cap),
        .frame_init(frame_init),.frame_final(frame_final),
        .force_raw_i(force_raw_i),.frame_ready(frame_ready),.frame_pressure(frame_pressure),
        .capacity_fault(capacity_fault),.frame_complete(frame_complete),
        .write_valid(write_valid),.write_data(write_data),.write_frame_end(write_frame_end),
        .replay_trigger(replay_trigger),.replay_data(replay_data),.replay_valid(replay_valid)
    );
    assign prepare_start=dut.prepare_start;
    assign command_present=dut.command_present;
    assign command_accepted=dut.command_accepted;
    assign replay_armed=dut.replay_armed;
    assign encoder_start=dut.encoder_start;
    assign commit_valid=dut.encode_commit_valid;
    assign commit_opcode=dut.encode_commit_opcode;
    assign commit_words=dut.encode_commit_words;
    assign commit_packet=dut.encode_commit_packet;
    assign selected_id=32'(dut.frame_id_q);
    assign commit_row=32'(dut.commit_count);
    assign read_row=32'(dut.read_index);
    assign captured_rows=32'(dut.capture_count);
    assign selected_word_cap=dut.frame_word_cap_q;
    assign current_max_words=dut.current_max_record_words;
    assign required_read_rows=dut.required_read_rows;
    assign payload_we=dut.payload_ram_write_en;
    assign payload_re=dut.payload_ram_read_en;
    assign prefetch_fire=dut.prefetch_fire;
    assign prefetch_opcode=dut.prefetch_opcode;
    assign write_rotation=dut.write_rotation;
    assign read_rotation=dut.read_rotation;
    assign decoder_done=dut.decoder_done;
    assign decoder_fault=dut.decoder_fault;
    assign decoder_first=dut.decoder_first;
    assign decoded_row=dut.decoded_row;
    assign decoded_write_en=dut.decoded_write_en;
    assign decoded_read_en=dut.decoded_read_en;
    assign replay_bypass=dut.replay_bypass;
    assign decoded_count=32'(dut.decoded_count);
    assign decoder_inflight=32'(dut.decoder_inflight);
    assign frame_valid=dut.frame_valid;
    assign inspect_descriptor=inspect_address<752 ? 32'(dut.directory[inspect_address]) : 0;
    genvar bank,frame;
    generate for (bank=0;bank<4;bank=bank+1) begin : g_bank
        assign allocated_addresses[bank*32 +: 32]=32'(dut.allocated_address[bank]);
        assign read_addresses[bank*32 +: 32]=32'(dut.old_address[bank]);
        assign free_counts[bank*32 +: 32]=32'(dut.bank_free_count[bank]);
        assign free_bits[bank*64 +: 64]=dut.free_bitmap[bank];
        for (frame=0;frame<16;frame=frame+1) begin : g_frame
            assign frame_bank_counts[(bank*16+frame)*6 +: 6]=dut.frame_bank_words[bank][frame];
        end
    end endgenerate
    generate for (frame=0;frame<16;frame=frame+1) begin : g_lengths
        assign frame_lengths[frame*6 +: 6]=dut.frame_lengths[frame];
        assign frame_max_words[frame*3 +: 3]=dut.frame_max_record_words[frame];
    end endgenerate
endmodule
