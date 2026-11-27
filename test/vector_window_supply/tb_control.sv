// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps

// 验证四个窗口槽位的代际隔离、失败排空与未知值传播。
module tb #(parameter bit REGISTERED=0, parameter int PE_COUNT=8);
  logic clk=0, rst_n=0, depthwise=1, state_failed=0;
  logic window_slot_available=0, window_response_fault=0, win_req_ready=1;
  logic [1:0] wf_bank=0, read_bank=0;
  logic dw_issue_fire=0, dw_group_last=1;
  logic state_compute_commit=0, compute_group_last_q=0, global_pool=0, spatial=1;
  logic clear_all=0, win_rsp_valid=0, win_rsp_last=1, win_rsp_error=0;
  logic [1:0] win_rsp_tag=0;
  wire win_req_valid, win_rsp_ready, window_request_fire, window_response_fire;
  wire [3:0] input_ready,input_reserved;
  logic [3:0] forced_ready,forced_reserved;
  logic expected_response,expected_request;
  integer checks=0, four_state=0, early=0, held=0, failed=0, blocked=0, released=0;
  integer seed=261127;
  window_control #(.p_input_bank_storage(REGISTERED), .p_pe_count(PE_COUNT)) dut (.*);

  function automatic logic four(input integer value);
    case(value)
      0: four=0;
      1: four=1;
      2: four=1'bx;
      default: four=1'bz;
    endcase
  endfunction

  task automatic check(input logic condition, input string message);
    if (condition !== 1'b1) $fatal(1,"%s",message);
    checks++;
  endtask

  task automatic tick;
    #1;
    if(window_request_fire && input_ready[wf_bank] &&
       !(dw_issue_fire && dw_group_last && wf_bank==read_bank)) early++;
    if(win_rsp_valid && !win_rsp_ready) held++;
    if(state_failed && window_response_fire) failed++;
    if(window_slot_available && input_ready[wf_bank] && !window_request_fire) blocked++;
    if(window_request_fire && dw_issue_fire && dw_group_last && wf_bank==read_bank) released++;
    clk=1; #1; clk=0; #1;
  endtask

  task automatic request(input integer bank);
    wf_bank=2'(bank);window_slot_available=1;#1;
    check(window_request_fire,"空闲请求记录应允许接受窗口");
    tick();window_slot_available=0;
    check(input_reserved[bank],"接受的请求必须保留目标槽号");
  endtask

  task automatic response(input integer bank);
    win_rsp_tag=2'(bank);win_rsp_valid=1;#1;
    check(window_response_fire,"已释放的槽位应允许响应写入");
    tick();win_rsp_valid=0;
    if(REGISTERED) tick();
    check(input_ready[bank] && !input_reserved[bank],"完整返回应形成就绪数据并结束请求");
  endtask

  initial begin
    tick();rst_n=1;tick();
    check(input_ready==0 && input_reserved==0,"复位应清空全部槽位");
    for(integer bank=0;bank<4;bank++) begin request(bank);response(bank);end
    check(input_ready==15 && input_reserved==0,"四个当前窗口均已就绪");
    if(PE_COUNT<16) begin
      for(integer bank=0;bank<4;bank++) request(bank);
      check(input_ready==15 && input_reserved==15,"当前数据与后续预约必须分别保存");
      for(integer bank=0;bank<4;bank++) begin
        wf_bank=2'(bank);window_slot_available=1;win_rsp_tag=2'(bank);win_rsp_valid=1;#1;
        check(!window_request_fire && !window_response_fire,"已预约请求和未消费数据应分别保持");
        tick();window_slot_available=0;win_rsp_valid=0;
        check(input_ready==15 && input_reserved==15,"响应等待不得改变槽位归属");
      end
      // 末组捕获边沿仍保存旧数据，下一周期开始接收后续返回。
      read_bank=0;dw_issue_fire=1;win_rsp_tag=0;win_rsp_valid=1;#1;
      check(!window_response_fire,"消费边沿应保持当前数据");
      tick();dw_issue_fire=0;win_rsp_valid=0;
      check(!input_ready[0] && input_reserved[0],"消费只释放当前数据");
    end else begin
      for(integer bank=0;bank<4;bank++) begin
        wf_bank=2'(bank);window_slot_available=1;#1;
        check(!window_request_fire,"十六路计算配置应等待当前窗口消费");
        tick();window_slot_available=0;
      end
      check(input_ready==15 && input_reserved==0,"等待消费期间应保存全部当前数据");
      for(integer bank=0;bank<4;bank++) begin
        read_bank=2'(bank);wf_bank=2'(bank);dw_issue_fire=1;window_slot_available=1;#1;
        check(window_request_fire,"末组消费边沿允许预约后续窗口");
        tick();dw_issue_fire=0;window_slot_available=0;
        check(!input_ready[bank] && input_reserved[bank],"消费完成后只保留后续请求");
      end
      check(input_ready==0 && input_reserved==15,"各槽位分别保存待返回请求");
    end
    response(0);
    // 失败状态继续接受全部已提交请求，并允许后续任务重新使用槽位。
    state_failed=1;
    for(integer bank=1;bank<4;bank++) response(bank);
    check(input_reserved==0,"失败状态必须排空已接收请求");
    clear_all=1;tick();clear_all=0;state_failed=0;
    check(input_ready==0 && input_reserved==0,"排空后的任务清空应释放全部槽位");
    request(3);response(3);
    check(input_ready==8 && input_reserved==0,"后续任务可以重新使用槽位");

    // 遍历返回资格的全部四态组合，错误与失败优先允许排空。
    force dut.input_ready=forced_ready;
    force dut.input_reserved=forced_reserved;
    forced_reserved=0;window_slot_available=0;win_rsp_valid=0;
    for(integer value=0;value<262144;value++) begin
      for(integer bit_index=0;bit_index<4;bit_index++)
        forced_ready[bit_index]=four((value>>(2*bit_index))&3);
      win_rsp_tag={four((value>>10)&3),four((value>>8)&3)};
      depthwise=four((value>>12)&3);
      state_failed=four((value>>14)&3);
      win_rsp_error=four((value>>16)&3);
      expected_response=!(depthwise && forced_ready[win_rsp_tag] && !state_failed && !win_rsp_error);
      #1;
      check(win_rsp_ready===expected_response,"返回资格的四态传播不一致");
      four_state++;
    end
    // 请求选择包含未知槽号、未知保留位、同拍消费以及任务错误。
    for(integer sample=0;sample<65536;sample++) begin
      for(integer bit_index=0;bit_index<4;bit_index++) begin
        forced_ready[bit_index]=four($random(seed)&3);
        forced_reserved[bit_index]=four($random(seed)&3);
      end
      wf_bank={four($random(seed)&3),four($random(seed)&3)};
      read_bank={four($random(seed)&3),four($random(seed)&3)};
      depthwise=four($random(seed)&3);window_slot_available=four($random(seed)&3);
      window_response_fault=four($random(seed)&3);dw_issue_fire=four($random(seed)&3);
      dw_group_last=four($random(seed)&3);
      expected_request=window_slot_available && !window_response_fault && !forced_reserved[wf_bank] &&
          ((PE_COUNT<16 && depthwise) || !forced_ready[wf_bank] ||
           (dw_issue_fire && dw_group_last && wf_bank==read_bank));
      #1;
      check(win_req_valid===expected_request,"请求资格的四态传播不一致");
      four_state++;
    end
    release dut.input_ready;release dut.input_reserved;
    $display("WINDOW_CONTROL_PASS checks=%0d four_state=%0d early=%0d held=%0d failed=%0d blocked=%0d released=%0d",
        checks,four_state,early,held,failed,blocked,released);
    $finish;
  end
endmodule
