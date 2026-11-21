// SPDX-License-Identifier: Apache-2.0
// 完整组范围下一值，保持全部状态编码和控制优先次序。
// source_sha256: b3325d6ce4678fc10cc8b6d94b059d567f23e4e4495c361cbf98444182c6b265
module range_reference #(parameter int SIZE=16,LANES=8,TILE_COUNT_W=$clog2(SIZE+1),
CHUNK_COUNT_W=$clog2(LANES+1),p_saved_group_lanes=LANES>4 && LANES<=8 ? 8 : 4)(
input logic [21:0] state,
input conv_im2col_pkg::conv_cfg_t c,
input logic rst_n,cfg_valid,cfg_ready,tile_commit,tile_invalid,tile_fast,
input logic cache_rsp_valid,cache_rsp_error,wr_valid,wr_ready,chunk_reaches_end,
input logic row_last_q,past_active_q,group_end_o_equal,group_shape_o_valid,
input logic [31:0] q0,decode_index,
input logic [CHUNK_COUNT_W-1:0] chunk_count,
input logic [TILE_COUNT_W-1:0] active_remaining,
input logic [p_saved_group_lanes:0] tile_channel_range,group_range_q,group_range_cfg,
input logic [5:0][p_saved_group_lanes:0] group_range_next,output logic [p_saved_group_lanes:0] result);
  typedef enum logic [21:0] {
    IDLE = 22'h000001,
    P_DECODE = 22'h000002,
    P_START = 22'h000004,
    P_WAIT = 22'h000008,
    Q_DECODE = 22'h000010,
    Q_START = 22'h000020,
    Q_WAIT = 22'h000040,
    K_DECODE = 22'h000080,
    K_START = 22'h000100,
    K_WAIT = 22'h000200,
    COORD = 22'h000400,
    COORD_SUM = 22'h000800,
    COORD_PAD = 22'h001000,
    ADDRESS = 22'h002000,
    ADDRESS_PIXEL = 22'h004000,
    ADDRESS_PRODUCT = 22'h008000,
    ADDRESS_BASE = 22'h010000,
    ADDRESS_CHANNEL = 22'h020000,
    FETCH = 22'h040000,
    WAIT_WORD = 22'h080000,
    STREAM = 22'h100000,
    ZERO_STREAM = 22'h200000
  } st_t;
typedef struct packed {
  logic invalid,fast;
  logic[p_saved_group_lanes:0] channel_range;
} tile_t;
tile_t committing_tile;
assign committing_tile={tile_invalid,tile_fast,tile_channel_range};
  // 行切换、组切换和通道递增先选择范围，写入握手只控制最终保存。
  (* keep = 1 *) logic [p_saved_group_lanes:0] group_range_stream_value;
  assign group_range_stream_value = chunk_reaches_end ? group_range_next[1] :
    group_end_o_equal ? group_range_next[0] : group_range_next[5];


always_comb begin
result=group_range_q;
begin
if (!rst_n) begin
result = '0;
end else begin
if (cfg_valid && cfg_ready) begin
result = group_range_cfg;
end else if (tile_commit) begin
if (committing_tile.invalid) ; else begin
if (committing_tile.fast) begin
result = committing_tile.channel_range;
end
end
end else case (1'b1)
state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: begin
if (state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) ; else if (wr_valid && wr_ready) begin
if (chunk_reaches_end) begin
if (row_last_q) ; else begin
result = group_range_stream_value;
end
end else begin
if (past_active_q || TILE_COUNT_W'(chunk_count)>=active_remaining) ; else if (group_end_o_equal) begin
result = group_range_stream_value;
end else begin
result = group_range_stream_value;
end
end
end
end
default: ;
endcase
case (1'b1)
state[$clog2(P_DECODE)]: ;
state[$clog2(P_START)]: ;
state[$clog2(P_WAIT)]: ;
state[$clog2(Q_DECODE)]: begin
if (q0==0) begin
result = group_range_next[0];
end else if (group_shape_o_valid) begin
result = group_range_next[2];
end else if (c.group_c==3 && q0<27) begin
result = group_range_next[3];
end
end
state[$clog2(Q_START)]: ;
state[$clog2(Q_WAIT)]: if (decode_index==q0) begin
result = group_range_next[4];
end
state[$clog2(K_DECODE)]: ;
state[$clog2(K_START)]: ;
state[$clog2(K_WAIT)]: ;
state[$clog2(COORD)]: ;
state[$clog2(COORD_SUM)]: ;
state[$clog2(COORD_PAD)]: ;
state[$clog2(ADDRESS)]: ;
state[$clog2(ADDRESS_PIXEL)]: ;
state[$clog2(ADDRESS_PRODUCT)]: ;
state[$clog2(ADDRESS_BASE)]: ;
state[$clog2(ADDRESS_CHANNEL)]: ;
state[$clog2(FETCH)]: ;
state[$clog2(IDLE)], state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: ;
default: ;
endcase
end
end
end
endmodule
