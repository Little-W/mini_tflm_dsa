// 连接十六位输出 FIFO、完整控制器、部分和读取及共享 RAM，检查全部内部寄存器到存储端口的组合路径。
module measure #(
 parameter REG_WIDTH=32, SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16, WEIGHT_WIDTH=16,
 parameter p_addr_width=12, p_bank_count_width=3, VLEN=16, BANKS=4
)(
input logic  s16_in_valid, // 十六位输出 FIFO 公开信号 in_valid
input logic  s16_in_tile_done, // 十六位输出 FIFO 公开信号 in_tile_done
input logic [VLEN*16-1:0] s16_in_vec_s16, // 十六位输出 FIFO 公开信号 in_vec_s16
output logic  s16_oa_fifo_req, // 十六位输出 FIFO 公开信号 oa_fifo_req
input logic [31:0] s16_reserve_banks, // 十六位输出 FIFO 公开信号 reserve_banks
input logic [31:0] s16_i_ready_bank_threshold, // 十六位输出 FIFO 公开信号 i_ready_bank_threshold
input logic [$clog2(VLEN)-1:0] s16_vec_valid_num_col, // 十六位输出 FIFO 公开信号 vec_valid_num_col
output logic  s16_output_valid, // 十六位输出 FIFO 公开信号 output_valid
input logic  s16_output_ready, // 十六位输出 FIFO 公开信号 output_ready
output logic  s16_output_row_switch, // 十六位输出 FIFO 公开信号 output_row_switch
output logic [BUS_WIDTH/8-1:0] s16_output_mask, // 十六位输出 FIFO 公开信号 output_mask
output logic [BUS_WIDTH-1:0] s16_output_data, // 十六位输出 FIFO 公开信号 output_data
input logic i_s16_mode, // 选择十六位输出 FIFO，八位输出满状态使用独立寄存输入。
input logic clk, // 测量时钟
input logic rst_n, // 低有效复位
input logic [31:0] i_bias_address, // 完整偏置基址
input logic [31:0] i_ws_channel, // 权重驻留通道
input logic [31:0] i_is_channel, // 输入驻留通道
input logic [5:0] i_bias_flags, // 帧模式、数据流、末帧偏置和帧位置
input logic [8:0] i_ps_flags, // 部分和读取条件与共享端口选择
input logic [8:0] i_frame_status, // 帧完成状态与输出运行状态
input logic [2:0] i_output_conditions, // 量化输出分组和输入输出待处理状态
input logic  c_calc_start, // 控制器input信号 calc_start
input logic  c_cfg_16bits_ia, // 控制器input信号 cfg_16bits_ia
input logic  c_cfg_tiling_error, // 控制器input信号 cfg_tiling_error
input logic  c_cfg_dataflow_mode, // 控制器input信号 cfg_dataflow_mode
output logic  c_sa_ready, // 控制器output信号 sa_ready
input logic [REG_WIDTH-1:0] c_lhs_base, // 控制器input信号 lhs_base
input logic [REG_WIDTH-1:0] c_rhs_base, // 控制器input信号 rhs_base
input logic [REG_WIDTH-1:0] c_dst_base, // 控制器input信号 dst_base
input logic [REG_WIDTH-1:0] c_q_mult_pt, // 控制器input信号 q_mult_pt
input logic [REG_WIDTH-1:0] c_q_shift_pt, // 控制器input信号 q_shift_pt
input logic  c_use_per_channel, // 控制器input信号 use_per_channel
input logic [REG_WIDTH-1:0] c_k, // 控制器input信号 k
input logic [REG_WIDTH-1:0] c_n, // 控制器input信号 n
input logic [REG_WIDTH-1:0] c_m, // 控制器input信号 m
input logic [REG_WIDTH-1:0] c_lhs_row_stride_b, // 控制器input信号 lhs_row_stride_b
input logic [REG_WIDTH-1:0] c_dst_row_stride_b, // 控制器input信号 dst_row_stride_b
input logic [REG_WIDTH-1:0] c_rhs_col_stride_b, // 控制器input信号 rhs_col_stride_b
output logic  c_init_cfg_ia, // 控制器output信号 init_cfg_ia
output logic  c_init_cfg_weight, // 控制器output信号 init_cfg_weight
output logic  c_init_cfg_bias, // 控制器output信号 init_cfg_bias
output logic  c_init_cfg_requant, // 控制器output信号 init_cfg_requant
output logic  c_init_cfg_oa, // 控制器output信号 init_cfg_oa
output logic  c_use_16bits, // 控制器output信号 use_16bits
input logic  c_partial_sum_calc_over, // 控制器input信号 partial_sum_calc_over
input logic  c_partial_sum_advance_ready, // 控制器input信号 partial_sum_advance_ready
input logic  c_tile_calc_over, // 控制器input信号 tile_calc_over
output logic  c_send_ia_trigger, // 控制器output信号 send_ia_trigger
input logic  c_ia_sending_done, // 控制器input信号 ia_sending_done
input logic  c_ia_data_valid, // 控制器input信号 ia_data_valid
input logic  c_ps_frame_ready, // 控制器input信号 ps_frame_ready
output logic  c_weight_commit, // 控制器output信号 weight_commit
output logic  c_send_weight_trigger, // 控制器output信号 send_weight_trigger
input logic  c_weight_sending_done, // 控制器input信号 weight_sending_done
input logic  c_weight_data_valid, // 控制器input信号 weight_data_valid
input logic  c_weight_resident, // 控制器input信号 weight_resident
input logic  c_bias_valid, // 控制器input信号 bias_valid
input logic  c_bias_sleep, // 控制器input信号 bias_sleep
input logic  c_quant_params_valid, // 控制器input信号 quant_params_valid
input logic  c_fifo_full_flag, // 控制器input信号 fifo_full_flag
input logic  c_oa_calc_over, // 控制器input信号 oa_calc_over
output logic  c_done_valid, // 控制器output信号 done_valid
input logic  c_done_ready, // 控制器input信号 done_ready
output logic [1:0] c_err_code, // 控制器output信号 err_code
input logic  m_i_access_enable, // 共享存储input信号 i_access_enable
input logic  m_i_cfg_valid, // 共享存储input信号 i_cfg_valid
input logic [p_bank_count_width-1:0] m_i_cfg_ia_banks, // 共享存储input信号 i_cfg_ia_banks
output logic  m_o_capacity_fault, // 共享存储output信号 o_capacity_fault
input logic [1:0] m_i_ia_read_en, // 共享存储input信号 i_ia_read_en
input logic [1:0] m_i_ia_write_en, // 共享存储input信号 i_ia_write_en
input logic [p_addr_width-1:0] m_i_ia_read_addr [2], // 共享存储input信号 i_ia_read_addr
input logic [p_addr_width-1:0] m_i_ia_write_addr [2], // 共享存储input信号 i_ia_write_addr
output logic [127:0] m_o_ia_read_data [2], // 共享存储output信号 o_ia_read_data
input logic [127:0] m_i_ia_write_data [2], // 共享存储input信号 i_ia_write_data
input logic [127:0] m_i_ia_shared_write_data, // 共享存储input信号 i_ia_shared_write_data
input logic [15:0] m_i_ia_write_mask [2], // 共享存储input信号 i_ia_write_mask
input logic [3:0] m_i_ps_read_en, // 共享存储input信号 i_ps_read_en
input logic [3:0] m_i_ps_write_en, // 共享存储input信号 i_ps_write_en
input logic [p_addr_width-1:0] m_i_ps_read_addr [4], // 共享存储input信号 i_ps_read_addr
input logic [p_addr_width-1:0] m_i_ps_write_addr [4], // 共享存储input信号 i_ps_write_addr
output logic [127:0] m_o_ps_read_data [4], // 共享存储output信号 o_ps_read_data
input logic [127:0] m_i_ps_write_data [4] // 共享存储input信号 i_ps_write_data
);
logic [31:0] bias_address_q,ws_channel_q,is_channel_q;
logic [5:0] bias_flags_q;
logic [8:0] ps_flags_q;
logic [8:0] frame_status_q;
logic [2:0] output_conditions_q;
logic  s16_in_valid_q;
logic  s16_in_tile_done_q;
logic [VLEN*16-1:0] s16_in_vec_s16_q;
logic  s16_oa_fifo_req_q;
logic [31:0] s16_reserve_banks_q;
logic [31:0] s16_i_ready_bank_threshold_q;
logic [$clog2(VLEN)-1:0] s16_vec_valid_num_col_q;
logic  s16_output_valid_q;
logic  s16_output_ready_q;
logic  s16_output_row_switch_q;
logic [BUS_WIDTH/8-1:0] s16_output_mask_q;
logic [BUS_WIDTH-1:0] s16_output_data_q;
logic frame_complete;
logic s16_mode_q, s16_full, s16_issue_full;
logic address_zero,base_nonzero,bias_present,frame_phase,issue_eligible,issue_qualified;
logic frame_accept,frame_read;
logic [3:0] memory_read_enable;
logic  calc_start_q;
logic  cfg_16bits_ia_q;
logic  cfg_tiling_error_q;
logic  cfg_dataflow_mode_q;
logic  sa_ready;
logic [REG_WIDTH-1:0] lhs_base_q;
logic [REG_WIDTH-1:0] rhs_base_q;
logic [REG_WIDTH-1:0] dst_base_q;
logic [REG_WIDTH-1:0] q_mult_pt_q;
logic [REG_WIDTH-1:0] q_shift_pt_q;
logic  use_per_channel_q;
logic [REG_WIDTH-1:0] k_q;
logic [REG_WIDTH-1:0] n_q;
logic [REG_WIDTH-1:0] m_q;
logic [REG_WIDTH-1:0] lhs_row_stride_b_q;
logic [REG_WIDTH-1:0] dst_row_stride_b_q;
logic [REG_WIDTH-1:0] rhs_col_stride_b_q;
logic  init_cfg_ia;
logic  init_cfg_weight;
logic  init_cfg_bias;
logic  init_cfg_requant;
logic  init_cfg_oa;
logic  use_16bits;
logic  partial_sum_calc_over_q;
logic  partial_sum_advance_ready_q;
logic  tile_calc_over_q;
logic  send_ia_trigger;
logic  ia_sending_done_q;
logic  ia_data_valid_q;
logic  ps_frame_ready_q;
logic  weight_commit;
logic  send_weight_trigger;
logic  weight_sending_done_q;
logic  weight_data_valid_q;
logic  weight_resident_q;
logic  bias_valid_q;
logic  bias_sleep_q;
logic  quant_params_valid_q;
logic  fifo_full_flag_q;
logic  oa_calc_over_q;
logic  done_valid;
logic  done_ready_q;
logic [1:0] err_code;
logic  mem_i_access_enable_q;
logic  mem_i_cfg_valid_q;
logic [p_bank_count_width-1:0] mem_i_cfg_ia_banks_q;
logic  mem_o_capacity_fault;
logic [1:0] mem_i_ia_read_en_q;
logic [1:0] mem_i_ia_write_en_q;
logic [p_addr_width-1:0] mem_i_ia_read_addr_q [2];
logic [p_addr_width-1:0] mem_i_ia_write_addr_q [2];
logic [127:0] mem_o_ia_read_data [2];
logic [127:0] mem_i_ia_write_data_q [2];
logic [127:0] mem_i_ia_shared_write_data_q;
logic [15:0] mem_i_ia_write_mask_q [2];
logic [3:0] mem_i_ps_read_en_q;
logic [3:0] mem_i_ps_write_en_q;
logic [p_addr_width-1:0] mem_i_ps_read_addr_q [4];
logic [p_addr_width-1:0] mem_i_ps_write_addr_q [4];
logic [127:0] mem_o_ps_read_data [4];
logic [127:0] mem_i_ps_write_data_q [4];
always_ff @(posedge clk) begin
s16_in_valid_q <= s16_in_valid;
s16_in_tile_done_q <= s16_in_tile_done;
s16_in_vec_s16_q <= s16_in_vec_s16;
s16_oa_fifo_req <= s16_oa_fifo_req_q;
s16_reserve_banks_q <= s16_reserve_banks;
s16_i_ready_bank_threshold_q <= s16_i_ready_bank_threshold;
s16_vec_valid_num_col_q <= s16_vec_valid_num_col;
s16_output_valid <= s16_output_valid_q;
s16_output_ready_q <= s16_output_ready;
s16_output_row_switch <= s16_output_row_switch_q;
s16_output_mask <= s16_output_mask_q;
s16_output_data <= s16_output_data_q;
s16_mode_q<=i_s16_mode;
bias_address_q<=i_bias_address;ws_channel_q<=i_ws_channel;is_channel_q<=i_is_channel;
bias_flags_q<=i_bias_flags;ps_flags_q<=i_ps_flags;
frame_status_q<=i_frame_status;output_conditions_q<=i_output_conditions;
calc_start_q<=c_calc_start;
cfg_16bits_ia_q<=c_cfg_16bits_ia;
cfg_tiling_error_q<=c_cfg_tiling_error;
cfg_dataflow_mode_q<=c_cfg_dataflow_mode;
c_sa_ready<=sa_ready;
lhs_base_q<=c_lhs_base;
rhs_base_q<=c_rhs_base;
dst_base_q<=c_dst_base;
q_mult_pt_q<=c_q_mult_pt;
q_shift_pt_q<=c_q_shift_pt;
use_per_channel_q<=c_use_per_channel;
k_q<=c_k;
n_q<=c_n;
m_q<=c_m;
lhs_row_stride_b_q<=c_lhs_row_stride_b;
dst_row_stride_b_q<=c_dst_row_stride_b;
rhs_col_stride_b_q<=c_rhs_col_stride_b;
c_init_cfg_ia<=init_cfg_ia;
c_init_cfg_weight<=init_cfg_weight;
c_init_cfg_bias<=init_cfg_bias;
c_init_cfg_requant<=init_cfg_requant;
c_init_cfg_oa<=init_cfg_oa;
c_use_16bits<=use_16bits;
partial_sum_calc_over_q<=c_partial_sum_calc_over;
partial_sum_advance_ready_q<=c_partial_sum_advance_ready;
tile_calc_over_q<=c_tile_calc_over;
c_send_ia_trigger<=send_ia_trigger;
ia_sending_done_q<=c_ia_sending_done;
ia_data_valid_q<=c_ia_data_valid;
ps_frame_ready_q<=c_ps_frame_ready;
c_weight_commit<=weight_commit;
c_send_weight_trigger<=send_weight_trigger;
weight_sending_done_q<=c_weight_sending_done;
weight_data_valid_q<=c_weight_data_valid;
weight_resident_q<=c_weight_resident;
bias_valid_q<=c_bias_valid;
bias_sleep_q<=c_bias_sleep;
quant_params_valid_q<=c_quant_params_valid;
fifo_full_flag_q<=c_fifo_full_flag;
oa_calc_over_q<=c_oa_calc_over;
c_done_valid<=done_valid;
done_ready_q<=c_done_ready;
c_err_code<=err_code;
mem_i_access_enable_q<=m_i_access_enable;
mem_i_cfg_valid_q<=m_i_cfg_valid;
mem_i_cfg_ia_banks_q<=m_i_cfg_ia_banks;
m_o_capacity_fault<=mem_o_capacity_fault;
mem_i_ia_read_en_q<=m_i_ia_read_en;
mem_i_ia_write_en_q<=m_i_ia_write_en;
mem_i_ia_read_addr_q<=m_i_ia_read_addr;
mem_i_ia_write_addr_q<=m_i_ia_write_addr;
m_o_ia_read_data<=mem_o_ia_read_data;
mem_i_ia_write_data_q<=m_i_ia_write_data;
mem_i_ia_shared_write_data_q<=m_i_ia_shared_write_data;
mem_i_ia_write_mask_q<=m_i_ia_write_mask;
mem_i_ps_read_en_q<=m_i_ps_read_en;
mem_i_ps_write_en_q<=m_i_ps_write_en;
mem_i_ps_read_addr_q<=m_i_ps_read_addr;
mem_i_ps_write_addr_q<=m_i_ps_write_addr;
m_o_ps_read_data<=mem_o_ps_read_data;
mem_i_ps_write_data_q<=m_i_ps_write_data;
end
(* keep=1 *) logic [5:0] base_zero_groups;
for(genvar g=0;g<6;g++)begin:g_zero
 localparam integer N=(32-6*g<6)?32-6*g:6;
 zero_reduce #(.p_width(N)) u_zero(.i_value(bias_address_q[6*g+:N]),.o_zero(base_zero_groups[g]));
end
assign base_nonzero=!(&base_zero_groups);
npu_bias_presence u_presence(
 .i_frame_mode(bias_flags_q[0]),.i_base_nonzero(base_nonzero),.i_is_mode(bias_flags_q[1]),
 .i_ws_final_bias(bias_flags_q[2]),.i_frame_final(bias_flags_q[3]),.i_frame_init(bias_flags_q[4]),
 .i_address_zero(address_zero),.i_visible_base_nonzero(base_nonzero),.o_present(bias_present), .o_frame_phase(frame_phase));
npu_bias_address_zero #(.p_width(32)) u_zero_address(
 .i_base(bias_address_q),.i_ws_channel(ws_channel_q),.i_is_channel(is_channel_q),
 .i_is_mode(bias_flags_q[1]),.o_zero(address_zero),.i_issue_eligible(issue_eligible),.i_frame_mode(bias_flags_q[0]),
 .i_base_nonzero(base_nonzero),.i_frame_phase(frame_phase),.i_visible_base_nonzero(base_nonzero),
 .i_bias_available(bias_valid_q || bias_sleep_q),.i_frame_incomplete(!(frame_status_q[8] && (frame_status_q[7] && (frame_status_q[6] || partial_sum_calc_over_q) && (!bias_flags_q[3] || frame_status_q[3] || (frame_status_q[2] && oa_calc_over_q))) && (frame_status_q[5] || frame_status_q[4]))),.i_output_complete(oa_calc_over_q),.o_issue(issue_qualified));
completion u_completion(.i_controls({bias_flags_q[0],frame_status_q[8:6],partial_sum_calc_over_q,frame_status_q[5:4],bias_flags_q[3],frame_status_q[3:2],oa_calc_over_q}),.o_complete(frame_complete));
npu_controller #(.REG_WIDTH(REG_WIDTH),.SIZE(SIZE),.BUS_WIDTH(BUS_WIDTH),.DATA_WIDTH(DATA_WIDTH),.WEIGHT_WIDTH(WEIGHT_WIDTH), .p_external_ia_issue(1'b1)) u_controller(
.clk(clk),
.rst_n(rst_n),
.calc_start(calc_start_q),
.cfg_16bits_ia(cfg_16bits_ia_q),
.cfg_tiling_error(cfg_tiling_error_q),
.cfg_dataflow_mode(cfg_dataflow_mode_q),
.sa_ready(sa_ready),
.lhs_base(lhs_base_q),
.rhs_base(rhs_base_q),
.dst_base(dst_base_q),
.bias_base(32'(bias_present)),
.q_mult_pt(q_mult_pt_q),
.q_shift_pt(q_shift_pt_q),
.use_per_channel(use_per_channel_q),
.k(k_q),
.n(n_q),
.m(m_q),
.lhs_row_stride_b(lhs_row_stride_b_q),
.dst_row_stride_b(dst_row_stride_b_q),
.rhs_col_stride_b(rhs_col_stride_b_q),
.init_cfg_ia(init_cfg_ia),
.init_cfg_weight(init_cfg_weight),
.init_cfg_bias(init_cfg_bias),
.init_cfg_requant(init_cfg_requant),
.init_cfg_oa(init_cfg_oa),
.use_16bits(use_16bits),
.partial_sum_calc_over(partial_sum_calc_over_q),
.partial_sum_advance_ready(partial_sum_advance_ready_q),
.tile_calc_over(tile_calc_over_q),
.send_ia_trigger(send_ia_trigger),
.o_ia_issue_eligible(issue_eligible),
.i_ia_issue_qualified(issue_qualified),
.ia_sending_done(ia_sending_done_q),
.ia_data_valid(ia_data_valid_q),
.ps_frame_ready(ps_frame_ready_q),
.weight_commit(weight_commit),
.send_weight_trigger(send_weight_trigger),
.weight_sending_done(weight_sending_done_q),
.weight_data_valid(weight_data_valid_q),
.weight_resident(weight_resident_q),
.bias_valid(bias_valid_q),
.bias_sleep(bias_sleep_q),
.quant_params_valid((quant_params_valid_q || (bias_flags_q[0] && !bias_flags_q[3])) && (!output_conditions_q[0] || output_conditions_q[1])),
.fifo_full_flag(s16_issue_full),
.oa_calc_over(frame_complete),
.done_valid(done_valid),
.done_ready(done_ready_q),
.err_code(err_code));
assign frame_accept=send_ia_trigger && !ps_flags_q[0];
ps_frame_read_enable u_read_enable(
 .i_request(ps_flags_q[1] && !ps_flags_q[0]),.i_accept(send_ia_trigger),.i_accept_permit(!ps_flags_q[0]),.i_accepted(ps_flags_q[2]),
 .i_first_ready(ps_flags_q[3]),.i_continue_ready(ps_flags_q[4]),.i_fault(ps_flags_q[5]),.o_read_enable(frame_read));
assign memory_read_enable=!ps_flags_q[7]?4'b0:ps_flags_q[8]?mem_i_ps_read_en_q:{4{frame_read}};
ia_ps_channel_ram #(.p_shared_write_stage(1'b1),.p_ia_nonempty_writes(1'b1),
 .p_allow_inactive_return_updates(1'b1),.p_paired_ia_ports(1'b1),
 .p_bank_bytes(8192),.p_total_bytes(57344)) u_ram(
.clk(clk),
.rst_n(rst_n),
.i_access_enable(mem_i_access_enable_q),
.i_cfg_valid(mem_i_cfg_valid_q),
.i_cfg_ia_banks(mem_i_cfg_ia_banks_q),
.o_capacity_fault(mem_o_capacity_fault),
.i_ia_read_en(mem_i_ia_read_en_q),
.i_ia_write_en(mem_i_ia_write_en_q),
.i_ia_read_addr(mem_i_ia_read_addr_q),
.i_ia_write_addr(mem_i_ia_write_addr_q),
.o_ia_read_data(mem_o_ia_read_data),
.i_ia_write_data(mem_i_ia_write_data_q),
.i_ia_shared_write_data(mem_i_ia_shared_write_data_q),
.i_ia_write_mask(mem_i_ia_write_mask_q),
.i_ps_read_en(memory_read_enable),
.i_ps_write_en(mem_i_ps_write_en_q),
.i_ps_read_addr(mem_i_ps_read_addr_q),
.i_ps_write_addr(mem_i_ps_write_addr_q),
.o_ps_read_data(mem_o_ps_read_data),
.i_ps_write_data(mem_i_ps_write_data_q));
vec_s16_to_fifo #(.VLEN(VLEN),.BANKS(BANKS),.BUS_WIDTH(BUS_WIDTH),.p_precomputed_watermark(1)) u_s16(
.clk(clk),
.rst_n(rst_n),
.in_valid(s16_in_valid_q),
.in_tile_done(s16_in_tile_done_q),
.in_vec_s16(s16_in_vec_s16_q),
.oa_fifo_req(s16_oa_fifo_req_q),
.reserve_banks(s16_reserve_banks_q),
.i_ready_bank_threshold(s16_i_ready_bank_threshold_q),
.vec_valid_num_col(s16_vec_valid_num_col_q),
.output_valid(s16_output_valid_q),
.output_ready(s16_output_ready_q),
.output_row_switch(s16_output_row_switch_q),
.output_mask(s16_output_mask_q),
.output_data(s16_output_data_q),
.fifo_full_flag(s16_full),
.i_full_select(s16_mode_q),.i_output_pending(output_conditions_q[2]),
.i_other_full(fifo_full_flag_q),.o_issue_full(s16_issue_full)
);
endmodule
// 直接采用生产矩阵引擎的完成表达式与实例连接。
module completion(input logic [10:0] i_controls, output logic o_complete);
logic o_frame_mode_q, frame_command_active, frame_execution_started, frame_compute_seen, partial_sum_calc_over, frame_store_seen, ps_frame_complete, frame_exec_final, frame_output_seen, frame_output_armed, oa_calc_over;
logic exec_oa_complete;
logic frame_issue_incomplete;
    logic frame_complete_i_mode, frame_complete_i_active, frame_complete_i_eligible;
    logic frame_complete_i_store_seen, frame_complete_i_store_complete;
    logic frame_complete_i_output_complete, frame_complete_o_complete;
    assign {o_frame_mode_q, frame_command_active, frame_execution_started, frame_compute_seen, partial_sum_calc_over, frame_store_seen, ps_frame_complete, frame_exec_final, frame_output_seen, frame_output_armed, oa_calc_over} = i_controls;
    assign frame_complete_i_mode = o_frame_mode_q;
    assign frame_complete_i_active = frame_command_active;
    assign frame_complete_i_eligible = frame_execution_started &&
        (frame_compute_seen || partial_sum_calc_over) &&
        (!frame_exec_final || frame_output_seen || (frame_output_armed && oa_calc_over));
    assign frame_complete_i_store_seen = frame_store_seen;
    assign frame_complete_i_store_complete = ps_frame_complete;
    assign frame_complete_i_output_complete = oa_calc_over;
    assign frame_issue_incomplete = !(frame_complete_i_active && frame_complete_i_eligible &&
        (frame_complete_i_store_seen || frame_complete_i_store_complete));
    assign exec_oa_complete = frame_complete_o_complete;
    npu_frame_complete_select u_frame_complete (
        .i_frame_mode(frame_complete_i_mode), .i_frame_active(frame_complete_i_active),
        .i_frame_eligible(frame_complete_i_eligible),
        .i_store_seen(frame_complete_i_store_seen), .i_store_complete(frame_complete_i_store_complete),
        .i_output_complete(frame_complete_i_output_complete), .o_complete(frame_complete_o_complete)
    );

    assign o_complete = exec_oa_complete;
endmodule
