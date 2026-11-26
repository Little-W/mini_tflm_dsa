// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同一有效位存储下比较按地址选择与按读出结果选择的行为。
module cache_preview_valid_compare #(
  parameter int p_sets = 16,
  parameter int p_set_width = $clog2(p_sets)
) (
  input logic rst_n, cfg_accept,
  input logic [1:0] foreground_state,
  input logic request_occupied, request_fire, input_valid, preview_selected,
  input logic [3:0][p_set_width-1:0] source_set,
  input logic [p_sets-1:0] stored_valid,
  input logic metadata_enable, clearing, metadata_fill, fill_selected,
  input logic fill_good, bypass, saved_valid,
  input logic [p_set_width-1:0] clear_set, fill_set,
  output logic current_valid, reference_valid,
  output logic match
);
  logic read_input;
  logic [2:0] request_select;
  logic [p_set_width-1:0] selected_request, selected_set;
  logic write_enable, write_value, clear_write, fill_write;
  logic [p_set_width-1:0] write_set;
  logic [3:0] source_valid, forwarded_valid;
  logic address_valid;

  assign read_input = !request_occupied ||
      (foreground_state != 2'd1 && request_fire && input_valid);
  assign request_select = {read_input && preview_selected,
      read_input && !preview_selected, !read_input};
  always_comb begin
    selected_request = (source_set[0] & {p_set_width{request_select[0]}}) |
        (source_set[1] & {p_set_width{request_select[1]}}) |
        (source_set[3] & {p_set_width{request_select[2]}});
    // 保留现有读源地址选择在未知状态下的条件优先级。
    if ((^{foreground_state, request_fire, input_valid, request_occupied,
             preview_selected, source_set[0], source_set[1], source_set[3]}) === 1'bx) begin
      selected_request = !request_occupied ?
          (preview_selected ? source_set[3] : source_set[1]) : source_set[0];
      if (foreground_state != 2'd1 && request_fire && request_occupied && input_valid)
        selected_request = preview_selected ? source_set[3] : source_set[1];
    end
  end
  assign selected_set = foreground_state == 2'd1 ? source_set[2] : selected_request;
  assign write_enable = rst_n && metadata_enable && (clearing || (metadata_fill && fill_selected));
  assign write_set = clearing ? clear_set : fill_set;
  assign write_value = !clearing && fill_good && !bypass;
  assign clear_write = rst_n && metadata_enable && clearing;
  assign fill_write = rst_n && metadata_enable && !clearing && metadata_fill && fill_selected;
  assign address_valid = write_enable && write_set == selected_set ? write_value : stored_valid[selected_set];

  for (genvar source = 0; source < 4; source++) begin : g_source
    conv_cache_valid_forward u_forward (
      .i_clear_write(clear_write), .i_clear_match(source_set[source] == clear_set),
      .i_fill_write(fill_write), .i_fill_match(source_set[source] == fill_set),
      .i_fill_valid(fill_good && !bypass), .i_stored_valid(stored_valid[source_set[source]]),
      .o_valid(forwarded_valid[source])
    );
    always_comb begin
      source_valid[source] = forwarded_valid[source];
      case (^{rst_n, metadata_enable, clearing, metadata_fill, fill_selected, fill_good, bypass})
        1'b0, 1'b1: begin end
        default: source_valid[source] = write_enable && write_set == source_set[source] ?
            write_value : stored_valid[source_set[source]];
      endcase
    end
  end
  conv_cache_lookup_valid_select u_current (
    .rst_n(rst_n), .i_cfg_accept(cfg_accept), .i_foreground_state(foreground_state),
    .i_request_occupied(request_occupied), .i_request_fire(request_fire),
    .i_input_valid(input_valid), .i_preview_selected(preview_selected),
    .i_source_valid(source_valid), .i_address_valid(address_valid),
    .i_saved_valid(saved_valid), .o_valid(current_valid)
  );
  always_comb begin
    reference_valid = address_valid;
    case (^{rst_n, cfg_accept})
      1'b0, 1'b1: begin end
      default: reference_valid = saved_valid;
    endcase
  end
  assign match = current_valid == reference_valid;
endmodule

`default_nettype wire
