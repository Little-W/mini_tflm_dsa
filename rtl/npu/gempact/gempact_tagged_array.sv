// Two weight contexts permit consecutive frames to overlap in one MAC array.
module gempact_tagged_array(
 input logic clk,weight_write,weight_write_bank,
 input logic signed[7:0] weight_in[16],a_in[16],
 input logic a_bank[16],
 output wire signed[31:0] result[16]
);
 wire signed[7:0] data_path[16][16];
 wire data_bank[16][16];
 wire signed[31:0] sum_path[16][16];
 wire signed[7:0] weights[16][16][2];
 for(genvar r=0;r<16;r++)begin:g_row
  for(genvar c=0;c<16;c++)begin:g_col
   logic signed[7:0] w0,w1,data_q,weight_q;logic bank_q;logic signed[31:0] sum_q;
   wire signed[7:0] next_weight;
   if(r==0)assign next_weight=weight_in[c];
   else assign next_weight=weight_write_bank?weights[r-1][c][1]:weights[r-1][c][0];
   wire signed[7:0] di;wire db;wire signed[31:0] si;
   if(c==0)begin assign di=a_in[r];assign db=a_bank[r];end
   else begin assign di=data_path[r][c-1];assign db=data_bank[r][c-1];end
   if(r==0)assign si=0;else assign si=sum_path[r-1][c];
   always_ff @(posedge clk)begin
    if(weight_write)begin if(weight_write_bank)w1<=next_weight;else w0<=next_weight;end
    data_q<=di;bank_q<=db;sum_q<=si;weight_q<=db?w1:w0;
   end
   (* use_dsp="yes" *)wire signed[31:0] product=$signed(data_q)*$signed(weight_q);
   assign weights[r][c][0]=w0;assign weights[r][c][1]=w1;
   assign data_path[r][c]=data_q;assign data_bank[r][c]=bank_q;
   assign sum_path[r][c]=sum_q+product;
  end
 end
 for(genvar c=0;c<16;c++)assign result[c]=sum_path[15][c];
endmodule
