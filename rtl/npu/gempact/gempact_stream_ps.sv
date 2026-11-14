// Banked exact 24/32-bit state with capacity prediction and in-place feedback.
// Final INT8 tiles retain one base page until the coalesced group write.
`ifndef GEMPACT_PCR_PS
module gempact_stream_ps #(
 parameter integer POOL_BYTES=327680,MAX_TILES=640,
 parameter integer PAGES=POOL_BYTES/256,PW=$clog2(PAGES),BW=$clog2(POOL_BYTES/64)
)(
 input logic clk,rst_n,group_start,group_release,
 input logic[5:0] group_rows,group_cols,
 output logic group_ready,
 input logic prepare_request,input logic[5:0] prepare_col,
 input logic prepare_final,prepare_finish,
 output logic prepare_ready,prepare_done,prepare_pressure,capacity_fault,
 input logic product_valid,input logic[9:0] product_tile,input logic[3:0] product_row,
 input logic[15:0] product_k,input logic[5:0] product_col,input logic product_frame_last,input logic product_final,input logic signed[31:0] product_data[16],
 output logic acc_valid,output logic[9:0] acc_tile,output logic[3:0] acc_row,
 output logic[15:0] acc_k,output logic[5:0] acc_col,output logic acc_frame_last,output logic signed[31:0] acc_data[16],
 input logic[5:0] c_write_col,input logic[15:0] c_write_k,input logic c_write_frame_last,
 input logic c_write_valid,input logic[9:0] c_write_tile,input logic[3:0] c_write_row,input logic[127:0] c_write_data,
 input logic c_read_request,input logic[9:0] c_read_tile,input logic[3:0] c_read_row,
 output logic c_read_valid,output logic[127:0] c_read_data,
 output logic all_c_ready,frame_committed,output logic[5:0] committed_col,output logic[15:0] committed_k,
 output logic[11:0] free_pages,output logic[31:0] peak_payload_bytes,
 output logic[63:0] records_written,long_records
);
 localparam integer DEPTH=POOL_BYTES/64;
 logic[MAX_TILES-1:0] valid_map,wide_map,risk_map,reserved_map,c_map;
 (* ram_style="distributed" *)logic[PW-1:0] high_page[0:MAX_TILES-1];
 (* ram_style="block" *)logic[PW-1:0] free_stack[0:PAGES-1];
 logic[PW-1:0] stack_out;
 logic[11:0] count,init_page,initial_pages,stack_count,next_unused;
 logic[10:0] tiles,c_count;
 logic[5:0] rows,cols;
 logic initializing,init_calculate;
 typedef enum logic[3:0]{P_IDLE,P_START,P_SCAN,P_DRAIN,P_EVAL,P_ALLOC,P_POP,P_POP_WAIT,P_DONE,P_PRESSURE} prep_t;
 prep_t prep_state;
 logic[5:0] scan_row,alloc_row,p_col;
 logic p_final,p_finish;
 logic[31:0] need_mask;
 logic[6:0] need_count;
 logic[9:0] frame_base,scan_tile,alloc_tile;
 logic need_q,scan_valid_q;logic[5:0] scan_row_q;
 wire needs_page=!p_final && valid_map[scan_tile] && !wide_map[scan_tile] && risk_map[scan_tile] && !reserved_map[scan_tile];
 logic release_active,release_has_high;
 logic[1:0] release_step;
 logic[PW-1:0] release_base,release_high;
 logic shrink_pending;logic[PW-1:0] shrink_page;
 wire push_page=release_active || shrink_pending;
 wire pop_page=prep_state==P_POP && !push_page;
 wire[PW-1:0] push_value=release_active?(release_step==2?release_high:release_base+PW'(release_step)+1'b1):shrink_page;
 logic[127:0] bank_rd[4],bank_wd[4];logic[BW-1:0] bank_ra[4],bank_wa[4];logic[3:0] bank_re,bank_we;
 logic prod_valid_q,prod_final_q,prod_old_valid_q,prod_old_wide_q,prod_frame_last_q;logic[5:0] prod_col_q;
 logic[9:0] prod_tile_q;logic[3:0] prod_row_q;logic[15:0] prod_k_q;logic[1:0] decode_phase_q;
 logic signed[31:0] prod_data_q[16];logic[511:0] packed_old;
 logic sum_valid,sum_final,sum_frame_last;logic[5:0] sum_col;logic[9:0] sum_tile;logic[3:0] sum_row;logic[15:0] sum_k;logic signed[31:0] sum_data[16];
 logic[383:0] low_packet;logic[127:0] high_packet;
 logic row_wide,row_risk,tile_wide,tile_risk;
 logic[1:0] c_read_bank_q,c_read_bank_qq,c_read_bank_qqq;logic c_read_request_q,c_read_request_qq;
 logic prod_valid_qq,prod_final_qq,prod_old_valid_qq,prod_old_wide_qq,prod_frame_last_qq;logic[5:0] prod_col_qq;
 logic[9:0] prod_tile_qq;logic[3:0] prod_row_qq;logic[15:0] prod_k_qq;logic[1:0] decode_phase_qq;logic signed[31:0] prod_data_qq[16];
 logic prod_valid_qqq,prod_final_qqq,prod_old_valid_qqq,prod_old_wide_qqq,prod_frame_last_qqq;
 logic[5:0] prod_col_qqq;logic[9:0] prod_tile_qqq;logic[3:0] prod_row_qqq;logic[15:0] prod_k_qqq;logic[1:0] decode_phase_qqq;
 logic signed[31:0] prod_data_qqq[16];
 logic[PW-1:0] prod_high_q,prod_high_qq,prod_high_qqq,sum_high;
 logic prod_has_high_q,prod_has_high_qq,prod_has_high_qqq,sum_has_high;
 wire[5:0] read_three={2'b0,product_row}+{1'b0,product_row,1'b0};
 wire[5:0] write_three={2'b0,sum_row}+{1'b0,sum_row,1'b0};
 wire[BW-1:0] read_base=BW'((product_tile<<3)+(product_tile<<2));
 wire[BW-1:0] write_base=BW'((sum_tile<<3)+(sum_tile<<2));
 wire[BW-1:0] c_read_base=BW'((c_read_tile<<3)+(c_read_tile<<2));
 wire[BW-1:0] c_write_base=BW'((c_write_tile<<3)+(c_write_tile<<2));
 assign free_pages=count;
 assign group_ready=!initializing;
 assign prepare_ready=prep_state==P_IDLE && !initializing;
 assign prepare_done=prep_state==P_DONE;
 assign prepare_pressure=prep_state==P_PRESSURE;
 assign acc_valid=sum_valid && sum_final;assign acc_tile=sum_tile;assign acc_row=sum_row;assign acc_k=sum_k;assign acc_col=sum_col;assign acc_frame_last=sum_frame_last;
 assign all_c_ready=c_count==tiles && tiles!=0;
 assign c_read_data=bank_rd[c_read_bank_qqq];
 always_comb begin
  row_wide=0;row_risk=0;
  for(int s=0;s<4;s++)packed_old[s*128+:128]=bank_rd[2'(decode_phase_qqq+2'(s))];
  for(int l=0;l<16;l++)begin
   acc_data[l]=sum_data[l];low_packet[l*24+:24]=sum_data[l][23:0];high_packet[l*8+:8]=sum_data[l][31:24];
   row_wide|=sum_data[l][31:24]!={8{sum_data[l][23]}};
   row_risk|=(sum_data[l][31:24]!={8{sum_data[l][23]}}) || (!sum_data[l][23] && (&sum_data[l][22:18])) || (sum_data[l][23] && !(|sum_data[l][22:18]));
  end
 end
 for(genvar b=0;b<4;b++)begin:g_bank
  wire[1:0] ro=2'(b)-read_three[1:0],wo=2'(b)-write_three[1:0];
  always_comb begin
   bank_we[b]=0;bank_re[b]=0;bank_wd[b]=0;bank_wa[b]=0;bank_ra[b]=0;
   if(product_valid)begin
    bank_re[b]=valid_map[product_tile] && (wide_map[product_tile] || ro!=3);
    bank_ra[b]=ro==3?BW'({high_page[product_tile],2'b0}+(product_row>>2)):read_base+BW'((read_three+{4'b0,ro})>>2);
   end else if(c_read_request && c_read_row[1:0]==b)begin bank_re[b]=1;bank_ra[b]=c_read_base+BW'(c_read_row>>2);end
   if(sum_valid && !sum_final)begin
    bank_we[b]=sum_has_high || wo!=3;
    bank_wa[b]=wo==3?BW'({sum_high,2'b0}+(sum_row>>2)):write_base+BW'((write_three+{4'b0,wo})>>2);
    case(wo)0:bank_wd[b]=low_packet[0+:128];1:bank_wd[b]=low_packet[128+:128];2:bank_wd[b]=low_packet[256+:128];3:bank_wd[b]=high_packet;endcase
   end
   if(c_write_valid && c_write_row[1:0]==b)begin bank_we[b]=1;bank_wa[b]=c_write_base+BW'(c_write_row>>2);bank_wd[b]=c_write_data;end
  end
  gempact_ps_bank #(.DEPTH(DEPTH),.AW(BW)) u_memory(.clk(clk),.write_enable(bank_we[b]),.read_enable(bank_re[b]),.write_address(bank_wa[b]),.read_address(bank_ra[b]),.write_data(bank_wd[b]),.read_data(bank_rd[b]));
 end
 always_ff @(posedge clk)begin
  if(pop_page)begin
   if(stack_count!=0)stack_out<=free_stack[stack_count-1'b1];else stack_out<=PW'(next_unused);
  end
  if(push_page && !initializing)free_stack[stack_count]<=push_value;
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   prod_valid_q<=0;prod_final_q<=0;prod_col_q<=0;prod_frame_last_q<=0;prod_valid_qq<=0;prod_final_qq<=0;prod_col_qq<=0;prod_frame_last_qq<=0;prod_old_valid_qq<=0;prod_old_wide_qq<=0;prod_tile_qq<=0;prod_row_qq<=0;prod_k_qq<=0;decode_phase_qq<=0;prod_old_valid_q<=0;prod_old_wide_q<=0;prod_tile_q<=0;prod_row_q<=0;prod_k_q<=0;decode_phase_q<=0;
   prod_valid_qqq<=0;prod_final_qqq<=0;prod_old_valid_qqq<=0;prod_old_wide_qqq<=0;prod_frame_last_qqq<=0;prod_col_qqq<=0;prod_tile_qqq<=0;prod_row_qqq<=0;prod_k_qqq<=0;decode_phase_qqq<=0;
   prod_high_q<=0;prod_high_qq<=0;prod_high_qqq<=0;sum_high<=0;prod_has_high_q<=0;prod_has_high_qq<=0;prod_has_high_qqq<=0;sum_has_high<=0;c_read_request_qq<=0;c_read_bank_qqq<=0;
   sum_valid<=0;sum_final<=0;sum_col<=0;sum_frame_last<=0;sum_tile<=0;sum_row<=0;sum_k<=0;c_read_valid<=0;c_read_bank_q<=0;c_read_bank_qq<=0;c_read_request_q<=0;
   for(int l=0;l<16;l++)begin prod_data_q[l]<=0;prod_data_qq[l]<=0;prod_data_qqq[l]<=0;sum_data[l]<=0;end
  end else begin
   prod_valid_q<=product_valid;prod_tile_q<=product_tile;prod_row_q<=product_row;prod_k_q<=product_k;prod_final_q<=product_final;prod_col_q<=product_col;prod_frame_last_q<=product_frame_last;
   prod_old_valid_q<=valid_map[product_tile];prod_old_wide_q<=wide_map[product_tile];decode_phase_q<=read_three[1:0];
   for(int l=0;l<16;l++)begin
    logic signed[31:0] old_value;
    old_value=prod_old_valid_qqq?{prod_old_wide_qqq?packed_old[384+l*8+:8]:{8{packed_old[l*24+23]}},packed_old[l*24+:24]}:32'sd0;
    prod_data_q[l]<=product_data[l];prod_data_qq[l]<=prod_data_q[l];prod_data_qqq[l]<=prod_data_qq[l];sum_data[l]<=prod_data_qqq[l]+old_value;
   end
   prod_valid_qq<=prod_valid_q;prod_tile_qq<=prod_tile_q;prod_row_qq<=prod_row_q;prod_k_qq<=prod_k_q;prod_final_qq<=prod_final_q;prod_col_qq<=prod_col_q;prod_frame_last_qq<=prod_frame_last_q;prod_old_valid_qq<=prod_old_valid_q;prod_old_wide_qq<=prod_old_wide_q;decode_phase_qq<=decode_phase_q;
   prod_valid_qqq<=prod_valid_qq;prod_tile_qqq<=prod_tile_qq;prod_row_qqq<=prod_row_qq;prod_k_qqq<=prod_k_qq;prod_final_qqq<=prod_final_qq;prod_col_qqq<=prod_col_qq;prod_frame_last_qqq<=prod_frame_last_qq;prod_old_valid_qqq<=prod_old_valid_qq;prod_old_wide_qqq<=prod_old_wide_qq;decode_phase_qqq<=decode_phase_qq;
   prod_high_q<=high_page[product_tile];prod_high_qq<=prod_high_q;prod_high_qqq<=prod_high_qq;sum_high<=prod_high_qqq;
   prod_has_high_q<=wide_map[product_tile] || reserved_map[product_tile];prod_has_high_qq<=prod_has_high_q;prod_has_high_qqq<=prod_has_high_qq;sum_has_high<=prod_has_high_qqq;
   sum_valid<=prod_valid_qqq;sum_tile<=prod_tile_qqq;sum_row<=prod_row_qqq;sum_k<=prod_k_qqq;sum_final<=prod_final_qqq;sum_col<=prod_col_qqq;sum_frame_last<=prod_frame_last_qqq;
   c_read_request_q<=c_read_request;c_read_request_qq<=c_read_request_q;c_read_valid<=c_read_request_qq;c_read_bank_q<=c_read_row[1:0];c_read_bank_qq<=c_read_bank_q;c_read_bank_qqq<=c_read_bank_qq;
  end
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   valid_map<=0;wide_map<=0;risk_map<=0;reserved_map<=0;c_map<=0;count<=0;init_page<=0;initial_pages<=0;stack_count<=0;next_unused<=0;tiles<=0;c_count<=0;rows<=0;cols<=0;initializing<=0;init_calculate<=0;
   prep_state<=P_IDLE;frame_base<=0;scan_tile<=0;alloc_tile<=0;need_q<=0;scan_valid_q<=0;scan_row_q<=0;scan_row<=0;alloc_row<=0;p_col<=0;p_final<=0;p_finish<=0;need_mask<=0;need_count<=0;
   capacity_fault<=0;release_active<=0;release_has_high<=0;release_step<=0;release_base<=0;release_high<=0;shrink_pending<=0;shrink_page<=0;
   tile_wide<=0;tile_risk<=0;frame_committed<=0;committed_col<=0;committed_k<=0;peak_payload_bytes<=0;records_written<=0;long_records<=0;
  end else begin
   frame_committed<=0;scan_valid_q<=prep_state==P_SCAN;
   if(prep_state==P_SCAN)begin need_q<=needs_page;scan_row_q<=scan_row;end
   if((PAGES-count)*256>peak_payload_bytes && !initializing && tiles!=0)peak_payload_bytes<=(PAGES-count)*256;
   if(group_start)begin
    valid_map<=0;wide_map<=0;risk_map<=0;reserved_map<=0;c_map<=0;count<=0;init_page<=0;stack_count<=0;next_unused<=0;initial_pages<=0;tiles<=11'(group_rows*group_cols);c_count<=0;rows<=group_rows;cols<=group_cols;initializing<=1;init_calculate<=1;prep_state<=P_IDLE;release_active<=0;shrink_pending<=0;capacity_fault<=0;
    if(group_rows==0 || group_cols==0)capacity_fault<=1;
   end else if(initializing && init_calculate)begin
    initial_pages<=12'(tiles*3);init_calculate<=0;
    if(tiles>MAX_TILES || 13'(tiles*3)+13'(rows)>13'(PAGES))capacity_fault<=1;
   end else if(initializing)begin
    count<=12'(PAGES)-initial_pages;next_unused<=initial_pages;stack_count<=0;initializing<=0;
   end else if(group_release)begin count<=PAGES;next_unused<=0;stack_count<=0;c_map<=0;c_count<=0;end
   else begin
    if(pop_page)begin
     count<=count-1'b1;
     if(stack_count!=0)stack_count<=stack_count-1'b1;else next_unused<=next_unused+1'b1;
    end
    if(push_page)begin
     count<=count+1'b1;stack_count<=stack_count+1'b1;
     if(release_active)begin
      if(release_step==2 || (release_step==1 && !release_has_high))release_active<=0;
      else release_step<=release_step+1'b1;
     end else shrink_pending<=0;
    end
    if(scan_valid_q && need_q)begin need_mask[scan_row_q]<=1;need_count<=need_count+1'b1;end
    case(prep_state)
     P_IDLE:if(prepare_request)begin p_col<=prepare_col;frame_base<=10'(prepare_col*rows);p_final<=prepare_final;p_finish<=prepare_finish;scan_row<=0;need_mask<=0;need_count<=0;prep_state<=P_START;end
     P_START:begin scan_tile<=frame_base;scan_row<=0;prep_state<=P_SCAN;end
     P_SCAN:begin
      if(scan_row==rows-1'b1)prep_state<=P_DRAIN;
      else begin scan_row<=scan_row+1'b1;scan_tile<=scan_tile+1'b1;end
     end
     P_DRAIN:prep_state<=P_EVAL;
     P_EVAL:begin
      if(!p_final && !p_finish && {1'b0,count}<{6'b0,need_count}+{7'b0,rows})prep_state<=P_PRESSURE;
      else if(count<need_count)begin capacity_fault<=1;prep_state<=P_IDLE;end
      else begin alloc_row<=0;prep_state<=P_ALLOC;end
     end
     P_ALLOC:begin
      if(need_mask[alloc_row])begin alloc_tile<=frame_base+10'(alloc_row);prep_state<=P_POP;end
      else if(alloc_row==rows-1'b1)prep_state<=P_DONE;
      else alloc_row<=alloc_row+1'b1;
     end
     P_POP:if(pop_page)prep_state<=P_POP_WAIT;
     P_POP_WAIT:begin
      high_page[alloc_tile]<=stack_out;reserved_map[alloc_tile]<=1;
      if(alloc_row==rows-1'b1)prep_state<=P_DONE;else begin alloc_row<=alloc_row+1'b1;prep_state<=P_ALLOC;end
     end
     P_DONE,P_PRESSURE:prep_state<=P_IDLE;
     default:prep_state<=P_IDLE;
    endcase
    if(sum_valid && !sum_final)begin
     tile_wide<=sum_row==0?row_wide:(tile_wide|row_wide);tile_risk<=sum_row==0?row_risk:(tile_risk|row_risk);records_written<=records_written+1'b1;
     if(row_wide)long_records<=long_records+1'b1;
     if(sum_row==15)begin
      valid_map[sum_tile]<=1;wide_map[sum_tile]<=tile_wide|row_wide;risk_map[sum_tile]<=tile_risk|row_risk;reserved_map[sum_tile]<=0;
      if(!(tile_wide|row_wide) && sum_has_high)begin shrink_pending<=1;shrink_page<=sum_high;end
      if(sum_frame_last)begin frame_committed<=1;committed_col<=sum_col;committed_k<=sum_k;end
     end
    end
    if(c_write_valid && c_write_row==15)begin
     c_map[c_write_tile]<=1;c_count<=c_count+1'b1;valid_map[c_write_tile]<=0;wide_map[c_write_tile]<=0;reserved_map[c_write_tile]<=0;
     release_active<=1;release_step<=0;release_base<=PW'(c_write_tile*3);release_high<=high_page[c_write_tile];release_has_high<=wide_map[c_write_tile] || reserved_map[c_write_tile];
     if(c_write_frame_last)begin frame_committed<=1;committed_col<=c_write_col;committed_k<=c_write_k;end
    end
   end
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk)if(rst_n)begin
  assert(count<=PAGES)else $fatal(1,"PS free-page limit");
  if(capacity_fault)$fatal(1,"PS capacity fault");
  if(sum_valid && !sum_final && row_wide)assert(wide_map[sum_tile] || reserved_map[sum_tile])else $fatal(1,"unreserved PS expansion");
  if(c_read_request)assert(c_map[c_read_tile])else $fatal(1,"C tile not ready");
  if(c_write_valid)assert(!(sum_valid && !sum_final))else $fatal(1,"PS/C write conflict");
  for(int b=0;b<4;b++)assert(!(bank_re[b] && bank_we[b] && bank_ra[b]==bank_wa[b]))else $fatal(1,"PS port address collision");
  if(c_write_valid && c_write_row==15)assert(!release_active)else $fatal(1,"C page release overlap");
 end
`endif
endmodule
`endif
