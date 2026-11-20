`timescale 1ns/1ps
module tb_four_dsp;
  logic clk = 0;
  logic i_en;
  logic signed [31:0] i_a, i_b;
  logic signed [31:0] captured_a, captured_b;
  logic signed [63:0] candidate[4], reference[4], generic_product[4];
  logic signed [63:0] pending[4], expected[4];
  int enabled = 0;
  int held = 0;
  int checked = 0;
  logic signed [31:0] directed[18];
  for (genvar mode = 0; mode < 4; mode++) begin : g_mode
    registered_multiplier_s32 #(
      .p_use_dsp(1), .p_input_register(mode/2), .p_b_input_register(mode%2)
    ) u_candidate (.clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(candidate[mode]));
    registered_multiplier_s32 #(
      .p_use_dsp(0), .p_input_register(mode/2), .p_b_input_register(mode%2)
    ) u_generic (.clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(generic_product[mode]));
    registered_multiplier_s32_reference #(
      .p_use_dsp(1), .p_input_register(mode/2), .p_b_input_register(mode%2)
    ) u_reference (.clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(reference[mode]));
  end
  logic signed [63:0] scalar_candidate, scalar_reference, scalar_pending, scalar_expected;
  vector_scalar_multiplier #(.p_use_dsp(1)) u_scalar_candidate(
    .clk(clk), .a(i_a), .b(i_b), .product(scalar_candidate));
  vector_scalar_multiplier_reference #(.p_use_dsp(1)) u_scalar_reference(
    .clk(clk), .a(i_a), .b(i_b), .product(scalar_reference));
`ifdef CHECK_MAPPED
  logic signed [63:0] mapped_reference_product, mapped_candidate_product;
  mapped_reference u_mapped_reference(
    .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(mapped_reference_product));
  mapped_candidate u_mapped_candidate(
    .clk(clk), .i_en(i_en), .i_a(i_a), .i_b(i_b), .o_product(mapped_candidate_product));
`endif
  task automatic sample(input logic en, input logic signed [31:0] a, b);
    logic signed [63:0] lhs, rhs;
    i_en = en; i_a = a; i_b = b;
    scalar_expected = scalar_pending;
    scalar_pending = 64'(a) * 64'(b);
    if (en) begin
      for (int mode = 0; mode < 4; mode++) begin
        expected[mode] = pending[mode];
        lhs = (mode/2) ? 64'(captured_a) : 64'(a);
        rhs = (mode%2) ? 64'(captured_b) : 64'(b);
        pending[mode] = lhs * rhs;
      end
      captured_a = a; captured_b = b;
      enabled++;
    end else held++;
    #1; clk = 1; #1;
    if (enabled > 3) begin
      for (int mode = 0; mode < 4; mode++) begin
        if (candidate[mode] !== expected[mode] || reference[mode] !== expected[mode] || generic_product[mode] !== expected[mode])
          $fatal(1,"Product mismatch mode=%0d cycle=%0d expected=%h candidate=%h reference=%h",
                 mode,checked,expected[mode],candidate[mode],reference[mode]);
      end
      if (scalar_candidate !== scalar_expected || scalar_reference !== scalar_expected)
        $fatal(1,"Scalar product mismatch cycle=%0d expected=%h reference=%h candidate=%h",
               checked,scalar_expected,scalar_reference,scalar_candidate);
`ifdef CHECK_MAPPED
      if (mapped_reference_product !== expected[`MAPPED_MODE] || mapped_candidate_product !== expected[`MAPPED_MODE])
        $fatal(1,"Mapped product mismatch cycle=%0d expected=%h reference=%h candidate=%h",
               checked,expected[`MAPPED_MODE],mapped_reference_product,mapped_candidate_product);
`endif
      checked++;
    end
    clk = 0; #1;
  endtask
  initial begin
    int seed;
    seed = 32'h8749135a; seed = $urandom(seed);
    directed = '{32'sh80000000,32'sh7fffffff,-32'sd1,32'sd0,32'sd1,
      32'sh0001ffff,32'shfffe0000,32'sh00020000,32'sh8001ffff,32'sh7ffe0001,
      32'sh5555aaaa,32'shaaaa5555,32'sh00010000,32'shffff0000,
      32'sh0000ffff,32'sh00008000,32'shffff8000,32'sh80000001};
    repeat (11) sample(0,32'($urandom),32'($urandom));
    for (int a = 0; a < 18; a++) for (int b = 0; b < 18; b++) begin
      sample(1,directed[a],directed[b]); sample(0,~directed[a],~directed[b]);
    end
    for (int bit_a = 0; bit_a < 32; bit_a++) for (int bit_b = 0; bit_b < 32; bit_b++) begin
      sample(1,32'd1 << bit_a,32'd1 << bit_b);
      sample(0,~(32'd1 << bit_a),32'd1 << bit_b);
      sample(1,32'd1 << bit_a,~(32'd1 << bit_b));
    end
    for (int lower = 0; lower < 131072; lower++) begin
      sample(1,{15'h3fff,17'(lower)},32'sh8001ffff);
      sample(1,{15'h4000,17'(lower)},32'sh7fffffff);
      sample(0,32'($urandom),32'($urandom));
    end
    for (int cycle = 0; cycle < 1000000; cycle++)
      sample((cycle%97 < 81) && ($urandom_range(0,7) != 0),32'($urandom),32'($urandom));
    repeat (4) sample(1,0,0);
    $display("FOUR_DSP_PASS checks=%0d enabled=%0d held=%0d modes=4",checked,enabled,held);
    $finish;
  end
endmodule
