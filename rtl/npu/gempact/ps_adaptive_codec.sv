`timescale 1ns/1ps

// A row contains sixteen little-endian signed 32-bit lanes. Each start is
// accepted independently; busy reports pipeline occupancy and is not ready.
module ps_adaptive_encoder (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    input  wire         row_first,
    input  wire         force_raw,
    input  wire [511:0] row_data,
    output wire         busy,
    output reg          done,
    output reg  [2:0]   opcode,
    output reg  [2:0]   words,
    output reg  [511:0] packet
);
    reg [511:0] previous;
    reg [2:0] valid;
    reg [511:0] s1_row, s1_folded;
    reg [15:0] s1_mask;
    reg [4:0] s1_k;
    reg [2:0] s1_literal;
    reg s1_first, s1_force_raw;

    reg [511:0] s2_folded, s2_prefix;
    reg [159:0] s2_positions;
    reg [15:0] s2_mask;
    reg [4:0] s2_k;
    reg [2:0] s2_opcode, s2_words;

    reg [511:0] s3_groups [0:3];
    reg [2:0] s3_opcode, s3_words;

    reg [511:0] input_folded;
    reg [15:0] input_mask;
    reg [4:0] input_k;
    reg [2:0] input_literal;
    reg input_s16, input_s24;
    reg [31:0] difference, folded;
    integer max_width, width, i, bit_index;
    always @* begin
        input_folded = 0;
        input_mask = 0;
        input_s16 = 1;
        input_s24 = 1;
        max_width = 0;
        difference = 0;
        folded = 0;
        width = 0;
        for (i = 0; i < 16; i = i + 1) begin
            difference = row_data[i*32 +: 32] - previous[i*32 +: 32];
            folded = (difference << 1) ^ (32'b0 - {31'b0,difference[31]});
            input_folded[i*32 +: 32] = folded;
            input_mask[i] = (difference != 0);
            width = 0;
            for (bit_index = 0; bit_index < 32; bit_index = bit_index + 1)
                if (folded[bit_index]) width = bit_index + 1;
            if (width > max_width) max_width = width;
            if (row_data[i*32+16 +: 16] != {16{row_data[i*32+15]}})
                input_s16 = 0;
            if (row_data[i*32+24 +: 8] != {8{row_data[i*32+23]}})
                input_s24 = 0;
        end
        input_k = max_width > 2 ? 5'(max_width - 2) : 5'd0;
        input_literal = input_s16 ? 3'd1 : input_s24 ? 3'd2 : 3'd3;
    end

    reg [511:0] choose_prefix;
    reg [159:0] choose_positions;
    reg [15:0] choose_mask, span_mask;
    reg [2:0] choose_opcode, choose_words;
    integer first_lane, last_lane, mask_bits, span_bits, mask_words;
    integer span_words, position, q, lane;
    reg choose_span;
    always @* begin
        choose_prefix = 0;
        choose_positions = 0;
        choose_mask = 0;
        span_mask = 0;
        choose_opcode = s1_literal;
        choose_words = s1_literal + 3'd1;
        choose_span = 0;
        first_lane = 16;
        last_lane = 0;
        mask_bits = 22;
        span_bits = 14;
        q = 0;
        for (lane = 0; lane < 16; lane = lane + 1) begin
            if (s1_mask[lane]) begin
                if (first_lane == 16) first_lane = lane;
                last_lane = lane;
                q = s1_folded[lane*32 +: 32] >> s1_k;
                mask_bits = mask_bits + q + 1 + int'(s1_k);
            end
            if (s1_literal == 1)
                choose_prefix[lane*16 +: 16] = s1_row[lane*32 +: 16];
            else if (s1_literal == 2)
                choose_prefix[lane*24 +: 24] = s1_row[lane*32 +: 24];
            else
                choose_prefix[lane*32 +: 32] = s1_row[lane*32 +: 32];
        end
        for (lane = 0; lane < 16; lane = lane + 1) begin
            if (lane >= first_lane && lane <= last_lane) begin
                span_mask[lane] = 1;
                q = s1_folded[lane*32 +: 32] >> s1_k;
                span_bits = span_bits + q + 1 + int'(s1_k);
            end
        end
        mask_words = (mask_bits + 127) >> 7;
        span_words = (span_bits + 127) >> 7;
        if (!s1_first) begin
            if (s1_mask == 0) begin
                choose_opcode = 0;
                choose_words = 0;
                choose_prefix = 0;
            end else begin
                if (mask_words < int'(choose_words)) begin
                    choose_opcode = 3'(mask_words + 3);
                    choose_words = 3'(mask_words);
                    choose_mask = s1_mask;
                end
                if (span_words < int'(choose_words)) begin
                    choose_opcode = 3'(span_words + 3);
                    choose_words = 3'(span_words);
                    choose_mask = span_mask;
                    choose_span = 1;
                end
                if (choose_opcode >= 4) begin
                    choose_prefix = 0;
                    choose_prefix[4:0] = s1_k;
                    choose_prefix[5] = choose_span;
                    if (choose_span) begin
                        choose_prefix[9:6] = 4'(first_lane);
                        choose_prefix[13:10] = 4'(last_lane-first_lane);
                    end else choose_prefix[21:6] = s1_mask;
                end
            end
        end
`ifdef PS_FORCE_RAW
        choose_opcode = 3;
        choose_words = 4;
        choose_mask = 0;
        choose_prefix = s1_row;
`elsif GEMMORA_PS_FORCE_RAW
        choose_opcode = 3;
        choose_words = 4;
        choose_mask = 0;
        choose_prefix = s1_row;
`else
        if (s1_force_raw) begin
            choose_opcode = 3;
            choose_words = 4;
            choose_mask = 0;
            choose_prefix = s1_row;
        end
`endif
        position = choose_span ? 14 : 22;
        for (lane = 0; lane < 16; lane = lane + 1) begin
            choose_positions[lane*10 +: 10] = 10'(position);
            if (choose_mask[lane]) begin
                q = s1_folded[lane*32 +: 32] >> s1_k;
                position = position + q + 1 + int'(s1_k);
            end
        end
    end

    reg [511:0] pack_groups [0:3];
    reg [63:0] symbol;
    reg [31:0] remainder_mask;
    integer pack_lane, pack_group, quotient;
    always @* begin
        for (pack_group = 0; pack_group < 4; pack_group = pack_group + 1)
            pack_groups[pack_group] = 0;
        pack_groups[0] = s2_prefix;
        symbol = 0;
        quotient = 0;
        remainder_mask = (32'h1 << s2_k) - 1;
        for (pack_lane = 0; pack_lane < 16; pack_lane = pack_lane + 1) begin
            if (s2_mask[pack_lane]) begin
                quotient = s2_folded[pack_lane*32 +: 32] >> s2_k;
                symbol = (64'h1 << quotient) |
                    ({32'b0,(s2_folded[pack_lane*32 +: 32] & remainder_mask)} << (quotient+1));
                pack_groups[pack_lane/4] = pack_groups[pack_lane/4] |
                    ({448'b0,symbol} << s2_positions[pack_lane*10 +: 10]);
            end
        end
    end

    assign busy = (|valid) | done;
    integer group_index;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            previous <= 0;
            valid <= 0;
            done <= 0;
            opcode <= 0;
            words <= 0;
            packet <= 0;
            s1_row <= 0; s1_folded <= 0; s1_mask <= 0;
            s1_k <= 0; s1_literal <= 0; s1_first <= 0; s1_force_raw <= 0;
            s2_folded <= 0; s2_prefix <= 0; s2_positions <= 0;
            s2_mask <= 0; s2_k <= 0; s2_opcode <= 0; s2_words <= 0;
            s3_opcode <= 0; s3_words <= 0;
            for (group_index=0; group_index<4; group_index=group_index+1)
                s3_groups[group_index] <= 0;
        end else begin
            valid <= {valid[1:0],start};
            done <= valid[2];
            if (start) begin
                previous <= row_data;
                s1_row <= row_data;
                s1_folded <= input_folded;
                s1_mask <= input_mask;
                s1_k <= input_k;
                s1_literal <= input_literal;
                s1_first <= row_first;
                s1_force_raw <= force_raw;
            end
            if (valid[0]) begin
                s2_folded <= s1_folded;
                s2_prefix <= choose_prefix;
                s2_positions <= choose_positions;
                s2_mask <= choose_mask;
                s2_k <= s1_k;
                s2_opcode <= choose_opcode;
                s2_words <= choose_words;
            end
            if (valid[1]) begin
                for (group_index=0; group_index<4; group_index=group_index+1)
                    s3_groups[group_index] <= pack_groups[group_index];
                s3_opcode <= s2_opcode;
                s3_words <= s2_words;
            end
            if (valid[2]) begin
                packet <= s3_groups[0] | s3_groups[1] | s3_groups[2] | s3_groups[3];
                opcode <= s3_opcode;
                words <= s3_words;
            end
        end
    end
endmodule

module ps_adaptive_decoder (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    input  wire         row_first,
    input  wire [2:0]   opcode,
    input  wire [511:0] packet,
    output wire         busy,
    output reg          done,
    output reg          fault,
    output reg  [511:0] row_data
);
    // parsed: fault[522], bit position[521:512], lane values[511:0].
    function automatic [522:0] parse_group;
        input [511:0] data;
        input [15:0] mask;
        input [4:0] k;
        input [9:0] limit;
        input [522:0] initial_state;
        input integer first_lane;
        input enable;
        reg [511:0] values;
        reg failed, found;
        reg [31:0] folded_value, residual, low_bits;
        integer position, lane, j, quotient;
        begin
            values = initial_state[511:0];
            position = int'(initial_state[521:512]);
            failed = initial_state[522];
            folded_value = 0; residual = 0; low_bits = 0;
            found = 0; quotient = 0;
            for (lane=first_lane; lane<first_lane+4; lane=lane+1) begin
                if (enable && mask[lane] && !failed) begin
                    found = 0;
                    quotient = 0;
                    for (j=0; j<4; j=j+1) begin
                        if (!found) begin
                            if (position+j >= int'(limit)) failed = 1;
                            else if (data[position+j]) begin
                                found = 1;
                                quotient = j;
                            end
                        end
                    end
                    if (!found) failed = 1;
                    if (!failed) begin
                        position = position + quotient + 1;
                        if (position+int'(k) > int'(limit)) failed = 1;
                        else begin
                            low_bits = 32'(data >> position) & ((32'h1 << k)-1);
                            folded_value = (32'(quotient) << k) | low_bits;
                            residual = (folded_value >> 1) ^ (32'b0 - {31'b0,folded_value[0]});
                            values[lane*32 +: 32] = residual;
                            position = position + int'(k);
                        end
                    end
                end
            end
            parse_group = {failed,10'(position),values};
        end
    endfunction

    reg [3:0] valid;
    reg [511:0] previous;
    reg [511:0] packets [0:3];
    reg [15:0] masks [0:3];
    reg [4:0] parameters [0:3];
    reg [9:0] limits [0:3];
    reg [2:0] opcodes [0:3];
    reg [522:0] parsed [0:3];
    reg [15:0] input_mask;
    reg [9:0] input_limit;
    reg [522:0] input_initial, input_parsed;
    reg [511:0] input_values;
    reg input_fault;
    integer input_position, span_first, span_count, input_lane;
    always @* begin
        input_mask = 0;
        input_limit = 0;
        input_values = 0;
        input_fault = (opcode == 7) || (row_first && (opcode == 0 || opcode >= 4));
        input_position = 0;
        span_first = int'(packet[9:6]);
        span_count = int'(packet[13:10])+1;
        if (opcode >= 4 && opcode <= 6) begin
            input_limit = 10'((int'(opcode)-3)*128);
            if (packet[4:0] > 30) input_fault = 1;
            if (packet[5]) begin
                input_position = 14;
                if (span_first+span_count > 16) input_fault = 1;
                for (input_lane=0; input_lane<16; input_lane=input_lane+1)
                    input_mask[input_lane] = input_lane>=span_first && input_lane<span_first+span_count;
            end else begin
                input_position = 22;
                input_mask = packet[21:6];
            end
            if (input_mask == 0) input_fault = 1;
        end else begin
            for (input_lane=0; input_lane<16; input_lane=input_lane+1) begin
                if (opcode == 1)
                    input_values[input_lane*32 +: 32] = {{16{packet[input_lane*16+15]}},packet[input_lane*16 +: 16]};
                else if (opcode == 2)
                    input_values[input_lane*32 +: 32] = {{8{packet[input_lane*24+23]}},packet[input_lane*24 +: 24]};
                else if (opcode == 3)
                    input_values[input_lane*32 +: 32] = packet[input_lane*32 +: 32];
            end
        end
        input_initial = {input_fault,10'(input_position),input_values};
        input_parsed = parse_group(packet,input_mask,packet[4:0],input_limit,input_initial,0,opcode>=4 && opcode<=6);
    end

    reg [511:0] reconstructed;
    reg [511:0] padding_mask, padding_remaining;
    reg output_fault;
    integer output_lane;
    always @* begin
        reconstructed = parsed[3][511:0];
        output_fault = parsed[3][522];
        padding_mask = {512{1'b1}} >> (10'd512-limits[3]);
        padding_remaining = (packets[3] & padding_mask) >> parsed[3][521:512];
        if (opcodes[3] == 0) reconstructed = previous;
        else if (opcodes[3] >= 4 && opcodes[3] <= 6) begin
            for (output_lane=0; output_lane<16; output_lane=output_lane+1)
                reconstructed[output_lane*32 +: 32] = previous[output_lane*32 +: 32] + parsed[3][output_lane*32 +: 32];
            if (|padding_remaining) output_fault = 1;
        end
    end
    assign busy = (|valid) | done;
    integer stage;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid <= 0; previous <= 0; done <= 0; fault <= 0; row_data <= 0;
            for (stage=0; stage<4; stage=stage+1) begin
                packets[stage] <= 0; masks[stage] <= 0;
                parameters[stage] <= 0; limits[stage] <= 0;
                opcodes[stage] <= 0; parsed[stage] <= 0;
            end
        end else begin
            valid <= {valid[2:0],start};
            done <= valid[3];
            fault <= valid[3] && output_fault;
            if (start) begin
                packets[0] <= packet; masks[0] <= input_mask;
                parameters[0] <= packet[4:0]; limits[0] <= input_limit;
                opcodes[0] <= opcode; parsed[0] <= input_parsed;
            end
            for (stage=1; stage<4; stage=stage+1) begin
                if (valid[stage-1]) begin
                    packets[stage] <= packets[stage-1]; masks[stage] <= masks[stage-1];
                    parameters[stage] <= parameters[stage-1]; limits[stage] <= limits[stage-1];
                    opcodes[stage] <= opcodes[stage-1];
                    parsed[stage] <= parse_group(packets[stage-1],masks[stage-1],parameters[stage-1],
                        limits[stage-1],parsed[stage-1],stage*4,opcodes[stage-1]>=4 && opcodes[stage-1]<=6);
                end
            end
            if (valid[3]) begin
                row_data <= output_fault ? 512'b0 : reconstructed;
                if (!output_fault) previous <= reconstructed;
            end
        end
    end
endmodule
