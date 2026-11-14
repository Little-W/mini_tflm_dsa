`ifdef GEMPACT_PCR_PS
`ifndef GEMPACT_PCR_ENABLE
`define GEMPACT_PCR_ENABLE 1
`endif
`ifndef GEMPACT_PCR_FAST_ENABLE
`define GEMPACT_PCR_FAST_ENABLE 1
`endif
// Compact 16-byte row records in a shared four-bank page pool.
// Two explicitly counted 1-KiB buffers prevent new packed rows overwriting
// unread rows of the old tile. All old tile reads precede its writeback.
module gempact_stream_ps #(
 parameter integer POOL_BYTES=327680,MAX_TILES=640,
 parameter integer PAGES=POOL_BYTES/256,PW=$clog2(PAGES),BW=$clog2(POOL_BYTES/64),
 parameter integer PCR_ENABLE=`GEMPACT_PCR_ENABLE,FAST_ENABLE=`GEMPACT_PCR_FAST_ENABLE
)(
 input logic clk,rst_n,group_start,group_release,
 input logic[5:0] group_rows,group_cols,output logic group_ready,
 input logic prepare_request,input logic[5:0] prepare_col,input logic prepare_final,prepare_finish,
 output logic prepare_ready,prepare_done,prepare_pressure,capacity_fault,
 input logic product_valid,input logic[9:0] product_tile,input logic[3:0] product_row,
 input logic[15:0] product_k,input logic[5:0] product_col,input logic product_frame_last,product_final,
 input logic signed[31:0] product_data[16],
 output logic acc_valid,output logic[9:0] acc_tile,output logic[3:0] acc_row,
 output logic[15:0] acc_k,output logic[5:0] acc_col,output logic acc_frame_last,
 output logic signed[31:0] acc_data[16],
 input logic[5:0] c_write_col,input logic[15:0] c_write_k,input logic c_write_frame_last,
 input logic c_write_valid,input logic[9:0] c_write_tile,input logic[3:0] c_write_row,input logic[127:0] c_write_data,
 input logic c_read_request,input logic[9:0] c_read_tile,input logic[3:0] c_read_row,
 output logic c_read_valid,output logic[127:0] c_read_data,
 output logic all_c_ready,frame_committed,output logic[5:0] committed_col,output logic[15:0] committed_k,
 output logic[11:0] free_pages,output logic[31:0] peak_payload_bytes,
 output logic[63:0] records_written,long_records
);
 localparam integer DEPTH=POOL_BYTES/64;
 localparam logic[3:0] M_ZERO=0,M_S8=1,M_S16=2,M_S24=3,M_RAW=4,M_CONST=13,M_PCR=14;
`ifdef GEMMORA_PS_FORCE_RAW
 localparam integer FORCE_RAW=1;
`else
 localparam integer FORCE_RAW=0;
`endif
 `include "gempact_pcr_functions.svh"

 function automatic logic[522:0] row_encode(input logic[511:0] values);
  logic[519:0] pc;
  logic[511:0] payload;
  logic[6:0] bytes;
  logic[3:0] mode;
  logic zero,same,f8,f16,f24;
  begin
   payload=values;bytes=64;mode=M_RAW;zero=1;same=1;f8=1;f16=1;f24=1;pc=0;
   for(integer l=0;l<16;l=l+1)begin
    zero=zero && values[l*32+:32]==0;same=same && values[l*32+:32]==values[31:0];
    f8=f8 && values[l*32+8+:24]=={24{values[l*32+7]}};
    f16=f16 && values[l*32+16+:16]=={16{values[l*32+15]}};
    f24=f24 && values[l*32+24+:8]=={8{values[l*32+23]}};
   end
   if(!FORCE_RAW)begin
    if(PCR_ENABLE)begin
     pc=pcr_encode(values);
     if(pc[519] && pc[518:512]<bytes)begin mode=M_PCR;bytes=pc[518:512];payload=pc[511:0];end
    end
    if(f24 && (48<bytes || (bytes==48 && M_S24<mode)))begin
     mode=M_S24;bytes=48;payload=0;for(integer l=0;l<16;l=l+1)payload[l*24+:24]=values[l*32+:24];
    end
    if(f16 && (32<bytes || (bytes==32 && M_S16<mode)))begin
     mode=M_S16;bytes=32;payload=0;for(integer l=0;l<16;l=l+1)payload[l*16+:16]=values[l*32+:16];
    end
    if(f8 && (16<bytes || (bytes==16 && M_S8<mode)))begin
     mode=M_S8;bytes=16;payload=0;for(integer l=0;l<16;l=l+1)payload[l*8+:8]=values[l*32+:8];
    end
    if(same && (4<bytes || (bytes==4 && M_CONST<mode)))begin mode=M_CONST;bytes=4;payload=0;payload[31:0]=values[31:0];end
    if(zero)begin mode=M_ZERO;bytes=0;payload=0;end
   end
   row_encode={mode,bytes,payload};
  end
 endfunction
 function automatic logic[511:0] row_decode(input logic[3:0] mode,input logic[511:0] payload);
  logic[511:0] values;
  begin
   values=0;
   case(mode)
    M_ZERO:values=0;
    M_S8:for(integer l=0;l<16;l=l+1)values[l*32+:32]={{24{payload[l*8+7]}},payload[l*8+:8]};
    M_S16:for(integer l=0;l<16;l=l+1)values[l*32+:32]={{16{payload[l*16+15]}},payload[l*16+:16]};
    M_S24:for(integer l=0;l<16;l=l+1)values[l*32+:32]={{8{payload[l*24+23]}},payload[l*24+:24]};
    M_CONST:for(integer l=0;l<16;l=l+1)values[l*32+:32]=payload[31:0];
    M_PCR:values=pcr_decode(1'b1,payload);
    default:values=payload;
   endcase
   row_decode=values;
  end
 endfunction
 function automatic logic[6:0] row_bytes(input logic[3:0] mode,input logic[511:0] payload);
  case(mode)
   M_ZERO:row_bytes=0;M_S8:row_bytes=16;M_S16:row_bytes=32;M_S24:row_bytes=48;M_CONST:row_bytes=4;
   M_PCR:row_bytes=7'(12+(pcr_pop16(payload[15:0])*int'(payload[90:85])+7)/8+4*pcr_pop16(payload[79:64]));
   default:row_bytes=64;
  endcase
 endfunction

 // A row descriptor is {word_count[2:0], start_word[5:0], mode[3:0]}.
 // Fixed page 0 belongs to tile ID and is also retained for final INT8 C.
 logic[MAX_TILES-1:0] valid_map,c_map,safe24_map;
 logic[MAX_TILES-1:0][1:0] allocated_map;
 (* ram_style="distributed" *)logic[207:0] row_directory[0:MAX_TILES-1];
 (* ram_style="distributed" *)logic[3*PW-1:0] extension_pages[0:MAX_TILES-1];
`ifndef ASIC_SRAM
 (* ram_style="block" *)logic[PW-1:0] free_stack[0:PAGES-1];
`endif
 logic[PW-1:0] stack_out;
 logic[11:0] count,initial_pages,stack_count,next_unused;
 logic[10:0] tiles,c_count;
 logic[5:0] rows,cols;
 logic initializing,init_calculate;
 logic[6:0] column_remaining[0:31];
 logic[6:0] maximum_after,current_after;
 typedef enum logic[3:0]{P_IDLE,P_START,P_SCAN,P_DRAIN,P_EVAL,P_ALLOC,P_POP,P_POP_WAIT,P_DONE,P_PRESSURE} prep_t;
 prep_t prep_state;
 logic[5:0] scan_row,alloc_row,p_col;
 logic p_final,p_finish,drain_final_pending;
 logic[31:0][1:0] need_slots;
 logic[6:0] need_count;
 logic[9:0] frame_base,scan_tile,alloc_tile;
 logic[1:0] required_count,needs_pages,need_q;
 logic scan_valid_q;logic[5:0] scan_row_q;
 logic[1:0] reclaim_count;
 logic[3*PW-1:0] reclaim_pages;
 logic[5:0] reclaim_col;
 logic reclaim_final;
 wire push_page=reclaim_count!=0;
 wire pop_page=prep_state==P_POP && !push_page;
 wire page_allocate=pop_page;
 wire[PW-1:0] push_value=reclaim_pages[0+:PW];

 logic[127:0] bank_rd[4],bank_wd[4];
 logic[BW-1:0] bank_ra[4],bank_wa[4];logic[3:0] bank_re,bank_we;
 wire[12:0] read_desc=valid_map[product_tile]?row_directory[product_tile][int'(product_row)*13+:13]:13'd0;
 logic[2:0] read_valid_pipe,read_final_pipe,read_frame_last_pipe,read_old_valid_pipe,read_zero_delta_pipe;
 logic[9:0] read_tile_pipe[3];logic[3:0] read_row_pipe[3];logic[15:0] read_k_pipe[3];logic[5:0] read_col_pipe[3];
 logic[511:0] read_delta_pipe[3];logic[12:0] read_desc_pipe[3];
 logic[3*PW-1:0] read_pages_pipe[3];logic[1:0] read_alloc_pipe[3];
 logic[511:0] input_delta,old_record,old_values;
 logic[520:0] fast_result;
 logic product_zero;
 logic sum_valid,sum_final,sum_frame_last,sum_zero_delta,sum_old_valid,sum_fast_hit;
 logic[5:0] sum_col;logic[9:0] sum_tile;logic[3:0] sum_row;logic[15:0] sum_k;
 logic[511:0] sum_bits,sum_old_record,sum_fast_record;
 logic signed[31:0] sum_data[16];
 logic[3:0] sum_fast_mask;
 logic[12:0] sum_old_desc;
 logic[3*PW-1:0] sum_pages;
 logic[1:0] sum_alloc;
 logic row_wide,row_risk,row_safe24;
 logic[522:0] encoded_row;
 logic[3:0] encoded_mask;
 logic encoded_hit;
 logic enc_valid,enc_frame_last,enc_safe24,enc_hit;
 logic[9:0] enc_tile;logic[3:0] enc_row,enc_mode,enc_mask;
 logic[15:0] enc_k;logic[5:0] enc_col,enc_old_offset;
 logic[2:0] enc_words,enc_old_words;
 logic[511:0] enc_record;
 logic[3*PW-1:0] enc_pages;
 logic[1:0] enc_alloc;

 // Fully counted staging: 2*16*512 data bits plus descriptors, masks and tags.
 logic[511:0] write_buffer[2][16];
 logic[207:0] buffer_directory[2];
 logic[3:0] buffer_masks[2][16];
 logic[15:0] buffer_fast_rows[2];
 logic[9:0] buffer_tile[2];logic[15:0] buffer_k[2];logic[5:0] buffer_col[2];
 logic buffer_frame_last[2],buffer_safe24[2];
 logic[3*PW-1:0] buffer_pages[2];logic[1:0] buffer_alloc[2],buffer_used[2];
 logic[1:0] buffer_ready;
 logic fill_bank,drain_bank,writeback_nonfinal;
 logic[3:0] writeback_row;
 logic[6:0] tile_word_cursor;
 logic tile_safe24;
 wire[6:0] new_offset=enc_row==0?7'd0:tile_word_cursor;
 wire[6:0] new_total=new_offset+7'(enc_words);
 wire[2:0] new_page_count=new_total==0?3'd1:3'((new_total+7'd15)>>4);
 wire completing_input=enc_valid && enc_row==15;
 wire next_buffer_ready=buffer_ready[!drain_bank] || (completing_input && fill_bank!=drain_bank);
 wire[12:0] writeback_desc=buffer_directory[drain_bank][int'(writeback_row)*13+:13];
 wire[9:0] writeback_tile=buffer_tile[drain_bank];
 wire[15:0] writeback_k=buffer_k[drain_bank];
 wire[3:0] writeback_mode=writeback_desc[3:0];
 wire[3:0] writeback_mask=buffer_masks[drain_bank][writeback_row];
 wire writeback_fast=buffer_fast_rows[drain_bank][writeback_row];
 wire fast_hit=enc_valid && enc_hit;
 logic commit_valid;
 logic[9:0] commit_tile;logic[15:0] commit_k;logic[5:0] commit_col;
 logic commit_frame_last,commit_safe24;
 logic[207:0] commit_directory;
 logic[3*PW-1:0] commit_pages;
 logic[1:0] commit_alloc,commit_used;
 wire reclaim_at_commit=commit_valid && commit_alloc>commit_used;
 wire reclaim_at_c=c_write_valid && c_write_row==15 && allocated_map[c_write_tile]!=0;
 wire reclaim_busy=push_page || reclaim_at_commit || reclaim_at_c;
 logic[2:0] c_read_valid_pipe;logic[1:0] c_read_bank_pipe[3];

 assign free_pages=count;assign group_ready=!initializing;
 assign prepare_ready=prep_state==P_IDLE && !initializing && !reclaim_busy && !drain_final_pending;
 assign prepare_done=prep_state==P_DONE;assign prepare_pressure=prep_state==P_PRESSURE;
 assign all_c_ready=c_count==tiles && tiles!=0;
 assign acc_valid=sum_valid && sum_final;assign acc_tile=sum_tile;assign acc_row=sum_row;
 assign acc_k=sum_k;assign acc_col=sum_col;assign acc_frame_last=sum_frame_last;
 assign c_read_valid=c_read_valid_pipe[2];assign c_read_data=bank_rd[c_read_bank_pipe[2]];
 for(genvar l=0;l<16;l++)begin:g_sum_alias
  assign sum_data[l]=$signed(sum_bits[l*32+:32]);assign acc_data[l]=sum_data[l];
 end

 always_comb begin
  // Complete-row RAW32 bound is mandatory when a shared PCR factor breaks.
  // SAFE24 is a value-range proof independent of old representation or sparsity.
  required_count=2'd3;
  if(!FORCE_RAW && (!valid_map[scan_tile] || safe24_map[scan_tile]))required_count=2'd2;
  needs_pages=(!p_final && required_count>allocated_map[scan_tile])?required_count-allocated_map[scan_tile]:2'd0;
  maximum_after=0;current_after=0;
  for(int c=0;c<32;c++)if(c<int'(cols))begin
   current_after=column_remaining[c];
   if(c==int'(p_col))current_after=column_remaining[c]>need_count?column_remaining[c]-need_count:7'd0;
   if(current_after>maximum_after)maximum_after=current_after;
  end
 end
 always_comb begin
  product_zero=1;input_delta=0;old_record=0;
  for(int l=0;l<16;l++)begin input_delta[l*32+:32]=product_data[l];product_zero&=product_data[l]==0;end
  for(int j=0;j<4;j++)if(j<int'(read_desc_pipe[2][12:10]))
   old_record[j*128+:128]=bank_rd[2'(read_desc_pipe[2][5:4]+2'(j))];
  old_values=read_old_valid_pipe[2]?row_decode(read_desc_pipe[2][3:0],old_record):512'd0;
  fast_result=0;
  if(PCR_ENABLE && FAST_ENABLE && !FORCE_RAW && read_old_valid_pipe[2] && !read_final_pipe[2] && read_desc_pipe[2][3:0]==M_PCR)
   fast_result=pcr_fast(1'b1,row_bytes(M_PCR,old_record),old_record,read_delta_pipe[2]);
  row_wide=0;row_risk=0;row_safe24=1;
  for(int l=0;l<16;l++)begin
   row_wide|=sum_bits[l*32+24+:8]!={8{sum_bits[l*32+23]}};
   row_safe24&=$signed(sum_bits[l*32+:32])>=-32'sd8126464 && $signed(sum_bits[l*32+:32])<=32'sd8126463;
  end
  row_risk=!row_safe24;
  encoded_row={M_ZERO,7'd0,512'd0};encoded_mask=0;encoded_hit=0;
  if(sum_valid && !sum_final)begin
   if(sum_zero_delta && sum_old_valid && !FORCE_RAW)begin
    encoded_row={sum_old_desc[3:0],row_bytes(sum_old_desc[3:0],sum_old_record),sum_old_record};
    encoded_mask=0;
   end else if(sum_fast_hit)begin
    encoded_row={M_PCR,row_bytes(M_PCR,sum_fast_record),sum_fast_record};encoded_mask=sum_fast_mask;encoded_hit=1;
   end else begin encoded_row=row_encode(sum_bits);encoded_mask=pcr_wordmask(encoded_row[518:512]);end
  end
 end

 for(genvar b=0;b<4;b++)begin:g_bank
  always_comb begin
   logic[2:0] rword,wword;
   logic[6:0] rlogical,wlogical;
   logic[1:0] rslot,wslot;
   logic[PW-1:0] rpage,wpage;
   rword={1'b0,2'(b)-read_desc[5:4]};wword={1'b0,2'(b)-writeback_desc[5:4]};
   rlogical={1'b0,read_desc[9:4]}+7'(rword);wlogical={1'b0,writeback_desc[9:4]}+7'(wword);
   rslot=rlogical[5:4];wslot=wlogical[5:4];
   rpage=rslot==0?PW'(product_tile):extension_pages[product_tile][(int'(rslot)-1)*PW+:PW];
   wpage=wslot==0?PW'(writeback_tile):buffer_pages[drain_bank][(int'(wslot)-1)*PW+:PW];
   bank_we[b]=0;bank_re[b]=0;bank_wd[b]=0;bank_wa[b]=0;bank_ra[b]=0;
   if(product_valid)begin
    bank_re[b]=valid_map[product_tile] && rword<read_desc[12:10];
    bank_ra[b]=BW'({rpage,2'b0}+rlogical[3:2]);
   end else if(c_read_request && c_read_row[1:0]==b)begin
    bank_re[b]=1;bank_ra[b]=BW'((c_read_tile<<2)+(c_read_row>>2));
   end
   if(writeback_nonfinal)begin
    bank_we[b]=wword<writeback_desc[12:10] && writeback_mask[wword[1:0]];
    bank_wd[b]=write_buffer[drain_bank][writeback_row][int'(wword)*128+:128];
    bank_wa[b]=BW'({wpage,2'b0}+wlogical[3:2]);
   end
   if(c_write_valid && c_write_row[1:0]==b)begin
    bank_we[b]=1;bank_wa[b]=BW'((c_write_tile<<2)+(c_write_row>>2));bank_wd[b]=c_write_data;
   end
  end
  gempact_ps_bank #(.DEPTH(DEPTH),.AW(BW)) u_memory(.clk(clk),.write_enable(bank_we[b]),.read_enable(bank_re[b]),.write_address(bank_wa[b]),.read_address(bank_ra[b]),.write_data(bank_wd[b]),.read_data(bank_rd[b]));
 end

 always_ff @(posedge clk)begin
  if(!rst_n || group_start || group_release)begin
   read_valid_pipe<=0;read_final_pipe<=0;read_frame_last_pipe<=0;read_old_valid_pipe<=0;read_zero_delta_pipe<=0;
   c_read_valid_pipe<=0;sum_valid<=0;sum_final<=0;sum_frame_last<=0;sum_zero_delta<=0;sum_old_valid<=0;sum_fast_hit<=0;
   sum_col<=0;sum_tile<=0;sum_row<=0;sum_k<=0;sum_bits<=0;sum_old_record<=0;sum_fast_record<=0;sum_fast_mask<=0;sum_old_desc<=0;sum_pages<=0;sum_alloc<=0;
   enc_valid<=0;enc_frame_last<=0;enc_safe24<=0;enc_hit<=0;enc_tile<=0;enc_row<=0;enc_mode<=0;enc_mask<=0;enc_k<=0;enc_col<=0;enc_old_offset<=0;enc_words<=0;enc_old_words<=0;enc_record<=0;enc_pages<=0;enc_alloc<=0;
   for(int t=0;t<3;t++)begin read_tile_pipe[t]<=0;read_row_pipe[t]<=0;read_k_pipe[t]<=0;read_col_pipe[t]<=0;read_delta_pipe[t]<=0;read_desc_pipe[t]<=0;read_pages_pipe[t]<=0;read_alloc_pipe[t]<=0;c_read_bank_pipe[t]<=0;end
  end else begin
   read_valid_pipe<={read_valid_pipe[1:0],product_valid};read_final_pipe<={read_final_pipe[1:0],product_final};
   read_frame_last_pipe<={read_frame_last_pipe[1:0],product_frame_last};read_old_valid_pipe<={read_old_valid_pipe[1:0],valid_map[product_tile]};
   read_zero_delta_pipe<={read_zero_delta_pipe[1:0],product_zero};
   read_tile_pipe[0]<=product_tile;read_row_pipe[0]<=product_row;read_k_pipe[0]<=product_k;read_col_pipe[0]<=product_col;
   read_delta_pipe[0]<=input_delta;read_desc_pipe[0]<=read_desc;read_pages_pipe[0]<=extension_pages[product_tile];read_alloc_pipe[0]<=allocated_map[product_tile];
   for(int t=1;t<3;t++)begin read_tile_pipe[t]<=read_tile_pipe[t-1];read_row_pipe[t]<=read_row_pipe[t-1];read_k_pipe[t]<=read_k_pipe[t-1];read_col_pipe[t]<=read_col_pipe[t-1];read_delta_pipe[t]<=read_delta_pipe[t-1];read_desc_pipe[t]<=read_desc_pipe[t-1];read_pages_pipe[t]<=read_pages_pipe[t-1];read_alloc_pipe[t]<=read_alloc_pipe[t-1];end
   sum_valid<=read_valid_pipe[2];sum_final<=read_final_pipe[2];sum_frame_last<=read_frame_last_pipe[2];sum_zero_delta<=read_zero_delta_pipe[2];sum_old_valid<=read_old_valid_pipe[2];
   sum_col<=read_col_pipe[2];sum_tile<=read_tile_pipe[2];sum_row<=read_row_pipe[2];sum_k<=read_k_pipe[2];
   for(int l=0;l<16;l++)sum_bits[l*32+:32]<=old_values[l*32+:32]+read_delta_pipe[2][l*32+:32];
   sum_old_record<=old_record;sum_old_desc<=read_desc_pipe[2];sum_fast_hit<=fast_result[512];sum_fast_record<=fast_result[511:0];sum_fast_mask<=fast_result[516:513];sum_pages<=read_pages_pipe[2];sum_alloc<=read_alloc_pipe[2];
   // A fast or zero-delta update may retain a longer historical PCR record.
   // SAFE24 therefore certifies both bounded values and at most three words
   // per retained row; a future full encode can always use signed24.
   enc_valid<=sum_valid && !sum_final;enc_frame_last<=sum_frame_last;
   enc_safe24<=row_safe24 && encoded_row[518:512]<=7'd48;enc_hit<=encoded_hit;
   enc_tile<=sum_tile;enc_row<=sum_row;enc_k<=sum_k;enc_col<=sum_col;enc_mode<=encoded_row[522:519];enc_record<=encoded_row[511:0];enc_mask<=encoded_mask;
   enc_words<=3'((encoded_row[518:512]+7'd15)>>4);enc_old_offset<=sum_old_desc[9:4];enc_old_words<=sum_old_desc[12:10];enc_pages<=sum_pages;enc_alloc<=sum_alloc;
   c_read_valid_pipe<={c_read_valid_pipe[1:0],c_read_request};c_read_bank_pipe[0]<=c_read_row[1:0];c_read_bank_pipe[1]<=c_read_bank_pipe[0];c_read_bank_pipe[2]<=c_read_bank_pipe[1];
  end
 end

 always_ff @(posedge clk)begin
  if(!rst_n || group_start || group_release)begin
   buffer_ready<=0;fill_bank<=0;drain_bank<=0;writeback_nonfinal<=0;writeback_row<=0;tile_word_cursor<=0;tile_safe24<=0;
   commit_valid<=0;commit_tile<=0;commit_k<=0;commit_col<=0;commit_frame_last<=0;commit_safe24<=0;commit_directory<=0;commit_pages<=0;commit_alloc<=0;commit_used<=0;
   for(int b=0;b<2;b++)begin buffer_directory[b]<=0;buffer_fast_rows[b]<=0;buffer_tile[b]<=0;buffer_k[b]<=0;buffer_col[b]<=0;buffer_frame_last[b]<=0;buffer_safe24[b]<=0;buffer_pages[b]<=0;buffer_alloc[b]<=0;buffer_used[b]<=0;end
  end else begin
   commit_valid<=writeback_nonfinal && writeback_row==15;
   if(!writeback_nonfinal && buffer_ready[drain_bank])begin writeback_nonfinal<=1;writeback_row<=0;end
   if(writeback_nonfinal)begin
    if(writeback_row==15)begin
     // Capture before this buffer is reused by the first row of the next tile.
     commit_tile<=buffer_tile[drain_bank];commit_k<=buffer_k[drain_bank];commit_col<=buffer_col[drain_bank];commit_frame_last<=buffer_frame_last[drain_bank];commit_safe24<=buffer_safe24[drain_bank];
     commit_directory<=buffer_directory[drain_bank];commit_pages<=buffer_pages[drain_bank];commit_alloc<=buffer_alloc[drain_bank];commit_used<=buffer_used[drain_bank];
     buffer_ready[drain_bank]<=0;drain_bank<=!drain_bank;writeback_row<=0;writeback_nonfinal<=next_buffer_ready;
    end else writeback_row<=writeback_row+1'b1;
   end
   if(enc_valid)begin
    write_buffer[fill_bank][enc_row]<=enc_record;
    buffer_directory[fill_bank][int'(enc_row)*13+:13]<={enc_words,new_offset[5:0],enc_mode};
    // A partial write is safe only if the complete row keeps its physical location.
    buffer_masks[fill_bank][enc_row]<=(new_offset[5:0]==enc_old_offset && enc_words==enc_old_words)?enc_mask:4'((5'd1<<enc_words)-1'b1);
    buffer_fast_rows[fill_bank][enc_row]<=enc_hit;
    tile_word_cursor<=new_total;tile_safe24<=enc_safe24 && (enc_row==0 || tile_safe24);
    if(enc_row==0)begin buffer_tile[fill_bank]<=enc_tile;buffer_k[fill_bank]<=enc_k;buffer_col[fill_bank]<=enc_col;buffer_pages[fill_bank]<=enc_pages;buffer_alloc[fill_bank]<=enc_alloc;end
    if(enc_row==15)begin buffer_ready[fill_bank]<=1;buffer_frame_last[fill_bank]<=enc_frame_last;buffer_safe24[fill_bank]<=enc_safe24 && tile_safe24;buffer_used[fill_bank]<=2'(new_page_count-1'b1);fill_bank<=!fill_bank;end
   end
  end
 end

`ifdef ASIC_SRAM
 wire[PW-1:0] stack_sram_out;
 logic[PW-1:0] stack_fresh_out;
 logic stack_from_sram;
 assign stack_out=stack_from_sram?stack_sram_out:stack_fresh_out;
 always_ff @(posedge clk)if(pop_page)begin
  stack_from_sram<=stack_count!=0;
  if(stack_count==0)stack_fresh_out<=PW'(next_unused);
 end
 smic40_sram_1r1w #(.DATA_WIDTH(PW),.DEPTH(PAGES),.ADDR_WIDTH(PW)) u_free_stack (
  .clk(clk),.write_enable(push_page && !initializing),.write_address(PW'(stack_count)),
  .write_data(push_value),.write_mask({PW{1'b1}}),
  .read_enable(pop_page && stack_count!=0),.read_address(PW'(stack_count-1'b1)),.read_data(stack_sram_out));
`else
 always_ff @(posedge clk)begin
  if(pop_page)begin if(stack_count!=0)stack_out<=free_stack[stack_count-1'b1];else stack_out<=PW'(next_unused);end
  if(push_page && !initializing)free_stack[stack_count]<=push_value;
 end
`endif
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   valid_map<=0;c_map<=0;safe24_map<='1;allocated_map<=0;
   count<=0;initial_pages<=0;stack_count<=0;next_unused<=0;tiles<=0;c_count<=0;rows<=0;cols<=0;initializing<=0;init_calculate<=0;
   prep_state<=P_IDLE;frame_base<=0;scan_tile<=0;alloc_tile<=0;need_q<=0;scan_valid_q<=0;scan_row_q<=0;scan_row<=0;alloc_row<=0;p_col<=0;p_final<=0;p_finish<=0;need_slots<=0;need_count<=0;drain_final_pending<=0;
   reclaim_count<=0;reclaim_pages<=0;reclaim_col<=0;reclaim_final<=0;capacity_fault<=0;frame_committed<=0;committed_col<=0;committed_k<=0;peak_payload_bytes<=0;records_written<=0;long_records<=0;
   for(int c=0;c<32;c++)column_remaining[c]<=0;
  end else begin
   frame_committed<=0;scan_valid_q<=prep_state==P_SCAN;
   if(prep_state==P_SCAN)begin need_q<=needs_pages;scan_row_q<=scan_row;end
   if((PAGES-count)*256>peak_payload_bytes && !initializing && tiles!=0)peak_payload_bytes<=(PAGES-count)*256;
   if(group_start)begin
    valid_map<=0;c_map<=0;safe24_map<='1;allocated_map<=0;count<=0;stack_count<=0;next_unused<=0;initial_pages<=0;
    tiles<=11'(group_rows*group_cols);c_count<=0;rows<=group_rows;cols<=group_cols;initializing<=1;init_calculate<=1;prep_state<=P_IDLE;reclaim_count<=0;capacity_fault<=0;drain_final_pending<=0;
    for(int c=0;c<32;c++)column_remaining[c]<=c<int'(group_cols)?7'(3*group_rows):7'd0;
    if(group_rows==0 || group_cols==0 || group_rows>32 || group_cols>32)capacity_fault<=1;
   end else if(initializing && init_calculate)begin
    initial_pages<=12'(tiles);init_calculate<=0;
    if(tiles>MAX_TILES || 13'(tiles)+13'(3*rows)>13'(PAGES))capacity_fault<=1;
   end else if(initializing)begin count<=12'(PAGES)-initial_pages;next_unused<=initial_pages;stack_count<=0;initializing<=0;end
   else if(group_release)begin
    count<=PAGES;next_unused<=0;stack_count<=0;c_map<=0;c_count<=0;valid_map<=0;allocated_map<=0;reclaim_count<=0;drain_final_pending<=0;
    for(int c=0;c<32;c++)column_remaining[c]<=0;
   end else begin
    if(pop_page)begin count<=count-1'b1;column_remaining[p_col]<=column_remaining[p_col]-1'b1;if(stack_count!=0)stack_count<=stack_count-1'b1;else next_unused<=next_unused+1'b1;end
    if(push_page)begin count<=count+1'b1;stack_count<=stack_count+1'b1;reclaim_count<=reclaim_count-1'b1;reclaim_pages<=reclaim_pages>>PW;if(!reclaim_final)column_remaining[reclaim_col]<=column_remaining[reclaim_col]+1'b1;end
    if(scan_valid_q)begin need_slots[scan_row_q]<=need_q;need_count<=need_count+7'(need_q);end
    case(prep_state)
     P_IDLE:if(prepare_request && !reclaim_busy && !drain_final_pending)begin
      p_col<=prepare_col;frame_base<=10'(prepare_col*rows);p_final<=prepare_final;p_finish<=prepare_finish;
      if(prepare_finish && prepare_final)drain_final_pending<=1;
      scan_row<=0;need_slots<=0;need_count<=0;prep_state<=P_START;
     end
     P_START:begin scan_tile<=frame_base;scan_row<=0;prep_state<=P_SCAN;end
     P_SCAN:begin if(scan_row==rows-1'b1)prep_state<=P_DRAIN;else begin scan_row<=scan_row+1'b1;scan_tile<=scan_tile+1'b1;end end
     P_DRAIN:prep_state<=P_EVAL;
     P_EVAL:if(!reclaim_busy)begin
      if(!p_final && !p_finish && {1'b0,count}<{6'b0,need_count}+{6'b0,maximum_after})prep_state<=P_PRESSURE;
      else if(count<need_count)begin capacity_fault<=1;prep_state<=P_IDLE;end
      else begin alloc_row<=0;prep_state<=P_ALLOC;end
     end
     P_ALLOC:begin if(need_slots[alloc_row]!=0)begin alloc_tile<=frame_base+10'(alloc_row);prep_state<=P_POP;end else if(alloc_row==rows-1'b1)prep_state<=P_DONE;else alloc_row<=alloc_row+1'b1;end
     P_POP:if(pop_page)prep_state<=P_POP_WAIT;
     P_POP_WAIT:begin
      extension_pages[alloc_tile][int'(allocated_map[alloc_tile])*PW+:PW]<=stack_out;allocated_map[alloc_tile]<=allocated_map[alloc_tile]+1'b1;need_slots[alloc_row]<=need_slots[alloc_row]-1'b1;
      if(need_slots[alloc_row]>1)prep_state<=P_POP;else if(alloc_row==rows-1'b1)prep_state<=P_DONE;else begin alloc_row<=alloc_row+1'b1;prep_state<=P_ALLOC;end
     end
     P_DONE,P_PRESSURE:prep_state<=P_IDLE;
     default:prep_state<=P_IDLE;
    endcase
    if(sum_valid && !sum_final)begin records_written<=records_written+1'b1;if(row_wide)long_records<=long_records+1'b1;end
    // The gempact_ps_bank write register commits this tile's last data on
    // this edge. Publish its new directory only on the same committed edge.
    if(commit_valid)begin
     valid_map[commit_tile]<=1;row_directory[commit_tile]<=commit_directory;safe24_map[commit_tile]<=commit_safe24;allocated_map[commit_tile]<=commit_used;
     if(reclaim_at_commit)begin reclaim_count<=commit_alloc-commit_used;reclaim_pages<=commit_pages>>(int'(commit_used)*PW);reclaim_col<=commit_col;reclaim_final<=0;end
     if(commit_frame_last)begin frame_committed<=1;committed_col<=commit_col;committed_k<=commit_k;end
    end
    if(c_write_valid && c_write_row==15)begin
     c_map[c_write_tile]<=1;c_count<=c_count+1'b1;valid_map[c_write_tile]<=0;allocated_map[c_write_tile]<=0;
     if(reclaim_at_c)begin reclaim_count<=allocated_map[c_write_tile];reclaim_pages<=extension_pages[c_write_tile];reclaim_col<=c_write_col;reclaim_final<=1;end
     if(c_write_frame_last)begin column_remaining[c_write_col]<=0;if(drain_final_pending && c_write_col==p_col)drain_final_pending<=0;frame_committed<=1;committed_col<=c_write_col;committed_k<=c_write_k;end
    end
   end
  end
 end

`ifndef SYNTHESIS
 logic check_active;logic[9:0] check_tile;logic[15:0] check_k;logic[3:0] check_row;
 always @(posedge clk)begin
  if(!rst_n || group_start || group_release)begin check_active<=0;check_tile<=0;check_k<=0;check_row<=0;end
  else if(enc_valid)begin
   if(enc_row==0)begin assert(!check_active)else $fatal(1,"PCR interleaved input tile");check_active<=1;check_tile<=enc_tile;check_k<=enc_k;check_row<=1;end
   else begin assert(check_active && enc_tile==check_tile && enc_k==check_k && enc_row==check_row)else $fatal(1,"PCR row order");check_row<=check_row+1'b1;if(enc_row==15)check_active<=0;end
  end
 end
 always @(posedge clk)if(rst_n)begin
  assert(POOL_BYTES%256==0 && MAX_TILES<=1024)else $fatal(1,"PCR physical configuration");
  assert(count<=PAGES)else $fatal(1,"PCR free page overflow");
  if(capacity_fault)$fatal(1,"PCR capacity fault");
  if(product_valid)begin
   assert(product_tile<MAX_TILES && product_tile<tiles)else $fatal(1,"PCR tile address");
   for(int l=0;l<16;l++)assert(product_data[l]>=-32'sd262144 && product_data[l]<=32'sd262144)else $fatal(1,"PCR requires bounded K16 INT8 update");
  end
  if(enc_valid)begin
   assert(!buffer_ready[fill_bank] || (writeback_nonfinal && writeback_row==15 && drain_bank==fill_bank))else $fatal(1,"PCR double buffer overflow");
   assert(new_total<=64 && enc_words<=4)else $fatal(1,"PCR row storage limit");
   if(enc_row==15)assert(new_page_count<=3'(enc_alloc)+3'd1)else $fatal(1,"PCR unreserved growth pages=%0d allocated=%0d",new_page_count,enc_alloc+1);
  end
  if(reclaim_at_commit || reclaim_at_c)assert(!push_page)else $fatal(1,"PCR reclaim queue overlap");
  if(pop_page)begin assert(count!=0 && column_remaining[p_col]!=0)else $fatal(1,"PCR allocation underflow");assert(allocated_map[alloc_tile]!=3)else $fatal(1,"PCR extension overflow");end
  if(c_read_request)assert(c_map[c_read_tile])else $fatal(1,"PCR C read before commit");
  if(c_write_valid)assert(!writeback_nonfinal)else $fatal(1,"PCR PS/C write conflict");
  for(int b=0;b<4;b++)assert(!(bank_re[b] && bank_we[b] && bank_ra[b]==bank_wa[b]))else $fatal(1,"PCR bank address collision");
  if(prep_state==P_EVAL && !p_finish && !reclaim_busy)for(int c=0;c<32;c++)if(c<int'(cols))assert(count>=column_remaining[c])else $fatal(1,"PCR reserve invariant free=%0d col=%0d remaining=%0d",count,c,column_remaining[c]);
 end
`endif
endmodule
`endif
