// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb;
  localparam int p_sets = 16;
  localparam int p_set_width = $clog2(p_sets);
  logic rst_n, cfg_accept;
  logic [1:0] foreground_state;
  logic request_occupied, request_fire, input_valid, preview_selected;
  logic [3:0][p_set_width-1:0] source_set;
  logic [4*p_set_width-1:0] source_bits;
  logic [p_sets-1:0] stored_valid;
  logic metadata_enable, clearing, metadata_fill, fill_selected, fill_good, bypass, saved_valid;
  logic [p_set_width-1:0] clear_set, fill_set;
  logic current_valid, reference_valid, match;
  int checks = 0;
  int unsigned random_state = 32'h9c7f03d2;
  cache_preview_valid_compare #(.p_sets(p_sets)) dut (.*);
  assign source_set = source_bits;

  function automatic logic four_state(input int code);
    case (code)
      0: four_state = 1'b0;
      1: four_state = 1'b1;
      2: four_state = 1'bx;
      3: four_state = 1'bz;
    endcase
  endfunction
  function automatic int unsigned next_random();
    random_state = random_state ^ (random_state << 13);
    random_state = random_state ^ (random_state >> 17);
    random_state = random_state ^ (random_state << 5);
    return random_state;
  endfunction
  task automatic initialize_binary;
    {rst_n,cfg_accept,foreground_state,request_occupied,request_fire,input_valid,preview_selected} = 8'(next_random());
    source_bits = 16'(next_random());
    stored_valid = 16'(next_random());
    {metadata_enable,clearing,metadata_fill,fill_selected,fill_good,bypass,saved_valid} = 7'(next_random());
    {clear_set,fill_set} = 8'(next_random());
  endtask
  task automatic check;
    #1;
    if (current_valid !== reference_valid)
      $fatal(1,"valid mismatch case=%0d controls=%b sources=%h stored=%h current=%b reference=%b",
          checks,{rst_n,cfg_accept,foreground_state,request_occupied,request_fire,input_valid,preview_selected},
          source_set,stored_valid,current_valid,reference_valid);
    checks++;
  endtask
  initial begin
    // 完整枚举读取、复位和配置控制的四态组合，交替覆盖写入和保留数据。
    for (int scenario = 0; scenario < 65536; scenario++) begin
      for (int pattern = 0; pattern < 4; pattern++) begin
        initialize_binary();
        {rst_n,cfg_accept,foreground_state,request_occupied,request_fire,input_valid,preview_selected} =
            {four_state((scenario>>14)&3),four_state((scenario>>12)&3),
             four_state((scenario>>10)&3),four_state((scenario>>8)&3),
             four_state((scenario>>6)&3),four_state((scenario>>4)&3),
             four_state((scenario>>2)&3),four_state(scenario&3)};
        case(pattern)
          0: begin metadata_enable=0; stored_valid='0; end
          1: begin metadata_enable=0; stored_valid='1; end
          2: begin metadata_enable=1; clearing=1; fill_good=1; clear_set=source_set[3]; end
          3: begin metadata_enable=1; clearing=0; metadata_fill=1; fill_selected=1;
                   fill_set=source_set[1]; end
        endcase
        check();
      end
    end
    // 二值控制下逐位覆盖未知地址、未知存储值及未知写入资格。
    for (int scenario = 0; scenario < 20000; scenario++) begin
      initialize_binary();
      for (int bit_index=0;bit_index<16;bit_index++) begin
        if ((next_random()&7)==0)
          source_bits[bit_index]=four_state(2+int'(next_random()&1));
        if ((next_random()&7)==0)
          stored_valid[bit_index]=four_state(2+int'(next_random()&1));
      end
      case(scenario%8)
        0: metadata_enable=four_state(2+(scenario&1));
        1: clearing=four_state(2+(scenario&1));
        2: metadata_fill=four_state(2+(scenario&1));
        3: fill_selected=four_state(2+(scenario&1));
        4: fill_good=four_state(2+(scenario&1));
        5: bypass=four_state(2+(scenario&1));
        6: clear_set[scenario%p_set_width]=four_state(2+(scenario&1));
        7: fill_set[scenario%p_set_width]=four_state(2+(scenario&1));
      endcase
      saved_valid=four_state(int'(next_random()&3));
      check();
    end
    $display("CACHE_PREVIEW_VALID_PASS checks=%0d",checks);
    $finish;
  end
endmodule
