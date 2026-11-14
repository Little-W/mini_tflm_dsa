// Two K=64 panels. The logical port ABI is retained while physical depth
// follows the maximum row/column tile group of this hardware instance.
`ifndef GEMPACT_PANEL_MAX_R
`define GEMPACT_PANEL_MAX_R 32
`endif
`ifndef GEMPACT_PANEL_MAX_W
`define GEMPACT_PANEL_MAX_W 32
`endif
module gempact_panel_cache #(
 parameter integer MAX_R=`GEMPACT_PANEL_MAX_R,
 parameter integer MAX_W=`GEMPACT_PANEL_MAX_W
)(
 input logic clk,rst_n,group_start,
 input logic[5:0] group_rows,group_cols,
 input logic[31:0] a_base,b_base,a_stride,b_stride,k_total,
 input logic load_request,input logic[15:0] load_panel,
 output logic load_ready,load_done,
 output logic[1:0] valid_buffers,output logic[15:0] panel_tags[2],
 input logic[15:0] a_re,input logic[11:0] a_addr[16],output logic signed[7:0] a_data[16],
 input logic b_re,input logic[9:0] b_addr,output logic[31:0] b_data[16],
 output logic arvalid,input logic arready,output logic[31:0] araddr,
 output logic[7:0] arlen,output logic[2:0] arsize,output logic[1:0] arburst,
 input logic rvalid,output logic rready,input logic[31:0] rdata,input logic[1:0] rresp,input logic rlast
);
 typedef enum logic[2:0]{IDLE,B_START,B_READ,A_START,A_READ,COMPLETE} st_t;
 st_t state;logic[31:0] ab,bb,as_,bs,kk;logic[5:0] rr,cc;
 logic[15:0] panel;logic buffer_sel;
 logic read_active,read_start,read_done,read_b;
 logic[9:0] issued_rows,total_rows;
 logic[8:0] response_row;
 logic[3:0] response_beat;
 logic[2:0] outstanding;
 logic[31:0] next_address,row_address;logic[6:0] row_bytes,row_remaining;
 logic[1:0] descriptor_head,descriptor_tail;logic descriptor_last[4];logic[3:0] descriptor_len[4];logic[3:0] physical_beat;
 logic[7:0] burst_len;
 wire[8:0] issue_bytes=({1'b0,burst_len}+9'd1)<<2;
 wire issue_row_last=issue_bytes=={2'b0,row_remaining};
 function automatic[7:0] burst_for(input logic[31:0] address,input logic[6:0] bytes);
  logic[12:0] boundary;logic[12:0] amount;
  boundary=13'd4096-{1'b0,address[11:0]};amount=boundary<{6'b0,bytes}?boundary:{6'b0,bytes};return 8'((amount>>2)-1'b1);
 endfunction
 wire ar_fire=arvalid&&arready,r_fire=rvalid&&rready;
 wire last_response=r_fire&&rlast;
 logic[31:0] panel_offset;
 logic[5:0] panel_words;
 assign load_ready=state==IDLE;
 assign load_done=state==COMPLETE;
 assign read_start=state==B_START || state==A_START;
 assign read_b=state==B_START || state==B_READ;
 assign rready=read_active;
 assign arlen=burst_len;assign arsize=2;assign arburst=1;
 always_comb begin
  panel_offset={10'b0,panel,6'b0};
  panel_words=(kk-panel_offset>=64)?6'd16:6'((kk-panel_offset)>>2);
 end
 for(genvar l=0;l<16;l++)begin:g_bank
  (* ram_style="block" *)logic signed[7:0] aram[0:128*MAX_R-1];
  (* ram_style="block" *)logic[31:0] bram[0:32*MAX_W-1];
  wire [$clog2(128*MAX_R)-1:0] a_phys=
      $clog2(128*MAX_R)'((int'(a_addr[l][11])*4+int'(a_addr[l][10:9]))*(16*MAX_R)+int'(a_addr[l][8:0]));
  wire [$clog2(32*MAX_W)-1:0] b_phys=
      $clog2(32*MAX_W)'((int'(b_addr[9])*MAX_W+int'(b_addr[8:4]))*16+int'(b_addr[3:0]));
  always_ff @(posedge clk)begin
   if(r_fire)begin
    if(read_b && response_row[3:0]==l)bram[(int'(buffer_sel)*MAX_W+int'(response_row[8:4]))*16+int'(response_beat)]<=rdata;
    if(!read_b)for(int z=0;z<4;z++)if(int'({response_beat[1:0],2'b0})+z==l)
     aram[(int'(buffer_sel)*4+int'(response_beat[3:2]))*(16*MAX_R)+int'(response_row)]<=$signed(rdata[z*8+:8]);
   end
   if(a_re[l])a_data[l]<=aram[a_phys];
   if(b_re)b_data[l]<=bram[b_phys];
  end
`ifndef SYNTHESIS
  always @(posedge clk)if(rst_n)begin
   if(a_re[l])assert(int'(a_addr[l][8:0])<16*MAX_R)else $fatal(1,"A panel address exceeds physical row capacity");
   if(b_re)assert(int'(b_addr[8:4])<MAX_W)else $fatal(1,"B panel address exceeds physical column capacity");
  end
`endif
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;ab<=0;bb<=0;as_<=0;bs<=0;kk<=0;rr<=0;cc<=0;panel<=0;buffer_sel<=0;valid_buffers<=0;panel_tags[0]<=0;panel_tags[1]<=0;
  end else begin
   if(group_start)begin
    ab<=a_base;bb<=b_base;as_<=a_stride;bs<=b_stride;kk<=k_total;rr<=group_rows;cc<=group_cols;valid_buffers<=0;state<=IDLE;
   end else case(state)
    IDLE:if(load_request)begin panel<=load_panel;buffer_sel<=load_panel[0];valid_buffers[load_panel[0]]<=0;state<=B_START;end
    B_START:state<=B_READ;
    B_READ:if(read_done)state<=A_START;
    A_START:state<=A_READ;
    A_READ:if(read_done)begin valid_buffers[buffer_sel]<=1;panel_tags[buffer_sel]<=panel;state<=COMPLETE;end
    COMPLETE:state<=IDLE;
    default:state<=IDLE;
   endcase
  end
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   arvalid<=0;araddr<=0;burst_len<=0;read_active<=0;read_done<=0;issued_rows<=0;total_rows<=0;response_row<=0;response_beat<=0;outstanding<=0;next_address<=0;row_address<=0;row_bytes<=0;row_remaining<=0;descriptor_head<=0;descriptor_tail<=0;physical_beat<=0;
  end else begin
   read_done<=0;
   if(read_start)begin
    read_active<=1;issued_rows<=0;total_rows<=10'(read_b?cc:rr)<<4;response_row<=0;response_beat<=0;outstanding<=0;
    arvalid<=0;next_address<=(read_b?bb:ab)+panel_offset;row_address<=(read_b?bb:ab)+panel_offset;row_bytes<=7'(panel_words<<2);row_remaining<=7'(panel_words<<2);descriptor_head<=0;descriptor_tail<=0;physical_beat<=0;
   end else if(read_active)begin
    if(ar_fire)begin
     arvalid<=0;descriptor_last[descriptor_tail]<=issue_row_last;descriptor_len[descriptor_tail]<=burst_len[3:0];descriptor_tail<=descriptor_tail+1'b1;
     if(issue_row_last)begin issued_rows<=issued_rows+1'b1;row_address<=row_address+(read_b?bs:as_);next_address<=row_address+(read_b?bs:as_);row_remaining<=row_bytes;end
     else begin next_address<=next_address+32'(issue_bytes);row_remaining<=row_remaining-7'(issue_bytes);end
    end else if(!arvalid && issued_rows<total_rows && outstanding<4)begin arvalid<=1;araddr<=next_address;burst_len<=burst_for(next_address,row_remaining);end
    case({ar_fire,last_response})2'b10:outstanding<=outstanding+1'b1;2'b01:outstanding<=outstanding-1'b1;default:;endcase
    if(r_fire)begin
     if(rlast)begin
      physical_beat<=0;descriptor_head<=descriptor_head+1'b1;
      if(descriptor_last[descriptor_head])begin
       response_beat<=0;response_row<=response_row+1'b1;
       if({1'b0,response_row}+1'b1==total_rows)begin read_active<=0;read_done<=1;end
      end else response_beat<=response_beat+1'b1;
     end else begin response_beat<=response_beat+1'b1;physical_beat<=physical_beat+1'b1;end
    end
   end
  end
 end
`ifndef SYNTHESIS
 initial begin
  assert(MAX_R>=1 && MAX_R<=32 && MAX_W>=1 && MAX_W<=32)else $fatal(1,"invalid physical panel configuration");
 end
 always @(posedge clk)if(rst_n)begin
  if(group_start)assert(group_rows>0 && group_rows<=MAX_R && group_cols>0 && group_cols<=MAX_W)else $fatal(1,"group exceeds physical panel capacity");
  assert(outstanding<=4)else $fatal(1,"panel outstanding limit");
  if(ar_fire)assert({1'b0,araddr[11:0]}+((13'(arlen)+1'b1)<<2)<=4096);
  if(r_fire)begin assert(rresp==0);assert(rlast==(physical_beat==descriptor_len[descriptor_head]));end
 end
`endif
endmodule
