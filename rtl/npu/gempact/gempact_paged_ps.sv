// Dense tile-addressed, lossless 24/32-bit PS storage. All intermediate bits
// stay on-chip. Four physical 128-bit 1R1W banks include the 1024-B scratch.
// Base pages are reserved per group; high-byte pages use a BRAM free stack.
module gempact_paged_ps #(
 parameter integer POOL_BYTES=500736, MAX_TILES=640,
 parameter integer PAGES=POOL_BYTES/256, PW=$clog2(PAGES), TW=$clog2(MAX_TILES), BW=$clog2(PAGES*4)
)(
 input logic clk,rst_n,group_start,
 input logic[10:0] group_tiles,initial_pages,
 output logic group_ready,
 input logic[TW-1:0] query_tile,
 output logic meta_valid,meta_wide,
 output logic[23:0] meta_headroom,
 output logic[11:0] free_pages,
 input logic begin_update,
 input logic[TW-1:0] update_tile,
 input logic read_req,input logic[3:0] read_row,
 output logic read_valid,output logic[511:0] read_data,
 input logic scratch_write,input logic[3:0] scratch_row,input logic[511:0] scratch_data,
 input logic commit,commit_final,
 output logic commit_done,capacity_fault,
 output logic[31:0] peak_payload_bytes,
 output logic[63:0] records_written,long_records
);
 localparam integer ALLOC_PAGES=PAGES-4;
 (* ram_style="distributed" *) logic[PW-1:0] high_page[0:MAX_TILES-1];
 logic[MAX_TILES-1:0] valid_map,wide_map,risk_map;
 (* ram_style="block" *) logic[PW-1:0] free_stack[0:ALLOC_PAGES-1];
 logic[PW-1:0] stack_out;
 logic[11:0] count,init_page;
 logic[TW-1:0] tile;
 logic[BW-1:0] tile_base;
 logic[PW-1:0] tile_high;
 logic old_valid,old_wide,new_wide,new_risk;
 logic[3:0] copy_row,copy_row_q;
 logic copy_valid_q;
 logic[2:0] free_step;
 typedef enum logic[3:0]{IDLE,INIT,READY,POP,POP_WAIT,COPY,COPY_DRAIN,RELEASE,FINISHED} st_t;
 st_t state;
 logic[127:0] bank_wd[4],bank_rd[4];logic[BW-1:0] bank_wa[4],bank_ra[4];logic[3:0] bank_we,bank_re;
 logic[1:0] decode_phase;logic decode_wide,decode_valid;
 logic[511:0] packed_read,scratch_read;
 logic[383:0] low_packet;logic[127:0] high_packet;
 logic row_wide,row_risk;
 assign group_ready=state==READY;
 assign free_pages=count;
 assign meta_valid=valid_map[query_tile];assign meta_wide=wide_map[query_tile];
 assign meta_headroom=risk_map[query_tile]?24'd0:24'd262144;
 always_comb begin
  row_wide=0;row_risk=0;
  for(int l=0;l<16;l++)begin
   row_wide|=($signed(scratch_data[l*32+:32])>32'sd8388607)||($signed(scratch_data[l*32+:32])< -32'sd8388608);
   row_risk|=($signed(scratch_data[l*32+:32])>32'sd8126463)||($signed(scratch_data[l*32+:32])< -32'sd8126464);
  end
  for(int s=0;s<4;s++)packed_read[s*128+:128]=bank_rd[2'(decode_phase+2'(s))];
  for(int b=0;b<4;b++)scratch_read[b*128+:128]=bank_rd[b];
  for(int l=0;l<16;l++)begin
   read_data[l*32+:24]=decode_valid?packed_read[l*24+:24]:'0;
   read_data[l*32+24+:8]=!decode_valid?8'b0:(decode_wide?packed_read[384+l*8+:8]:{8{packed_read[l*24+23]}});
   low_packet[l*24+:24]=scratch_read[l*32+:24];high_packet[l*8+:8]=scratch_read[l*32+24+:8];
  end
 end
 for(genvar b=0;b<4;b++)begin:g_bank
  (* ram_style="block" *) logic[127:0] ram[0:PAGES*4-1];
  wire[5:0] read_three={2'b0,read_row}+{1'b0,read_row,1'b0};
  wire[5:0] write_three={2'b0,copy_row_q}+{1'b0,copy_row_q,1'b0};
  wire[1:0] ro=2'(b)-read_three[1:0],wo=2'(b)-write_three[1:0];
  always_comb begin
   bank_we[b]=0;bank_re[b]=0;bank_wd[b]=0;bank_wa[b]=0;bank_ra[b]=0;
   if(read_req && state==READY)begin
    bank_re[b]=old_valid && (old_wide || ro!=3);
    bank_ra[b]=ro==3 ? BW'({tile_high,2'b0}+(read_row>>2)) : tile_base+BW'((read_three+{4'b0,ro})>>2);
   end
   if(state==COPY)begin bank_re[b]=1;bank_ra[b]=BW'(ALLOC_PAGES*4)+BW'(copy_row);end
   if(scratch_write && state==READY)begin
    bank_we[b]=1;bank_wa[b]=BW'(ALLOC_PAGES*4)+BW'(scratch_row);bank_wd[b]=scratch_data[b*128+:128];
   end else if(copy_valid_q)begin
    bank_we[b]=new_wide || wo!=3;
    bank_wa[b]=wo==3 ? BW'({tile_high,2'b0}+(copy_row_q>>2)) : tile_base+BW'((write_three+{4'b0,wo})>>2);
    case(wo)
     0:bank_wd[b]=low_packet[0+:128];1:bank_wd[b]=low_packet[128+:128];
     2:bank_wd[b]=low_packet[256+:128];3:bank_wd[b]=high_packet;
    endcase
   end
  end
  always_ff @(posedge clk)begin
   if(bank_we[b])ram[bank_wa[b]]<=bank_wd[b];
   if(bank_re[b])bank_rd[b]<=ram[bank_ra[b]];
  end
 end
 // The free list uses one synchronous pop or one push per cycle.
 always_ff @(posedge clk)begin
  if(state==INIT && init_page>=initial_pages && init_page<ALLOC_PAGES)free_stack[count]<=PW'(init_page);
  if(state==POP)stack_out<=free_stack[count-1'b1];
  if(state==RELEASE)begin
   if(free_step<3)free_stack[count]<=PW'((tile_base>>2)+free_step);
   else free_stack[count]<=tile_high;
  end
  if(state==READY && commit && !commit_final && !new_wide && old_wide)free_stack[count]<=tile_high;
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;count<=0;init_page<=0;tile<=0;tile_base<=0;tile_high<=0;old_valid<=0;old_wide<=0;
   new_wide<=0;new_risk<=0;valid_map<=0;wide_map<=0;risk_map<=0;read_valid<=0;decode_phase<=0;
   decode_valid<=0;decode_wide<=0;copy_row<=0;copy_row_q<=0;copy_valid_q<=0;commit_done<=0;
   capacity_fault<=0;free_step<=0;peak_payload_bytes<=0;records_written<=0;long_records<=0;
  end else begin
   commit_done<=0;read_valid<=read_req && state==READY;
   copy_valid_q<=state==COPY;copy_row_q<=copy_row;
   if(read_req)begin decode_phase<=2'(read_row*3);decode_valid<=old_valid;decode_wide<=old_wide;end
   if((ALLOC_PAGES-count)*256+1024>peak_payload_bytes && state!=INIT && state!=IDLE)peak_payload_bytes<=(ALLOC_PAGES-count)*256+1024;
   if(group_start)begin
    state<=INIT;count<=0;init_page<=0;valid_map<=0;wide_map<=0;risk_map<=0;capacity_fault<=0;
    if(group_tiles>MAX_TILES || {1'b0,initial_pages}>ALLOC_PAGES)begin state<=IDLE;capacity_fault<=1;end
   end else case(state)
    INIT:begin
     if(init_page>=initial_pages && init_page<ALLOC_PAGES)count<=count+1'b1;
     if(init_page==ALLOC_PAGES-1)state<=READY;else init_page<=init_page+1'b1;
    end
    READY:begin
     if(begin_update)begin
      tile<=update_tile;tile_base<=BW'((update_tile<<3)+(update_tile<<2));tile_high<=high_page[update_tile];
      old_valid<=valid_map[update_tile];old_wide<=wide_map[update_tile];new_wide<=0;new_risk<=0;
     end
     if(scratch_write)begin new_wide<=new_wide|row_wide;new_risk<=new_risk|row_risk;end
     if(commit)begin
      if(commit_final)begin free_step<=0;state<=RELEASE;end
      else if(new_wide && !old_wide)begin if(count==0)capacity_fault<=1;else state<=POP;end
      else begin
       if(!new_wide && old_wide)count<=count+1'b1;
       copy_row<=0;state<=COPY;
      end
     end
    end
    POP:begin count<=count-1'b1;state<=POP_WAIT;end
    POP_WAIT:begin tile_high<=stack_out;high_page[tile]<=stack_out;copy_row<=0;state<=COPY;end
    COPY:if(copy_row==15)state<=COPY_DRAIN;else copy_row<=copy_row+1'b1;
    COPY_DRAIN:begin
     valid_map[tile]<=1;wide_map[tile]<=new_wide;risk_map[tile]<=new_risk;records_written<=records_written+16;
     if(new_wide)long_records<=long_records+16;
     state<=FINISHED;
    end
    RELEASE:begin
     count<=count+1'b1;
     if(free_step==3 || (free_step==2 && !old_wide))begin valid_map[tile]<=0;wide_map[tile]<=0;state<=FINISHED;end
     else free_step<=free_step+1'b1;
    end
    FINISHED:begin commit_done<=1;state<=READY;end
    default:;
   endcase
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk)if(rst_n)begin
  assert(count<=ALLOC_PAGES)else $fatal(1,"PS free-stack overflow");
  for(int b=0;b<4;b++)assert(!(bank_we[b]&&bank_re[b]&&bank_wa[b]==bank_ra[b]))else $fatal(1,"PS bank collision");
  if(capacity_fault)$fatal(1,"dynamic PS capacity fault");
 end
`endif
endmodule
