// SPDX-License-Identifier: Apache-2.0
// 遍历全部状态和数据类型，比较读写地址的随机数据与四态输入结果。
module tb;
  logic clk = 1'b0;
  logic [$bits(vector_engine_pkg::vector_engine_cfg_t)-1:0] random_config;
  logic [5:0] state;
  logic [2:0] load_kind;
  vector_engine_pkg::vector_engine_cfg_t c;
  logic [31:0] pool_byte_offset, vector_offset, position_offset;
  logic [15:0] channel_base;
  logic [7:0] soft_lut_index_q;
  wire [31:0] ref_address, new_address, ref_write_origin, new_write_origin;
  int checks = 0;

  reference u_ref (
      .clk(clk), .state(state), .load_kind(load_kind), .c(c),
      .pool_byte_offset(pool_byte_offset), .vector_offset(vector_offset),
      .position_offset(position_offset), .channel_base(channel_base),
      .soft_lut_index_q(soft_lut_index_q), .rd_base_addr(ref_address),
      .write_origin_next(ref_write_origin)
  );
  candidate u_dut (
      .clk(clk), .state(state), .load_kind(load_kind), .c(c),
      .pool_byte_offset(pool_byte_offset), .vector_offset(vector_offset),
      .position_offset(position_offset), .channel_base(channel_base),
      .soft_lut_index_q(soft_lut_index_q), .rd_base_addr(new_address),
      .write_origin_next(new_write_origin)
  );

  task automatic compare;
    #1;
    if (ref_address !== new_address)
      $fatal(1, "Read address state=%h kind=%h expected=%h actual=%h",
          state, load_kind, ref_address, new_address);
    if (ref_write_origin !== new_write_origin)
      $fatal(1, "Write address state=%h expected=%h actual=%h",
          state, ref_write_origin, new_write_origin);
    checks += 2;
  endtask

  task automatic randomize_values;
    for (int bit_index = 0; bit_index < $bits(c); bit_index++)
      random_config[bit_index] = 1'($urandom);
    c = random_config;
    pool_byte_offset = $urandom;
    vector_offset = $urandom;
    position_offset = $urandom;
    channel_base = 16'($urandom);
    soft_lut_index_q = 8'($urandom);
  endtask

  initial begin
    for (int state_code = 0; state_code < 64; state_code++) begin
      for (int kind_code = 0; kind_code < 8; kind_code++) begin
        state = 6'(state_code);
        load_kind = 3'(kind_code);
        for (int trial = 0; trial < 16; trial++) begin
          randomize_values();
          compare();
        end
        randomize_values(); c = 'x; compare(); c = 'z; compare();
        randomize_values(); pool_byte_offset = 'x; compare(); pool_byte_offset = 'z; compare();
        randomize_values(); vector_offset = 'x; compare(); vector_offset = 'z; compare();
        randomize_values(); position_offset = 'x; compare(); position_offset = 'z; compare();
        randomize_values(); channel_base = 'x; compare(); channel_base = 'z; compare();
        randomize_values(); soft_lut_index_q = 'x; compare(); soft_lut_index_q = 'z; compare();
        randomize_values(); c.input_base = 32'hx00f000z; compare();
        randomize_values(); c.output_base = 32'hx00f000z; compare();
      end
    end
    // 状态和读取类型中的未知位独立检查普通 case 的选择行为。
    for (int trial = 0; trial < 512; trial++) begin
      randomize_values();
      state = 6'($urandom);
      load_kind = 3'($urandom);
      state[trial % 6] = 1'bx; compare();
      state[trial % 6] = 1'bz; compare();
      state = 6'($urandom);
      load_kind[trial % 3] = 1'bx; compare();
      load_kind[trial % 3] = 1'bz; compare();
    end
    $display("ADDRESS_FOUR_STATE_PASS checks=%0d", checks);
    $finish;
  end
endmodule
