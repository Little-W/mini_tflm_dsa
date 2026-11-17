`timescale 1ns/1ps
module shared_storage_tb #(
    parameter int BANK_BYTES = 2048,
    parameter int BANK_COUNT = 7,
    localparam int ADDR_BITS = $clog2(BANK_COUNT*BANK_BYTES/16)
) (
    input logic clk, rst_n, cfg_valid, direct_mode,
    input logic [$clog2(BANK_COUNT+1)-1:0] cfg_ia_banks,
    input logic [31:0] cfg_pool_bank_words, cfg_pool_bank_count, cfg_directory_stride,
    input logic [1:0] ia_read_en, ia_write_en,
    input logic [ADDR_BITS-1:0] ia_read_addr [0:1], ia_write_addr [0:1],
    input logic [127:0] ia_write_data [0:1],
    input logic [15:0] ia_write_mask [0:1],
    output logic [127:0] ia_read_data [0:1],
    input logic [3:0] direct_read_en, direct_write_en,
    input logic [ADDR_BITS-1:0] direct_read_addr [0:3], direct_write_addr [0:3],
    input logic [127:0] direct_write_data [0:3],
    output wire [3:0] memory_read_en, memory_write_en,
    output wire [ADDR_BITS-1:0] memory_read_addr [0:3], memory_write_addr [0:3],
    output wire [127:0] memory_read_data [0:3], memory_write_data [0:3],
    output logic memory_fault,
    input logic frame_request, frame_accept,
    input logic [3:0] frame_id,
    input logic [31:0] frame_rows, frame_reserve_rows,
    input logic [2:0] frame_word_cap,
    input logic frame_init, frame_final, force_raw_i,
    output wire frame_ready, frame_pressure, capacity_fault, frame_complete,
    input logic write_valid, write_frame_end, replay_trigger,
    input logic [511:0] write_data,
    output wire [511:0] replay_data,
    output wire replay_valid,
    output wire prepare_start, encoder_start, commit_valid, prefetch_fire,
    output wire [2:0] commit_opcode, commit_words, prefetch_opcode,
    output wire [511:0] commit_packet, decoded_row,
    output wire [31:0] selected_id, commit_row, read_row, directory_base,
    output wire [2:0] write_rotation, read_rotation,
    output wire [31:0] free_counts [0:BANK_COUNT-2],
    output wire [BANK_BYTES/16-1:0] free_bits [0:BANK_COUNT-2],
    output wire [15:0] frame_valid,
    output wire [31:0] frame_lengths [0:15], frame_bank_counts [0:BANK_COUNT-2][0:15],
    output wire [2:0] frame_max_words [0:15],
    output wire decoder_done, decoder_fault, decoded_write_en, decoded_read_en, replay_bypass,
    output wire command_present, command_accepted, replay_armed, configuration_ready,
    output wire [31:0] decoded_count, decoder_inflight,
    input logic [9:0] inspect_address,
    output wire [63:0] inspect_descriptor
);
    wire [3:0] store_read_en, store_write_en;
    wire [ADDR_BITS-1:0] store_read_addr [0:3], store_write_addr [0:3];
    wire [127:0] store_write_data [0:3];
    assign memory_read_en=direct_mode ? direct_read_en : store_read_en;
    assign memory_write_en=direct_mode ? direct_write_en : store_write_en;
    for (genvar b=0;b<4;b++) begin : g_ports
        assign memory_read_addr[b]=direct_mode ? direct_read_addr[b] : store_read_addr[b];
        assign memory_write_addr[b]=direct_mode ? direct_write_addr[b] : store_write_addr[b];
        assign memory_write_data[b]=direct_mode ? direct_write_data[b] : store_write_data[b];
    end
    for (genvar b=0;b<BANK_COUNT-1;b++) begin : g_bank_counts
        assign free_counts[b]=32'(dut.bank_free_count[b]);
        assign free_bits[b]=(BANK_BYTES/16)'(dut.free_bitmap[b]);
        for (genvar f=0;f<16;f++) begin : g_frame_counts
            assign frame_bank_counts[b][f]=32'(dut.frame_bank_words[b][f]);
        end
    end
    ia_ps_shared_ram #(.BANK_BYTES(BANK_BYTES),.TOTAL_BYTES(BANK_BYTES*BANK_COUNT),
        .IA_ADDR_BITS(ADDR_BITS),.PS_ADDR_BITS(ADDR_BITS)) shared_ram (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_ia_banks(cfg_ia_banks),.capacity_fault(memory_fault),
        .ia_read_en(ia_read_en),.ia_read_addr(ia_read_addr),.ia_read_data(ia_read_data),
        .ia_write_en(ia_write_en),.ia_write_addr(ia_write_addr),.ia_write_data(ia_write_data),.ia_write_mask(ia_write_mask),
        .ps_read_en(memory_read_en),.ps_read_addr(memory_read_addr),.ps_read_data(memory_read_data),
        .ps_write_en(memory_write_en),.ps_write_addr(memory_write_addr),.ps_write_data(memory_write_data)
    );
    ps_frame_store #(.MAX_FRAME_ROWS(BANK_BYTES/8),.FRAME_COUNT(16),
        .POOL_BYTES(BANK_BYTES*(BANK_COUNT-1)),.BANK_BYTES(BANK_BYTES),
        .EXTERNAL_RAM(1),.DIRECTORY_ROWS(1024),.RAM_ADDR_BITS(ADDR_BITS)) dut (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_pool_bank_words(cfg_pool_bank_words),
        .cfg_directory_stride(cfg_directory_stride),.cfg_pool_bank_count(cfg_pool_bank_count),
        .ram_read_en(store_read_en),.ram_read_addr(store_read_addr),.ram_read_data(memory_read_data),
        .ram_write_en(store_write_en),.ram_write_addr(store_write_addr),.ram_write_data(store_write_data),
        .frame_request(frame_request),.frame_accept(frame_accept),.frame_id(frame_id),.frame_rows(frame_rows),
        .frame_reserve_rows(frame_reserve_rows),.frame_word_cap(frame_word_cap),
        .frame_init(frame_init),.frame_final(frame_final),.force_raw_i(force_raw_i),
        .frame_ready(frame_ready),.frame_pressure(frame_pressure),.capacity_fault(capacity_fault),.frame_complete(frame_complete),
        .write_valid(write_valid),.write_data(write_data),.write_frame_end(write_frame_end),
        .replay_trigger(replay_trigger),.replay_data(replay_data),.replay_valid(replay_valid)
    );
    assign prepare_start=dut.prepare_start;
    assign encoder_start=dut.encoder_start;
    assign commit_valid=dut.encode_commit_valid;
    assign commit_opcode=dut.tb_observer.encode_commit_opcode;
    assign commit_words=dut.tb_observer.encode_commit_words;
    assign commit_packet=dut.encode_commit_packet;
    assign prefetch_fire=dut.prefetch_fire;
    assign prefetch_opcode=dut.prefetch_opcode;
    assign selected_id=32'(dut.frame_id_q);
    assign commit_row=32'(dut.commit_count);
    assign read_row=32'(dut.read_index);
    assign directory_base=32'(dut.directory_base_q);
    assign write_rotation=dut.write_rotation;
    assign read_rotation=dut.read_rotation;
    assign frame_valid=dut.frame_valid;
    for (genvar f=0;f<16;f++) begin : g_frame_metadata
        assign frame_lengths[f]=32'(dut.frame_lengths[f]);
        assign frame_max_words[f]=dut.frame_max_record_words[f];
    end
    assign decoder_done=dut.decoder_done;
    assign decoder_fault=dut.decoder_fault;
    assign decoded_row=dut.decoded_row;
    assign decoded_write_en=dut.decoded_write_en;
    assign decoded_read_en=dut.decoded_read_en;
    assign replay_bypass=dut.replay_bypass;
    assign command_present=dut.command_present;
    assign command_accepted=dut.command_accepted;
    assign replay_armed=dut.replay_armed;
    assign configuration_ready=dut.configuration_ready;
    assign decoded_count=32'(dut.decoded_count);
    assign decoder_inflight=32'(dut.decoder_inflight);
    assign inspect_descriptor=64'(dut.directory[inspect_address]);
endmodule
