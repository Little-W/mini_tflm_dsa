`timescale 1ns/1ps

// One command selects an entire frame. Admission reserves a proved literal
// word bound before any old row is read. Rows use the existing II=1 codec.
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
    localparam integer BANKS = EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4;
    localparam integer BANK_DEPTH = EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64;
    localparam integer ROTATION_BITS = $clog2(BANKS)>0 ? $clog2(BANKS) : 1;
    localparam integer ACTIVE_BANK_BITS = $clog2(BANKS+1);
    localparam integer BANK_ADDR_BITS = $clog2(BANK_DEPTH) > 0 ? $clog2(BANK_DEPTH) : 1;
    localparam integer BANK_COUNT_BITS = $clog2(BANK_DEPTH+1);
    localparam integer FRAME_ID_BITS = $clog2(FRAME_COUNT) > 0 ? $clog2(FRAME_COUNT) : 1;
    localparam integer LENGTH_BITS = $clog2(MAX_FRAME_ROWS+1);
    localparam integer DIRECTORY_ADDR_BITS = $clog2(DIRECTORY_ROWS) > 0 ? $clog2(DIRECTORY_ROWS) : 1;
    localparam integer DIRECTORY_BITS = 3 + ROTATION_BITS + 4*BANK_ADDR_BITS;
    localparam integer FIFO_PTR_BITS = $clog2(DECODE_FIFO_ROWS) > 0 ? $clog2(DECODE_FIFO_ROWS) : 1;
    localparam integer FIFO_COUNT_BITS = $clog2(DECODE_FIFO_ROWS+1);
    localparam integer PREFETCH_CREDITS = DECODE_FIFO_ROWS-1;

    reg [DIRECTORY_BITS-1:0] directory [0:DIRECTORY_ROWS-1];
    reg [FRAME_COUNT-1:0] frame_valid;
    reg [LENGTH_BITS-1:0] frame_lengths [0:FRAME_COUNT-1];
    reg [2:0] frame_max_record_words [0:FRAME_COUNT-1];
    wire [LENGTH_BITS-1:0] frame_bank_words [0:BANKS-1][0:FRAME_COUNT-1];
    reg [BANK_DEPTH-1:0] free_bitmap [0:BANKS-1];
    reg [BANK_COUNT_BITS-1:0] bank_free_count [0:BANKS-1];
    reg [511:0] decoded_ram [0:DECODE_FIFO_ROWS-1];
    reg decoded_first [0:DECODE_FIFO_ROWS-1];

    reg command_present, command_accepted, input_ended;
    reg [FRAME_ID_BITS-1:0] frame_id_q;
    reg [LENGTH_BITS-1:0] frame_rows_q;
    reg [31:0] frame_reserve_rows_q;
    reg [2:0] frame_word_cap_q, current_max_record_words;
    reg frame_init_q, frame_final_q, frame_force_raw_q;
    reg [LENGTH_BITS-1:0] capture_count, commit_count, read_index, replay_index;
    reg replay_active, replay_armed;
    reg [ROTATION_BITS-1:0] write_rotation;
    reg [FIFO_PTR_BITS-1:0] decoded_write_pointer, decoded_read_pointer;
    reg [FIFO_COUNT_BITS-1:0] decoded_count, decoder_inflight;
    wire idle = !command_present;
    reg configuration_ready, configuration_pending;
    reg [BANK_COUNT_BITS-1:0] pool_bank_words_q;
    reg [ACTIVE_BANK_BITS-1:0] pool_bank_count_q;
    reg [LENGTH_BITS-1:0] directory_stride_q;
    reg [DIRECTORY_ADDR_BITS-1:0] directory_base_q;
    wire configuration_valid=cfg_pool_bank_words!=0 && cfg_pool_bank_words<=BANK_DEPTH &&
        cfg_pool_bank_count!=0 && cfg_pool_bank_count<=BANKS &&
        cfg_directory_stride!=0 && cfg_directory_stride<=MAX_FRAME_ROWS &&
        cfg_directory_stride<=DIRECTORY_ROWS;
    wire configuration_allowed=!command_present && frame_valid==0;
    wire configure_start=cfg_valid && configuration_allowed;
    wire initialize_external=(EXTERNAL_RAM!=0) && configuration_pending && !configure_start;
    wire clear_metadata=configure_start || initialize_external;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            configuration_ready<=EXTERNAL_RAM==0;
            configuration_pending<=0;
            pool_bank_words_q<=EXTERNAL_RAM==0 ? BANK_COUNT_BITS'(BANK_DEPTH) : 0;
            pool_bank_count_q<=EXTERNAL_RAM==0 ? ACTIVE_BANK_BITS'(BANKS) : 0;
            directory_stride_q<=LENGTH_BITS'(MAX_FRAME_ROWS);
        end else if (configure_start) begin
            configuration_ready<=EXTERNAL_RAM==0;
            configuration_pending<=EXTERNAL_RAM!=0;
            pool_bank_words_q<=EXTERNAL_RAM==0 ? BANK_COUNT_BITS'(BANK_DEPTH) : 0;
            pool_bank_count_q<=EXTERNAL_RAM==0 ? ACTIVE_BANK_BITS'(BANKS) : 0;
            directory_stride_q<=LENGTH_BITS'(MAX_FRAME_ROWS);
        end else if (initialize_external) begin
            configuration_ready<=1;
            configuration_pending<=0;
            pool_bank_words_q<=configuration_valid ? BANK_COUNT_BITS'(cfg_pool_bank_words) : 0;
            pool_bank_count_q<=configuration_valid ? ACTIVE_BANK_BITS'(cfg_pool_bank_count) : 0;
            directory_stride_q<=configuration_valid ? LENGTH_BITS'(cfg_directory_stride) : 0;
        end
    end

    function automatic [2:0] opcode_words;
        input [2:0] opcode;
        begin
            case (opcode)
                0: opcode_words=0;
                1: opcode_words=2;
                2: opcode_words=3;
                3: opcode_words=4;
                4: opcode_words=1;
                5: opcode_words=2;
                6: opcode_words=3;
                default: opcode_words=0;
            endcase
        end
    endfunction

    function automatic integer record_bank(input [ROTATION_BITS-1:0] rotation,input integer word_offset);
        integer sum;
        begin
            sum=int'(rotation)+word_offset;
            record_bank=sum>=int'(pool_bank_count_q) ? sum-int'(pool_bank_count_q) : sum;
        end
    endfunction

    reg request_valid, request_fits;
    reg [31:0] request_directory_base;
    integer directory_bit;
    always @* begin
        request_directory_base=0;
        for (directory_bit=0;directory_bit<FRAME_ID_BITS;directory_bit=directory_bit+1)
            if (frame_id[directory_bit])
                request_directory_base=request_directory_base+(32'(directory_stride_q)<<directory_bit);
    end
    wire request_directory_fits=frame_rows<=32'(directory_stride_q) &&
        {1'b0,request_directory_base}+33'(directory_stride_q)<=33'(DIRECTORY_ROWS);
    wire [31:0] request_reserve_rows=frame_reserve_rows>frame_rows ? frame_reserve_rows : frame_rows;
`ifdef PS_FORCE_RAW
    wire [2:0] request_word_cap=3'd4;
`elsif GEMMORA_PS_FORCE_RAW
    wire [2:0] request_word_cap=3'd4;
`else
    wire [2:0] request_word_cap=force_raw_i ? 3'd4 : frame_word_cap;
`endif
    wire [34:0] request_reserve_extended={3'b0,request_reserve_rows};
    wire [34:0] request_word_total=request_word_cap==2 ? (request_reserve_extended<<1) :
        request_word_cap==3 ? ((request_reserve_extended<<1)+request_reserve_extended) :
        (request_reserve_extended<<2);
    reg [34:0] request_bank_words;
    always @* begin
        case (32'(pool_bank_count_q))
            1: request_bank_words=request_word_total;
            2: request_bank_words=(request_word_total+1)>>1;
            3: request_bank_words=(request_word_total+2)/35'd3;
            4: request_bank_words=(request_word_total+3)>>2;
            5: request_bank_words=(request_word_total+4)/35'd5;
            6: request_bank_words=(request_word_total+5)/35'd6;
            7: request_bank_words=(request_word_total+6)/35'd7;
            8: request_bank_words=(request_word_total+7)>>3;
            default: request_bank_words={35{1'b1}};
        endcase
    end
    integer request_bank;
    always @* begin
        request_valid=32'(frame_id)<FRAME_COUNT && frame_rows!=0 && frame_rows<=MAX_FRAME_ROWS &&
            (frame_word_cap==2 || frame_word_cap==3 || frame_word_cap==4) &&
            (frame_final || 32'(request_word_cap)<=32'(pool_bank_count_q));
        request_fits=(frame_init && frame_final) || request_directory_fits;
        if (32'(frame_id)<FRAME_COUNT) begin
            if (frame_init) request_valid=request_valid && !frame_valid[frame_id];
            else request_valid=request_valid && frame_valid[frame_id] &&
                frame_rows==32'(frame_lengths[frame_id]) &&
                frame_max_record_words[frame_id]<=request_word_cap;
            for (request_bank=0;request_bank<BANKS;request_bank=request_bank+1)
                if (request_bank<int'(pool_bank_count_q) && !frame_final && 35'(bank_free_count[request_bank])+
                    (frame_init ? 35'd0 : 35'(frame_bank_words[request_bank][frame_id]))<request_bank_words)
                    request_fits=0;
        end else request_fits=0;
    end
    assign frame_pressure=frame_request && configuration_ready && !clear_metadata &&
        !command_present && !capacity_fault && request_valid && !request_fits;
    wire prepare_start=frame_request && configuration_ready && !clear_metadata &&
        !command_present && !capacity_fault && request_valid && request_fits;
    assign frame_ready=configuration_ready && !clear_metadata && command_present && !command_accepted && !capacity_fault &&
        (frame_init_q || decoded_count!=0);

    wire encoder_start=write_valid && !clear_metadata && command_accepted && !frame_final_q && !input_ended && !capacity_fault;
    wire encoder_busy, encoder_done;
    wire [2:0] encode_commit_opcode, encode_commit_words;
    wire [511:0] encode_commit_packet;
    wire [31:0] encode_row_ordinal=32'(commit_count)+1;
    wire [31:0] read_lead=EXTERNAL_RAM==0 ? 32'd1 :
        frame_word_cap_q==2 ? ((32'(pool_bank_count_q)+1)>>1) :
        frame_word_cap_q==3 ? ((32'(pool_bank_count_q)+2)/32'd3) :
        ((32'(pool_bank_count_q)+3)>>2);
    wire [31:0] required_read_rows=encode_row_ordinal+read_lead<32'(frame_rows_q) ?
        encode_row_ordinal+read_lead : 32'(frame_rows_q);
    wire commit_reclaim_ok=frame_init_q || required_read_rows<=32'(read_index);
    wire [BANKS-1:0] write_bank_mask;
    reg allocation_available;
    wire encode_commit_valid=encoder_done && !clear_metadata && !capacity_fault && command_accepted &&
        commit_count<frame_rows_q && commit_reclaim_ok && allocation_available &&
        encode_commit_words<=frame_word_cap_q;
    ps_adaptive_encoder u_encoder (
        .clk(clk),.rst_n(rst_n),.start(encoder_start),.row_first(capture_count==0),
        .force_raw(frame_force_raw_q),.row_data(write_data),.busy(encoder_busy),.done(encoder_done),
        .opcode(encode_commit_opcode),.words(encode_commit_words),.packet(encode_commit_packet)
    );

    wire [DIRECTORY_ADDR_BITS-1:0] read_directory_address=directory_base_q+DIRECTORY_ADDR_BITS'(read_index);
    wire [DIRECTORY_ADDR_BITS-1:0] write_directory_address=directory_base_q+DIRECTORY_ADDR_BITS'(commit_count);
    wire [DIRECTORY_BITS-1:0] read_descriptor=directory[read_directory_address];
    wire [2:0] prefetch_opcode=read_descriptor[2:0];
    wire [ROTATION_BITS-1:0] read_rotation=read_descriptor[3+:ROTATION_BITS];
    wire [2:0] prefetch_words=opcode_words(prefetch_opcode);
    wire prefetch_fire=command_present && !clear_metadata && !frame_init_q && read_index<frame_rows_q && !capacity_fault &&
        32'(decoded_count)+32'(decoder_inflight)<PREFETCH_CREDITS;
    wire [BANKS-1:0] payload_ram_write_en, payload_ram_read_en;
    wire [BANK_ADDR_BITS-1:0] allocated_address [0:BANKS-1];
    wire [BANK_ADDR_BITS-1:0] old_address [0:BANKS-1];
    wire [127:0] payload_read_data [0:BANKS-1];
    reg [DIRECTORY_BITS-1:0] write_descriptor;
    integer descriptor_bank;
    always @* begin
        write_descriptor=0;
        write_descriptor[2:0]=encode_commit_opcode;
        write_descriptor[3+:ROTATION_BITS]=write_rotation;
        allocation_available=1;
        for (descriptor_bank=0;descriptor_bank<BANKS;descriptor_bank=descriptor_bank+1) begin
            if (write_bank_mask[descriptor_bank] && bank_free_count[descriptor_bank]==0)
                allocation_available=0;
        end
        for (descriptor_bank=0;descriptor_bank<4;descriptor_bank=descriptor_bank+1) begin
            if (EXTERNAL_RAM==0)
                write_descriptor[3+ROTATION_BITS+descriptor_bank*BANK_ADDR_BITS +: BANK_ADDR_BITS]=allocated_address[descriptor_bank];
            else
                write_descriptor[3+ROTATION_BITS+descriptor_bank*BANK_ADDR_BITS +: BANK_ADDR_BITS]=
                    allocated_address[record_bank(write_rotation,descriptor_bank)];
        end
    end
    always @(posedge clk)
        if (encode_commit_valid) directory[write_directory_address]<=write_descriptor;

    genvar bank;
    generate for (bank=0;bank<BANKS;bank=bank+1) begin : g_payload
        reg [LENGTH_BITS-1:0] resident_words [0:FRAME_COUNT-1];
        reg [BANK_ADDR_BITS-1:0] allocation;
        reg found;
        integer address_index, initialize_index, frame_index;
        wire [ROTATION_BITS:0] write_offset=bank>=int'(write_rotation) ?
            (ROTATION_BITS+1)'(bank-int'(write_rotation)) :
            (ROTATION_BITS+1)'(bank+int'(pool_bank_count_q)-int'(write_rotation));
        wire [ROTATION_BITS:0] read_offset=bank>=int'(read_rotation) ?
            (ROTATION_BITS+1)'(bank-int'(read_rotation)) :
            (ROTATION_BITS+1)'(bank+int'(pool_bank_count_q)-int'(read_rotation));
        assign write_bank_mask[bank]=bank<int'(pool_bank_count_q) && 32'(write_offset)<32'(encode_commit_words);
        assign allocated_address[bank]=allocation;
        if (EXTERNAL_RAM==0) begin : g_internal_descriptor
            assign old_address[bank]=read_descriptor[3+ROTATION_BITS+bank*BANK_ADDR_BITS +: BANK_ADDR_BITS];
        end else begin : g_external_descriptor
            assign old_address[bank]=read_offset<4 ?
                read_descriptor[3+ROTATION_BITS+read_offset*BANK_ADDR_BITS +: BANK_ADDR_BITS] : 0;
        end
        assign payload_ram_write_en[bank]=encode_commit_valid && write_bank_mask[bank];
        assign payload_ram_read_en[bank]=prefetch_fire && bank<int'(pool_bank_count_q) && 32'(read_offset)<32'(prefetch_words);
        for (genvar resident=0;resident<FRAME_COUNT;resident=resident+1) begin : g_resident
            assign frame_bank_words[bank][resident]=resident_words[resident];
        end
        always @* begin
            allocation=0;
            found=0;
            for (address_index=0;address_index<BANK_DEPTH;address_index=address_index+1)
                if (!found && free_bitmap[bank][address_index]) begin
                    allocation=BANK_ADDR_BITS'(address_index);
                    found=1;
                end
        end
        wire [BANK_DEPTH-1:0] release_mask=payload_ram_read_en[bank] ?
            ({{(BANK_DEPTH-1){1'b0}},1'b1} << old_address[bank]) : {BANK_DEPTH{1'b0}};
        wire [BANK_DEPTH-1:0] allocation_mask=payload_ram_write_en[bank] ?
            ({{(BANK_DEPTH-1){1'b0}},1'b1} << allocation) : {BANK_DEPTH{1'b0}};
        if (EXTERNAL_RAM==0) begin : g_internal
            reg [127:0] payload_ram [0:BANK_DEPTH-1];
            reg [127:0] read_data;
            always @(posedge clk) begin
                if (payload_ram_write_en[bank])
                    payload_ram[allocation]<=encode_commit_packet[write_offset*128 +: 128];
                if (payload_ram_read_en[bank]) read_data<=payload_ram[old_address[bank]];
            end
            assign payload_read_data[bank]=read_data;
        end else begin : g_external
            assign payload_read_data[bank]=0;
        end
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) begin
                free_bitmap[bank]<=EXTERNAL_RAM==0 ? {BANK_DEPTH{1'b1}} : 0;
                bank_free_count[bank]<=EXTERNAL_RAM==0 ? BANK_COUNT_BITS'(BANK_DEPTH) : 0;
                for (frame_index=0;frame_index<FRAME_COUNT;frame_index=frame_index+1)
                    resident_words[frame_index]<=0;
            end else if (clear_metadata) begin
                for (initialize_index=0;initialize_index<BANK_DEPTH;initialize_index=initialize_index+1)
                    free_bitmap[bank][initialize_index]<=EXTERNAL_RAM==0 ||
                        (initialize_external && configuration_valid && bank<int'(cfg_pool_bank_count) && 32'(initialize_index)<cfg_pool_bank_words);
                bank_free_count[bank]<=EXTERNAL_RAM==0 ? BANK_COUNT_BITS'(BANK_DEPTH) :
                    (initialize_external && configuration_valid && bank<int'(cfg_pool_bank_count) ? BANK_COUNT_BITS'(cfg_pool_bank_words) : 0);
                for (frame_index=0;frame_index<FRAME_COUNT;frame_index=frame_index+1)
                    resident_words[frame_index]<=0;
            end else begin
                free_bitmap[bank]<=(free_bitmap[bank] | release_mask) & ~allocation_mask;
                bank_free_count[bank]<=BANK_COUNT_BITS'(32'(bank_free_count[bank])+
                    (payload_ram_read_en[bank] ? 1 : 0)-(payload_ram_write_en[bank] ? 1 : 0));
                if (payload_ram_read_en[bank] || payload_ram_write_en[bank])
                    resident_words[frame_id_q]<=LENGTH_BITS'(32'(resident_words[frame_id_q])+
                        (payload_ram_write_en[bank] ? 1 : 0)-(payload_ram_read_en[bank] ? 1 : 0));
            end
        end
`ifndef SYNTHESIS
        always @(posedge clk) if (rst_n) begin
            if (payload_ram_write_en[bank]) begin
                assert (found && free_bitmap[bank][allocation]) else $fatal(1,"PS allocation uses a live address");
                assert (32'(allocation)<32'(pool_bank_words_q)) else $fatal(1,"PS allocation exceeds bank depth");
            end
            if (payload_ram_read_en[bank]) begin
                assert (32'(old_address[bank])<32'(pool_bank_words_q) && !free_bitmap[bank][old_address[bank]])
                    else $fatal(1,"PS read does not own a bank address");
                assert (frame_bank_words[bank][frame_id_q]!=0) else $fatal(1,"PS frame bank count underflow");
            end
            assert (32'(bank_free_count[bank])<=BANK_DEPTH) else $fatal(1,"PS free count exceeds bank depth");
        end
`endif
    end endgenerate

    generate for (genvar port_word=0;port_word<4;port_word++) begin : g_ram_port
        if (EXTERNAL_RAM==0) begin : g_internal
            assign ram_read_en[port_word]=payload_ram_read_en[port_word];
            assign ram_write_en[port_word]=payload_ram_write_en[port_word];
            assign ram_read_addr[port_word]=RAM_ADDR_BITS'(old_address[port_word]);
            assign ram_write_addr[port_word]=RAM_ADDR_BITS'(allocated_address[port_word]);
            wire [1:0] offset=2'(port_word)-write_rotation;
            assign ram_write_data[port_word]=encode_commit_packet[offset*128+:128];
        end else begin : g_external
            wire [ROTATION_BITS-1:0] write_bank=ROTATION_BITS'(record_bank(write_rotation,port_word));
            wire [ROTATION_BITS-1:0] read_bank=ROTATION_BITS'(record_bank(read_rotation,port_word));
            wire [BANK_ADDR_BITS-1:0] read_address=read_descriptor[3+ROTATION_BITS+port_word*BANK_ADDR_BITS+:BANK_ADDR_BITS];
            assign ram_read_en[port_word]=prefetch_fire && port_word<int'(prefetch_words);
            assign ram_write_en[port_word]=encode_commit_valid && port_word<int'(encode_commit_words);
            assign ram_read_addr[port_word]=RAM_ADDR_BITS'({read_bank,read_address});
            assign ram_write_addr[port_word]=RAM_ADDR_BITS'({write_bank,allocated_address[write_bank]});
            assign ram_write_data[port_word]=encode_commit_packet[port_word*128+:128];
        end
    end endgenerate

    reg ram_read_valid, ram_read_first;
    reg [2:0] ram_read_opcode, ram_read_words;
    reg [ROTATION_BITS-1:0] ram_read_rotation;
    reg [511:0] decoder_packet;
    integer packet_word;
    always @* begin
        decoder_packet=0;
        for (packet_word=0;packet_word<4;packet_word=packet_word+1)
            if (packet_word<int'(ram_read_words))
                decoder_packet[packet_word*128 +: 128]=EXTERNAL_RAM!=0 ? ram_read_data[packet_word] :
                    payload_read_data[record_bank(ram_read_rotation,packet_word)];
    end
    wire decoder_busy, decoder_done, decoder_fault;
    wire [511:0] decoded_row;
    reg [4:0] decode_first_pipe;
    wire decoder_first=decode_first_pipe[4];
    ps_adaptive_decoder u_decoder (
        .clk(clk),.rst_n(rst_n),.start(ram_read_valid),.row_first(ram_read_first),
        .opcode(ram_read_opcode),.packet(decoder_packet),.busy(decoder_busy),.done(decoder_done),
        .fault(decoder_fault),.row_data(decoded_row)
    );

    wire decoded_read_en=replay_active && decoded_count!=0 && !capacity_fault;
    wire replay_bypass=replay_active && decoded_count==0 && decoder_done && !decoder_fault && !capacity_fault;
    wire decoded_write_en=decoder_done && !decoder_fault && !capacity_fault && !replay_bypass;
    wire replay_consume=decoded_read_en || replay_bypass;
    wire consumed_first=replay_bypass ? decoder_first : decoded_first[decoded_read_pointer];
    reg [511:0] decoded_ram_read_data, replay_bypass_data;
    reg replay_bypass_q;
    always @(posedge clk) begin
        if (decoded_write_en) begin
            decoded_ram[decoded_write_pointer]<=decoded_row;
            decoded_first[decoded_write_pointer]<=decoder_first;
        end
        if (decoded_read_en) decoded_ram_read_data<=decoded_ram[decoded_read_pointer];
        if (replay_bypass) replay_bypass_data<=decoded_row;
    end
    assign replay_data=replay_valid ? (replay_bypass_q ? replay_bypass_data : decoded_ram_read_data) : 512'b0;

    wire complete_now=command_present && command_accepted && input_ended && !capacity_fault &&
        !replay_active && !replay_armed && !encoder_busy && !decoder_busy && !ram_read_valid &&
        decoded_count==0 && decoder_inflight==0 &&
        (frame_final_q || commit_count==frame_rows_q) &&
        (frame_init_q || replay_index==frame_rows_q);
    integer reset_frame;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            capacity_fault<=0;frame_complete<=0;
            command_present<=0;command_accepted<=0;input_ended<=0;
            frame_id_q<=0;frame_rows_q<=0;frame_reserve_rows_q<=0;
            directory_base_q<=0;
            frame_word_cap_q<=4;current_max_record_words<=0;
            frame_init_q<=0;frame_final_q<=0;frame_force_raw_q<=0;
            capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            replay_active<=0;replay_armed<=0;write_rotation<=0;
            decoded_write_pointer<=0;decoded_read_pointer<=0;decoded_count<=0;decoder_inflight<=0;
            ram_read_valid<=0;ram_read_first<=0;ram_read_opcode<=0;ram_read_words<=0;ram_read_rotation<=0;
            decode_first_pipe<=0;replay_valid<=0;replay_bypass_q<=0;frame_valid<=0;
            for (reset_frame=0;reset_frame<FRAME_COUNT;reset_frame=reset_frame+1) begin
                frame_lengths[reset_frame]<=0;
                frame_max_record_words[reset_frame]<=0;
            end
        end else if (clear_metadata) begin
            capacity_fault<=initialize_external && !configuration_valid;
            frame_complete<=0;
            command_present<=0;command_accepted<=0;input_ended<=0;
            frame_id_q<=0;frame_rows_q<=0;frame_reserve_rows_q<=0;directory_base_q<=0;
            frame_word_cap_q<=4;current_max_record_words<=0;
            frame_init_q<=0;frame_final_q<=0;frame_force_raw_q<=0;
            capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
            replay_active<=0;replay_armed<=0;write_rotation<=0;
            decoded_write_pointer<=0;decoded_read_pointer<=0;decoded_count<=0;decoder_inflight<=0;
            ram_read_valid<=0;ram_read_first<=0;ram_read_opcode<=0;ram_read_words<=0;ram_read_rotation<=0;
            decode_first_pipe<=0;replay_valid<=0;replay_bypass_q<=0;frame_valid<=0;
            for (reset_frame=0;reset_frame<FRAME_COUNT;reset_frame=reset_frame+1) begin
                frame_lengths[reset_frame]<=0;
                frame_max_record_words[reset_frame]<=0;
            end
        end else begin
            frame_complete<=0;
            ram_read_valid<=prefetch_fire;
            decode_first_pipe<={decode_first_pipe[3:0],ram_read_valid && ram_read_first};
            replay_valid<=replay_consume;
            replay_bypass_q<=replay_bypass;
            decoded_count<=FIFO_COUNT_BITS'(32'(decoded_count)+(decoded_write_en ? 1 : 0)-(decoded_read_en ? 1 : 0));
            decoder_inflight<=FIFO_COUNT_BITS'(32'(decoder_inflight)+(prefetch_fire ? 1 : 0)-(decoder_done ? 1 : 0));

            if (cfg_valid && !configuration_allowed) capacity_fault<=1;
            if (frame_request && configuration_ready && !command_present && !request_valid) capacity_fault<=1;
            if (prepare_start) begin
                command_present<=1;
                command_accepted<=0;
                input_ended<=0;
                frame_id_q<=frame_id;
                directory_base_q<=DIRECTORY_ADDR_BITS'(request_directory_base);
                frame_rows_q<=LENGTH_BITS'(frame_rows);
                frame_reserve_rows_q<=request_reserve_rows;
                frame_word_cap_q<=request_word_cap;
                current_max_record_words<=0;
                frame_init_q<=frame_init;
                frame_final_q<=frame_final;
                frame_force_raw_q<=force_raw_i;
                capture_count<=0;commit_count<=0;read_index<=0;replay_index<=0;
                replay_armed<=!frame_init;
                if (decoded_count!=0 || decoder_inflight!=0 || encoder_busy || decoder_busy)
                    capacity_fault<=1;
            end
            if (frame_accept) begin
                if (!frame_request || !frame_ready || frame_id!=frame_id_q || frame_rows!=32'(frame_rows_q) ||
                    (!frame_final_q && request_reserve_rows!=frame_reserve_rows_q) ||
                    request_word_cap!=frame_word_cap_q ||
                    frame_init!=frame_init_q || frame_final!=frame_final_q || force_raw_i!=frame_force_raw_q)
                    capacity_fault<=1;
                command_accepted<=1;
            end
            if (encoder_start) capture_count<=capture_count+1'b1;
            if (write_valid && (!command_accepted || frame_final_q || input_ended || capture_count>=frame_rows_q))
                capacity_fault<=1;
            if (write_frame_end) begin
                if (!command_accepted || input_ended || replay_armed ||
                    (!frame_final_q && 32'(capture_count)+(encoder_start ? 1 : 0)!=32'(frame_rows_q)))
                    capacity_fault<=1;
                input_ended<=1;
            end
            if (encoder_done && (!encode_commit_valid || encode_commit_words>4 || encode_commit_opcode==7))
                capacity_fault<=1;
            if (encode_commit_valid) begin
                commit_count<=commit_count+1'b1;
                write_rotation<=ROTATION_BITS'(record_bank(write_rotation,int'(encode_commit_words)));
                if (encode_commit_words>current_max_record_words)
                    current_max_record_words<=encode_commit_words;
            end
            if (prefetch_fire) begin
                read_index<=read_index+1'b1;
                ram_read_first<=read_index==0;
                ram_read_opcode<=prefetch_opcode;
                ram_read_words<=prefetch_words;
                ram_read_rotation<=read_rotation;
                if (prefetch_opcode==7 || (read_index==0 && (prefetch_opcode==0 || prefetch_opcode>=4)))
                    capacity_fault<=1;
            end
            if (decoded_write_en) begin
                decoded_write_pointer<=32'(decoded_write_pointer)==DECODE_FIFO_ROWS-1 ? 0 : decoded_write_pointer+1'b1;
                if (32'(decoded_count)==DECODE_FIFO_ROWS && !decoded_read_en) capacity_fault<=1;
            end
            if (decoded_read_en)
                decoded_read_pointer<=32'(decoded_read_pointer)==DECODE_FIFO_ROWS-1 ? 0 : decoded_read_pointer+1'b1;
            if (decoder_done && (decoder_fault || decoder_inflight==0)) capacity_fault<=1;
            if (replay_trigger && replay_armed && (command_accepted || frame_accept)) begin
                replay_active<=1;
                replay_armed<=0;
            end
            if (replay_active) begin
                if (!replay_consume) capacity_fault<=1;
                if (replay_consume) begin
                    if (consumed_first!=(replay_index==0)) capacity_fault<=1;
                    replay_index<=replay_index+1'b1;
                    if (replay_index+1'b1==frame_rows_q) replay_active<=0;
                end
            end
            if (complete_now) begin
                frame_complete<=1;
                command_present<=0;
                command_accepted<=0;
                frame_valid[frame_id_q]<=!frame_final_q;
                frame_lengths[frame_id_q]<=frame_final_q ? 0 : frame_rows_q;
                frame_max_record_words[frame_id_q]<=frame_final_q ? 0 : current_max_record_words;
            end
        end
    end

`ifndef SYNTHESIS
    always @(posedge clk) if (rst_n) begin
        if (encode_commit_valid) begin
            assert (frame_init_q || required_read_rows<=32'(read_index))
                else $fatal(1,"PS replacement lacks the required old-row prefix");
            assert (encode_commit_words<=frame_word_cap_q)
                else $fatal(1,"PS record exceeds the selected word cap");
        end
        assert (32'(decoded_count)+32'(decoder_inflight)<=PREFETCH_CREDITS)
            else $fatal(1,"PS prefetch exceeds decoded capacity");
        if (frame_pressure)
            assert (!prefetch_fire && !encode_commit_valid) else $fatal(1,"PS pressure modified storage");
    end
    initial begin
        if (MAX_FRAME_ROWS<1 || FRAME_COUNT<1 || POOL_BYTES<64 || POOL_BYTES%64!=0 || DECODE_FIFO_ROWS<8 ||
            DIRECTORY_ROWS<1 || RAM_ADDR_BITS<BANK_ADDR_BITS || BANKS<1 || BANKS>8 ||
            (EXTERNAL_RAM!=0 && (BANK_BYTES<32 || (BANK_BYTES&(BANK_BYTES-1))!=0 ||
             POOL_BYTES%BANK_BYTES!=0 || RAM_ADDR_BITS<BANK_ADDR_BITS+ROTATION_BITS)))
            $fatal(1,"Invalid frame-store dimensions");
    end
`endif
endmodule
