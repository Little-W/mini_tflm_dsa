// NPU 顶层模块：矩阵/卷积算子的分块计算、量化和写回数据通路
`ifndef GEMPACT_PANEL_MAX_R
`define GEMPACT_PANEL_MAX_R 32
`endif
`ifndef GEMPACT_PANEL_MAX_W
`define GEMPACT_PANEL_MAX_W 32
`endif
module gempact_panel_engine #(
    parameter integer POOL_BYTES=327680,
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


 typedef enum logic[4:0]{IDLE,CHECK,GROUP_ADDR0,GROUP_ADDR1,GROUP_SETUP,GROUP_WAIT,RUN,FLUSH_CONFIG,FLUSH_SEGMENT,FLUSH_START,FLUSH_WAIT,RELEASE,NEXT_GROUP,TASK_DONE,TASK_FAIL} st_t;
 typedef enum logic[2:0]{P_IDLE,P_REQUEST,P_WAIT,P_PANEL,P_ENQUEUE} pr_t;
 st_t state;pr_t producer;
 logic mode;logic[31:0] abase,bbase,cbase,astride,bstride,cstride,red_k,R,W,row_groups,col_groups,row_tail,col_tail;
 logic[31:0] a_product,b_product,c_product,a_group,b_group,c_group;
 logic[15:0] kt,gr,gc,rg,cg;
 logic[5:0] group_rows,group_cols,qcol,normal_col;
 logic[15:0] qk,normal_k;
 logic[31:0] active_cols;logic draining,production_done;
 logic[5:0] inflight;
 logic accepted_phase_final;
`ifdef GEMPACT_PCR_PS
 wire ps_phase_wait=inflight!=0 && ((qk==kt-1'b1)!=accepted_phase_final);
`else
 wire ps_phase_wait=1'b0;
`endif
 logic[31:0] column_committed;logic[15:0] column_last_k[32];
 wire predecessor_ready=qk==0 || (column_committed[qcol] && column_last_k[qcol]>=qk-1'b1);
 logic[31:0] early_frames;logic[63:0] tile_commands,issued_frames,completed_frames;
 logic[31:0] q_multiplier,q_shift,dst_offset;logic signed[31:0] clamp_min,clamp_max;
 wire group_start=state==GROUP_SETUP;
 logic ps_ready,prep_ready,prep_done,prep_pressure,ps_fault;
 logic[11:0] free_pages;logic[31:0] peak_ps;logic[63:0] ps_records,ps_long_records;
 logic all_c_ready,frame_committed;logic[5:0] committed_col;logic[15:0] committed_k;
 wire prepare_request=state==RUN && producer==P_REQUEST && prep_ready;
 logic load_request,load_ready,load_done;logic[15:0] load_panel;
 logic[1:0] cache_valid,buffer_busy;logic[15:0] cache_tags[2];
 wire[15:0] wanted_panel=qk>>2;
 wire[15:0] panel_count=(kt+16'd3)>>2;
 wire panel_available=cache_valid[wanted_panel[0]] && cache_tags[wanted_panel[0]]==wanted_panel;
 wire cache_active=(state==GROUP_WAIT || state==RUN) && ps_ready && !ps_fault && !production_done && active_cols!=0;
 wire[15:0] next_panel=wanted_panel+1'b1;
 logic job_ready,core_busy,frame_launch,frame_input_done;
 wire job_valid=state==RUN && producer==P_ENQUEUE;
 wire job_accept=job_valid && job_ready;
 logic[15:0] a_re;logic[11:0] a_addr[16];logic signed[7:0] a_data[16];
 logic b_re;logic[9:0] b_addr;logic[31:0] b_data[16];
 logic core_valid,core_final,core_frame_last;logic[9:0] core_tile;logic[3:0] core_row;logic[15:0] core_k;logic[5:0] core_col;logic signed[31:0] core_data[16];
 logic acc_data_valid,acc_frame_last;logic[9:0] acc_tile;logic[3:0] acc_row;logic[15:0] acc_k;logic[5:0] acc_col;logic signed[31:0] acc_data_out[16];
 logic quant_valid,quant_last;logic signed[7:0] quant_data[16];logic[127:0] quant_packed;
 logic[9:0] quant_tile_pipe[12];logic[3:0] quant_row_pipe[12];logic[5:0] quant_col_pipe[12];logic[15:0] quant_k_pipe[12];logic[11:0] quant_frame_last_pipe;
 logic c_write_valid,c_write_frame_last,c_pack_busy;logic[9:0] c_write_tile;logic[3:0] c_write_row;logic[5:0] c_write_col;logic[15:0] c_write_k;logic[127:0] c_write_data;
 logic c_read_request,c_read_valid;logic[9:0] c_read_tile;logic[3:0] c_read_row;logic[127:0] c_read_data;
 logic[9:0] flush_row;logic[5:0] flush_col,width_tiles;logic[9:0] height_rows;logic reads_complete;logic[3:0] read_pending;logic read_issue;
 logic linear_flush;logic[5:0] chunk_cols,write_chunk_col,read_chunk_base;
 logic[31:0] linear_remaining,linear_next_base,write_base_q,write_stride_q,write_rows_q;logic[7:0] write_len_q;
 logic[31:0] first_bytes,segment_bytes;
 logic[31:0] strided_row_base,strided_next_base,strided_left,strided_bytes;logic[9:0] strided_row;
 always_comb begin
  strided_bytes=32'd4096-{20'b0,strided_next_base[11:0]};if(strided_left<strided_bytes)strided_bytes=strided_left;
 end
 always_comb begin first_bytes=32'd1024-{22'b0,linear_next_base[9:0]};segment_bytes=linear_remaining<first_bytes?linear_remaining:first_bytes;end
 logic[127:0] write_queue[4];logic[1:0] queue_rp,queue_wp,word_index;logic[2:0] queue_count;
 logic fifo_valid,fifo_ready;logic[31:0] fifo_data;logic wr_done,wr_error,wr_busy;
 wire queue_pop=fifo_valid && fifo_ready && word_index==3;
 wire queue_push=c_read_valid;
 assign sa_ready=state==IDLE;assign done_valid=state==TASK_DONE || state==TASK_FAIL;assign err_code=state==TASK_FAIL?2'd1:2'd0;
 always_comb begin
  load_request=0;load_panel=wanted_panel;
  if(cache_active && load_ready)begin
   if(!panel_available)begin if(!buffer_busy[wanted_panel[0]])load_request=1;end
   else if(next_panel<panel_count && !buffer_busy[next_panel[0]] && (!cache_valid[next_panel[0]] || cache_tags[next_panel[0]]!=next_panel))begin load_request=1;load_panel=next_panel;end
  end
 end
 always_ff @(posedge clk)begin
  if(!rst_n || group_start)begin column_committed<=0;for(int c=0;c<32;c++)column_last_k[c]<=0;end
  else if(frame_committed)begin column_committed[committed_col]<=1;column_last_k[committed_col]<=committed_k;end
 end
 gempact_panel_cache u_cache(.clk(clk),.rst_n(rst_n),.group_start(group_start),.group_rows(group_rows),.group_cols(group_cols),
  .a_base(a_group),.b_base(b_group),.a_stride(astride),.b_stride(bstride),.k_total(red_k),.load_request(load_request),.load_panel(load_panel),.load_ready(load_ready),.load_done(load_done),.valid_buffers(cache_valid),.panel_tags(cache_tags),
  .a_re(a_re),.a_addr(a_addr),.a_data(a_data),.b_re(b_re),.b_addr(b_addr),.b_data(b_data),
  .arvalid(m_axi_arvalid),.arready(m_axi_arready),.araddr(m_axi_araddr),.arlen(m_axi_arlen),.arsize(m_axi_arsize),.arburst(m_axi_arburst),.rvalid(m_axi_rvalid),.rready(m_axi_rready),.rdata(m_axi_rdata),.rresp(m_axi_rresp),.rlast(m_axi_rlast));
 gempact_frame_array u_core(.clk(clk),.rst_n(rst_n),.job_valid(job_valid),.job_ready(job_ready),.job_rows(group_rows),.job_col(qcol),.job_k(qk),.job_buffer(wanted_panel[0]),.job_final(qk==kt-1'b1),
  .frame_launch(frame_launch),.frame_input_done(frame_input_done),.a_re(a_re),.a_addr(a_addr),.a_data(a_data),.b_re(b_re),.b_addr(b_addr),.b_data(b_data),
  .row_valid(core_valid),.row_tile(core_tile),.row_index(core_row),.row_k(core_k),.row_final(core_final),.row_col(core_col),.row_frame_last(core_frame_last),.row_data(core_data),.buffer_busy(buffer_busy),.busy(core_busy));
 gempact_stream_ps #(.POOL_BYTES(POOL_BYTES),.MAX_TILES(`GEMPACT_PANEL_MAX_R*`GEMPACT_PANEL_MAX_W)) u_ps(.clk(clk),.rst_n(rst_n),.group_start(group_start),.group_release(state==RELEASE),.group_rows(group_rows),.group_cols(group_cols),.group_ready(ps_ready),
  .prepare_request(prepare_request),.prepare_col(qcol),.prepare_final(qk==kt-1'b1),.prepare_finish(draining),.prepare_ready(prep_ready),.prepare_done(prep_done),.prepare_pressure(prep_pressure),.capacity_fault(ps_fault),
  .product_valid(core_valid),.product_tile(core_tile),.product_row(core_row),.product_k(core_k),.product_col(core_col),.product_frame_last(core_frame_last),.product_final(core_final),.product_data(core_data),
  .acc_valid(acc_data_valid),.acc_tile(acc_tile),.acc_row(acc_row),.acc_k(acc_k),.acc_col(acc_col),.acc_frame_last(acc_frame_last),.acc_data(acc_data_out),
  .c_write_col(c_write_col),.c_write_k(c_write_k),.c_write_frame_last(c_write_frame_last),.c_write_valid(c_write_valid),.c_write_tile(c_write_tile),.c_write_row(c_write_row),.c_write_data(c_write_data),
  .c_read_request(c_read_request),.c_read_tile(c_read_tile),.c_read_row(c_read_row),.c_read_valid(c_read_valid),.c_read_data(c_read_data),.all_c_ready(all_c_ready),.frame_committed(frame_committed),.committed_col(committed_col),.committed_k(committed_k),.free_pages(free_pages),.peak_payload_bytes(peak_ps),.records_written(ps_records),.long_records(ps_long_records));
 vec_requant #(.VLEN(16),.ENABLE_PER_CHANNEL(0),.ENABLE_IS_MODE(0)) u_quant(
  .clk(clk),.rst_n(rst_n),.init_cfg(state==CHECK),.cfg_per_channel(1'b0),.cfg_dataflow_mode(1'b0),.activation_min_in(clamp_min),.activation_max_in(clamp_max),.dst_offset_in(dst_offset),.multiplier_in(q_multiplier),.shift_in(q_shift),
  .k(32'd16),.m(32'd16),.ia_reuse_num_in(32'd1),.load_quant_req(),.load_quant_granted(1'b0),.quant_params_valid(),.dma_start(),.dma_is_write(),.dma_linear_read_mode(),.dma_base_addr(),.dma_row_stride(),.dma_rows_to_read(),.dma_burst_len_m1(),.dma_slot_id(),.dma_use_16bits(),.dma_lhs_zp(),.dma_raw_data(32'b0),.dma_raw_valid(1'b0),
  .in_valid(acc_data_valid),.in_tile_done(acc_data_valid && acc_row==15),.in_vec_s32(acc_data_out),.out_valid(quant_valid),.out_tile_done(quant_last),.out_vec_s8(quant_data),.quant_multiplier_lane(),.quant_shift_lane());
 for(genvar l=0;l<16;l++)assign quant_packed[l*8+:8]=quant_data[l];
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   quant_frame_last_pipe<=0;for(int t=0;t<12;t++)begin quant_tile_pipe[t]<=0;quant_row_pipe[t]<=0;quant_col_pipe[t]<=0;quant_k_pipe[t]<=0;end
  end else begin
   quant_frame_last_pipe<={quant_frame_last_pipe[10:0],acc_frame_last};quant_tile_pipe[0]<=acc_tile;quant_row_pipe[0]<=acc_row;quant_col_pipe[0]<=acc_col;quant_k_pipe[0]<=acc_k;
   for(int t=1;t<12;t++)begin quant_tile_pipe[t]<=quant_tile_pipe[t-1];quant_row_pipe[t]<=quant_row_pipe[t-1];quant_col_pipe[t]<=quant_col_pipe[t-1];quant_k_pipe[t]<=quant_k_pipe[t-1];end
  end
 end
 gempact_c_pack u_cpack(.clk(clk),.rst_n(rst_n),.transpose(mode),.in_valid(quant_valid),.in_tile(quant_tile_pipe[11]),.in_row(quant_row_pipe[11]),.in_col(quant_col_pipe[11]),.in_k(quant_k_pipe[11]),.in_frame_last(quant_frame_last_pipe[11]),.in_data(quant_packed),
  .out_valid(c_write_valid),.out_tile(c_write_tile),.out_row(c_write_row),.out_col(c_write_col),.out_k(c_write_k),.out_frame_last(c_write_frame_last),.out_data(c_write_data),.busy(c_pack_busy));
 always_comb begin
  width_tiles=mode?group_rows:group_cols;height_rows=10'(mode?group_cols:group_rows)<<4;
  read_issue=(state==FLUSH_START || state==FLUSH_WAIT) && !reads_complete && (4'(queue_count)+4'(read_pending[0])+4'(read_pending[1])+4'(read_pending[2])+4'(read_pending[3])<4'd4);
 end
 assign fifo_valid=queue_count!=0;assign fifo_data=write_queue[queue_rp][word_index*32+:32];
 always_ff @(posedge clk)begin
  if(!rst_n || group_start)begin flush_row<=0;flush_col<=0;read_chunk_base<=0;reads_complete<=0;read_pending<=0;c_read_request<=0;c_read_tile<=0;c_read_row<=0;queue_rp<=0;queue_wp<=0;queue_count<=0;word_index<=0;end
  else begin
   c_read_request<=read_issue;
   c_read_tile<=mode?10'(flush_row[9:4]*group_rows+flush_col):10'(flush_col*group_rows+flush_row[9:4]);c_read_row<=flush_row[3:0];
   read_pending<={read_pending[2:0],read_issue};
   if(read_issue)begin
    if(flush_col+1'b1<read_chunk_base+chunk_cols)flush_col<=flush_col+1'b1;
    else if(flush_row!=height_rows-1'b1)begin flush_col<=read_chunk_base;flush_row<=flush_row+1'b1;end
    else begin
     flush_row<=0;read_chunk_base<=read_chunk_base+chunk_cols;flush_col<=read_chunk_base+chunk_cols;
     if(read_chunk_base+chunk_cols>=width_tiles)reads_complete<=1;
    end
   end
   if(queue_push)begin write_queue[queue_wp]<=c_read_data;queue_wp<=queue_wp+1'b1;end
   if(fifo_valid && fifo_ready)begin if(word_index==3)begin word_index<=0;queue_rp<=queue_rp+1'b1;end else word_index<=word_index+1'b1;end
   case({queue_push,queue_pop})2'b10:queue_count<=queue_count+1'b1;2'b01:queue_count<=queue_count-1'b1;default:;endcase
  end
 end
 axi_dual_block_dma #(.DATA_WIDTH(8),.SIZE(16),.CACHE_BLOCKS(64),.READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4)) u_writer(
  .conv_cfg_ready(),.conv_error(),.conv_busy(),.conv_stat_hits(),.conv_stat_misses(),.conv_stat_read_bytes(),
  .clk(clk),.rst_n(rst_n),.rd_start(1'b0),.rd_linear_read_mode(1'b0),.rd_base_addr(32'b0),.rd_row_stride(32'b0),.rd_rows_to_read(32'b0),.rd_valid_cols(32'b0),.rd_burst_len_m1(8'b0),.rd_slot_id(6'b0),.rd_use_16bits(1'b0),.rd_lhs_zp(32'b0),.rd_busy(),.rd_done(),.rd_finish_beat(),
  .wr_start(state==FLUSH_START),.wr_base_addr(write_base_q),.wr_row_stride(write_stride_q),.wr_rows_to_write(write_rows_q),.wr_burst_len_m1(write_len_q),.wr_busy(wr_busy),.wr_done(wr_done),.src_wdata(fifo_data),.src_wmask(4'hf),.src_wvalid(fifo_valid),.src_wready(fifo_ready),
  .wr_slot(),.wr_row(),.wr_col_base(),.wr_data(),.wr_valid(),.wr_use_16bits(),.rd_raw_data(),.rd_raw_valid(),.rd_raw_row(),.rd_raw_col_base(),.rd_error(),.wr_error(wr_error),
  .m_axi_arvalid(),.m_axi_arready(1'b0),.m_axi_araddr(),.m_axi_arlen(),.m_axi_arsize(),.m_axi_arburst(),.m_axi_rvalid(1'b0),.m_axi_rready(),.m_axi_rdata(32'b0),.m_axi_rresp(2'b0),.m_axi_rlast(1'b0),
  .m_axi_awvalid(m_axi_awvalid),.m_axi_awready(m_axi_awready),.m_axi_awaddr(m_axi_awaddr),.m_axi_awlen(m_axi_awlen),.m_axi_awsize(m_axi_awsize),.m_axi_awburst(m_axi_awburst),.m_axi_wvalid(m_axi_wvalid),.m_axi_wready(m_axi_wready),.m_axi_wdata(m_axi_wdata),.m_axi_wstrb(m_axi_wstrb),.m_axi_wlast(m_axi_wlast),.m_axi_bvalid(m_axi_bvalid),.m_axi_bready(m_axi_bready),.m_axi_bresp(m_axi_bresp));
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;producer<=P_IDLE;mode<=0;abase<=0;bbase<=0;cbase<=0;astride<=0;bstride<=0;cstride<=0;red_k<=0;R<=0;W<=0;row_groups<=0;col_groups<=0;row_tail<=0;col_tail<=0;
   a_product<=0;b_product<=0;c_product<=0;a_group<=0;b_group<=0;c_group<=0;kt<=0;gr<=0;gc<=0;rg<=0;cg<=0;group_rows<=0;group_cols<=0;qcol<=0;qk<=0;normal_col<=0;normal_k<=0;active_cols<=0;draining<=0;production_done<=0;inflight<=0;early_frames<=0;tile_commands<=0;issued_frames<=0;completed_frames<=0;
   q_multiplier<=0;q_shift<=0;dst_offset<=0;clamp_min<=0;clamp_max<=0;strided_row_base<=0;strided_next_base<=0;strided_left<=0;strided_row<=0;linear_flush<=0;chunk_cols<=1;write_chunk_col<=0;linear_remaining<=0;linear_next_base<=0;write_base_q<=0;write_stride_q<=0;write_rows_q<=0;write_len_q<=0;accepted_phase_final<=0;
  end else begin
   if(state==RUN)begin
    if(job_accept)accepted_phase_final<=qk==kt-1'b1;
    case({job_accept,frame_committed})2'b10:inflight<=inflight+1'b1;2'b01:inflight<=inflight-1'b1;default:;endcase
    if(frame_committed)completed_frames<=completed_frames+1'b1;
   end
   case(state)
    IDLE:if(calc_start)begin
     mode<=cfg_dataflow_mode;abase<=cfg_dataflow_mode?rhs_base:lhs_base;bbase<=cfg_dataflow_mode?lhs_base:rhs_base;cbase<=dst_base;astride<=cfg_dataflow_mode?rhs_col_stride_b:lhs_row_stride_b;bstride<=cfg_dataflow_mode?lhs_row_stride_b:rhs_col_stride_b;cstride<=dst_row_stride_b;
     red_k<=n;kt<=16'(n>>4);R<=cfg_ia_reuse_num;W<=cfg_w_reuse_num;row_groups<=cfg_row_groups;col_groups<=cfg_col_groups;row_tail<=cfg_row_tail_tiles;col_tail<=cfg_col_tail_tiles;
     q_multiplier<=q_mult_pt;q_shift<=q_shift_pt;dst_offset<=dst_zp;clamp_min<=act_min;clamp_max<=act_max;
     gr<=0;gc<=0;rg<=0;cg<=0;early_frames<=0;tile_commands<=0;issued_frames<=0;completed_frames<=0;state<=CHECK;
     if(cfg_ia_reuse_num>`GEMPACT_PANEL_MAX_R || cfg_w_reuse_num>`GEMPACT_PANEL_MAX_W)state<=TASK_FAIL;
     if(SIZE!=16 || BUS_WIDTH!=32 || cfg_16bits_ia || cfg_16x8 || use_per_channel || bias_base!=0 || lhs_zp!=0 || rhs_zp!=0 || k==0 || n==0 || m==0 || (k|n|m)&15 || (k>>20)!=0 || (n>>20)!=0 || (m>>20)!=0 || cfg_ia_reuse_num==0 || cfg_ia_reuse_num>32 || cfg_w_reuse_num==0 || cfg_w_reuse_num>32 || cfg_row_groups==0 || cfg_row_groups>65535 || cfg_col_groups==0 || cfg_col_groups>65535 || cfg_row_tail_tiles==0 || cfg_row_tail_tiles>cfg_ia_reuse_num || cfg_col_tail_tiles==0 || cfg_col_tail_tiles>cfg_w_reuse_num || lhs_base==0 || rhs_base==0 || dst_base==0 || ((lhs_base|rhs_base|dst_base|lhs_row_stride_b|rhs_col_stride_b|dst_row_stride_b)&32'hf)!=0)state<=TASK_FAIL;
    end
    CHECK:state<=GROUP_ADDR0;
    GROUP_ADDR0:begin group_rows<=6'(rg==row_groups-1?row_tail:R);group_cols<=6'(cg==col_groups-1?col_tail:W);a_product<=gr*astride;b_product<=gc*bstride;c_product<=(mode?gc:gr)*cstride;state<=GROUP_ADDR1;end
    GROUP_ADDR1:begin a_group<=abase+(a_product<<4);b_group<=bbase+(b_product<<4);c_group<=cbase+(c_product<<4)+(mode?32'(gr):32'(gc))*16;state<=GROUP_SETUP;end
    GROUP_SETUP:begin qcol<=0;qk<=0;active_cols<=32'((33'h1<<group_cols)-1'b1);draining<=0;production_done<=0;inflight<=0;producer<=P_IDLE;state<=GROUP_WAIT;end
    GROUP_WAIT:if(ps_fault)state<=TASK_FAIL;else if(ps_ready)state<=RUN;
    RUN:begin
     if(ps_fault)state<=TASK_FAIL;
     else if(production_done && inflight==0 && all_c_ready && !core_busy && !c_pack_busy && !c_write_valid && load_ready)state<=FLUSH_CONFIG;
     else if(!production_done)case(producer)
      P_IDLE:begin
       if(active_cols==0)production_done<=1;
       else if(!active_cols[qcol])begin
        if(qcol==group_cols-1'b1)begin qcol<=0;if(qk==kt-1'b1)production_done<=1;else qk<=qk+1'b1;end
        else qcol<=qcol+1'b1;
       end else if(!predecessor_ready || ps_phase_wait || ((draining || group_cols==1) && inflight!=0))begin end
       else producer<=P_REQUEST;
      end
      P_REQUEST:if(prep_ready)producer<=P_WAIT;
      P_WAIT:begin
       if(prep_pressure)begin draining<=1;normal_k<=qk;normal_col<=qcol;early_frames<=early_frames+1'b1;producer<=P_IDLE;end
       else if(prep_done)producer<=P_PANEL;
      end
      P_PANEL:if(panel_available)producer<=P_ENQUEUE;
      P_ENQUEUE:if(job_ready)begin
       tile_commands<=tile_commands+group_rows;issued_frames<=issued_frames+1'b1;producer<=P_IDLE;
       if(draining)begin
        if(qk!=kt-1'b1)qk<=qk+1'b1;
        else begin
         active_cols[qcol]<=0;draining<=0;qk<=normal_k;
         if(normal_col==group_cols-1'b1)begin qcol<=0;if(normal_k==kt-1'b1)production_done<=1;else qk<=normal_k+1'b1;end
         else qcol<=normal_col+1'b1;
        end
       end else if(qcol!=group_cols-1'b1)qcol<=qcol+1'b1;
       else begin qcol<=0;if(qk==kt-1'b1)production_done<=1;else qk<=qk+1'b1;end
      end
      default:producer<=P_IDLE;
     endcase
    end
    FLUSH_CONFIG:begin
     linear_flush<=(32'(width_tiles)<<4)==cstride;linear_remaining<=32'(group_rows*group_cols)<<8;linear_next_base<=c_group;write_chunk_col<=0;
     chunk_cols<=width_tiles;
     strided_row_base<=c_group;strided_next_base<=c_group;strided_left<=32'(width_tiles)<<4;strided_row<=0;
     state<=FLUSH_SEGMENT;
    end
    FLUSH_SEGMENT:begin
     if(linear_flush)begin
      write_base_q<=linear_next_base;write_stride_q<=1024;
      if(linear_next_base[9:0]!=0 || linear_remaining<1024)begin
       write_rows_q<=1;write_len_q<=8'((segment_bytes>>2)-1'b1);linear_next_base<=linear_next_base+segment_bytes;linear_remaining<=linear_remaining-segment_bytes;
      end else begin
       write_rows_q<=linear_remaining>>10;write_len_q<=255;linear_next_base<=linear_next_base+{linear_remaining[31:10],10'b0};linear_remaining<={22'b0,linear_remaining[9:0]};
      end
     end else if(strided_left==(32'(width_tiles)<<4) &&
                 cstride!=0 && cstride<=4096 && (cstride&(cstride-1'b1))==0 &&
                 (strided_next_base&(cstride-1'b1))+(32'(width_tiles)<<4)<=cstride)begin
      // Batch equal-width rows through the existing strided DMA and its four
      // outstanding writes.  Each row keeps its own AXI address and payload;
      // no bytes in the gaps are transferred.  Power-of-two row strides that
      // divide 4 KiB make the checked within-row bound valid for every row.
      // The DMA row counter is nine bits; cap a batch at 255 rows.
      write_base_q<=strided_next_base;write_stride_q<=cstride;
      write_len_q<=8'((32'(width_tiles)<<2)-1'b1);
      if(height_rows-strided_row>255)begin
       write_rows_q<=255;strided_row<=strided_row+255;
       strided_row_base<=strided_row_base+cstride*255;
       strided_next_base<=strided_next_base+cstride*255;
      end else begin
       write_rows_q<=32'(height_rows-strided_row);strided_row<=height_rows;
      end
     end else begin
      write_base_q<=strided_next_base;write_stride_q<=0;write_rows_q<=1;write_len_q<=8'((strided_bytes>>2)-1'b1);
      if(strided_bytes==strided_left)begin
       strided_row<=strided_row+1'b1;strided_row_base<=strided_row_base+cstride;strided_next_base<=strided_row_base+cstride;strided_left<=32'(width_tiles)<<4;
      end else begin strided_next_base<=strided_next_base+strided_bytes;strided_left<=strided_left-strided_bytes;end
     end
     state<=FLUSH_START;
    end
    FLUSH_START:state<=FLUSH_WAIT;
    FLUSH_WAIT:begin
     if(wr_error)state<=TASK_FAIL;
     else if(wr_done)begin
      if(linear_flush && linear_remaining!=0)state<=FLUSH_SEGMENT;
      else if(!linear_flush && strided_row<height_rows)state<=FLUSH_SEGMENT;
      else state<=RELEASE;
     end
    end
    RELEASE:state<=NEXT_GROUP;
    NEXT_GROUP:begin
     if(cg+1<col_groups)begin cg<=cg+1'b1;gc<=gc+16'(W);state<=GROUP_ADDR0;end
     else if(rg+1<row_groups)begin rg<=rg+1'b1;gr<=gr+16'(R);cg<=0;gc<=0;state<=GROUP_ADDR0;end
     else state<=TASK_DONE;
    end
    TASK_DONE,TASK_FAIL:if(done_ready)state<=IDLE;
    default:state<=TASK_FAIL;
   endcase
  end
 end
`ifndef SYNTHESIS
 always @(posedge clk)if(rst_n)begin
  assert(queue_count<=4)else $fatal(1,"C write queue overflow");
  if(frame_committed)assert(inflight!=0)else $fatal(1,"unexpected PS frame completion");
  if(job_accept)assert(panel_available)else $fatal(1,"operand panel unavailable");
 end
`endif
endmodule
