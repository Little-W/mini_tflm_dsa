// SPDX-License-Identifier: Apache-2.0
// 地址参考模型按读取状态与数据类型选择分量，并保留完整加法的四态传播。
module reference(input logic clk, input logic[5:0] state,input logic[2:0] load_kind,
 input vector_engine_pkg::vector_engine_cfg_t c,
 input logic[31:0] pool_byte_offset,vector_offset,position_offset,input logic[15:0] channel_base,
 input logic[7:0] soft_lut_index_q,output logic[31:0] rd_base_addr,write_origin_next);
 typedef enum logic [5:0] {
    IDLE, CHECK, CONFIGURE, TILE_INIT, LOAD_REQ, LOAD_WAIT,
    OUTPUT_INIT, TAP_CHECK, WINDOW_WAIT, EXECUTE, TAP_NEXT,
    QUANT_INIT, AVG_START, AVG_WAIT, POOL_STORE, WRITE_PREP,
    OUTPUT_NEXT, VECTOR_INIT, VECTOR_NEXT, VECTOR_REDUCE, FAILED, DONE,
    ADD_MULT, ADD_DRAIN, ADD_ROUND, ADD_SUM, ADD_STORE,
    POOL_LOAD_PREP, POOL_LOAD_REQ, POOL_LOAD_WAIT,
    DRAIN, DRAIN_TILE, SOFT_START, SOFT_RUN, SOFT_LUT_REQ, SOFT_LUT_WAIT,
    CHECK_WAIT, QUANT_STREAM, EXECUTE_COMMIT, ADD_ROUND_WAIT, AVG_POWER_STORE, POOL_LOAD_DRAIN,
    DW_EXECUTE, DW_FINISH
  } state_t;
 typedef enum logic [2:0] {LD_WEIGHT, LD_BIAS, LD_MULT, LD_SHIFT, LD_A, LD_B, LD_LUT} load_t;
 logic[31:0] read_address_base,read_address_offset;logic[15:0] read_address_channel;logic[1:0] unused_read_address_carry;
   always_comb begin
    read_address_base = 32'd0;
    read_address_offset = 32'd0;
    read_address_channel = 16'd0;
    case (state)
      SOFT_LUT_REQ, SOFT_LUT_WAIT: begin
        read_address_base = c.rhs_base;
        read_address_offset = {22'd0, soft_lut_index_q, 2'b00};
      end
      POOL_LOAD_REQ, POOL_LOAD_WAIT: begin
        read_address_base = c.input_base;
        read_address_offset = pool_byte_offset;
        read_address_channel = channel_base;
      end
      default: begin
        case (load_kind)
          LD_WEIGHT: begin
            read_address_base = c.rhs_base;
            read_address_channel = channel_base;
          end
          LD_BIAS, LD_MULT, LD_SHIFT: begin
            case (load_kind)
              LD_BIAS: read_address_base = c.bias_base;
              LD_MULT: read_address_base = c.multiplier_base;
              default: read_address_base = c.shift_base;
            endcase
            read_address_offset = {14'd0, channel_base, 2'b00};
          end
          LD_A: begin
            read_address_base = c.input_base;
            read_address_offset = vector_offset << c.vector_s16;
          end
          LD_B: begin
            read_address_base = c.rhs_base;
            read_address_offset = vector_offset << c.vector_s16;
          end
          default: begin end
        endcase
      end
    endcase
  end
  vector_read_address_add_reference u_read_address (
    .clk(clk), .i_base(read_address_base), .i_offset(read_address_offset),
    .i_channel(read_address_channel), .o_address(rd_base_addr),
    .o_carry(unused_read_address_carry)
  );

  // 写回状态选择完整偏移，公共加法器生成最终输出地址。
  logic [31:0] write_address_offset;
  logic unused_write_origin_carry;
  always_comb begin
    write_address_offset = 32'd0;
    case (state)
      EXECUTE_COMMIT: write_address_offset = vector_offset << 2;
      ADD_STORE: write_address_offset = vector_offset;
      // 空间位置与通道号共同组成行偏移。
      QUANT_STREAM, AVG_POWER_STORE, AVG_WAIT, POOL_STORE, DW_FINISH:
        write_address_offset = position_offset + {16'd0, channel_base};
      default: begin end
    endcase
  end
  parallel_prefix_add #(.p_width(32), .p_preserve_groups(1'b1)) u_write_origin (
      .i_a(c.output_base), .i_b(write_address_offset), .i_carry(1'b0),
      .o_sum(write_origin_next), .o_carry(unused_write_origin_carry)
  );


endmodule
module vector_read_address_add_reference #(
`ifdef ASIC_SYNTHESIS
  parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
  parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
  parameter bit p_use_dsp = 1'b1
`else
  parameter bit p_use_dsp = 1'b0
`endif
) (
  input logic clk,
  input logic [31:0] i_base,
  input logic [31:0] i_offset,
  input logic [15:0] i_channel,
  output logic [31:0] o_address,
  output logic [1:0] o_carry
);
  logic [33:0] base_extended, offset_extended, channel_extended;
  logic [33:0] address_sum, address_carry, address_result;
  logic unused_address_carry;

  // 三项先压缩成两项，再以三位分组求和，保留两个地址进位位。
  assign base_extended = {2'b00, i_base};
  assign offset_extended = {2'b00, i_offset};
  assign channel_extended = {18'd0, i_channel};
  assign address_sum = base_extended ^ offset_extended ^ channel_extended;
  assign address_carry = ((base_extended & offset_extended) |
      (base_extended & channel_extended) | (offset_extended & channel_extended)) << 1;
  parallel_prefix_add #(.p_width(34), .p_group_width(3), .p_preserve_groups(1'b1)) u_address_sum (
      .i_a(address_sum), .i_b(address_carry), .i_carry(1'b0),
      .o_sum(address_result), .o_carry(unused_address_carry)
  );
  assign {o_carry, o_address} = address_result;
endmodule
