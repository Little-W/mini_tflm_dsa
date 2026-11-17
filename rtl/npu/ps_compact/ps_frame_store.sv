`timescale 1ns/1ps

// Fixed INT32 rows occupy deterministic frame slots in the shared data banks.
module ps_frame_store #(
    parameter integer MAX_FRAME_ROWS = 47,
    parameter integer FRAME_COUNT = 16,
    parameter integer POOL_BYTES = 4096,
    parameter integer BANK_BYTES = 2048,
    parameter integer DECODE_FIFO_ROWS = 8,
    parameter integer EXTERNAL_RAM = 0,
    parameter integer DIRECTORY_ROWS = FRAME_COUNT * MAX_FRAME_ROWS,
    parameter integer RAM_ADDR_BITS = EXTERNAL_RAM!=0 ? $clog2(POOL_BYTES/16) :
        ($clog2(POOL_BYTES/64)>0 ? $clog2(POOL_BYTES/64) : 1)
) (
    input  wire clk,
    input  wire rst_n,
    input  wire cfg_valid = 1'b0,
    input  wire [31:0] cfg_pool_bank_words = EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64,
    input  wire [31:0] cfg_pool_bank_count = EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4,
    input  wire [31:0] cfg_directory_stride = MAX_FRAME_ROWS,
    output wire [3:0] ram_read_en,
    output wire [RAM_ADDR_BITS-1:0] ram_read_addr [0:3],
    input  wire [127:0] ram_read_data [0:3] = '{default:'0},
    output wire [3:0] ram_write_en,
    output wire [RAM_ADDR_BITS-1:0] ram_write_addr [0:3],
    output wire [127:0] ram_write_data [0:3],
    input  wire frame_request,
    input  wire frame_accept,
    input  wire [((FRAME_COUNT > 1) ? $clog2(FRAME_COUNT) : 1)-1:0] frame_id,
    input  wire [31:0] frame_rows,
    input  wire [31:0] frame_reserve_rows,
    input  wire [2:0] frame_word_cap = 3'd4,
    input  wire frame_init,
    input  wire frame_final,
    input  wire force_raw_i,
    output wire frame_ready,
    output wire frame_pressure,
    output reg  capacity_fault,
    output reg  frame_complete,
    input  wire write_valid,
    input  wire [511:0] write_data,
    input  wire write_frame_end,
    input  wire replay_trigger,
    output wire [511:0] replay_data,
    output reg  replay_valid
);
    localparam integer BANKS=EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4;
    localparam integer BANK_DEPTH=EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64;
    localparam integer BANK_ADDR_BITS=$clog2(BANK_DEPTH)>0 ? $clog2(BANK_DEPTH) : 1;
    localparam integer ROTATION_BITS=$clog2(BANKS)>0 ? $clog2(BANKS) : 1;
    localparam integer FRAME_ID_BITS=FRAME_COUNT>1 ? $clog2(FRAME_COUNT) : 1;
    localparam integer FIFO_PTR_BITS=$clog2(DECODE_FIFO_ROWS);
    localparam integer PREFETCH_CREDITS=DECODE_FIFO_ROWS-1;
    localparam integer LENGTH_BITS=$clog2(MAX_FRAME_ROWS+1);
    reg configuration_ready,configuration_pending;
    reg [BANK_ADDR_BITS:0] pool_bank_words_q;
    reg [ROTATION_BITS:0] pool_bank_count_q;
    reg [LENGTH_BITS-1:0] directory_stride_q;
    reg [FRAME_COUNT-1:0] frame_valid;
    reg [LENGTH_BITS-1:0] frame_lengths [FRAME_COUNT];
    reg command_present,command_accepted,input_ended,replay_armed,replay_active;
    reg [FRAME_ID_BITS-1:0] frame_id_q;
    reg [LENGTH_BITS-1:0] frame_rows_q,capture_count,commit_count,read_index,replay_index;
    reg frame_init_q,frame_final_q;
    reg [BANK_ADDR_BITS:0] read_cursor,write_cursor;
    reg [ROTATION_BITS-1:0] read_rotation,write_rotation;
    wire configuration_valid=cfg_pool_bank_count>=4 && cfg_pool_bank_count<=BANKS &&
        cfg_pool_bank_words>0 && cfg_pool_bank_words<=BANK_DEPTH &&
        cfg_directory_stride>0 && cfg_directory_stride<=MAX_FRAME_ROWS;
    wire configure_start=cfg_valid && !command_present && frame_valid==0;
    wire clear_metadata=configure_start || configuration_pending;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            configuration_ready<=EXTERNAL_RAM==0;configuration_pending<=0;
            pool_bank_words_q<=EXTERNAL_RAM==0 ? BANK_DEPTH : 0;
            pool_bank_count_q<=EXTERNAL_RAM==0 ? BANKS : 0;
            directory_stride_q<=MAX_FRAME_ROWS;
        end else if(configure_start) begin
            configuration_ready<=EXTERNAL_RAM==0;configuration_pending<=EXTERNAL_RAM!=0;
        end else if(configuration_pending) begin
            configuration_pending<=0;configuration_ready<=configuration_valid;
            pool_bank_words_q<=cfg_pool_bank_words;pool_bank_count_q<=cfg_pool_bank_count;
            directory_stride_q<=cfg_directory_stride;
        end
    end
    localparam integer RAW_LINEAR_BITS=$clog2(FRAME_COUNT*MAX_FRAME_ROWS*4+1);
    wire [RAW_LINEAR_BITS-1:0] initial_linear=RAW_LINEAR_BITS'(frame_id)*RAW_LINEAR_BITS'(directory_stride_q)<<2;
    wire [63:0] reserve_rows=frame_reserve_rows>frame_rows ? 64'(frame_reserve_rows) : 64'(frame_rows);
    wire request_valid=32'(frame_id)<FRAME_COUNT && frame_rows>0 && frame_rows<=MAX_FRAME_ROWS &&
        frame_rows<=directory_stride_q && (frame_init ? !frame_valid[frame_id] :
        frame_valid[frame_id] && frame_lengths[frame_id]==frame_rows);
    wire request_fits=(frame_init && frame_final) ||
        64'(initial_linear)+(reserve_rows<<2)<=64'(pool_bank_words_q)*64'(pool_bank_count_q);
    wire prepare_start=frame_request && configuration_ready && !command_present && request_valid && request_fits && !capacity_fault;
    assign frame_pressure=frame_request && configuration_ready && !command_present && request_valid && !request_fits && !capacity_fault;
    reg [31:0] initial_row,initial_bank;
    always @* begin
        initial_row=0;initial_bank=0;
        case(pool_bank_count_q)
            4:begin initial_row=32'(initial_linear>>2);initial_bank=32'(initial_linear&3);end
            5:begin initial_row=32'(initial_linear/RAW_LINEAR_BITS'(5));initial_bank=32'(initial_linear%RAW_LINEAR_BITS'(5));end
            6:begin initial_row=32'(initial_linear/RAW_LINEAR_BITS'(6));initial_bank=32'(initial_linear%RAW_LINEAR_BITS'(6));end
            7:begin initial_row=32'(initial_linear/RAW_LINEAR_BITS'(7));initial_bank=32'(initial_linear%RAW_LINEAR_BITS'(7));end
            8:begin initial_row=32'(initial_linear>>3);initial_bank=32'(initial_linear&7);end
            default:;
        endcase
    end
    reg encoder_done;
    wire encoder_start=write_valid && command_accepted && !frame_final_q && !input_ended && !capacity_fault;
    reg [511:0] encode_commit_packet;
    wire encode_commit_valid=encoder_done && !capacity_fault;
    wire [2:0] encode_commit_opcode=3'd3,encode_commit_words=3'd4;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin encoder_done<=0;encode_commit_packet<=0;end
        else begin
            encoder_done<=encoder_start && !clear_metadata;
            if(encoder_start) encode_commit_packet<=write_data;
        end
    end
    reg [511:0] decoded_ram [DECODE_FIFO_ROWS];
    reg decoded_first_mem [DECODE_FIFO_ROWS];
    reg [FIFO_PTR_BITS-1:0] decoded_write_pointer,decoded_read_pointer;
    reg [FIFO_PTR_BITS:0] decoded_count,decoder_inflight;
    wire prefetch_fire=command_present && !frame_init_q && read_index<frame_rows_q &&
        32'(decoded_count)+32'(decoder_inflight)<PREFETCH_CREDITS && !capacity_fault && !clear_metadata;
    wire [BANKS-1:0] payload_ram_read_en,payload_ram_write_en;
    wire [127:0] payload_read_data [BANKS];
    wire [127:0] incoming_words [4];
    for(genvar word=0;word<4;word++) begin:g_port
        wire [ROTATION_BITS:0] rsum={1'b0,read_rotation}+(ROTATION_BITS+1)'(word);
        wire [ROTATION_BITS:0] wsum={1'b0,write_rotation}+(ROTATION_BITS+1)'(word);
        wire rwrap=32'(rsum)>=pool_bank_count_q;
        wire wwrap=32'(wsum)>=pool_bank_count_q;
        wire [ROTATION_BITS-1:0] rb=ROTATION_BITS'(rwrap ? 32'(rsum)-pool_bank_count_q : 32'(rsum));
        wire [ROTATION_BITS-1:0] wb=ROTATION_BITS'(wwrap ? 32'(wsum)-pool_bank_count_q : 32'(wsum));
        assign ram_read_en[word]=prefetch_fire;
        assign ram_write_en[word]=encode_commit_valid;
        assign ram_read_addr[word]=EXTERNAL_RAM!=0 ? RAM_ADDR_BITS'({rb,BANK_ADDR_BITS'(read_cursor+rwrap)}) : RAM_ADDR_BITS'(read_cursor);
        assign ram_write_addr[word]=EXTERNAL_RAM!=0 ? RAM_ADDR_BITS'({wb,BANK_ADDR_BITS'(write_cursor+wwrap)}) : RAM_ADDR_BITS'(write_cursor);
        assign ram_write_data[word]=encode_commit_packet[word*128+:128];
        assign incoming_words[word]=EXTERNAL_RAM!=0 ? ram_read_data[word] : payload_read_data[word];
    end
    for(genvar bank=0;bank<BANKS;bank++) begin:g_payload
        wire [3:0] rselect,wselect;
        for(genvar port_index=0;port_index<4;port_index++)begin:g_select
            assign rselect[port_index]=ram_read_en[port_index] &&
                (EXTERNAL_RAM!=0 ? (32'(ram_read_addr[port_index])>>BANK_ADDR_BITS)==bank : port_index==bank);
            assign wselect[port_index]=ram_write_en[port_index] &&
                (EXTERNAL_RAM!=0 ? (32'(ram_write_addr[port_index])>>BANK_ADDR_BITS)==bank : port_index==bank);
        end
        assign payload_ram_read_en[bank]=|rselect;
        assign payload_ram_write_en[bank]=|wselect;
        if(EXTERNAL_RAM==0) begin:g_internal
            reg [127:0] payload_ram [BANK_DEPTH];
            reg [127:0] data_q;
            always @(posedge clk) begin
                if(prefetch_fire) data_q<=payload_ram[read_cursor];
                if(encode_commit_valid) payload_ram[write_cursor]<=encode_commit_packet[bank*128+:128];
            end
            assign payload_read_data[bank]=data_q;
        end else begin:g_external
            assign payload_read_data[bank]=0;
        end
    end

    reg ram_read_valid,ram_read_first,decoder_done,decoder_first;
    reg [511:0] decoded_row;
    wire decoder_fault=1'b0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            ram_read_valid<=0;ram_read_first<=0;decoder_done<=0;decoder_first<=0;decoded_row<=0;
        end else begin
            ram_read_valid<=prefetch_fire;
            if(prefetch_fire)ram_read_first<=read_index==0;
            decoder_done<=ram_read_valid && !clear_metadata;
            if(ram_read_valid) begin
                decoded_row<={incoming_words[3],incoming_words[2],incoming_words[1],incoming_words[0]};
                decoder_first<=ram_read_first;
            end
        end
    end
    wire decoded_read_en=replay_active && decoded_count!=0 && !capacity_fault;
    wire replay_bypass=replay_active && decoded_count==0 && decoder_done && !capacity_fault;
    wire decoded_write_en=decoder_done && !replay_bypass && !capacity_fault;
    wire replay_consume=decoded_read_en || replay_bypass;
    reg [511:0] replay_q;
    assign replay_data=replay_valid ? replay_q : 512'd0;
    assign frame_ready=command_present && !command_accepted && !capacity_fault &&
        (frame_init_q || decoded_count!=0);
    wire complete_now=command_present && command_accepted && input_ended && !capacity_fault &&
        !replay_armed && !replay_active && !encoder_done && !ram_read_valid && !decoder_done &&
        decoded_count==0 && decoder_inflight==0 && (frame_final_q || commit_count==frame_rows_q) &&
        (frame_init_q || replay_index==frame_rows_q);
    always @(posedge clk) begin
        if(decoded_write_en) begin
            decoded_ram[decoded_write_pointer]<=decoded_row;
            decoded_first_mem[decoded_write_pointer]<=decoder_first;
        end
        if(decoded_read_en) replay_q<=decoded_ram[decoded_read_pointer];
        else if(replay_bypass)replay_q<=decoded_row;
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            capacity_fault<=0;frame_complete<=0;frame_valid<=0;
            command_present<=0;command_accepted<=0;input_ended<=0;replay_armed<=0;replay_active<=0;
            frame_id_q<=0;frame_rows_q<=0;frame_init_q<=0;frame_final_q<=0;
            capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            read_cursor<=0;write_cursor<=0;read_rotation<=0;write_rotation<=0;
            decoded_count<=0;decoder_inflight<=0;decoded_write_pointer<=0;decoded_read_pointer<=0;replay_valid<=0;
            for(integer f=0;f<FRAME_COUNT;f++)frame_lengths[f]<=0;
        end else if(clear_metadata) begin
            capacity_fault<=configuration_pending && !configuration_valid;
            frame_complete<=0;frame_valid<=0;command_present<=0;command_accepted<=0;input_ended<=0;
            replay_armed<=0;replay_active<=0;capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            decoded_count<=0;decoder_inflight<=0;decoded_write_pointer<=0;decoded_read_pointer<=0;replay_valid<=0;
        end else begin
            frame_complete<=0;replay_valid<=replay_consume;
            decoded_count<=decoded_count+(decoded_write_en ? 1'b1 : 1'b0)-(decoded_read_en ? 1'b1 : 1'b0);
            decoder_inflight<=decoder_inflight+(prefetch_fire ? 1'b1 : 1'b0)-(decoder_done ? 1'b1 : 1'b0);
            if(frame_request && configuration_ready && !command_present && !request_valid)capacity_fault<=1;
            if(prepare_start)begin
                command_present<=1;command_accepted<=0;input_ended<=0;
                frame_id_q<=frame_id;frame_rows_q<=frame_rows;frame_init_q<=frame_init;frame_final_q<=frame_final;
                replay_armed<=!frame_init;replay_active<=0;
                capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
                read_cursor<=(BANK_ADDR_BITS+1)'(initial_row);write_cursor<=(BANK_ADDR_BITS+1)'(initial_row);
                read_rotation<=ROTATION_BITS'(initial_bank);write_rotation<=ROTATION_BITS'(initial_bank);
            end
            if(frame_accept)begin
                if(!frame_ready || !frame_request || frame_id!=frame_id_q)capacity_fault<=1;
                command_accepted<=1;
            end
            if(encoder_start)capture_count<=capture_count+1;
            if(encode_commit_valid)begin
                commit_count<=commit_count+1;
                if(32'(write_rotation)+4>=pool_bank_count_q)begin
                    write_cursor<=write_cursor+1;write_rotation<=ROTATION_BITS'(32'(write_rotation)+4-pool_bank_count_q);
                end else write_rotation<=write_rotation+ROTATION_BITS'(4);
            end
            if(prefetch_fire)begin
                read_index<=read_index+1;
                if(32'(read_rotation)+4>=pool_bank_count_q)begin
                    read_cursor<=read_cursor+1;read_rotation<=ROTATION_BITS'(32'(read_rotation)+4-pool_bank_count_q);
                end else read_rotation<=read_rotation+ROTATION_BITS'(4);
            end
            if(write_frame_end)begin
                if(!command_accepted || replay_armed || (!frame_final_q && capture_count+(encoder_start ? 1 : 0)!=frame_rows_q))capacity_fault<=1;
                input_ended<=1;
            end
            if(decoded_write_en)decoded_write_pointer<=decoded_write_pointer+1'b1;
            if(decoded_read_en)decoded_read_pointer<=decoded_read_pointer+1'b1;
            if(replay_trigger && replay_armed && (command_accepted || frame_accept))begin replay_active<=1;replay_armed<=0;end
            if(replay_active)begin
                if(!replay_consume)capacity_fault<=1;
                else begin
                    replay_index<=replay_index+1;
                    if(replay_index+1==frame_rows_q)replay_active<=0;
                end
            end
            if(complete_now)begin
                frame_complete<=1;command_present<=0;command_accepted<=0;
                frame_valid[frame_id_q]<=!frame_final_q;frame_lengths[frame_id_q]<=frame_final_q ? 0 : frame_rows_q;
            end
        end
    end
endmodule
