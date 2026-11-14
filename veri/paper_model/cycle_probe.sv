module python_cycle_probe(input logic clk);
 timeunit 1ns;timeprecision 1ps;
 import "DPI-C" function void py_task_accept();
 import "DPI-C" function void py_capture(input int unsigned lane_count,input int unsigned scalar_values[32],input int unsigned ia_values[16],input int unsigned weight_values[16],input int unsigned acc_values[16],input int unsigned requant_values[16]);
 int unsigned scalars[32];int unsigned ia[16],weight_data[16],acc[16],requant[16];
 always @(posedge clk)begin
  #1ps;
  scalars[0]=$root.tb_npu_top.rst_n;
  scalars[1]=$root.tb_npu_top.calc_start;
  scalars[2]=$root.tb_npu_top.sa_ready;
  scalars[3]=$root.tb_npu_top.done_valid;
  scalars[4]=$root.tb_npu_top.err_code;
  scalars[5]=$root.tb_npu_top.u_dut.u_panel.core_busy;
  scalars[6]=$root.tb_npu_top.u_dut.u_panel.u_core.b_valid_q;
  scalars[7]=$root.tb_npu_top.u_dut.u_panel.acc_data_valid;
  scalars[8]=$root.tb_npu_top.u_dut.u_panel.quant_valid;
  scalars[9]=$root.tb_npu_top.u_dut.u_panel.queue_count==2;
  scalars[10]=$root.tb_npu_top.u_dut.u_panel.acc_row==15 && $root.tb_npu_top.u_dut.u_panel.acc_data_valid;
  scalars[11]={20'b0,$root.tb_npu_top.m_axi_bready,$root.tb_npu_top.m_axi_bvalid,$root.tb_npu_top.m_axi_wlast,$root.tb_npu_top.m_axi_wready,$root.tb_npu_top.m_axi_wvalid,$root.tb_npu_top.m_axi_awready,$root.tb_npu_top.m_axi_awvalid,$root.tb_npu_top.m_axi_rlast,$root.tb_npu_top.m_axi_rready,$root.tb_npu_top.m_axi_rvalid,$root.tb_npu_top.m_axi_arready,$root.tb_npu_top.m_axi_arvalid};
  scalars[12]=$root.tb_npu_top.m_axi_araddr;
  scalars[13]=$root.tb_npu_top.m_axi_arlen;
  scalars[14]=$root.tb_npu_top.m_axi_rdata;
  scalars[15]=$root.tb_npu_top.m_axi_awaddr;
  scalars[16]=$root.tb_npu_top.m_axi_awlen;
  scalars[17]=$root.tb_npu_top.m_axi_wdata;
  scalars[18]=$root.tb_npu_top.m_axi_wstrb;
  scalars[19]=$root.tb_npu_top.u_dut.u_panel.state;
  scalars[20]=$root.tb_npu_top.u_dut.u_panel.frame_committed;
  scalars[21]=$root.tb_npu_top.u_dut.u_panel.frame_launch;
  scalars[22]=$root.tb_npu_top.u_dut.u_panel.core_final;
  scalars[23]=$root.tb_npu_top.u_dut.u_panel.panel_available;
  scalars[24]=$root.tb_npu_top.u_dut.u_panel.fifo_valid;
  scalars[25]=$root.tb_npu_top.u_dut.u_panel.fifo_ready;
  scalars[26]=$root.tb_npu_top.u_dut.u_panel.u_cache.read_done && !$root.tb_npu_top.u_dut.u_panel.u_cache.read_b;
  scalars[27]=$root.tb_npu_top.u_dut.u_panel.u_cache.read_done && $root.tb_npu_top.u_dut.u_panel.u_cache.read_b;
  scalars[28]=$root.tb_npu_top.u_dut.u_panel.wr_done;
  scalars[29]=$root.tb_npu_top.cfg[8][0];
  scalars[30]=0;
  scalars[31]=0;
  for(int i=0;i<16;i++)begin
   ia[i]=$signed($root.tb_npu_top.u_dut.u_panel.u_core.array_a[i]);weight_data[i]=$signed($root.tb_npu_top.u_dut.u_panel.u_core.weight_vec[i]);acc[i]=$signed($root.tb_npu_top.u_dut.u_panel.acc_data_out[i]);requant[i]=$signed($root.tb_npu_top.u_dut.u_panel.quant_data[i]);
  end
  if($root.tb_npu_top.u_dut.u_panel.state==1)py_task_accept();
  py_capture(16,scalars,ia,weight_data,acc,requant);
 end
endmodule
bind tb_npu_top python_cycle_probe u_python_probe(.clk(clk));
