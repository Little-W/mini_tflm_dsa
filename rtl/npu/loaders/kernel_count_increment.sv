// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 五位分组和六组聚合形成并行进位，各结果位独立计算翻转条件。
module kernel_count_increment #(
    parameter int p_width = 48
) (
    input  wire logic [p_width-1:0] i_value,
    output logic [p_width-1:0] o_next
);
    localparam int p_chunk_bits = 5;
    localparam int p_block_chunks = 6;
    localparam int p_chunks = (p_width + p_chunk_bits - 1) / p_chunk_bits;
    localparam int p_blocks = (p_chunks + p_block_chunks - 1) / p_block_chunks;
    (* keep *) logic [p_chunks-1:0] chunk_all;
    (* keep *) logic [p_blocks-1:0] block_all;

    for (genvar block_index = 0; block_index < p_blocks; block_index++) begin : g_block
        localparam int p_low_chunk = block_index * p_block_chunks;
        localparam int p_block_width = p_chunks - p_low_chunk < p_block_chunks ?
            p_chunks - p_low_chunk : p_block_chunks;
        assign block_all[block_index] = &chunk_all[p_low_chunk +: p_block_width];
    end
    for (genvar chunk = 0; chunk < p_chunks; chunk++) begin : g_chunk
        localparam int p_low = chunk * p_chunk_bits;
        localparam int p_chunk_width = p_width - p_low < p_chunk_bits ?
            p_width - p_low : p_chunk_bits;
        localparam int p_block = chunk / p_block_chunks;
        localparam int p_inner = chunk % p_block_chunks;
        logic chunk_carry;
        assign chunk_all[chunk] = &i_value[p_low +: p_chunk_width];
        if (chunk == 0) begin : g_first
            assign chunk_carry = 1'b1;
        end else if (p_block == 0) begin : g_first_block
            assign chunk_carry = &chunk_all[chunk-1:0];
        end else if (p_inner == 0) begin : g_block_start
            assign chunk_carry = &block_all[p_block-1:0];
        end else begin : g_inside_block
            assign chunk_carry = (&block_all[p_block-1:0]) &&
                (&chunk_all[p_block*p_block_chunks +: p_inner]);
        end
        for (genvar bit_index = 0; bit_index < p_chunk_width; bit_index++) begin : g_bit
            if (bit_index == 0) begin : g_low
                assign o_next[p_low] = i_value[p_low] ^ chunk_carry;
            end else begin : g_high
                assign o_next[p_low+bit_index] = i_value[p_low+bit_index] ^
                    (chunk_carry && (&i_value[p_low +: bit_index]));
            end
        end
    end
endmodule

`default_nettype wire
