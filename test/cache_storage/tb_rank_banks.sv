// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_rank_banks;
localparam integer SETS=128,SI=7;
logic clk=0,clear_en=0,write_en=0,fill_valid=0,hint_valid=0,hit_valid=0,read_en=0;
logic [SI-1:0] clear_addr=0,fill_addr=0,hint_addr=0,hit_addr=0,read_addr=0;
logic [1:0] read_data,reference_data;
logic [1:0] reference_memory[SETS];
wire [SETS-1:0][1:0] combined;
logic initialized=0;
integer checks=0;
logic [31:0] random_state=32'hc00100ab;
always #5 clk=~clk;
conv_cache_rank_table dut (
 .clk(clk), .i_clear_en(clear_en), .i_clear_addr(clear_addr), .i_write_en(write_en),
 .i_fill_valid(fill_valid), .i_fill_addr(fill_addr), .i_hint_valid(hint_valid), .i_hint_addr(hint_addr),
 .i_hit_valid(hit_valid), .i_hit_addr(hit_addr), .i_read_en(read_en), .i_read_addr(read_addr),
 .o_read_data(read_data)
);
for(genvar row=0;row<SETS;row++) begin:g_row
 assign combined[row]=dut.g_bank[0].u_storage.mem[row]^dut.g_bank[1].u_storage.mem[row]^dut.g_bank[2].u_storage.mem[row];
end
always @(posedge clk) begin
 if(clear_en)reference_memory[clear_addr]<=0;
 else if(write_en)begin
  if(hit_valid)reference_memory[hit_addr]<=2;
  if(hint_valid)reference_memory[hint_addr]<=1;
  if(fill_valid)reference_memory[fill_addr]<=0;
 end
 if(read_en)reference_data<=reference_memory[read_addr];
 #1;
 if(initialized)begin
  if(read_data!==reference_data)$fatal(1,"Read mismatch");
  for(integer row=0;row<SETS;row=row+1)begin
   if(combined[row]!==reference_memory[row])$fatal(1,"State mismatch row=%0d",row);
   if(((^combined[row]) === 1'bx))$fatal(1,"Undefined initialized state row=%0d current=%b reference=%b banks=%b/%b/%b",row,combined[row],reference_memory[row],dut.g_bank[0].u_storage.mem[row],dut.g_bank[1].u_storage.mem[row],dut.g_bank[2].u_storage.mem[row]);
  end
  checks=checks+1;
 end
end
initial begin
 for(integer row=0;row<SETS;row=row+1)begin
  @(negedge clk);clear_en=1;clear_addr=SI'(row);
 end
 @(negedge clk);clear_en=0;initialized=1;
 for(integer cycle=0;cycle<100000;cycle=cycle+1)begin
  @(negedge clk);
  random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
  {fill_valid,hint_valid,hit_valid}=random_state[2:0];write_en=random_state[4];read_en=random_state[5];
  clear_en=random_state[12:6]==7'd37;clear_addr=random_state[19:13];
  fill_addr=random_state[6:0];hint_addr=random_state[13:7];hit_addr=random_state[20:14];read_addr=random_state[27:21];
  case(cycle%4)
   0:begin hint_addr=fill_addr;hit_addr=fill_addr;end
   1:hint_addr=hit_addr;
   2:hit_addr=fill_addr;
   default:;
  endcase
 end
 @(negedge clk);$display("RANK_BANK_FOUR_STATE_PASS cycles=%0d state_bits=256",checks);$finish;
end
endmodule
