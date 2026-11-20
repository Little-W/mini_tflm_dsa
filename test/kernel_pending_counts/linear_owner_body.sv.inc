logic initial_cycle=1'b1;
logic rst_n;
always_ff @(posedge clk) initial_cycle<=1'b0;
assign rst_n=requested_rst_n&&!initial_cycle;
axi_linear_block_dma #(.DATA_WIDTH(DATA_WIDTH),.SIZE(SIZE),.BUS_WIDTH(BUS_WIDTH),.REG_WIDTH(REG_WIDTH),
    .CACHE_BLOCKS(CACHE_BLOCKS),.DMA_MAX_BYTES(DMA_MAX_BYTES),.READ_OUTSTANDING(READ_OUTSTANDING),
    .RD_CONTEXT_DEPTH(RD_CONTEXT_DEPTH),.RD_TAG_WIDTH(RD_TAG_WIDTH),.WRITE_OUTSTANDING(WRITE_OUTSTANDING)) dut (.*);
logic [RD_CONTEXT_DEPTH-1:0] owner_valid;
logic [$clog2(CACHE_BLOCKS)-1:0] owner_slot[RD_CONTEXT_DEPTH];
logic [RD_TAG_WIDTH-1:0] owner_tag[RD_CONTEXT_DEPTH];
logic done_saved;
logic [$clog2(CACHE_BLOCKS)-1:0] done_slot;
logic [RD_TAG_WIDTH-1:0] done_tag;
logic [$clog2(RD_CONTEXT_DEPTH+2):0] pending_count;
always_ff @(posedge clk) begin
 if(!rst_n) begin owner_valid<='0;done_saved<=0;done_slot<='0;done_tag<='0;pending_count<='0;end
 else begin
  done_saved<=dut.rd_finish_beat;
  if(dut.rd_finish_beat) begin
   owner_valid[dut.rd_context_head]<=0;
   done_slot<=owner_slot[dut.rd_context_head];
   done_tag<=owner_tag[dut.rd_context_head];
  end
  if(dut.rd_accept_start) begin
   owner_valid[dut.rd_context_tail]<=1;
   owner_slot[dut.rd_context_tail]<=rd_slot_id;
   owner_tag[dut.rd_context_tail]<=rd_tag;
  end
  case({dut.rd_accept_start,rd_done})
   2'b10:pending_count<=pending_count+1'b1;
   2'b01:pending_count<=pending_count-1'b1;
   default:;
  endcase
 end
end
logic [RD_CONTEXT_DEPTH-1:0] ring_valid, memory_match;
for(genvar i=0;i<RD_CONTEXT_DEPTH;i++) begin:g_owner_ring
 logic [$clog2(RD_CONTEXT_DEPTH)-1:0] index;
 assign index=dut.rd_context_head+$clog2(RD_CONTEXT_DEPTH)'(i);
 assign ring_valid[i]=owner_valid[index]==(i<dut.rd_context_count);
 assign memory_match[i]=!owner_valid[i] ||
     (owner_slot[i]==dut.u_context_storage.mem[i][REG_WIDTH+2 +: $clog2(CACHE_BLOCKS)] &&
      owner_tag[i]==dut.rd_context_tag_q[i]);
end
assign relation=!rst_n || (
 dut.rd_context_count<=RD_CONTEXT_DEPTH &&
 dut.rd_context_tail==$clog2(RD_CONTEXT_DEPTH)'(dut.rd_context_head+dut.rd_context_count) &&
 (&ring_valid) && (&memory_match) &&
 (!dut.rd_finish_beat || owner_valid[dut.rd_context_head]) &&
 (!dut.rd_accept_start || !owner_valid[dut.rd_context_tail] ||
   (dut.rd_finish_beat && dut.rd_context_head==dut.rd_context_tail)) &&
 (!dut.rd_active || (owner_slot[dut.rd_context_head]==dut.rd_head.slot && owner_tag[dut.rd_context_head]==dut.rd_head.tag)) &&
 done_saved==rd_done &&
 (!rd_done || (wr_slot==done_slot && rd_response_tag==done_tag)) &&
 pending_count==(dut.rd_context_count+($clog2(RD_CONTEXT_DEPTH+2)+1)'(rd_done)) &&
 pending_count<=RD_CONTEXT_DEPTH+1);
endmodule
