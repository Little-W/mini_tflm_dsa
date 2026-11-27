/* verilator lint_off DECLFILENAME */
// SPDX-License-Identifier: Apache-2.0
// 前端配置、描述符队列和连续输出的独立数值验证。
// 输入文件由 direct_im2col 方程生成，传入 +VECTORS=<path> 执行。
module tb_conv_im2col_frontend;
  import conv_im2col_pkg::*;
  parameter int SIZE=16, LANES=16, CACHE_POLICY=3, BUS_WIDTH=64;
  parameter int SLOT_W=6;
  parameter bit REGISTER_DESCRIPTOR=1'b1;
  parameter int CACHE_RESPONSE_DEPTH=1;
  parameter int NARROW_MODE=0;
  localparam int BUS_BYTES=BUS_WIDTH/8;
  parameter bit PREFETCH=0, WINDOWED=0;
  parameter int CACHE_SETS=128, CACHE_WAYS=2, LINE_BYTES=16;
  parameter bit USE_TILE_PATH=0;
  parameter logic [31:0] NATIVE_SCHED_R=0, NATIVE_SCHED_GROUPS=0;
  parameter int EXPECT_GEOMETRY_PREDICTIONS=-1;
  parameter int unsigned MAX_CYCLES=100000000;
  localparam int CW=$clog2(SIZE), RW=$clog2(SIZE+1), MEM_BYTES=1048576;
  logic unused_wr_last;
  logic clk;
  initial begin clk=0; forever #5 clk=~clk; end
  logic rst_n=0, cfg_valid=0, cfg_ready;
  conv_cfg_t cfg;
  logic tile_valid=0,tile_ready;
  logic tile_narrow=0;
  logic [31:0] tile_p0=0,tile_q0=0;
  logic [RW-1:0] tile_rows=0;
  logic [SLOT_W-1:0] tile_slot=0;
  logic wr_valid,wr_ready;
  logic [SLOT_W-1:0] wr_slot;
  logic [CW-1:0] wr_row,wr_col;
  logic signed [15:0] wr_data[LANES];
  logic [LANES-1:0] wr_mask;
  logic tile_done,tile_error,error,busy;
  logic [31:0] stat_hits,stat_misses,stat_read_bytes;
  logic [31:0] stat_prefetch_lines,stat_prefetch_used,stat_prefetch_wasted,stat_prefetch_unused,stat_prefetch_bytes,stat_prefetch_late;
  logic arvalid,arready,rvalid,rready,rlast;
  logic [31:0] araddr;
  logic [BUS_WIDTH-1:0] rdata;
  logic [7:0] arlen;
  logic [2:0] arsize;
  logic [1:0] arburst,rresp;
  byte unsigned memory[MEM_BYTES];
  // 参考结果保存固定数量的矩阵元素，描述符容量随分块尺寸调整。
  localparam int MAX_TILES=(262144+SIZE*SIZE-1)/(SIZE*SIZE);
  int expected[MAX_TILES][SIZE][SIZE];
  logic [31:0] descriptor_p[MAX_TILES],descriptor_q[MAX_TILES];
  int descriptor_rows[MAX_TILES],descriptor_slot[MAX_TILES];
  longint unsigned accepted_cycle[MAX_TILES],first_output_cycle[MAX_TILES];
  longint unsigned committed_cycle[MAX_TILES];
  bit committed_fast[MAX_TILES];
  int received_tiles,accepted_tiles;
  int committed_tiles;
  longint unsigned simultaneous_accepts,latency_total,latency_max;
  longint unsigned fast_first_total,fast_first_min,fast_first_max,fast_first_count;
  longint unsigned accept_gap_total,accept_gap_min,accept_gap_max;
  longint unsigned consecutive_beats,output_beats,previous_output_cycle;
  bit previous_output_valid;
  bit held_output;
  logic [SLOT_W-1:0] held_slot;
  logic [CW-1:0] held_row,held_col;
  logic [LANES-1:0] held_mask;
  logic held_last;
  logic signed [15:0] held_data[LANES];
  bit seen[SIZE][SIZE];
  int written;
  int unsigned input_base=0;
  longint unsigned input_end=0;
  longint unsigned job_bus_start=0;
  bit inject_error=0, error_injected;
  longint unsigned cycles,bus_byte_count;
  longint unsigned geometry_predictions;
  logic geometry_prediction_start;
  logic [31:0] lfsr;
  bit mem_active;
  int unsigned mem_addr,mem_left,mem_size;
  int jobs,ntiles,nbytes,expect_fault;
  int fd,rc,job,ti,v[22];
  byte unsigned tmp;
  string vectors;
  logic [31:0] virtual_stride;
  generate if (!USE_TILE_PATH) begin : g_direct
    conv_im2col_frontend #(.SIZE(SIZE),.SLOT_W(SLOT_W),.REGISTER_DESCRIPTOR(REGISTER_DESCRIPTOR),.CACHE_RESPONSE_DEPTH(CACHE_RESPONSE_DEPTH),.LANES(LANES),.BUS_WIDTH(BUS_WIDTH),.CACHE_POLICY(CACHE_POLICY),.CACHE_SETS(CACHE_SETS),.CACHE_WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES)) dut (
      .clk,.rst_n,.cfg_valid,.cfg_ready,.cfg,
      .cfg_sched_r(NATIVE_SCHED_R),.cfg_sched_groups(NATIVE_SCHED_GROUPS),
      .tile_valid,.tile_ready,.tile_p0,.tile_q0,.tile_rows,.tile_slot,.tile_narrow,
      .wr_valid,.wr_ready,.wr_slot,.wr_row,.wr_col,.wr_data,.wr_mask,.wr_last(unused_wr_last),
      .tile_done,.tile_error,.error,.busy,
      .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
    );
    // 独立记录需求读取的接收顺序，返回首字必须对应当前运行地址。
    logic [31:0] request_address_queue[16];
    int request_write_index, request_read_index, request_count;
    always @(posedge clk) begin
      if (!rst_n) begin
        request_write_index=0;
        request_read_index=0;
        request_count=0;
      end else begin
        if (cfg_valid && cfg_ready && request_count!=0)
          $fatal(1,"configuration accepted with outstanding demand reads");
        if (dut.cache_port_valid && dut.cache_port_ready) begin
          if (request_count==16) $fatal(1,"demand request scoreboard overflow");
          request_address_queue[request_write_index]=dut.REGISTER_CACHE_REQUEST ?
              dut.request_addr_q : dut.cache_req_addr;
          request_write_index=(request_write_index+1)%16;
          request_count++;
        end
        if (dut.cache_rsp_valid && dut.cache_rsp_ready) begin
          if (request_count==0) $fatal(1,"demand response without accepted request");
          if (!error &&
              (request_address_queue[request_read_index] >> dut.p_word_shift) !=
              (dut.addr >> dut.p_word_shift))
            $fatal(1,"demand response address differs from running descriptor");
          request_read_index=(request_read_index+1)%16;
          request_count--;
        end
      end
    end
    // 对停顿、行切换和归约尾部检查新寄存状态与原组合判断一致。
    always @(posedge clk) begin
      if (rst_n && dut.past_active_q !== (dut.col_idx >= dut.active_cols_q))
        $fatal(1, "active-column boundary mismatch");
      if (rst_n && wr_valid && dut.narrow_output && $countones(wr_mask)>BUS_BYTES)
        $fatal(1, "narrow output width exceeded");
    end
    assign stat_hits=dut.tb_observer.stat_hits;
    assign stat_misses=dut.tb_observer.stat_misses;
    assign stat_read_bytes=dut.tb_observer.stat_read_bytes;
    assign stat_prefetch_lines=dut.tb_observer.stat_prefetch_lines;
    assign stat_prefetch_used=dut.tb_observer.stat_prefetch_used;
    assign stat_prefetch_wasted=dut.tb_observer.stat_prefetch_wasted;
    assign stat_prefetch_unused=dut.tb_observer.stat_prefetch_unused;
    assign stat_prefetch_bytes=dut.tb_observer.stat_prefetch_bytes;
    assign stat_prefetch_late=dut.tb_observer.stat_prefetch_late;

    assign geometry_prediction_start=dut.pred_start;
  end else begin : g_tile_path
    logic path_busy, use16;
    logic signed [15:0] data4[4];
    logic valid4[4];
    conv_ia_tile_path #(.SIZE(SIZE),.CACHE_BLOCKS(8),
      .CACHE_SETS(CACHE_SETS),.CACHE_WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES)) dut (
      .clk,.rst_n,.init_cfg(cfg_valid),.cfg_ready,.conv_cfg(cfg),
      .virtual_base(32'h40000000),.virtual_stride_b(virtual_stride),
      .tl_start(tile_valid && tile_ready),
      .tl_base_addr(32'h40000000 + tile_p0*virtual_stride + (tile_q0<<1)),
      .tl_rows_to_read(32'(tile_rows)),.tl_slot_id(tile_slot),
      .tl_busy(path_busy),.tl_tile_done(tile_done),.error,
      .tl_wr_slot(wr_slot),.tl_wr_row(wr_row),.tl_wr_col_base(wr_col),
      .tl_wr_data(data4),.tl_wr_valid(valid4),.tl_wr_use_16bits(use16),
      .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
    );
    assign stat_hits=dut.tb_observer.stat_hits;
    assign stat_misses=dut.tb_observer.stat_misses;
    assign stat_read_bytes=dut.tb_observer.stat_read_bytes;

    assign busy=path_busy;
    assign geometry_prediction_start=1'b0;
    assign stat_prefetch_lines=0;
    assign stat_prefetch_used=0;
    assign stat_prefetch_wasted=0;
    assign stat_prefetch_unused=0;
    assign stat_prefetch_bytes=0;
    assign stat_prefetch_late=0;
    assign tile_ready=!path_busy && !cfg_valid;
    assign tile_error=error;
    assign wr_valid=valid4[0] || valid4[1];
    assign wr_mask={valid4[1],valid4[0]};
    assign wr_data[0]=data4[0];
    assign wr_data[1]=data4[1];
    always @(posedge clk) if (rst_n) begin
      if (!use16 || valid4[2] || valid4[3]) $fatal(1,"invalid adapter lanes/precision");
    end
  end endgenerate

  // Memory channel model. AR and R payloads are retained until accepted.
  always @(posedge clk) begin
    if (!rst_n) begin
      arready<=0;rvalid<=0;rlast<=0;rdata<=0;rresp<=0;wr_ready<=0;
      mem_active=0; mem_addr=0;mem_left=0;mem_size=0;
      lfsr<=32'hca17cafe;cycles<=0;bus_byte_count<=0;geometry_predictions<=0;
    end else begin
      if (wr_valid && !busy) $fatal(1,"write when frontend idle");
      cycles<=cycles+1;
      if (held_output) begin
        if (!wr_valid || {wr_slot,wr_row,wr_col,wr_mask,unused_wr_last} !==
            {held_slot,held_row,held_col,held_mask,held_last})
          $fatal(1,"output descriptor changed during backpressure");
        for(int lane=0;lane<LANES;lane++)
          if(held_mask[lane] && wr_data[lane] !== held_data[lane])
            $fatal(1,"output data changed during backpressure");
      end
      held_output=wr_valid&&!wr_ready;
      held_slot=wr_slot;held_row=wr_row;held_col=wr_col;held_mask=wr_mask;held_last=unused_wr_last;
      for(int lane=0;lane<LANES;lane++)held_data[lane]=wr_data[lane];
      if (tile_valid&&tile_ready&&g_direct.dut.tile_commit) simultaneous_accepts++;
      if(g_direct.dut.tile_commit&&!g_direct.dut.committing_tile.invalid)begin
        committed_cycle[committed_tiles]=cycles;
        committed_fast[committed_tiles]=g_direct.dut.committing_tile.fast;
        committed_tiles++;
      end

      if (geometry_prediction_start) geometry_predictions<=geometry_predictions+1;
      lfsr<={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
      wr_ready<=USE_TILE_PATH || lfsr[5] || lfsr[9];
      arready<=!mem_active && (lfsr[0] || lfsr[3]);
      if (arvalid && arready) begin
        if (mem_active) $fatal(1,"multiple outstanding requests in single-burst slave");
        if (arburst!=1 || !(arsize==0 || arsize==3'($clog2(BUS_BYTES)))) $fatal(1,"unsupported AR");
        if ((araddr&4095)+((int'(arlen)+1)<<arsize)>4096) $fatal(1,"4 KiB crossing");
        mem_active=1;mem_addr=araddr;mem_left=int'(arlen)+1;mem_size=1<<arsize;
        arready<=0;
      end
      if (rvalid && rready) begin
        bus_byte_count<=bus_byte_count+64'(mem_size);
        rvalid<=0;mem_addr=mem_addr+mem_size;mem_left=mem_left-1;
        if (mem_left==0) mem_active=0;
      end else if (mem_active && !rvalid && lfsr[2]) begin
        if (mem_addr<input_base || 64'(mem_addr)+64'(mem_size)>input_end)
          $fatal(1,"out-of-range read addr=%h size=%0d bounds=%h..%h",mem_addr,mem_size,input_base,input_end);
        if (mem_size==BUS_BYTES && (mem_addr & (BUS_BYTES-1))!=0) $fatal(1,"unaligned full-width burst");
        rdata<={BUS_WIDTH/32{32'ha5b6c7d8}}; // Invalid byte lanes deliberately not zero.
        for (int b=0;b<BUS_BYTES;b++)
          if (b<mem_size) rdata[((mem_addr&(BUS_BYTES-1))+b)*8 +: 8]<=memory[mem_addr-input_base+unsigned'(b)];
        rlast<=mem_left==1;
        rresp<=(inject_error && !error_injected) ? 2'b10 : 2'b00;
        if (inject_error && !error_injected) error_injected=1;
        rvalid<=1;
      end
      if (wr_valid && wr_ready) begin
        if(received_tiles>=ntiles)$fatal(1,"unexpected output transaction");
        if(written==0)begin
          first_output_cycle[received_tiles]=cycles;
          latency_total+=cycles-accepted_cycle[received_tiles];
          if(cycles-accepted_cycle[received_tiles]>latency_max)
            latency_max=cycles-accepted_cycle[received_tiles];
          if(committed_fast[received_tiles])begin
            fast_first_count++;fast_first_total+=cycles-committed_cycle[received_tiles];
            if(cycles-committed_cycle[received_tiles]<fast_first_min)
              fast_first_min=cycles-committed_cycle[received_tiles];
            if(cycles-committed_cycle[received_tiles]>fast_first_max)
              fast_first_max=cycles-committed_cycle[received_tiles];
          end
        end
        if(previous_output_valid&&cycles==previous_output_cycle+1)consecutive_beats++;
        previous_output_valid=1;previous_output_cycle=cycles;output_beats++;
        if (32'(wr_slot)!=descriptor_slot[received_tiles]) $fatal(1,"wrong slot");
        for (int l=0;l<LANES;l++) if (wr_mask[l]) begin
          if (32'(wr_row)>=descriptor_rows[received_tiles] || int'(wr_col)+l>=SIZE) $fatal(1,"write coordinate overflow");
          if (seen[wr_row][int'(wr_col)+l]) $fatal(1,"duplicate write");
          if (32'($signed(wr_data[l]))!=expected[received_tiles][wr_row][int'(wr_col)+l])
            $fatal(1,"mismatch job=%0d tile=%0d row=%0d col=%0d got=%0d exp=%0d",
              job,received_tiles,wr_row,int'(wr_col)+l,$signed(wr_data[l]),expected[received_tiles][wr_row][int'(wr_col)+l]);
          seen[wr_row][int'(wr_col)+l]=1; written=written+1;
        end
        if(unused_wr_last)begin
          if(written!=descriptor_rows[received_tiles]*SIZE)$fatal(1,"missing tile outputs");
          received_tiles++;written=0;
          for(int row=0;row<SIZE;row++)for(int column=0;column<SIZE;column++)seen[row][column]=0;
        end
      end
      if (cycles>64'(MAX_CYCLES)) $fatal(1,"global timeout");
    end
  end


  function automatic logic [15:0] dimension_sample(input int ordinal);
    case (ordinal % 12)
      0: dimension_sample = 16'd0;
      1: dimension_sample = 16'd1;
      2: dimension_sample = 16'd2;
      3: dimension_sample = 16'd3;
      4: dimension_sample = 16'd255;
      5: dimension_sample = 16'd256;
      6: dimension_sample = 16'd32767;
      7: dimension_sample = 16'd32768;
      8: dimension_sample = 16'd65534;
      9: dimension_sample = 16'd65535;
      default: dimension_sample = 16'($urandom);
    endcase
  endfunction

  task automatic check_configuration_products;
    conv_cfg_t command;
    longint unsigned tensor_product, reduction_product;
    longint unsigned row_displacement, tap_displacement, row_pixel, tap_pixel;
    longint unsigned accepted_at, config_cycles, config_cycles_total;
    logic expected_valid;
    config_cycles_total = 64'd0;
    for (int sample = 0; sample < 1024; sample++) begin
      command = '0;
      command.windowed = WINDOWED;
      command.prefetch_enable = PREFETCH;
      command.input_h = dimension_sample(sample);
      command.input_w = dimension_sample(sample / 3 + 1);
      command.input_c = dimension_sample(sample / 5 + 2);
      command.kernel_h = dimension_sample(sample / 7 + 3);
      command.kernel_w = dimension_sample(sample / 11 + 4);
      command.output_h = dimension_sample(sample / 13 + 5);
      command.output_w = dimension_sample(sample / 17 + 6);
      command.stride_h = dimension_sample(sample / 19 + 7);
      command.stride_w = dimension_sample(sample / 23 + 8);
      command.dilation_h = dimension_sample(sample / 29 + 9);
      command.dilation_w = dimension_sample(sample / 31 + 10);
      command.group_c = dimension_sample(sample / 37 + 11);
      command.group_offset = 16'($urandom);
      command.input_base = $urandom;
      command.input_s16 = 1'(sample);
      command.input_offset = 16'(sample % 257 - 128);
      if (sample % 8 == 0) begin
        command.input_h = 16'd3;
        command.input_w = 16'd17;
        command.input_c = 16'd19;
        command.group_c = 16'd11;
        command.group_offset = 16'd8;
        command.kernel_h = 16'd3;
        command.kernel_w = 16'd2;
        command.output_h = 16'd3;
        command.output_w = 16'd16;
        command.stride_h = 16'd2;
        command.stride_w = 16'd1;
        command.dilation_h = 16'd4;
        command.dilation_w = 16'd5;
        command.input_base = 32'h00004002;
        command.input_offset = 16'd0;
        command.input_s16 = 1'(sample / 8);
      end
      tensor_product = (64'(command.input_h) * 64'(command.input_w) *
          64'(command.input_c)) << command.input_s16;
      reduction_product = 64'(command.kernel_h) * 64'(command.kernel_w) * 64'(command.group_c);
      row_displacement = (64'd1 - 64'(command.output_w)) * 64'(command.stride_w);
      tap_displacement = (64'd1 - 64'(command.kernel_w)) * 64'(command.dilation_w);
      row_pixel = 64'(command.stride_h) * 64'(command.input_w) + row_displacement;
      tap_pixel = 64'(command.dilation_h) * 64'(command.input_w) + tap_displacement;
      expected_valid = command.input_h != 0 && command.input_w != 0 && command.input_c != 0 &&
          command.group_c != 0 && command.kernel_h != 0 && command.kernel_w != 0 &&
          command.output_h != 0 && command.output_w != 0 && command.stride_h != 0 &&
          command.stride_w != 0 && command.dilation_h != 0 && command.dilation_w != 0 &&
          17'(command.group_offset) + 17'(command.group_c) <= 17'(command.input_c) &&
          (command.input_s16 ? command.input_offset == 0 && !command.input_base[0] :
              $signed(command.input_offset) >= -127 && $signed(command.input_offset) <= 128) &&
          tensor_product < 64'h1_0000_0000 && reduction_product < 64'h1_0000_0000 &&
          64'(command.input_base) + tensor_product < 64'h1_0000_0000;
      @(negedge clk);
      while (!cfg_ready) @(negedge clk);
      cfg = command;
      cfg_valid = 1'b1;
      do @(posedge clk); while (!cfg_ready);
      accepted_at = cycles;
      @(negedge clk);
      cfg_valid = 1'b0;
      cfg = '0;
      while (!cfg_ready) @(negedge clk);
      config_cycles = cycles - accepted_at;
      config_cycles_total += config_cycles;
      if (g_direct.dut.u_geometry.cfg_tensor_product !== 49'(tensor_product) ||
          g_direct.dut.u_geometry.cfg_reduction_product !== 48'(reduction_product) ||
          g_direct.dut.u_geometry.cfg_position_product !== 32'(64'(command.output_h) * 64'(command.output_w)) ||
          g_direct.dut.row_wrap_dx !== 33'(row_displacement) ||
          g_direct.dut.tap_wrap_dx !== 33'(tap_displacement) ||
          g_direct.dut.row_y_pixels !== 33'(64'(command.stride_h) * 64'(command.input_w)) ||
          g_direct.dut.tap_y_pixels !== 33'(64'(command.dilation_h) * 64'(command.input_w)) ||
          g_direct.dut.row_pair_dx !== 33'(row_displacement + 64'(command.stride_w)) ||
          g_direct.dut.row_wrap_pixels !== 33'(row_pixel) ||
          g_direct.dut.tap_wrap_pixels !== 33'(tap_pixel) ||
          g_direct.dut.row_step_bytes !== 32'((64'(command.stride_w) * 64'(command.input_c)) << command.input_s16) ||
          g_direct.dut.tap_step_bytes !== 32'((64'(command.dilation_w) * 64'(command.input_c)) << command.input_s16) ||
          g_direct.dut.row_wrap_bytes !== 32'((row_pixel * 64'(command.input_c)) << command.input_s16) ||
          g_direct.dut.tap_wrap_bytes !== 32'((tap_pixel * 64'(command.input_c)) << command.input_s16) ||
          g_direct.dut.configured !== expected_valid || error !== !expected_valid)
        $fatal(1, "configuration arithmetic mismatch sample=%0d", sample);
    end
    $display("FRONTEND_CONFIG_PROFILE count=1024 configuration_cycles_total=%0d", config_cycles_total);
  endtask

  initial begin
    cfg='0;cfg.windowed=WINDOWED;cfg.prefetch_enable=PREFETCH;
    if (!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"missing +VECTORS");
    fd=$fopen(vectors,"r"); if (fd==0) $fatal(1,"cannot open vectors");
    rc=$fscanf(fd,"%d",jobs); if(rc!=1) $fatal(1,"bad vector header");
    repeat(5) @(posedge clk);
    @(negedge clk);rst_n=1;
    check_configuration_products();
    for(job=0;job<jobs;job++) begin
      for(int j=0;j<22;j++) begin rc=$fscanf(fd,"%d",v[j]); if(rc!=1)$fatal(1,"bad cfg"); end
      input_base=32'(v[0]);nbytes=v[21];input_end=64'(input_base)+64'(nbytes);
      if(nbytes<=0 || nbytes>MEM_BYTES || input_end>=64'h1_0000_0000)
        $fatal(1,"bench tensor bounds");
      job_bus_start=bus_byte_count;
      for(int j=0;j<nbytes;j++) begin
        rc=$fscanf(fd,"%h",tmp);if(rc!=1)$fatal(1,"bad input bytes");memory[j]=8'(tmp);
      end
      virtual_stride=32'(((v[6]*v[7]*v[4]+SIZE-1)/SIZE)*SIZE*2);
      if (virtual_stride==0) $fatal(1,"invalid virtual stride in vectors");
      cfg.input_base=32'(v[0]);cfg.input_h=16'(v[1]);cfg.input_w=16'(v[2]);cfg.input_c=16'(v[3]);
      cfg.group_c=16'(v[4]);cfg.group_offset=16'(v[5]);cfg.kernel_h=16'(v[6]);cfg.kernel_w=16'(v[7]);
      cfg.output_h=16'(v[8]);cfg.output_w=16'(v[9]);cfg.stride_h=16'(v[10]);cfg.stride_w=16'(v[11]);
      cfg.dilation_h=16'(v[12]);cfg.dilation_w=16'(v[13]);cfg.pad_top=16'(v[14]);cfg.pad_left=16'(v[15]);
      cfg.input_offset=16'(v[16]);cfg.input_s16=1'(v[17]);cfg.bypass_cache=1'(v[18]);
      expect_fault=v[19];inject_error=expect_fault!=0;error_injected=0;ntiles=v[20];
      @(negedge clk);
      if (USE_TILE_PATH) while (!cfg_ready) @(negedge clk);
      cfg_valid=1;
      do @(posedge clk); while(!cfg_ready);
      @(negedge clk);cfg_valid=0;
      // Drive unrelated values after handshake: active configuration must be latched.
      cfg='0;cfg.windowed=WINDOWED;cfg.prefetch_enable=PREFETCH;
      if(error)$fatal(1,"valid cfg rejected");
      if(ntiles>MAX_TILES)$fatal(1,"too many descriptors in vector job");
      if(expect_fault!=0&&ntiles!=1)$fatal(1,"fault vector requires one descriptor");
      received_tiles=0;accepted_tiles=0;committed_tiles=0;written=0;held_output=0;
      simultaneous_accepts=0;latency_total=0;latency_max=0;
      fast_first_count=0;fast_first_total=0;fast_first_min='1;fast_first_max=0;
      accept_gap_total=0;accept_gap_min='1;accept_gap_max=0;
      consecutive_beats=0;output_beats=0;previous_output_valid=0;previous_output_cycle=0;
      for(int r=0;r<SIZE;r++)for(int c=0;c<SIZE;c++)seen[r][c]=0;
      for(ti=0;ti<ntiles;ti++)begin
        for(int j=0;j<4;j++)begin rc=$fscanf(fd,"%d",v[j]);if(rc!=1)$fatal(1,"bad tile");end
        descriptor_p[ti]=32'(v[0]);descriptor_q[ti]=32'(v[1]);
        descriptor_rows[ti]=v[2];descriptor_slot[ti]=(v[3]+8*job)&((1<<SLOT_W)-1);
        for(int r=0;r<descriptor_rows[ti];r++)for(int c=0;c<SIZE;c++)begin
          rc=$fscanf(fd,"%d",expected[ti][r][c]);if(rc!=1)$fatal(1,"bad expected matrix");
        end
      end
      fork
        begin
          @(negedge clk);
          for(int issue=0;issue<ntiles;issue++)begin
            tile_p0=descriptor_p[issue];tile_q0=descriptor_q[issue];
            tile_rows=RW'(descriptor_rows[issue]);tile_slot=SLOT_W'(descriptor_slot[issue]);
            tile_narrow=NARROW_MODE==1 || (NARROW_MODE==2 && (issue%2)!=0);
            tile_valid=1;
            do @(posedge clk);while(!tile_ready);
            accepted_cycle[issue]=cycles;accepted_tiles++;
            if(issue!=0)begin
              accept_gap_total+=cycles-accepted_cycle[issue-1];
              if(cycles-accepted_cycle[issue-1]<accept_gap_min)
                accept_gap_min=cycles-accepted_cycle[issue-1];
              if(cycles-accepted_cycle[issue-1]>accept_gap_max)
                accept_gap_max=cycles-accepted_cycle[issue-1];
            end
            @(negedge clk);
          end
          tile_valid=0;
        end
        begin
          do @(posedge clk);while(received_tiles!=ntiles&&!tile_error);
          if(expect_fault!=0)begin
            if(!tile_error||!error||tile_done)$fatal(1,"read error not propagated");
          end else if(tile_error||error)$fatal(1,"unexpected frontend error");
          @(negedge clk);
        end
      join
      $display("FRONTEND_QUEUE_PROFILE job=%0d accepted=%0d completed=%0d overlap=%0d latency_total=%0d latency_max=%0d accept_gap_total=%0d accept_gap_min=%0d accept_gap_max=%0d output_beats=%0d consecutive_beats=%0d",
        job,accepted_tiles,received_tiles,simultaneous_accepts,latency_total,latency_max,
        accept_gap_total,accept_gap_min,accept_gap_max,output_beats,consecutive_beats);
      $display("FRONTEND_FAST_PROFILE job=%0d count=%0d first_total=%0d first_min=%0d first_max=%0d",
        job,fast_first_count,fast_first_total,fast_first_min,fast_first_max);
      while(busy && !error) @(negedge clk);
      if (64'(stat_read_bytes) != bus_byte_count-job_bus_start)
        $fatal(1,"read byte counter mismatch");
      if (mem_active || rvalid) $fatal(1,"job ended without draining accepted reads");
      $display("RTL_FRONTEND_JOB_PASS job=%0d tiles=%0d hits=%0d misses=%0d read_bytes=%0d fault=%0d",
        job,ntiles,stat_hits,stat_misses,stat_read_bytes,expect_fault);
      if (!USE_TILE_PATH && stat_prefetch_lines!=stat_prefetch_used+stat_prefetch_wasted+stat_prefetch_unused)
        $fatal(1,"prefetch accounting mismatch");
    end
    $fclose(fd);
    if (EXPECT_GEOMETRY_PREDICTIONS>=0) begin
      if (geometry_predictions!=64'(EXPECT_GEOMETRY_PREDICTIONS))
        $fatal(1,"geometry prediction count=%0d expected=%0d",geometry_predictions,EXPECT_GEOMETRY_PREDICTIONS);
      $display("RTL_NATIVE_GEOMETRY_PASS predictions=%0d",geometry_predictions);
    end
    $display("RTL_FRONTEND_PASS jobs=%0d cycles=%0d cache_sets=%0d cache_ways=%0d line_bytes=%0d tile_path=%0d (not upstream full NPU)",jobs,cycles,CACHE_SETS,CACHE_WAYS,LINE_BYTES,USE_TILE_PATH);
    $finish;
  end
endmodule
