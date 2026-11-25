`timescale 1ns/1ps
module tb;
  logic [33:0] value[8], delta[8];
  wire [33:0] actual[8], expected[8];
  integer comparisons = 0;

  coordinate_step_current dut(.coordinate_step_i_value(value),
      .coordinate_step_i_delta(delta), .coordinate_step_o_value(actual));
  coordinate_step_reference ref_dut(.coordinate_step_i_value(value),
      .coordinate_step_i_delta(delta), .coordinate_step_o_value(expected));

  task check;
    #1;
    for (integer lane = 0; lane < 8; lane++) begin
      if (actual[lane] !== expected[lane])
        $fatal(1, "coordinate differs lane=%0d value=%h delta=%h actual=%h expected=%h",
               lane, value[lane], delta[lane], actual[lane], expected[lane]);
      comparisons++;
    end
  endtask

  initial begin
    for (integer sample = 0; sample < 20000; sample++) begin
      for (integer lane = 0; lane < 8; lane++) begin
        value[lane] = {$urandom, $urandom};
        delta[lane] = {$urandom, $urandom};
        if (sample < 16) begin
          case (sample % 8)
            0: value[lane] = 0;
            1: value[lane] = 65535;
            2: value[lane] = 65536;
            3: value[lane] = 131071;
            4: value[lane] = -1;
            5: value[lane] = -131072;
            6: value[lane] = -65536;
            7: value[lane] = -65535;
          endcase
          delta[lane] = sample < 8 ? 0 : 65535;
        end else begin
          case (sample % 7)
            0: value[lane][sample % 34] = 1'bx;
            1: value[lane][sample % 34] = 1'bz;
            2: delta[lane][sample % 34] = 1'bx;
            3: delta[lane][sample % 34] = 1'bz;
            4: value[lane] = 'x;
            5: delta[lane] = 'z;
            default: ;
          endcase
        end
      end
      check();
    end
    $display("COORDINATE_FOUR_STATE_PASS comparisons=%0d", comparisons);
    $finish;
  end
endmodule
