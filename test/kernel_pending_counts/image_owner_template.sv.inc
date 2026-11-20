module image_ownership #(
 parameter int DATA_WIDTH=16, SIZE=64, BUS_WIDTH=64, REG_WIDTH=32, CACHE_BLOCKS=64, RD_TAG_WIDTH=3, IM2COL_SIZE=16
)(input logic clk,requested_rst_n,abort,rd_start,rd_im2col,conv_cfg_valid,conv_enable,dma_range_enable,
 input logic linear_busy,linear_done,linear_finish,linear_start_ready,fe_busy,win_busy,guard_idle,mux_idle,
 input logic fe_cfg_ready,fe_tile_ready,fe_done,fe_tile_error,fe_error,
 input logic [RD_TAG_WIDTH-1:0] rd_tag,
 input logic [$clog2(CACHE_BLOCKS)-1:0] rd_slot_id,
 input logic [31:0] rd_p0,rd_q0,rd_group,rd_rows_to_read,rd_valid_cols,
 output logic relation);
 localparam int SLOT_W=$clog2(CACHE_BLOCKS),CONV_RW=$clog2(IM2COL_SIZE+1);
 localparam bit CONV_SUPPORTED = DATA_WIDTH >= 16 && (BUS_WIDTH == 32 || BUS_WIDTH == 64) && REG_WIDTH == 32 && IM2COL_SIZE <= SIZE;
 logic initial_cycle=1'b1; logic rst_n;
 always_ff @(posedge clk) initial_cycle<=1'b0;
 assign rst_n=requested_rst_n&&!initial_cycle;
 logic job_conv,job_read_guard,cfg_fire,conv_cfg_ready;
 logic conv_active,conv_pending,conv_finished,conv_command_error;
 logic conv_done_r,conv_done_error,descriptor_error,command_im2col;
 logic [RD_TAG_WIDTH-1:0] conv_tag_q;
 logic [31:0] p0_q,q0_q,group_q;
 logic [CONV_RW-1:0] rows_q,cols_q;
 logic [SLOT_W-1:0] slot_q;
 logic accept_read,accept_linear,accept_image,image_start_ready;
 logic rd_busy,rd_done,rd_finish_beat,rd_start_ready;
 assign conv_cfg_ready=!rd_busy&&!rd_done&&fe_cfg_ready;
 assign cfg_fire=conv_cfg_valid&&conv_cfg_ready;
@@CONTROL@@
 // 卷积任务的仲裁仅在已有读事务全部结束后发出下一个描述符。
 always_comb if(rst_n) assume(!conv_active || !linear_finish);
 logic [1:0] pending_images;
 logic [SLOT_W-1:0] owner_slot;
 logic [RD_TAG_WIDTH-1:0] owner_tag;
 always_ff @(posedge clk) begin
  if(!rst_n) begin pending_images<='0;owner_slot<='0;owner_tag<='0;end
  else begin
   case({accept_image,conv_done_r})
    2'b10:pending_images<=pending_images+1'b1;
    2'b01:pending_images<=pending_images-1'b1;
    default:;
   endcase
   if(accept_image) begin owner_slot<=rd_slot_id;owner_tag<=rd_tag;end
  end
 end
 assign relation=!rst_n || (pending_images<=1 && pending_images==(2'(conv_active)+2'(conv_done_r)) &&
   (!accept_image || !conv_active) &&
   (!(conv_active || conv_done_r) || (owner_slot==slot_q && owner_tag==conv_tag_q)));
endmodule
