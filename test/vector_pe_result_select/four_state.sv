`timescale 1ns/1ps
module tb #(parameter int p_trials=2048);
  logic clk=0, i_en=0;
  logic [2:0] i_op;
  logic signed [15:0] i_a, i_b;
  logic signed [31:0] i_acc;
  wire signed [31:0] result[4], reference_result[4];
  logic [66:0] stimulus, saved;
  logic [31:0] rng=32'h83bc7325;
  integer checks=0, samples=0, hold_checks=0;

  assign {i_op,i_a,i_b,i_acc}=stimulus;
  for (genvar configuration=0; configuration<4; configuration++) begin : g_configuration
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(configuration/2),
                .p_accumulator_preselected(configuration%2)) u_current (
      .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(result[configuration]));
    reference_pe #(.ENABLE_EXTENDED_MULTIPLY(configuration/2),
                   .p_accumulator_preselected(configuration%2)) u_reference (
      .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(reference_result[configuration]));
  end
  task automatic sample(input logic enabled);
    logic [31:0] previous[4];
    for (integer configuration=0; configuration<4; configuration++)
      previous[configuration]=result[configuration];
    i_en=enabled; clk=0; #1; clk=1; #1;
    for (integer configuration=0; configuration<4; configuration++) begin
      if (result[configuration] !== reference_result[configuration])
        $fatal(1,"PE result mismatch configuration=%0d sample=%0d",configuration,samples);
      checks++;
      if (enabled !== 1'b1) begin
        if (result[configuration] !== previous[configuration]) $fatal(1,"PE hold mismatch");
        hold_checks++;
      end
    end
    samples++; clk=0; #1;
  endtask
  initial begin
    // 未接收操作数时同时检查原始未知状态；接收后逐位注入 X 和 Z。
    stimulus='0; sample(1'b0); sample(1'bx); sample(1'bz); sample(1'b1);
    for (integer trial=0; trial<p_trials; trial++) begin
      for (integer bit_index=0; bit_index<67; bit_index++) begin
        rng=rng^(rng<<13); rng=rng^(rng>>17); rng=rng^(rng<<5);
        stimulus[bit_index]=rng[0];
      end
      sample(1'b1); saved=stimulus;
      for (integer bit_index=0; bit_index<67; bit_index++) begin
        stimulus=saved; stimulus[bit_index]=1'bx; sample(1'b1);
        stimulus=saved; stimulus[bit_index]=1'bz; sample(1'b1);
      end
      stimulus=~saved; sample(1'b0); sample(1'bx); sample(1'bz);
    end
    $display("PE_RESULT_FOUR_STATE_PASS samples=%0d checks=%0d hold_checks=%0d",samples,checks,hold_checks);
    $finish;
  end
endmodule
