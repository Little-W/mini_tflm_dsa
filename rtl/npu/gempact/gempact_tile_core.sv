// Existing 16x16 WS systolic PE array with independent tile command boundaries.
module gempact_tile_core(input logic clk,rst_n,start,load_weights,
 output logic busy,done,
 output logic[3:0] a_row[16],output logic[15:0] a_re,
 input logic signed[7:0] a_data[16],
 output logic[3:0] b_row,output logic b_re,input logic signed[7:0] b_data[16],
 output logic row_valid,output logic[3:0] row_index,output logic signed[31:0] row_data[16],
 output logic signed[7:0] ia_debug[16],weight_debug[16]
);
 typedef enum logic[2:0]{IDLE,LOAD,LOAD_DRAIN,COMMIT_WEIGHTS,RUN,END_TILE} st_t;
 st_t state;logic[5:0] step;logic[3:0] load_row,out_row;
 logic load_q;logic[15:0] a_valid_q;
 wire signed[31:0] sums[16];wire signed[31:0] zero_sum[16];
 wire aligned_valid,tile_over,stream_over;
 assign busy=state!=IDLE;assign done=state==END_TILE;
 assign b_re=state==LOAD;assign b_row=15-load_row;
 assign row_index=out_row;assign row_valid=aligned_valid;
 always_comb begin
  for(int r=0;r<16;r++)begin
   a_re[r]=state==RUN && step>=r && step<r+16;
   a_row[r]=4'(step-r);
   ia_debug[r]=a_valid_q[r]?a_data[r]:8'sd0;
   weight_debug[r]=b_data[r];
  end
 end
 for(genvar c=0;c<16;c++)assign zero_sum[c]=0;
 ws_systolic_array #(.SIZE(16),.DATA_IN_WIDTH(8),.WEIGHT_WIDTH(8)) u_array(
  .clk(clk),.weight_commit(state==COMMIT_WEIGHTS),.store_weight_req(load_q),.weight_in(b_data),.data_in(ia_debug),.sum_in(zero_sum),.sum_out(sums));
 de_diagonalizer #(.SIZE(16),.DATA_WIDTH(32)) u_align(
  .clk(clk),.rst_n(rst_n),.data_in(sums),.input_valid_i(state==RUN && step>=17 && step<=47),
  .burst_start_i(state==RUN && step==17),.burst_last_i(state==RUN && step==47),
  .data_out(row_data),.data_valid_o(aligned_valid),.tile_calc_over_o(tile_over),.stream_calc_over_o(stream_over));
 always_ff @(posedge clk)begin
  if(!rst_n)begin state<=IDLE;step<=0;load_row<=0;out_row<=0;load_q<=0;a_valid_q<=0;end
  else begin
   load_q<=b_re;a_valid_q<=a_re;
   if(aligned_valid)out_row<=out_row+1'b1;
   case(state)
    IDLE:if(start)begin step<=0;out_row<=0;load_row<=0;state<=load_weights?LOAD:RUN;end
    LOAD:if(load_row==15)begin state<=LOAD_DRAIN;step<=0;end else load_row<=load_row+1'b1;
    LOAD_DRAIN:state<=COMMIT_WEIGHTS;
    COMMIT_WEIGHTS:state<=RUN;
    RUN:if(step==49)state<=END_TILE;else step<=step+1'b1;
    END_TILE:state<=IDLE;
   endcase
  end
 end
endmodule
