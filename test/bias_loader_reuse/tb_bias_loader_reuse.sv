module bias_reuse_case #(parameter int GROUP_BLOCKS = 1, parameter int BUS_WIDTH = 32)(output logic finished);
  localparam int SIZE = 16;
  localparam int LANES = BUS_WIDTH/8;
  localparam int WORDS = BUS_WIDTH/32;
  logic clk = 0;
  always #5 clk = !clk;
  logic rst_n = 0, init_cfg = 0, bias_switch = 0, bias_last_loop = 0;
  logic [31:0] bias_base = 0, channels = 0, step_blocks = 1;
  logic req, grant, valid, group_valid, dma_start, dma_busy = 0, dma_done = 0;
  logic group_read_start = 0;
  logic [31:0] dma_base, dma_rows;
  logic [7:0] dma_len;
  logic dma_slot, wr_slot = 0;
  logic [5:0] wr_row = 0, wr_col = 0;
  logic signed [7:0] wr_data[LANES];
  logic wr_valid[LANES];
  logic signed [31:0] data[SIZE], scalar;
  logic [$clog2(GROUP_BLOCKS*SIZE)-1:0] read_idx = 0;
  int commands = 0, cycle = 0, generation = 0;
  int transfer_word = 0, transfer_rows = 0, transfer_cols = 0, delay_left = 0;
  logic [31:0] transfer_base;
  logic transfer_bank;

  function automatic logic [31:0] memory_word(input logic [31:0] address);
    return (32'h31415926 ^ (address * 32'h10203)) + 32'(generation * 1777);
  endfunction

  assign grant = req && !dma_busy && cycle % 3 == 0;
  bias_loader #(.SIZE(SIZE), .BUS_WIDTH(BUS_WIDTH), .COUNT_WIDTH(12), .GROUP_BLOCKS_MAX(GROUP_BLOCKS)) dut (
    .clk, .rst_n, .init_cfg, .bias_base, .k(32'd128), .m(channels),
    .bias_step_blocks(step_blocks), .bias_switch, .bias_sleep(1'b0), .bias_last_loop,
    .load_bias_req(req), .load_bias_granted(grant), .bias_valid(valid),
    .bias_group_valid(group_valid), .load_bias_done(), .group_read_start, .group_read_idx(read_idx),
    .data_out(data), .group_data_scalar(scalar), .ext_dma_start(dma_start),
    .ext_dma_is_write(), .ext_dma_linear_read_mode(), .ext_dma_base_addr(dma_base),
    .ext_dma_row_stride(), .ext_dma_rows_to_read(dma_rows), .ext_dma_burst_len_m1(dma_len),
    .ext_dma_slot_id(dma_slot), .ext_dma_use_16bits(), .ext_dma_lhs_zp(),
    .ext_dma_busy(dma_busy), .ext_dma_done(dma_done), .ext_dma_wr_slot(wr_slot),
    .ext_dma_wr_row(wr_row), .ext_dma_wr_col_base(wr_col), .ext_dma_wr_data(wr_data),
    .ext_dma_wr_valid(wr_valid), .ext_dma_wr_use_16bits(1'b0));

  always @(posedge clk) begin
    cycle <= cycle + 1;
    dma_done <= 0;
    for (int b=0;b<LANES;b++) wr_valid[b] <= 0;
    if (dma_start) begin
      assert(!dma_busy) else $fatal(1,"DMA request while busy");
      assert(dma_rows>0 && dma_base>=bias_base &&
             64'(dma_base)+(64'(dma_rows)-1)*SIZE*4+(64'(dma_len)+1)*LANES<=64'(bias_base)+((64'(channels)*4+64'(LANES)-1)/64'(LANES))*64'(LANES))
        else $fatal(1,"Bias request outside allocated channels");
      commands <= commands + 1;
      dma_busy <= 1;
      transfer_word <= 0;
      transfer_rows <= int'(dma_rows);
      transfer_cols <= (int'(dma_len) + 1)*WORDS;
      transfer_base <= dma_base;
      transfer_bank <= dma_slot;
      delay_left <= 2;
    end else if (dma_busy) begin
      if (delay_left != 0) delay_left <= delay_left - 1;
      else if (cycle % 4 != 0) begin
        automatic int row = transfer_word / transfer_cols;
        automatic int col = transfer_word % transfer_cols;
        wr_row <= 6'(row);
        wr_col <= 6'(col*4);
        wr_slot <= transfer_bank;
        for (int b=0;b<LANES;b++) begin
          wr_data[b] <= 8'(memory_word(transfer_base+32'((row*SIZE+col+b/4)*4)) >> ((b%4)*8));
          wr_valid[b] <= 1;
        end
        transfer_word <= transfer_word + WORDS;
        if (transfer_word + WORDS == transfer_rows * transfer_cols) begin
          dma_busy <= 0;
          dma_done <= 1;
        end
      end
    end
  end

  task automatic await_group;
    int timeout_count = 0;
    while (!group_valid) begin
      @(negedge clk);
      timeout_count++;
      assert(timeout_count < 2000) else $fatal(1,"Bias group timeout");
    end
  endtask

  function automatic int expected_dma(input int count, step, repeats);
    int base[2], span[2], active, blocks, needed, index, total;
    base[0]=-1; base[1]=-1; span[0]=0; span[1]=0; active=0; total=0;
    blocks=(count+SIZE-1)/SIZE;
    for(int rep=0;rep<repeats;rep++) begin
      for(index=0;index<blocks;index+=step) begin
        needed=(blocks-index<step)?blocks-index:step;
        if(base[0]>=0 && index>=base[0] && index+needed<=base[0]+span[0]) active=0;
        else if(base[1]>=0 && index>=base[1] && index+needed<=base[1]+span[1]) active=1;
        else begin
          if(total!=0) active=1-active;
          base[active]=index;
          span[active]=(blocks-index<GROUP_BLOCKS)?blocks-index:GROUP_BLOCKS;
          total++;
          if(index+span[active]==blocks && span[active]>1 && count%SIZE!=0) total++;
        end
      end
    end
    return total;
  endfunction

  task automatic run_case(input int count, step, repeats);
    int before_commands, first_cycle, blocks, groups, expected_commands, previous_group_base;
    expected_commands = expected_dma(count,step,repeats);
    previous_group_base = -1;
    before_commands = commands;
    first_cycle = cycle;
    blocks = (count + SIZE - 1) / SIZE;
    groups = (blocks + step - 1) / step;
    @(negedge clk);
    channels = 32'(count); step_blocks = 32'(step); bias_base = 32'h1000;
    generation++; init_cfg = 1; bias_last_loop = 0;
    @(negedge clk); init_cfg = 0;
    for (int rep=0;rep<repeats;rep++) begin
      for (int group=0;group<groups;group++) begin
        int elements;
        elements = count - group * step * SIZE;
        if (elements > step * SIZE) elements = step * SIZE;
        await_group();
        read_idx = 0;
        #1;
        if (previous_group_base >= 0)
          assert(scalar === $signed(memory_word(bias_base + 32'(previous_group_base*4))))
            else $fatal(1,"Executing bias group changed during preparation");
        group_read_start = 1;
        @(negedge clk); group_read_start = 0;
        previous_group_base = group*step*SIZE;
        for (int i=0;i<elements;i++) begin
          read_idx = $clog2(GROUP_BLOCKS*SIZE)'(i);
          #1;
          assert(scalar === $signed(memory_word(bias_base + 32'((group*step*SIZE+i)*4))))
            else $fatal(1,"Bias scalar mismatch: capacity=%0d channels=%0d group=%0d element=%0d",GROUP_BLOCKS,count,group,i);
          if (i<SIZE) assert(data[i] === scalar) else $fatal(1,"Bias lane mismatch");
          @(negedge clk);
        end
        bias_last_loop = rep == repeats-1 && group == groups-1;
        bias_switch = 1;
        @(negedge clk); bias_switch = 0;
        @(negedge clk);
      end
    end
    repeat(4) @(negedge clk);
    assert(commands-before_commands == expected_commands)
      else $fatal(1,"DMA count: capacity=%0d channels=%0d got=%0d expected=%0d",GROUP_BLOCKS,count,commands-before_commands,expected_commands);
    $display("BIAS_REUSE_PASS bus=%0d capacity=%0d channels=%0d step=%0d repeats=%0d dma_commands=%0d cycles=%0d",BUS_WIDTH,GROUP_BLOCKS,count,step,repeats,commands-before_commands,cycle-first_cycle);
  endtask

  initial begin
    finished = 0;
    for (int b=0;b<LANES;b++) begin wr_data[b]=0; wr_valid[b]=0; end
    repeat(3) @(negedge clk);
    rst_n = 1;
    run_case(7,1,5);
    run_case(32,1,4);
    run_case(17,1,3);
    run_case(48,1,3);
    run_case(16,1,2);
    run_case(16,1,2);
    if (GROUP_BLOCKS >= 2) begin
      run_case(64,2,4);
      run_case(49,2,3);
      run_case(33,2,3);
      run_case(96,2,2);
      run_case(23,2,4);
      run_case(31,2,3);
    end
    if (GROUP_BLOCKS >= 4) begin
      run_case(63,4,3);
      run_case(127,4,3);
    end
    if (GROUP_BLOCKS >= 4) begin
      run_case(64,1,4);
      run_case(95,3,3);
      run_case(129,3,3);
    end
    if (GROUP_BLOCKS >= 8) begin
      run_case(127,8,3);
      run_case(255,8,3);
    end
    @(negedge clk); bias_base = 0; init_cfg = 1;
    @(negedge clk); init_cfg = 0;
    repeat(20) begin
      @(negedge clk);
      assert(!req && !dma_start) else $fatal(1,"Unexpected DMA for absent bias");
    end
    finished = 1;
  end
endmodule

module tb_bias_loader_reuse;
  wire [7:0] done;
  for(genvar b=0;b<2;b++) begin : gen_bus
    for(genvar c=0;c<4;c++) begin : gen_capacity
      bias_reuse_case #(.GROUP_BLOCKS(1<<c),.BUS_WIDTH(32*(b+1))) dut(done[b*4+c]);
    end
  end
  initial begin
    wait(&done);
    $display("BIAS_LOADER_REUSE_PASS");
    $finish;
  end
  initial begin
    #2000000;
    $fatal(1,"Test timeout");
  end
endmodule
