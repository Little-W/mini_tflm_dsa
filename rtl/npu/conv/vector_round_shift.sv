// SPDX-License-Identifier: Apache-2.0
// Signed round-to-nearest-even with a fixed six-stage shift-and-jam network.
module vector_round_shift #(
  parameter bit REGISTER_MIDDLE = 1'b0
) (
  input wire logic clk,
  input wire signed [63:0] value,
  input wire [5:0] amount,
  output wire signed [63:0] result,
  output wire signed [63:0] floor_value
);
  wire signed [65:0] shift0, shift1, shift2, shift4;
  wire signed [65:0] middle_data, shift8, shift16, shift32;
  wire [2:0] middle_amount;

  // The two low bits retain the guard and sticky information for exact rounding.
  assign shift0={value,2'b00};
  assign shift1=amount[0] ?
      {shift0[65],shift0[65:2],(|shift0[1:0])} : shift0;
  assign shift2=amount[1] ?
      {{2{shift1[65]}},shift1[65:3],(|shift1[2:0])} : shift1;
  assign shift4=amount[2] ?
      {{4{shift2[65]}},shift2[65:5],(|shift2[4:0])} : shift2;

  generate
    if (REGISTER_MIDDLE) begin : g_middle_register
      logic signed [65:0] data;
      logic [2:0] remaining_amount;
      always_ff @(posedge clk) begin
        data<=shift4;
        remaining_amount<=amount[5:3];
      end
      assign middle_data=data;
      assign middle_amount=remaining_amount;
    end else begin : g_middle_combinational
      assign middle_data=shift4;
      assign middle_amount=amount[5:3];
    end
  endgenerate

  assign shift8=middle_amount[0] ?
      {{8{middle_data[65]}},middle_data[65:9],(|middle_data[8:0])} : middle_data;
  assign shift16=middle_amount[1] ?
      {{16{shift8[65]}},shift8[65:17],(|shift8[16:0])} : shift8;
  assign shift32=middle_amount[2] ?
      {{32{shift16[65]}},shift16[65:33],(|shift16[32:0])} : shift16;
  wire increment=shift32[1] && (shift32[0] || shift32[2]);
  assign floor_value=$signed(shift32[65:2]);
  assign result=floor_value+64'(increment);
endmodule
