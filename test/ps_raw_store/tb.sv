module ps_raw_store_tb #(parameter MAX_FRAME_ROWS=16)(
 input logic clk,rst_n,cfg_valid,
 input logic [31:0] cfg_pool_bank_count,
 input logic frame_request,frame_accept,
 input logic [1:0] frame_id,
 input logic [31:0] frame_rows,
 input logic frame_init,frame_final,
 output wire frame_ready,frame_pressure,capacity_fault,frame_complete,
 input logic write_valid,write_frame_end,replay_trigger,
 input logic [511:0] write_data,
 output wire [511:0] replay_data,
 output wire replay_valid,
 output wire [3:0] ram_read_en,ram_write_en,
 output wire [39:0] read_addresses,write_addresses,
 output wire [511:0] ram_write_packet,
 input logic [511:0] ram_read_packet
);
 wire [9:0] ram_read_addr[4],ram_write_addr[4];
 wire [127:0] ram_read_data[4],ram_write_data[4];
 for(genvar p=0;p<4;p++)begin
  assign read_addresses[p*10+:10]=ram_read_addr[p];
  assign write_addresses[p*10+:10]=ram_write_addr[p];
  assign ram_write_packet[p*128+:128]=ram_write_data[p];
  assign ram_read_data[p]=ram_read_packet[p*128+:128];
 end
 ps_frame_store #(.MAX_FRAME_ROWS(MAX_FRAME_ROWS),.FRAME_COUNT(4),.POOL_BYTES(16384),.BANK_BYTES(2048),
  .EXTERNAL_RAM(1),.DIRECTORY_ROWS(4*MAX_FRAME_ROWS),.RAM_ADDR_BITS(10)) dut(
  .clk,.rst_n,.cfg_valid,.cfg_pool_bank_words(32'd128),.cfg_pool_bank_count,.cfg_directory_stride(32'(MAX_FRAME_ROWS)),
  .ram_read_en,.ram_read_addr,.ram_read_data,.ram_write_en,.ram_write_addr,.ram_write_data,
  .frame_request,.frame_accept,.frame_id,.frame_rows,.frame_reserve_rows(32'd16),.frame_word_cap(3'd4),
  .frame_init,.frame_final,.force_raw_i(1'b1),.frame_ready,.frame_pressure,.capacity_fault,.frame_complete,
  .write_valid,.write_data,.write_frame_end,.replay_trigger,.replay_data,.replay_valid);
`ifdef PS_COMPARE_REFERENCE
 wire ref_frame_ready,ref_frame_pressure,ref_capacity_fault,ref_frame_complete,ref_replay_valid;
 wire [511:0] ref_replay_data;
 wire [3:0] ref_ram_read_en,ref_ram_write_en;
 wire [9:0] ref_ram_read_addr[4],ref_ram_write_addr[4];
 wire [127:0] ref_ram_write_data[4];
 ps_frame_store_ref #(.MAX_FRAME_ROWS(MAX_FRAME_ROWS),.FRAME_COUNT(4),.POOL_BYTES(16384),.BANK_BYTES(2048),
  .EXTERNAL_RAM(1),.DIRECTORY_ROWS(4*MAX_FRAME_ROWS),.RAM_ADDR_BITS(10)) reference(
  .clk,.rst_n,.cfg_valid,.cfg_pool_bank_words(32'd128),.cfg_pool_bank_count,.cfg_directory_stride(32'(MAX_FRAME_ROWS)),
  .ram_read_en(ref_ram_read_en),.ram_read_addr(ref_ram_read_addr),.ram_read_data,
  .ram_write_en(ref_ram_write_en),.ram_write_addr(ref_ram_write_addr),.ram_write_data(ref_ram_write_data),
  .frame_request,.frame_accept,.frame_id,.frame_rows,.frame_reserve_rows(32'd16),.frame_word_cap(3'd4),
  .frame_init,.frame_final,.force_raw_i(1'b1),.frame_ready(ref_frame_ready),.frame_pressure(ref_frame_pressure),
  .capacity_fault(ref_capacity_fault),.frame_complete(ref_frame_complete),.write_valid,.write_data,.write_frame_end,
  .replay_trigger,.replay_data(ref_replay_data),.replay_valid(ref_replay_valid));
 always @(negedge clk) if(rst_n)begin
  assert({frame_ready,frame_pressure,capacity_fault,frame_complete,replay_valid,ram_read_en,ram_write_en,replay_data}===
   {ref_frame_ready,ref_frame_pressure,ref_capacity_fault,ref_frame_complete,ref_replay_valid,
    ref_ram_read_en,ref_ram_write_en,ref_replay_data})else $fatal(1,"PS control or replay cycle mismatch");
  for(int p=0;p<4;p++)begin
   assert(ram_read_addr[p]===ref_ram_read_addr[p])else $fatal(1,"PS read address cycle mismatch");
   assert(ram_write_addr[p]===ref_ram_write_addr[p])else $fatal(1,"PS write address cycle mismatch");
   assert(ram_write_data[p]===ref_ram_write_data[p])else $fatal(1,"PS write data cycle mismatch");
  end
 end
`endif
endmodule
