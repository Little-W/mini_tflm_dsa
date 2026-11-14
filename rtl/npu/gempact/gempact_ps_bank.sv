// Explicit 1024-word BRAM segments preserve physical depth without rounding
// the complete bank up to the next power of two. Read latency is three clocks.
module gempact_ps_bank #(
 parameter integer DEPTH=5120,AW=$clog2(DEPTH),PARTS=(DEPTH+1023)/1024
)(
 input logic clk,write_enable,read_enable,
 input logic[AW-1:0] write_address,read_address,
 input logic[127:0] write_data,
 output logic[127:0] read_data
);
 localparam integer SW=PARTS<=1?1:$clog2(PARTS);
 logic write_enable_q=0,read_enable_q=0;
 logic[AW-1:0] write_address_q,read_address_q;
 logic[127:0] write_data_q;
 always @(posedge clk)begin
  write_enable_q<=write_enable;read_enable_q<=read_enable;
  write_address_q<=write_address;read_address_q<=read_address;write_data_q<=write_data;
 end
 logic[127:0] part_data[PARTS];logic[SW-1:0] part_select;
 for(genvar p=0;p<PARTS;p++)begin:g_part
  localparam integer WORDS=DEPTH-p*1024>=1024?1024:DEPTH-p*1024;
  (* ram_style="block" *)logic[127:0] ram[0:WORDS-1];
  always_ff @(posedge clk)begin
   if(write_enable_q && (write_address_q>>10)==p)ram[write_address_q&10'h3ff]<=write_data_q;
   if(read_enable_q && (read_address_q>>10)==p)part_data[p]<=ram[read_address_q&10'h3ff];
  end
 end
 always_ff @(posedge clk)begin
  if(read_enable_q)part_select<=SW'(read_address_q>>10);
  read_data<=part_data[part_select];
 end
endmodule
