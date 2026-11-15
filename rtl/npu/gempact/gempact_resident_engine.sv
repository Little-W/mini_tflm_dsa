// NPU 顶层模块：矩阵/卷积算子的分块计算、量化和写回数据通路
module gempact_resident_engine #(
    parameter integer POOL_BYTES=500736,
    parameter int unsigned WEIGHT_WIDTH = 16,  // 权重数据宽度；WS 下 s8 符号扩展，IS+s16 下使用 16bit LHS
    parameter int unsigned DATA_WIDTH = 16,  // IA数据宽度
    parameter int unsigned SIZE = 16,  // 阵列大小
    parameter int unsigned BUS_WIDTH = 32,  // 总线宽度
    parameter int unsigned REG_WIDTH = 32,  // 寄存器宽度
    parameter int unsigned ADDR_WIDTH = 19,  // AXI 地址宽度
    parameter int unsigned IA_CACHE_BLOCKS = 4,  // IA loader cache slots；默认 IA reuse = IA_CACHE_BLOCKS/2
    parameter int unsigned OPERAND_CACHE_ENABLE = 0,
    parameter int unsigned PS_FRAME_COUNT = SIZE,  // PS buffer 可保留的输出列 tile 数
    parameter int unsigned OPERAND_STREAM_BYTES = (PS_FRAME_COUNT >= 16) ? 65536 : 262144,
    parameter int unsigned AXI_READ_OUTSTANDING = 4,  // AXI 读通道最多提前排队的 burst 数
    parameter int unsigned AXI_WRITE_OUTSTANDING = AXI_READ_OUTSTANDING,  // AXI 写通道最多提前排队的 burst 数
    parameter int unsigned ENABLE_IS_MODE = 1,  // 置 0 时综合裁剪 IS 转置/分组 bias 支持
    parameter int unsigned ENABLE_PER_CHANNEL = 1,  // 置 0 时综合裁剪 per-channel 量化装载路径
    parameter int unsigned OA_FIFO_BANKS_MAX =
        ((ENABLE_IS_MODE == 0) && (ENABLE_PER_CHANNEL == 0)) ? 16 :
        32  // common 8 KiB output FIFO in this experiment; 写回 FIFO 最大 tile bank 数；裁剪版用更浅线性 FIFO 压低面积
) (
    //==== 时钟与复位 ====
    input wire clk,   // 系统时钟
    input wire rst_n, // 异步复位，低有效

    //==== 外部控制接口 ====
    input wire cfg_operand_fetch64, // 0: 16-byte sectors; 1: 64-byte read allocation
    input wire calc_start,  // 计算开始信号
    input wire cfg_16bits_ia,  // 使用16位IA数据
    input wire cfg_16x8,  // TFLM s16 activation x s8 weight, s32 bias, s16 output
    input wire cfg_dataflow_mode,  // 0: WS, 1: IS
    input  logic [REG_WIDTH-1:0] cfg_ia_reuse_num,  // IA L1 组复用深度，ABI 2: 外部写入最终生效值，0 非法
    input  logic [REG_WIDTH-1:0] cfg_w_reuse_num,   // W 侧复用窗口，ABI 2: 外部写入最终生效值，0 非法
    input logic [REG_WIDTH-1:0] cfg_row_groups,
    input logic [REG_WIDTH-1:0] cfg_row_tail_tiles,
    input logic [REG_WIDTH-1:0] cfg_col_groups,
    input logic [REG_WIDTH-1:0] cfg_col_tail_tiles,
    output wire sa_ready,  // 系统就绪信号

    //==== 完成握手接口 ====
    output wire       done_valid,  // 任务完成有效信号
    input  wire       done_ready,  // 任务完成接收就绪信号
    output wire [1:0] err_code,  // 完成状态码

    // --- base pointers
    input logic [REG_WIDTH-1:0] lhs_base,  // A base         (MULT_LHS_PTR)
    input logic [REG_WIDTH-1:0] rhs_base,  // B base (s8)    (MULT_RHS_PTR, N x K row-major)
    input logic [REG_WIDTH-1:0] dst_base,  // C base (s8)    (MULT_DST_PTR)
    input logic [REG_WIDTH-1:0] bias_base, // bias s32 (0=none)   (MULT_BIAS_PTR)

    // --- quantization & zero-points ---
    input logic signed [REG_WIDTH-1:0] lhs_zp,          // A zero-point (s32)  (MULT_LHS_OFFSET)
    input logic signed [REG_WIDTH-1:0] rhs_zp,          // B zero-point (s32)  (MULT_RHS_OFFSET)
    input logic signed [REG_WIDTH-1:0] dst_zp,          // C zero-point (s32)  (MULT_DST_OFFSET)
    input logic signed [REG_WIDTH-1:0] q_mult_pt,       // per-tensor mult     (MULT_DST_MULT)
    input logic signed [REG_WIDTH-1:0] q_shift_pt,      // per-tensor rshift
    // (MULT_DST_SHIFT, +N => >>N)
    input logic                        use_per_channel, // 1: per-channel; 0: per-tensor

    // --- dimensions ---
    input logic [REG_WIDTH-1:0] k,  // IA矩阵行数
    input logic [REG_WIDTH-1:0] n,  // IA矩阵列数 = W矩阵行数
    input logic [REG_WIDTH-1:0] m,  // W矩阵列数

    // --- row strides (all in BYTES) ---
    input logic [REG_WIDTH-1:0] lhs_row_stride_b,  // A row stride       (MULT_LHS_COLS_OFFSET)
    input logic [REG_WIDTH-1:0] dst_row_stride_b,  // C row stride       (MULT_ROW_ADDR_OFFSET)
    input logic [REG_WIDTH-1:0] rhs_col_stride_b,  // B row stride       (MULT_RHS_ROW_STRIDE) （转置后的右矩阵是列展平的，所以这个步长本质上是列步长）

    // --- activation clamp ---
    input logic signed [REG_WIDTH-1:0] act_min,  // (MULT_ACT_MIN)
    input logic signed [REG_WIDTH-1:0] act_max,  // (MULT_ACT_MAX)

    //==== AXI4 master 接口 ====
    output logic                   m_axi_arvalid,
    input  logic                   m_axi_arready,
    output logic [  REG_WIDTH-1:0] m_axi_araddr,
    output logic [            7:0] m_axi_arlen,
    output logic [            2:0] m_axi_arsize,
    output logic [            1:0] m_axi_arburst,
    input  logic                   m_axi_rvalid,
    output logic                   m_axi_rready,
    input  logic [  BUS_WIDTH-1:0] m_axi_rdata,
    input  logic [            1:0] m_axi_rresp,
    input  logic                   m_axi_rlast,

    output logic                   m_axi_awvalid,
    input  logic                   m_axi_awready,
    output logic [  REG_WIDTH-1:0] m_axi_awaddr,
    output logic [            7:0] m_axi_awlen,
    output logic [            2:0] m_axi_awsize,
    output logic [            1:0] m_axi_awburst,
    output logic                   m_axi_wvalid,
    input  logic                   m_axi_wready,
    output logic [  BUS_WIDTH-1:0] m_axi_wdata,
    output logic [BUS_WIDTH/8-1:0] m_axi_wstrb,
    output logic                   m_axi_wlast,
    input  logic                   m_axi_bvalid,
    output logic                   m_axi_bready,
    input  logic [            1:0] m_axi_bresp
);


 localparam integer AP=POOL_BYTES/256-4;
 typedef enum logic[4:0]{IDLE,CHECK,GROUP_PREP,GROUP_INIT,GROUP_WAIT,SCHED_START,WAIT_CMD,ADDR0,ADDR1,CACHE_A,LOAD_A,CACHE_B,LOAD_B,CORE_START,WAIT_ROWS,COMMIT,WAIT_STORE,WAIT_OUTPUT,WRITE_START,WRITE_WAIT,NEXT_GROUP,TASK_DONE,TASK_FAIL} st_t;
 st_t state;
 logic[31:0] abase,bbase,cbase,astride,bstride,cstride;
 logic[31:0] row_groups,col_groups,row_tail,col_tail,R,W;
 logic[15:0] kt,gr,gc,rg,cg;
 logic[5:0] group_rows,group_cols;
 logic[10:0] group_tiles,group_pages;
 logic mode;
 logic[5:0] qr,qc,cmd_row,cmd_col;
 logic[15:0] qk,cmd_k,cmd_gr,cmd_gc;
 logic[9:0] query_id_q,cmd_id;
 logic[27:0] old_query;
 logic[1:0] query_stable;
 logic meta_valid,meta_wide,meta_valid_q,meta_wide_q;
 logic[23:0] meta_headroom,meta_headroom_q;
 logic sched_valid,sched_ready,sched_complete,sched_last,sched_draining,sched_done,sched_error,frame_release;
 logic[1:0] required_pages;logic[2:0] sched_state;
 logic store_ready,store_done,ps_capacity_fault;logic store_init_pulse;
 logic[11:0] free_pages;
 logic[31:0] peak_ps;
 logic[63:0] ps_records,ps_long_records;
 logic cmd_last,cmd_draining;
 logic[31:0] a_product,b_product,c_product,a_addr,b_addr,c_addr;
 logic[31:0] a_key,b_key;
 logic[5:0] a_slot;
 logic b_slot;
 logic[63:0] a_valid;
 logic[1:0] b_valid;
 (* ram_style="distributed" *)logic[31:0] a_tags[64];logic[31:0] b_tags[2];
 logic weights_valid;logic[31:0] weights_key;
 logic fetch_b;
 logic rd_start,rd_busy,rd_done,wr_start,wr_busy,wr_done,rd_error,wr_error;
 logic[5:0] dma_slot;logic[3:0] dma_row,dma_col;
 logic signed[7:0] dma_data[4];logic dma_valid[4];
 logic signed[7:0] a_data[16],b_data[16],ia_debug[16],weight_debug[16];
 logic[3:0] a_rrow[16],b_rrow,core_row;
 logic[15:0] a_re;logic b_re,core_row_valid,core_busy,core_done;
 logic signed[31:0] core_data[16],partial_q[16],sum_q[16],acc_data_out[16];
 logic partial_valid,sum_valid,acc_data_valid;
 logic[3:0] partial_row,sum_row,acc_row;
 logic[511:0] ps_read_data,scratch_data;
 logic ps_read_valid;
 logic quant_valid,quant_last;logic signed[7:0] quant_data[16];logic[127:0] quant_packed;
 logic fifo_req,fifo_valid,fifo_ready,fifo_full,fifo_row_switch;logic[31:0] fifo_data;logic[3:0] fifo_mask;
 logic[31:0] early_frames;logic[63:0] tile_commands;
 logic[31:0] q_multiplier,q_shift,dst_offset;logic signed[31:0] clamp_min,clamp_max;
 assign sa_ready=state==IDLE;
 assign done_valid=state==TASK_DONE || state==TASK_FAIL;
 assign err_code=state==TASK_FAIL?2'd1:2'd0;
 assign sched_ready=state==WAIT_CMD;
 always_ff @(posedge clk)begin
  if(!rst_n)begin query_id_q<=0;old_query<=0;query_stable<=0;meta_valid_q<=0;meta_wide_q<=0;meta_headroom_q<=0;end
  else begin
   query_id_q<=10'(qc*group_rows+qr);
   old_query<={qk,qc,qr};meta_valid_q<=meta_valid;meta_wide_q<=meta_wide;meta_headroom_q<=meta_headroom;
   if({qk,qc,qr}!=old_query || sched_complete || state==SCHED_START || state==GROUP_INIT)query_stable<=0;
   else query_stable<={query_stable[0],1'b1};
  end
 end
 ps_capacity_schedule #(.MAX_ROWS(32),.MAX_COLS(32),.PREALLOCATED_BASE(1)) u_capacity(
  .clk(clk),.rst_n(rst_n),.start(state==SCHED_START),.cfg_rows(group_rows),.cfg_cols(group_cols),.cfg_k_tiles(kt),
  .cfg_initial_pages({1'b0,group_pages}),.free_pages(state==SCHED_START?12'(AP):free_pages),
  .meta_initialized(meta_valid_q),.meta_wide(meta_wide_q),.meta_headroom(meta_headroom_q),.meta_ready(query_stable[1] && {qk,qc,qr}==old_query),
  .query_row(qr),.query_col(qc),.query_k(qk),.command_valid(sched_valid),.command_ready(sched_ready),.command_complete(sched_complete),
  .command_last_k(sched_last),.command_finish_mode(sched_draining),.required_pages(required_pages),
  .frame_released(frame_release),.done(sched_done),.error(sched_error),.state_debug(sched_state));
 gempact_paged_ps #(.POOL_BYTES(POOL_BYTES)) u_ps(
  .clk(clk),.rst_n(rst_n),.group_start(store_init_pulse),.group_tiles(group_tiles),.initial_pages(group_pages),
  .group_ready(store_ready),.query_tile(query_id_q),.meta_valid(meta_valid),.meta_wide(meta_wide),.meta_headroom(meta_headroom),.free_pages(free_pages),
  .begin_update(state==CORE_START),.update_tile(cmd_id),.read_req(core_row_valid),.read_row(core_row),.read_valid(ps_read_valid),.read_data(ps_read_data),
  .scratch_write(sum_valid),.scratch_row(sum_row),.scratch_data(scratch_data),
  .commit(state==COMMIT),.commit_final(cmd_last),.commit_done(store_done),.capacity_fault(ps_capacity_fault),
  .peak_payload_bytes(peak_ps),.records_written(ps_records),.long_records(ps_long_records));
 for(genvar l=0;l<16;l++)begin:g_operand
  (* ram_style="block" *)logic signed[7:0] a_ram[0:1023];
  (* ram_style="distributed" *)logic signed[7:0] b_ram[0:31];
  always_ff @(posedge clk)begin
   for(int z=0;z<4;z++)begin
    if(dma_valid[z] && !fetch_b && (int'(dma_col)+z)==l)a_ram[{dma_slot,dma_row}]<=dma_data[z];
    if(dma_valid[z] && fetch_b && dma_row==l)b_ram[{dma_slot[0],dma_col}+5'(z)]<=dma_data[z];
   end
   if(a_re[l])a_data[l]<=a_ram[{a_slot,a_rrow[l]}];
   if(b_re)b_data[l]<=b_ram[{b_slot,b_rrow}];
  end
  assign scratch_data[l*32+:32]=sum_q[l];
  assign quant_packed[l*8+:8]=quant_data[l];
 end
 gempact_tile_core u_core(.clk(clk),.rst_n(rst_n),.start(state==CORE_START),.load_weights(!weights_valid || weights_key!=b_key),
  .busy(core_busy),.done(core_done),.a_row(a_rrow),.a_re(a_re),.a_data(a_data),.b_row(b_rrow),.b_re(b_re),.b_data(b_data),
  .row_valid(core_row_valid),.row_index(core_row),.row_data(core_data),.ia_debug(ia_debug),.weight_debug(weight_debug));
 always_ff @(posedge clk)begin
  if(!rst_n)begin partial_valid<=0;sum_valid<=0;acc_data_valid<=0;partial_row<=0;sum_row<=0;acc_row<=0;end
  else begin
   partial_valid<=core_row_valid;sum_valid<=partial_valid;acc_data_valid<=sum_valid && cmd_last;
   partial_row<=core_row;sum_row<=partial_row;
   for(int l=0;l<16;l++)begin
    partial_q[l]<=core_data[l];sum_q[l]<=partial_q[l]+$signed(ps_read_data[l*32+:32]);
    if(sum_valid)acc_data_out[l]<=sum_q[l];
   end
   if(sum_valid)acc_row<=sum_row;
  end
 end
 vec_requant #(.VLEN(16),.ENABLE_PER_CHANNEL(0),.ENABLE_IS_MODE(0)) u_quant(
  .clk(clk),.rst_n(rst_n),.init_cfg(state==CHECK),.cfg_per_channel(1'b0),.cfg_dataflow_mode(1'b0),
  .activation_min_in(clamp_min),.activation_max_in(clamp_max),.dst_offset_in(dst_offset),.multiplier_in(q_multiplier),.shift_in(q_shift),
  .k(32'd16),.m(32'd16),.ia_reuse_num_in(32'd1),.load_quant_req(),.load_quant_granted(1'b0),.quant_params_valid(),
  .dma_start(),.dma_is_write(),.dma_linear_read_mode(),.dma_base_addr(),.dma_row_stride(),.dma_rows_to_read(),.dma_burst_len_m1(),.dma_slot_id(),.dma_use_16bits(),.dma_lhs_zp(),.dma_raw_data(32'b0),.dma_raw_valid(1'b0),
  .in_valid(acc_data_valid),.in_tile_done(acc_data_valid && acc_row==15),.in_vec_s32(acc_data_out),
  .out_valid(quant_valid),.out_tile_done(quant_last),.out_vec_s8(quant_data),.quant_multiplier_lane(),.quant_shift_lane());
 vec_s8_to_fifo #(.VLEN(16),.BANKS(2),.ENABLE_TRANSPOSE(1)) u_output(
  .clk(clk),.rst_n(rst_n),.in_valid(quant_valid),.in_tile_done(quant_last),.in_vec_s8(quant_packed),.oa_fifo_req(fifo_req),
  .transpose_mode(mode),.coalesce_enable(1'b0),.coalesce_rows(32'd1),.coalesce_cols(32'd1),.reserve_banks(32'd1),.vec_valid_num_col(4'd15),.vec_valid_num_row(4'd15),
  .output_valid(fifo_valid),.output_ready(fifo_ready),.output_row_switch(fifo_row_switch),.output_mask(fifo_mask),.output_data(fifo_data),.fifo_full_flag(fifo_full));
 assign rd_start=state==LOAD_A || state==LOAD_B;
 assign wr_start=state==WRITE_START;
 axi_dual_block_dma #(.DATA_WIDTH(8),.SIZE(16),.CACHE_BLOCKS(64),.READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4)) u_dma(
 .conv_cfg_ready(),.conv_error(),.conv_busy(),.conv_stat_hits(),.conv_stat_misses(),.conv_stat_read_bytes(),
 .clk(clk),.rst_n(rst_n),.rd_start(rd_start),.rd_linear_read_mode(1'b0),.rd_base_addr(fetch_b?b_addr:a_addr),
 .rd_row_stride(fetch_b?bstride:astride),.rd_rows_to_read(32'd16),.rd_valid_cols(32'd16),.rd_burst_len_m1(8'd3),
 .rd_slot_id(fetch_b?{5'b0,b_slot}:a_slot),.rd_use_16bits(1'b0),.rd_lhs_zp(32'b0),.rd_busy(rd_busy),.rd_done(rd_done),.rd_finish_beat(),
 .wr_start(wr_start),.wr_base_addr(c_addr),.wr_row_stride(cstride),.wr_rows_to_write(32'd16),.wr_burst_len_m1(8'd3),.wr_busy(wr_busy),.wr_done(wr_done),
 .src_wdata(fifo_data),.src_wmask(fifo_mask),.src_wvalid(fifo_valid),.src_wready(fifo_ready),
 .wr_slot(dma_slot),.wr_row(dma_row),.wr_col_base(dma_col),.wr_data(dma_data),.wr_valid(dma_valid),.wr_use_16bits(),
 .rd_raw_data(),.rd_raw_valid(),.rd_raw_row(),.rd_raw_col_base(),.rd_error(rd_error),.wr_error(wr_error),
 .m_axi_arvalid(m_axi_arvalid),
 .m_axi_arready(m_axi_arready),
 .m_axi_araddr(m_axi_araddr),
 .m_axi_arlen(m_axi_arlen),
 .m_axi_arsize(m_axi_arsize),
 .m_axi_arburst(m_axi_arburst),
 .m_axi_rvalid(m_axi_rvalid),
 .m_axi_rready(m_axi_rready),
 .m_axi_rdata(m_axi_rdata),
 .m_axi_rresp(m_axi_rresp),
 .m_axi_rlast(m_axi_rlast),
 .m_axi_awvalid(m_axi_awvalid),
 .m_axi_awready(m_axi_awready),
 .m_axi_awaddr(m_axi_awaddr),
 .m_axi_awlen(m_axi_awlen),
 .m_axi_awsize(m_axi_awsize),
 .m_axi_awburst(m_axi_awburst),
 .m_axi_wvalid(m_axi_wvalid),
 .m_axi_wready(m_axi_wready),
 .m_axi_wdata(m_axi_wdata),
 .m_axi_wstrb(m_axi_wstrb),
 .m_axi_wlast(m_axi_wlast),
 .m_axi_bvalid(m_axi_bvalid),
 .m_axi_bready(m_axi_bready),
 .m_axi_bresp(m_axi_bresp));
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;store_init_pulse<=0;abase<=0;bbase<=0;cbase<=0;astride<=0;bstride<=0;cstride<=0;row_groups<=0;col_groups<=0;row_tail<=0;col_tail<=0;R<=0;W<=0;
   kt<=0;gr<=0;gc<=0;rg<=0;cg<=0;mode<=0;group_rows<=0;group_cols<=0;group_tiles<=0;group_pages<=0;
   cmd_row<=0;cmd_col<=0;cmd_k<=0;cmd_gr<=0;cmd_gc<=0;cmd_id<=0;cmd_last<=0;cmd_draining<=0;
   a_product<=0;b_product<=0;c_product<=0;a_addr<=0;b_addr<=0;c_addr<=0;a_key<=0;b_key<=0;a_slot<=0;b_slot<=0;
   a_valid<=0;b_valid<=0;weights_valid<=0;weights_key<=0;fetch_b<=0;sched_complete<=0;early_frames<=0;tile_commands<=0;
   q_multiplier<=0;q_shift<=0;dst_offset<=0;clamp_min<=0;clamp_max<=0;
  end else begin
   sched_complete<=0;store_init_pulse<=0;
   if(frame_release)early_frames<=early_frames+1'b1;
   case(state)
    IDLE:if(calc_start)begin
     mode<=cfg_dataflow_mode;abase<=cfg_dataflow_mode?rhs_base:lhs_base;bbase<=cfg_dataflow_mode?lhs_base:rhs_base;cbase<=dst_base;
     astride<=cfg_dataflow_mode?rhs_col_stride_b:lhs_row_stride_b;bstride<=cfg_dataflow_mode?lhs_row_stride_b:rhs_col_stride_b;cstride<=dst_row_stride_b;
     kt<=16'(n>>4);R<=cfg_ia_reuse_num;W<=cfg_w_reuse_num;row_groups<=cfg_row_groups;col_groups<=cfg_col_groups;row_tail<=cfg_row_tail_tiles;col_tail<=cfg_col_tail_tiles;
     q_multiplier<=q_mult_pt;q_shift<=q_shift_pt;dst_offset<=dst_zp;clamp_min<=act_min;clamp_max<=act_max;
     gr<=0;gc<=0;rg<=0;cg<=0;a_valid<=0;b_valid<=0;weights_valid<=0;early_frames<=0;tile_commands<=0;state<=CHECK;
     if(SIZE!=16 || BUS_WIDTH!=32 || cfg_16bits_ia || cfg_16x8 || use_per_channel || bias_base!=0 || lhs_zp!=0 || rhs_zp!=0 ||
       k==0 || n==0 || m==0 || k[3:0]!=0 || n[3:0]!=0 || m[3:0]!=0 || (n>>20)!=0 ||
       (k>>20)!=0 || (m>>20)!=0 ||
       cfg_row_groups>65535 || cfg_col_groups>65535 || cfg_row_tail_tiles>cfg_ia_reuse_num || cfg_col_tail_tiles>cfg_w_reuse_num ||
       cfg_ia_reuse_num==0 || cfg_ia_reuse_num>32 || cfg_w_reuse_num==0 || cfg_w_reuse_num>32 ||
       cfg_row_groups==0 || cfg_col_groups==0 || cfg_row_tail_tiles==0 || cfg_col_tail_tiles==0 ||
       lhs_base==0 || rhs_base==0 || dst_base==0)state<=TASK_FAIL;
    end
    CHECK:state<=GROUP_PREP;
    GROUP_PREP:begin
     group_rows<=6'((rg==row_groups-1)?row_tail:R);group_cols<=6'((cg==col_groups-1)?col_tail:W);state<=GROUP_INIT;
    end
    GROUP_INIT:begin group_tiles<=11'(group_rows*group_cols);group_pages<=11'((group_rows*group_cols)*3);store_init_pulse<=1;state<=GROUP_WAIT;end
    GROUP_WAIT:begin
     // Start initialization only after products have been registered.
     if(group_tiles>640 || group_pages+group_rows>AP)state<=TASK_FAIL;
     else if(store_ready && !store_init_pulse)state<=SCHED_START;
    end
    SCHED_START:state<=WAIT_CMD;
    WAIT_CMD:begin
     if(sched_error)state<=TASK_FAIL;
     else if(sched_done)state<=NEXT_GROUP;
     else if(sched_valid)begin
      cmd_row<=qr;cmd_col<=qc;cmd_k<=qk;cmd_id<=query_id_q;cmd_last<=sched_last;cmd_draining<=sched_draining;
      cmd_gr<=gr+qr;cmd_gc<=gc+qc;state<=ADDR0;tile_commands<=tile_commands+1'b1;
     end
    end
    ADDR0:begin
     a_product<=cmd_gr*astride;b_product<=cmd_gc*bstride;c_product<=(mode?cmd_gc:cmd_gr)*cstride;
     a_key<={cmd_gr,cmd_k};b_key<={cmd_gc,cmd_k};a_slot<=cmd_gr[5:0];b_slot<=cmd_gc[0];state<=ADDR1;
    end
    ADDR1:begin a_addr<=abase+(a_product<<4)+{12'b0,cmd_k,4'b0};b_addr<=bbase+(b_product<<4)+{12'b0,cmd_k,4'b0};
     c_addr<=cbase+(c_product<<4)+(mode?{12'b0,cmd_gr,4'b0}:{12'b0,cmd_gc,4'b0});state<=CACHE_A;end
    CACHE_A:if(a_valid[a_slot] && a_tags[a_slot]==a_key)state<=CACHE_B;else begin fetch_b<=0;state<=LOAD_A;end
    LOAD_A:state<=CACHE_B; // DMA launch pulse; CACHE_B waits for accepted A read.
    CACHE_B:begin
     if(!fetch_b && rd_busy)begin end
     else if(!fetch_b && rd_done)begin a_valid[a_slot]<=1;a_tags[a_slot]<=a_key;end
     else if(b_valid[b_slot] && b_tags[b_slot]==b_key)state<=CORE_START;
     else begin fetch_b<=1;state<=LOAD_B;end
    end
    LOAD_B:state<=WAIT_ROWS;
    WAIT_ROWS:begin
     if(fetch_b && rd_done)begin b_valid[b_slot]<=1;b_tags[b_slot]<=b_key;state<=CORE_START;end
     else if(sum_valid && sum_row==15)state<=COMMIT;
    end
    CORE_START:begin weights_valid<=1;weights_key<=b_key;state<=WAIT_ROWS;end
    COMMIT:state<=WAIT_STORE;
    WAIT_STORE:if(store_done)begin if(cmd_last)state<=WAIT_OUTPUT;else begin sched_complete<=1;state<=WAIT_CMD;end end
    WAIT_OUTPUT:if(fifo_req)state<=WRITE_START;
    WRITE_START:state<=WRITE_WAIT;
    WRITE_WAIT:if(wr_done)begin sched_complete<=1;state<=WAIT_CMD;end
    NEXT_GROUP:begin
     if(cg+1<col_groups)begin cg<=cg+1'b1;gc<=gc+16'(W);state<=GROUP_PREP;end
     else if(rg+1<row_groups)begin rg<=rg+1'b1;gr<=gr+16'(R);cg<=0;gc<=0;state<=GROUP_PREP;end
     else state<=TASK_DONE;
    end
    TASK_DONE,TASK_FAIL:if(done_ready)state<=IDLE;
    default:state<=TASK_FAIL;
   endcase
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk)if(rst_n && sched_ready && sched_valid)begin
  assert(query_id_q==qc*group_rows+qr)else $fatal(1,"PS metadata address mismatch");
 end
`endif
endmodule
