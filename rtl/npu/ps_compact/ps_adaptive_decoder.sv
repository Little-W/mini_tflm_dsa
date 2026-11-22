// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每行包含十六个小端有符号 INT32 元素，启动事件独立接收。
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
    integer sparse_width;
    reg [31:0] sparse_value;
    reg sparse_width_required;
    always @* begin
        input_mask = 0;
        input_limit = 0;
        input_values = 0;
        input_fault = row_first && (opcode == 0 || (opcode >= 4 && opcode <= 6));
        input_position = 0;
        sparse_width = (int'(packet[17:16]) + 1) * 8;
        sparse_value = 0;
        sparse_width_required = packet[17:16] == 0;
        span_first = int'(packet[9:6]);
        span_count = int'(packet[13:10])+1;
        if (opcode == 7) begin
            input_limit = 10'd128;
            input_position = 18;
            for (input_lane = 0; input_lane < 16; input_lane = input_lane + 1) begin
                if (packet[input_lane]) begin
                    if (input_position + sparse_width > 128) input_fault = 1;
                    else begin
                        sparse_value = 32'(packet >> input_position);
                        case (packet[17:16])
                            2'd0: sparse_value = {{24{sparse_value[7]}},sparse_value[7:0]};
                            2'd1: sparse_value = {{16{sparse_value[15]}},sparse_value[15:0]};
                            2'd2: sparse_value = {{8{sparse_value[23]}},sparse_value[23:0]};
                            default: sparse_value = sparse_value;
                        endcase
                        if (sparse_value == 0) input_fault = 1;
                        if ((packet[17:16] == 1 && sparse_value != {{24{sparse_value[7]}},sparse_value[7:0]}) ||
                            (packet[17:16] == 2 && sparse_value != {{16{sparse_value[15]}},sparse_value[15:0]}) ||
                            (packet[17:16] == 3 && sparse_value != {{8{sparse_value[23]}},sparse_value[23:0]}))
                            sparse_width_required = 1;
                        input_values[input_lane*32 +: 32] = sparse_value;
                    end
                    input_position = input_position + sparse_width;
                end
            end
            if (!sparse_width_required) input_fault = 1;
        end else if (opcode >= 4 && opcode <= 6) begin
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
        else if (opcodes[3] == 7 && |padding_remaining) output_fault = 1;
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

`default_nettype wire
