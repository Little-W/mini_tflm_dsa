// SPDX-License-Identifier: Apache-2.0
module tb;
  reg clk = 0;
  reg signed [63:0] value, known, delayed_value;
  reg [5:0] amount, delayed_amount;
  wire signed [63:0] old_result[4], new_result[4], old_floor[4], new_floor[4];
  integer checks = 0, seed = 32'h174be82a;

  always @(posedge clk) begin
    delayed_value <= value;
    delayed_amount <= amount;
  end
  for (genvar middle = 0; middle < 2; middle++) begin : g_middle
    for (genvar input_stage = 0; input_stage < 2; input_stage++) begin : g_input
      localparam int INDEX = 2 * middle + input_stage;
      wire signed [63:0] reference_value;
      wire [5:0] reference_amount;
      assign reference_value = input_stage ? delayed_value : value;
      assign reference_amount = input_stage ? delayed_amount : amount;
      round_reference #(.REGISTER_MIDDLE(middle)) u_old (
          .clk(clk), .value(reference_value),
          .amount(reference_amount),
          .result(old_result[INDEX]), .floor_value(old_floor[INDEX]));
      round_current #(.REGISTER_MIDDLE(middle), .REGISTER_INPUT(input_stage)) u_new (
          .clk(clk), .value(value), .amount(amount),
          .result(new_result[INDEX]), .floor_value(new_floor[INDEX]));
    end
  end

  task check;
    begin
      #1; clk = 1; #1;
      for (integer stage = 0; stage < 4; stage++) begin
        if (old_result[stage] !== new_result[stage] || old_floor[stage] !== new_floor[stage])
          $fatal(1, "Four-state mismatch stage=%0d value=%h amount=%b old=%h new=%h",
                 stage, value, amount, old_result[stage], new_result[stage]);
      end
      checks = checks + 1;
      clk = 0; #1;
    end
  endtask

  initial begin
    for (integer sample = 0; sample < 256; sample++) begin
      known = {$random(seed), $random(seed)};
      if (sample == 0) known = '0;
      if (sample == 1) known = '1;
      if (sample == 2) known = 64'h8000_0000_0000_0000;
      if (sample == 3) known = 64'h7fff_ffff_ffff_ffff;
      for (integer shift = 0; shift < 64; shift++) begin
        amount = 6'(shift); value = known; check();
        if (sample < 4) begin
          for (integer bit_i = 0; bit_i < 64; bit_i++) begin
            value = known; value[bit_i] = 1'bx; check();
            value = known; value[bit_i] = 1'bz; check();
          end
        end
      end
      for (integer bit_i = 0; bit_i < 6; bit_i++) begin
        value = known; amount = '0; amount[bit_i] = 1'bx; check();
        amount = '1; amount[bit_i] = 1'bz; check();
      end
    end
    for (integer shift = 0; shift < 64; shift++) begin
      amount = 6'(shift); value = 'x; check(); value = 'z; check();
    end
    $display("ROUND_PIPELINE_FOUR_STATE_PASS checks=%0d configurations=4 outputs=2", checks);
    $finish;
  end
endmodule
