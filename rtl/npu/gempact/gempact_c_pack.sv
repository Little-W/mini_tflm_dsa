// Two 256-byte register tiles transpose final vectors at one row per cycle.
module gempact_c_pack(
 input logic clk,rst_n,transpose,
 input logic in_valid,input logic[9:0] in_tile,input logic[3:0] in_row,
 input logic[5:0] in_col,input logic[15:0] in_k,input logic in_frame_last,
 input logic[127:0] in_data,
 output logic out_valid,output logic[9:0] out_tile,output logic[3:0] out_row,
 output logic[5:0] out_col,output logic[15:0] out_k,output logic out_frame_last,
 output logic[127:0] out_data,output logic busy
);
 logic[127:0] data[2][16];logic[1:0] ready;
 logic write_bank,read_bank,draining;
 logic[3:0] drain_row;
 logic[9:0] tile_tag[2];logic[5:0] col_tag[2];logic[15:0] k_tag[2];logic last_tag[2];
 wire completing_input=in_valid && in_row==15;
 wire next_ready=ready[!read_bank] || (completing_input && write_bank!=read_bank);
 assign busy=draining || ready!=0;
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   ready<=0;write_bank<=0;read_bank<=0;draining<=0;drain_row<=0;out_valid<=0;out_tile<=0;out_row<=0;out_col<=0;out_k<=0;out_frame_last<=0;out_data<=0;
   for(int b=0;b<2;b++)begin tile_tag[b]<=0;col_tag[b]<=0;k_tag[b]<=0;last_tag[b]<=0;end
  end else begin
   out_valid<=draining;
   if(!draining && ready[read_bank])begin draining<=1;drain_row<=0;end
   if(draining)begin
    out_tile<=tile_tag[read_bank];out_row<=drain_row;out_col<=col_tag[read_bank];out_k<=k_tag[read_bank];out_frame_last<=last_tag[read_bank];
    for(int l=0;l<16;l++)out_data[l*8+:8]<=transpose?data[read_bank][l][drain_row*8+:8]:data[read_bank][drain_row][l*8+:8];
    if(drain_row==15)begin ready[read_bank]<=0;read_bank<=!read_bank;drain_row<=0;draining<=next_ready;end
    else drain_row<=drain_row+1'b1;
   end
   if(in_valid)begin
    data[write_bank][in_row]<=in_data;
    if(in_row==0)begin tile_tag[write_bank]<=in_tile;col_tag[write_bank]<=in_col;k_tag[write_bank]<=in_k;end
    if(in_row==15)begin ready[write_bank]<=1;last_tag[write_bank]<=in_frame_last;write_bank<=!write_bank;end
   end
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk)if(rst_n && in_valid)begin
  assert(!ready[write_bank] || (draining && drain_row==15 && read_bank==write_bank))else $fatal(1,"C transpose capacity");
 end
`endif
endmodule
