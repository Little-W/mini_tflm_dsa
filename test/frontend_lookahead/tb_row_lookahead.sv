// SPDX-License-Identifier: Apache-2.0
// 检查连续像素候选的地址、行号顺序、空间边界、停顿和上下文清空。
module tb_row_lookahead;
  import conv_im2col_pkg::*;
  parameter int p_word_shift=4;
  localparam int p_word_bytes=1<<p_word_shift;
  logic i_clk=0, i_rst_n=1, i_clear=0;
  conv_cfg_t i_configuration;
  logic i_stream, i_row_eligible, i_row_wrap, i_narrow, i_past_active;
  logic [4:0] i_row,i_rows,i_column,i_columns,i_active_columns,i_next_row;
  logic [15:0] i_channel,i_initial_channel,i_next_input_x,i_output_x;
  logic [31:0] i_seed_address,i_seed_pixel,i_saved_address,i_saved_pixel;
  logic i_capture_ready;
  wire o_active,o_issue,o_preissued,o_continuing;
  wire reference_active,reference_issue,reference_preissued,reference_continuing;
  wire [31:0] o_address,o_pixel;
  logic [2:0] request_select;
  int checks=0, captures=0, stalls=0, clear_checks=0, four_state_checks=0;
  int unsigned random_state=32'h17d362ad;
  conv_im2col_row_lookahead #(.p_word_shift(p_word_shift)) dut(.*);
  conv_im2col_row_lookahead_reference #(.p_word_shift(p_word_shift)) u_reference (
    .o_active(reference_active),.o_issue(reference_issue),
    .o_preissued(reference_preissued),.o_continuing(reference_continuing),.*
  );
  always_comb begin
    request_select=3'b001;
    if(o_issue)request_select=o_continuing ? 3'b100 : 3'b010;
  end
  conv_im2col_request_payload #(.p_word_shift(p_word_shift)) u_payload (
    .i_select(request_select),.i_address(i_seed_address),.i_pixel(i_seed_pixel),
    .i_seed_address,.i_seed_pixel,.i_saved_address,.i_saved_pixel,.o_address,.o_pixel
  );

  function automatic int unsigned random_word;
    random_state^=random_state<<13;
    random_state^=random_state>>17;
    random_state^=random_state<<5;
    return random_state;
  endfunction
  function automatic logic value4(input integer value);
    case(value)
      0:return 1'b0;
      1:return 1'b1;
      2:return 1'bx;
      default:return 1'bz;
    endcase
  endfunction
  task automatic clock_edge;
    #1;i_clk=1;#1;
    if({o_active,o_issue,o_preissued,o_continuing} !==
       {reference_active,reference_issue,reference_preissued,reference_continuing})
      $fatal(1,"LOOKAHEAD_CONTROL_REFERENCE");
    i_clk=0;
  endtask
  task automatic clear_context;
    i_clear=1;
    #1;
    if(o_issue!==0 || o_preissued!==0) $fatal(1,"LOOKAHEAD_CLEAR_QUALIFICATION");
    clock_edge();
    #1;
    if(o_active!==0) $fatal(1,"LOOKAHEAD_CLEAR_STATE");
    clear_checks++;
    i_clear=0;
  endtask
  task automatic defaults;
    i_configuration='0;
    i_configuration.input_c=16'(p_word_bytes);
    i_configuration.group_c=16'(p_word_bytes);
    i_configuration.stride_w=1;
    i_configuration.input_w=16'd100;
    i_configuration.output_w=16'd100;
    i_configuration.input_base=32'h10000;
    i_stream=1;i_row_eligible=1;i_row_wrap=0;i_narrow=0;i_past_active=0;
    i_row=0;i_rows=16;i_next_row=1;i_column=0;
    i_columns=5'(p_word_bytes);i_active_columns=5'(p_word_bytes);
    i_channel=0;i_initial_channel=0;i_next_input_x=1;i_output_x=0;
    i_seed_address=32'h10000+p_word_bytes;i_seed_pixel=32'd1;
    i_saved_address=32'h10000;i_saved_pixel=0;i_capture_ready=1;
  endtask
  task automatic segment(input integer rows,input integer input_room,input integer output_room,
      input logic [31:0] base_address,input logic [31:0] base_pixel);
    integer issued,current_row,maximum_row;
    logic expected_issue,expected_preissued;
    logic [31:0] expected_address,expected_pixel;
    defaults();clear_context();
    i_rows=5'(rows);i_configuration.input_w=16'(input_room);
    i_configuration.output_w=16'(output_room);
    issued=0;current_row=0;
    maximum_row=rows-1;
    if(maximum_row>=input_room)maximum_row=input_room-1;
    if(maximum_row>=output_room)maximum_row=output_room-1;
    i_saved_address=base_address;i_saved_pixel=base_pixel;
    for(integer step=0;step<256;step++)begin
      i_row=5'(current_row);i_next_row=5'(current_row+1);
      i_next_input_x=16'(current_row+1);i_output_x=16'(current_row);
      i_seed_address=base_address+32'((current_row+1)*p_word_bytes);
      i_seed_pixel=base_pixel+32'(current_row+1);
      i_row_eligible=current_row<maximum_row;
      i_row_wrap=current_row+1>=output_room;
      i_capture_ready=value4(integer'(random_word()%4));
      expected_issue=issued<maximum_row;
      expected_preissued=current_row<issued;
      expected_address=base_address+32'((issued+1)*p_word_bytes);
      expected_pixel=base_pixel+32'(issued+1);
      #1;
      if(o_issue!==expected_issue || o_preissued!==expected_preissued)
        $fatal(1,"LOOKAHEAD_SEQUENCE_QUALIFICATION rows=%0d issued=%0d current=%0d step=%0d",rows,issued,current_row,step);
      if(expected_issue && (o_address!==expected_address || o_pixel!==expected_pixel))
        $fatal(1,"LOOKAHEAD_SEQUENCE_ADDRESS expected=%h actual=%h pixel_expected=%h actual=%h",expected_address,o_address,expected_pixel,o_pixel);
      checks++;
      if(o_issue && i_capture_ready===1'b1)begin
        i_saved_address=o_address;i_saved_pixel=o_pixel;
        issued++;
        captures++;
      end else if(o_issue)stalls++;
      clock_edge();
      if(current_row<issued && random_word()%3!=0)current_row++;
    end
    if(issued!=maximum_row || current_row!=maximum_row)
      $fatal(1,"LOOKAHEAD_SEQUENCE_COMPLETION");
    clear_context();
  endtask

  initial begin
    defaults();#1;i_rst_n=0;clock_edge();i_rst_n=1;
    for(integer rows=1;rows<=16;rows++)
      for(integer room=1;room<=17;room+=4)begin
        segment(rows,room,20,32'h10000,32'd735);
        segment(rows,20,room,32'hffff_ffc0,32'hffff_fff8);
      end
    // 四态格式和资格输入只允许明确有效的候选进入现有请求流水级。
    for(integer field=0;field<19;field++)
      for(integer value=0;value<4;value++)begin
        defaults();clear_context();
        case(field)
          0:i_configuration.input_s16=value4(value);
          1:i_configuration.input_c[0]=value4(value);
          2:i_configuration.group_c[0]=value4(value);
          3:i_configuration.group_offset[0]=value4(value);
          4:i_configuration.stride_w[1]=value4(value);
          5:i_configuration.input_base[0]=value4(value);
          6:i_column[0]=value4(value);
          7:i_columns[0]=value4(value);
          8:i_active_columns[0]=value4(value);
          9:i_channel[0]=value4(value);
          10:i_initial_channel[0]=value4(value);
          11:i_narrow=value4(value);
          12:i_past_active=value4(value);
          13:i_row_wrap=value4(value);
          14:i_clear=value4(value);
          15:i_stream=~value4(value);
          16:i_row_eligible=~value4(value);
          17:i_next_row[4]=value4(value);
          18:i_rows[4]=~value4(value);
          default:begin end
        endcase
        #1;
        if(value!=0 && o_issue!==0)$fatal(1,"LOOKAHEAD_FORMAT_QUALIFICATION field=%0d value=%0d",field,value);
        if(value==0 && o_issue!==1)$fatal(1,"LOOKAHEAD_VALID_FORMAT field=%0d",field);
        four_state_checks++;
      end
    // 新上下文的输入坐标和输出坐标包含未知位时，比较两个寄存组织的完整行为。
    for(integer field=0;field<2;field++)
      for(integer bit_index=0;bit_index<16;bit_index++)
        for(integer value=0;value<4;value++)begin
          defaults();clear_context();
          if(field==0)i_next_input_x[bit_index]=value4(value);
          else i_output_x[bit_index]=value4(value);
          clock_edge();clock_edge();
          four_state_checks+=2;
        end
    if(!captures || !stalls || !clear_checks || !four_state_checks)
      $fatal(1,"LOOKAHEAD_COVERAGE");
    $display("LOOKAHEAD_SEQUENCE_PASS shift=%0d checks=%0d captures=%0d stalls=%0d clears=%0d four_state=%0d",
      p_word_shift,checks,captures,stalls,clear_checks,four_state_checks);
    $finish;
  end
endmodule
