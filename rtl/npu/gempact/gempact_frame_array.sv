// Consecutive tall frames carry their weight context and PS address tags.
module gempact_frame_array(
 input logic clk,rst_n,
 input logic job_valid,output logic job_ready,
 input logic[5:0] job_rows,job_col,
 input logic[15:0] job_k,
 input logic job_buffer,job_final,
 output logic frame_launch,frame_input_done,
 output logic[15:0] a_re,
 output logic[11:0] a_addr[16],
 input logic signed[7:0] a_data[16],
 output logic b_re,output logic[9:0] b_addr,
 input logic[31:0] b_data[16],
 output logic row_valid,output logic[9:0] row_tile,
 output logic[3:0] row_index,output logic[15:0] row_k,
 output logic row_final,output logic[5:0] row_col,output logic row_frame_last,
 output logic signed[31:0] row_data[16],
 output logic[1:0] buffer_busy,
 output logic busy
);
 logic queued,loaded,load_active,next_bank,queued_bank;
 logic[5:0] qrows,qcol;logic[15:0] qk;logic qbuf,qfinal;
 logic[5:0] guard_count;logic[4:0] load_step;
 logic b_valid_q,b_bank_q;logic[1:0] b_byte_q;
 logic signed[7:0] weight_vec[16];
 logic[9:0] queued_tile_base,feed_tile_base;
 logic feed_active;logic[8:0] feed_row;logic[5:0] feed_rows,feed_col;
 logic[15:0] feed_k;logic feed_buffer,feed_bank,feed_final;
 wire launch=queued && loaded && !feed_active;
 logic src_valid,src_bank,src_final;logic[11:0] src_addr;logic[9:0] src_tile;logic[3:0] src_row;
 logic[15:0] src_k;
 logic valid_pipe[16],bank_pipe[16];logic[11:0] addr_pipe[16];logic[15:0] a_valid_q;logic a_bank_q[16];
 logic[32:0] tag_valid,tag_final,tag_frame_last;logic[5:0] tag_col[33];logic[9:0] tag_tile[33];logic[3:0] tag_row[33];logic[15:0] tag_k[33];
 wire signed[31:0] sums[16];logic signed[7:0] array_a[16];
 assign job_ready=!queued;
 assign b_re=queued && !loaded && guard_count==0 && (!load_active || load_step<16);
 wire[3:0] load_index=4'(15-load_step);
 assign b_addr={qbuf,qcol[4:0],qk[1:0],load_index[3:2]};
 assign frame_launch=launch;
 assign frame_input_done=feed_active && feed_row==9'((feed_rows<<4)-1'b1);
 always_comb begin
  src_valid=feed_active || launch;src_bank=feed_active?feed_bank:queued_bank;
  src_final=feed_active?feed_final:qfinal;src_k=feed_active?feed_k:qk;
  src_row=feed_active?feed_row[3:0]:0;
  src_tile=(feed_active?feed_tile_base:queued_tile_base)+10'(feed_active?feed_row[8:4]:0);
  // Explicit narrow fields keep cache addressing independent of multipliers.
  src_addr={feed_active?feed_buffer:qbuf,2'(feed_active?feed_k:qk),feed_active?feed_row:9'd0};
  for(int l=0;l<16;l++)begin
   a_re[l]=l==0?src_valid:valid_pipe[l-1];
   a_addr[l]=l==0?src_addr:addr_pipe[l-1];
   array_a[l]=a_valid_q[l]?a_data[l]:8'sd0;
   weight_vec[l]=$signed(b_data[l]>>(b_byte_q*8));
  end
 end
 gempact_tagged_array u_array(.clk(clk),.weight_write(b_valid_q),.weight_write_bank(b_bank_q),.weight_in(weight_vec),.a_in(array_a),.a_bank(a_bank_q),.result(sums));
 for(genvar c=0;c<16;c++)begin:g_align
  logic signed[31:0] delay_line[0:15-c];
  always_ff @(posedge clk)begin
   delay_line[0]<=sums[c];
   for(int d=1;d<=15-c;d++)delay_line[d]<=delay_line[d-1];
  end
  assign row_data[c]=delay_line[15-c];
 end
 assign row_valid=tag_valid[32];assign row_tile=tag_tile[32];assign row_index=tag_row[32];assign row_k=tag_k[32];assign row_final=tag_final[32];assign row_col=tag_col[32];assign row_frame_last=tag_frame_last[32];
 assign busy=queued || feed_active || |tag_valid;
 always_comb begin
  buffer_busy=0;if(queued)buffer_busy[qbuf]=1;if(feed_active)buffer_busy[feed_buffer]=1;
  for(int l=0;l<16;l++)if(valid_pipe[l])buffer_busy[addr_pipe[l][11]]=1;
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   queued_tile_base<=0;feed_tile_base<=0;queued<=0;loaded<=0;load_active<=0;next_bank<=0;queued_bank<=0;qrows<=0;qcol<=0;qk<=0;qbuf<=0;qfinal<=0;guard_count<=0;load_step<=0;b_valid_q<=0;b_bank_q<=0;b_byte_q<=0;
   feed_active<=0;feed_row<=0;feed_rows<=0;feed_col<=0;feed_k<=0;feed_buffer<=0;feed_bank<=0;feed_final<=0;tag_valid<=0;tag_final<=0;tag_frame_last<=0;a_valid_q<=0;
   for(int l=0;l<16;l++)begin valid_pipe[l]<=0;bank_pipe[l]<=0;addr_pipe[l]<=0;a_bank_q[l]<=0;end
   for(int t=0;t<33;t++)begin tag_tile[t]<=0;tag_row[t]<=0;tag_k[t]<=0;tag_col[t]<=0;end
  end else begin
   if(guard_count!=0)guard_count<=guard_count-1'b1;
   b_valid_q<=b_re;b_bank_q<=queued_bank;b_byte_q<=load_index[1:0];
   if(job_valid && job_ready)begin
    queued<=1;loaded<=0;load_active<=0;load_step<=0;
    queued_tile_base<=10'(job_col*job_rows);qrows<=job_rows;qcol<=job_col;qk<=job_k;qbuf<=job_buffer;qfinal<=job_final;queued_bank<=next_bank;
   end
   if(b_re)begin load_active<=1;load_step<=load_step+1'b1;end
   if(load_active && load_step==16 && !b_re)begin loaded<=1;load_active<=0;end
   if(launch)begin
    queued<=0;loaded<=0;next_bank<=!next_bank;guard_count<=32;
    feed_tile_base<=queued_tile_base;feed_rows<=qrows;feed_col<=qcol;feed_k<=qk;feed_buffer<=qbuf;feed_bank<=queued_bank;feed_final<=qfinal;
    feed_active<=1;feed_row<=1;
   end else if(feed_active)begin
    if(feed_row==9'((feed_rows<<4)-1'b1))feed_active<=0;
    else feed_row<=feed_row+1'b1;
   end
   valid_pipe[0]<=src_valid;addr_pipe[0]<=src_addr;bank_pipe[0]<=src_bank;
   for(int l=1;l<16;l++)begin valid_pipe[l]<=valid_pipe[l-1];addr_pipe[l]<=addr_pipe[l-1];bank_pipe[l]<=bank_pipe[l-1];end
   for(int l=0;l<16;l++)begin a_valid_q[l]<=a_re[l];a_bank_q[l]<=l==0?src_bank:bank_pipe[l-1];end
   tag_valid<={tag_valid[31:0],src_valid};tag_final<={tag_final[31:0],src_final};
   tag_frame_last<={tag_frame_last[31:0],feed_active && feed_row==9'((feed_rows<<4)-1'b1)};tag_col[0]<=feed_active?feed_col:qcol;
   tag_tile[0]<=src_tile;tag_row[0]<=src_row;tag_k[0]<=src_k;
   for(int t=1;t<33;t++)begin tag_tile[t]<=tag_tile[t-1];tag_row[t]<=tag_row[t-1];tag_k[t]<=tag_k[t-1];tag_col[t]<=tag_col[t-1];end
  end
 end
endmodule
