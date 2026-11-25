// SPDX-License-Identifier: Apache-2.0
// 比较窗口目标保存、保持和复位控制的四态事件行为。
module tb;
 logic i_clk=0,i_rst_n=0,window_prepare_write=0;
 logic [160:0] stimulus;
 logic [3:0] expected[2],actual[2];
 logic [31:0] random_state=32'h75bc19af;
 logic [31:0] q0,tile_q;
 logic [15:0] channels,kx,ky,last_kx,kernel_w,last_channel;
 logic group_nonzero;
 integer checks=0;
 for(genvar mode=0;mode<2;mode++)begin:g_mode
   reference #(.p_register_descriptor(mode)) r(.*,.observed(expected[mode]));
   candidate #(.p_register_descriptor(mode)) c(.*,.observed(actual[mode]));
 end
 function automatic [31:0] random_word;
   random_state=random_state^(random_state<<13);
   random_state=random_state^(random_state>>17);
   random_state=random_state^(random_state<<5);
   return random_state;
 endfunction
 task automatic check;
   #1;
   for(integer mode=0;mode<2;mode++)begin
     if(expected[mode]!==actual[mode])
       $fatal(1,"Window eligibility differs: check=%0d mode=%0d expected=%b actual=%b",checks,mode,expected[mode],actual[mode]);
   end
   checks++;
 endtask
 initial begin
   stimulus='0;check();
   for(integer trial=0;trial<16384;trial++)begin
     i_clk=0;
     q0=random_word();tile_q=random_word();channels=16'(random_word());
     kx=16'(random_word());ky=16'(random_word());last_kx=16'(random_word());
     kernel_w=16'(random_word());
     case(trial%8)
       0:q0=0;
       1:q0=32'hffffffff;
       2:q0=32'h80000000;
       3:q0=32'h7fffffff;
       default:;
     endcase
     case(trial%5)
       0:channels=0;
       1:channels=1;
       2:channels=16'hffff;
       default:;
     endcase
     if(trial%3==0)begin kx=0;ky=1;kernel_w=3;last_kx=2;end
     if(trial%3==1)begin kx=1;last_kx=2;end
     case(trial%4)
       0:tile_q=q0+32'(channels);
       1:tile_q=q0-32'(channels);
       2:tile_q=q0-(32'(channels)<<1);
       default:tile_q=q0;
     endcase
     last_channel=channels-16'd1;group_nonzero=|channels;
     if(trial%7==0)begin last_channel=16'(random_word());group_nonzero=1'(random_word());end
     stimulus={q0,tile_q,channels,last_channel,kx,ky,last_kx,kernel_w,group_nonzero};
     i_rst_n=1;window_prepare_write=trial%4!=0;
     if(trial%37==0)i_rst_n=0;
     if(trial%13==0)window_prepare_write=1'bx;
     if(trial%17==0)window_prepare_write=1'bz;
     if(trial%41==0)i_rst_n=1'bx;
     if(trial%43==0)i_rst_n=1'bz;
     if(trial%2==0)stimulus[trial%161]=trial%4==0?1'bx:1'bz;
     check();i_clk=1;check();
   end
   $display("WINDOW_ELIGIBILITY_FOUR_STATE_PASS checks=%0d modes=2",checks);$finish;
 end
endmodule
