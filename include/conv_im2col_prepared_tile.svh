// SPDX-License-Identifier: Apache-2.0
// 描述符的字段顺序由各阶段共同使用，位宽继承包含此文件的模块参数。
typedef struct packed {
  logic invalid, fast, padding, word_hit, output_position_update, output_wrap, kernel_last;
  logic geometry, narrow_output;
  logic [31:0] position, reduction, group_index;
  logic [p_prepared_count_w-1:0] rows, columns, active_columns;
  logic [p_prepared_slot_w-1:0] slot;
  logic [32:0] next_group, skip_group;
  logic [31:0] tap, channel;
  logic [15:0] kernel_x, kernel_y;
  logic signed [p_prepared_coord_w-1:0] input_x, input_y;
  logic [31:0] pixel, address, group_address;
  logic [15:0] output_x, output_y;
  logic [p_saved_group_lanes:0] channel_range;
  logic [8:0] padding_select, padding_value;
  logic [31-p_word_shift:0] word_address;
  logic saved_word_valid;
  logic [9:0] operation;
  logic row_wrap;
} prepared_tile_t;
