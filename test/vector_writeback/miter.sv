module miter;
  parameter BUS_WIDTH = 64;
  reg clk = 0, rst_n = 0;
  reg request_valid = 0, request_byte_output = 0, request_coalesce = 0;
  reg request_last = 0, flush = 0, wr_granted = 0, src_wready = 0;
  reg wr_done = 0, wr_error = 0;
  reg [31:0] request_address = 0;
  reg [6:0] request_bytes = 0;
  reg [511:0] result_words = 0;
  wire [1:0] request_ready, busy, done, error, wr_req, wr_start, src_wvalid;
  wire [31:0] wr_base_addr [2], wr_row_stride [2], wr_rows_to_write [2];
  wire [7:0] wr_burst_len_m1 [2];
  wire [BUS_WIDTH-1:0] src_wdata [2];
  wire [BUS_WIDTH/8-1:0] src_wmask [2];
  vector_writeback #(.BUS_WIDTH(BUS_WIDTH)) candidate (
    .clk, .rst_n, .request_valid, .request_ready(request_ready[0]), .request_address,
    .request_bytes, .request_byte_output, .result_words, .request_coalesce,
    .request_last, .flush, .busy(busy[0]), .done(done[0]), .error(error[0]),
    .wr_req(wr_req[0]), .wr_start(wr_start[0]), .wr_granted,
    .wr_base_addr(wr_base_addr[0]), .wr_row_stride(wr_row_stride[0]),
    .wr_rows_to_write(wr_rows_to_write[0]), .wr_burst_len_m1(wr_burst_len_m1[0]),
    .src_wdata(src_wdata[0]), .src_wmask(src_wmask[0]), .src_wvalid(src_wvalid[0]),
    .src_wready, .wr_done, .wr_error);
  vector_writeback_baseline #(.BUS_WIDTH(BUS_WIDTH)) baseline (
    .clk, .rst_n, .request_valid, .request_ready(request_ready[1]), .request_address,
    .request_bytes, .request_byte_output, .result_words, .request_coalesce,
    .request_last, .flush, .busy(busy[1]), .done(done[1]), .error(error[1]),
    .wr_req(wr_req[1]), .wr_start(wr_start[1]), .wr_granted,
    .wr_base_addr(wr_base_addr[1]), .wr_row_stride(wr_row_stride[1]),
    .wr_rows_to_write(wr_rows_to_write[1]), .wr_burst_len_m1(wr_burst_len_m1[1]),
    .src_wdata(src_wdata[1]), .src_wmask(src_wmask[1]), .src_wvalid(src_wvalid[1]),
    .src_wready, .wr_done, .wr_error);
  integer cycle, i;
  reg [31:0] next_address = 32'hff8;
  initial begin
    for (cycle=0; cycle<30000; cycle=cycle+1) begin
      clk=0;
      rst_n=(cycle>=3 && cycle%5003!=0);
      request_valid=($urandom_range(0,3)!=0);
      request_bytes=$urandom_range(1,64);
      request_byte_output=$urandom_range(0,1);
      if (request_byte_output) request_bytes=$urandom_range(1,16);
      request_coalesce=$urandom_range(0,3)!=0;
      request_last=$urandom_range(0,7)==0;
      flush=$urandom_range(0,31)==0;
      wr_granted=$urandom_range(0,3)!=0;
      src_wready=$urandom_range(0,3)!=0;
      wr_done=$urandom_range(0,3)==0;
      wr_error=$urandom_range(0,4)==0;
      request_address=next_address;
      for (i=0;i<16;i=i+1) result_words[i*32+:32]=$urandom;
      #1;
      if (rst_n && cycle>4) begin
        if (request_ready[0] !== request_ready[1] || busy[0] !== busy[1] ||
            done[0] !== done[1] || error[0] !== error[1] || wr_req[0] !== wr_req[1] ||
            wr_start[0] !== wr_start[1] || src_wvalid[0] !== src_wvalid[1])
          $fatal(1,"control mismatch cycle %0d",cycle);
        if (wr_req[0] && {wr_base_addr[0],wr_row_stride[0],wr_rows_to_write[0],wr_burst_len_m1[0]} !==
                         {wr_base_addr[1],wr_row_stride[1],wr_rows_to_write[1],wr_burst_len_m1[1]})
          $fatal(1,"request mismatch cycle %0d",cycle);
        if (src_wvalid[0]) begin
          if (src_wmask[0] !== src_wmask[1]) $fatal(1,"mask mismatch cycle %0d",cycle);
          if (src_wdata[0] !== src_wdata[1]) $fatal(1,"data mismatch cycle %0d",cycle);
        end
      end
      if (request_valid && request_ready[0]) begin
        next_address=next_address+request_bytes;
        if ($urandom_range(0,15)==0) next_address=next_address+$urandom_range(1,7);
      end
      clk=1; #1;
    end
    $display("MITER_PASS width=%0d cycles=%0d", BUS_WIDTH, cycle);
    $finish;
  end
endmodule
