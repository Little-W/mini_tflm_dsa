`timescale 1ns/1ps
module kernel_pending #(
    parameter int BUS_WIDTH = 64,
    parameter int COUNT_WIDTH = 29
) (
    input logic clk,requested_rst_n,request_init_cfg,cfg_command_mode_request,cache_flush,
    input logic prefetch_valid,
    input logic [31:0] prefetch_base_addr,prefetch_p0,prefetch_q0,prefetch_rows,prefetch_valid_cols,
    input logic cfg_im2col, cfg_tile_packed,
    input logic [31:0] cfg_p0_base,cfg_q0_base,
    input logic load_weight_granted,send_weight_trigger,
    input logic [31:0] k,n,m,rhs_base,rhs_row_stride_b,
    input logic signed [31:0] rhs_zp,
    input logic use_16bits,
    input logic [31:0] ia_reuse_num,w_reuse_num,row_groups,row_tail_tiles,col_groups,col_tail_tiles,
    output logic prefetch_idle,load_weight_req,
    output logic ext_dma_start,ext_dma_is_write,ext_dma_linear_read_mode,ext_dma_im2col,
    output logic [31:0] ext_dma_p0,ext_dma_q0,ext_dma_group,ext_dma_base_addr,ext_dma_row_stride,ext_dma_rows_to_read,
    output logic [7:0] ext_dma_burst_len_m1,
    output logic ext_dma_slot_id,ext_dma_use_16bits,
    output logic signed [31:0] ext_dma_lhs_zp,
    input logic request_done, response_slot,
    input logic [3:0] ext_dma_wr_row,ext_dma_wr_col_base,
    input logic signed [15:0] ext_dma_wr_data [BUS_WIDTH/8],
    input logic ext_dma_wr_valid [BUS_WIDTH/8],
    output logic weight_sending_done,load_weight_done,store_weight_req,weight_data_valid,
    output logic signed [15:0] weight_out [16],
    output wire [1:0] dbg_top_state,dbg_ctrl_state,dbg_prefetch_state,dbg_valid_count,
    output wire dbg_transfer_active,dbg_transfer_prefetch,dbg_transfer_discard,
    output wire dbg_prefetch_capture,dbg_prefetch_start,dbg_cache_hit,dbg_discard,
    output wire dbg_load_commit,dbg_buf_send_start,dbg_load_busy,dbg_raw_done,
    output wire dbg_window_open,dbg_demand_confirmed,dbg_managed_mode,dbg_tile_packed,
    output wire [31:0] dbg_dma_valid_cols,
    output wire [47:0] dbg_loaded_count,dbg_sent_count,
    output wire [15:0] dbg_ram_write_en,dbg_ram_read_en,
    output logic bounds, relation, event_relation,
    output wire [47:0] relation_flags,
    output logic [1:0] logical_slots, logical_loading,
    output wire [3*COUNT_WIDTH-1:0] pending_loads, pending_sends,
    output logic [1:0] dma_pending
);
    logic init_cfg;
    assign init_cfg = request_init_cfg && dut.top_state == 0 && logical_slots == 0 &&
        logical_loading == 0 && !dut.u_buf.send_active && !dut.u_buf.send_pending &&
        !dut.u_buf.send_prefetch && !dut.buf_weight_sending_done && !dut.weight_sending_done;
    logic initial_cycle = 1'b1;
    logic rst_n;
    always_ff @(posedge clk) initial_cycle <= 1'b0;
    assign rst_n = requested_rst_n && !initial_cycle;
    logic cfg_command_mode, command_mode_saved, command_mode_seen;
    assign cfg_command_mode = command_mode_seen ? command_mode_saved : cfg_command_mode_request;
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) command_mode_seen <= 1'b0;
        else if (init_cfg) begin
            command_mode_seen <= 1'b1;
            command_mode_saved <= cfg_command_mode;
        end
    end
    logic ext_dma_busy, ext_dma_done, ext_dma_wr_slot;
    assign ext_dma_done = request_done && dma_pending[response_slot];
    assign ext_dma_wr_slot = response_slot;
    assign ext_dma_busy = |dma_pending;
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) dma_pending <= '0;
        else begin
            if (ext_dma_done) dma_pending[response_slot] <= 1'b0;
            if (ext_dma_start) dma_pending[ext_dma_slot_id] <= 1'b1;
        end
    end
    logic issue_slot, prefetch_slot_q, cache_hit_slot_q, demand_slot_q;
    logic queue_head;
    assign queue_head = dut.u_buf.rd_slot ^ (dut.u_buf.send_active || dut.u_buf.send_prefetch);
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush) begin
            demand_slot_q <= 1'b0;
            prefetch_slot_q <= 1'b0;
            cache_hit_slot_q <= 1'b0;
        end else begin
            if (dut.demand_dma_start || dut.cache_hit_fire) demand_slot_q <= issue_slot;
            if (dut.prefetch_dma_start) prefetch_slot_q <= dut.buf_load_slot;
            if (dut.cache_hit_fire) cache_hit_slot_q <= prefetch_slot_q;
        end
    end
    logic [3:0] storage_objects;
    assign issue_slot = dut.cache_hit_fire ? prefetch_slot_q : dut.buf_load_slot;
    always_ff @(posedge clk) begin
        if (!rst_n || cache_flush || (dut.u_ctrl.state == 0 && dut.cfg_valid)) begin
            logical_slots <= '0;
            logical_loading <= '0;
        end else begin
            if (dut.u_buf.send_pending) logical_slots[dut.u_buf.rd_slot] <= 1'b0;
            if (dut.dma_done) logical_loading[dut.cache_hit_done ? cache_hit_slot_q : ext_dma_wr_slot] <= 1'b0;
            if (dut.ctrl_dma_start) begin
                logical_slots[issue_slot] <= 1'b1;
                logical_loading[issue_slot] <= 1'b1;
            end
        end
    end
    assign storage_objects = 4'(logical_slots[0]) + 4'(logical_slots[1]) +
        4'(dut.u_buf.send_active || dut.u_buf.send_prefetch) +
        4'(dut.buf_weight_sending_done) + 4'(dut.weight_sending_done);
    assign relation_flags[0] = !rst_n || ((dma_pending & ~dut.u_buf.slot_reserved) == 0);
    assign relation_flags[1] = !rst_n || ((dma_pending & ~dut.response_slots_active) == 0);
    assign relation_flags[2] = !rst_n || ((dut.u_buf.slot_loaded & ~dut.u_buf.slot_reserved) == 0);
    assign relation_flags[3] = !rst_n || ((dut.u_buf.slot_loaded & dma_pending) == 0);
    assign relation_flags[4] = !rst_n || ((!dut.u_buf.load_done_q || (dut.u_buf.slot_reserved[dut.u_buf.done_slot_q] && !dma_pending[dut.u_buf.done_slot_q])));
    assign relation_flags[5] = !rst_n || ((!dut.u_buf.send_pending || dut.u_buf.slot_reserved[dut.u_buf.rd_slot]));
    assign relation_flags[6] = !rst_n || ((4'(dut.u_buf.send_active) + 4'(dut.u_buf.send_prefetch) + 4'(dut.buf_weight_sending_done) + 4'(dut.weight_sending_done)) <= 1);
    assign relation_flags[7] = !rst_n || ((4'(dut.u_buf.send_active) + 4'(dut.u_buf.send_prefetch) + 4'(dut.u_buf.send_pending)) <= 1);
    assign relation_flags[8] = !rst_n || ((dut.u_ctrl.state != 1 || (pending_loads == 0 && pending_sends == 0 && logical_slots == 0 && logical_loading == 0 &&
            !dut.u_buf.send_active && !dut.u_buf.send_pending && !dut.u_buf.send_prefetch && !dut.buf_weight_sending_done && !dut.weight_sending_done)));
    assign relation_flags[9] = !rst_n || ((dut.u_ctrl.state != 2 || (pending_loads == (3*COUNT_WIDTH)'(logical_loading[0]) + (3*COUNT_WIDTH)'(logical_loading[1]))));
    assign relation_flags[10] = !rst_n || ((dut.u_ctrl.state != 2 || (pending_sends == (3*COUNT_WIDTH)'(storage_objects))));
    assign relation_flags[11] = !rst_n || ((((logical_slots & ~dut.u_buf.slot_reserved) == 0)));
    assign relation_flags[12] = !rst_n || ((((logical_loading & ~logical_slots) == 0)));
    assign relation_flags[13] = !rst_n || (((logical_loading == ((dma_pending & logical_slots) |
                (dut.cache_hit_done ? (2'b01 << cache_hit_slot_q) : 2'b00)))));
    assign relation_flags[14] = !rst_n || ((((!dut.cache_hit_done || (logical_slots[cache_hit_slot_q] && dut.u_buf.slot_loaded[cache_hit_slot_q])))));
    assign relation_flags[15] = !rst_n || (!dut.managed_mode || (dma_pending != 2'b11 &&
        (dma_pending == 0 || (dut.transfer_active && !dut.transfer_discard &&
            (dut.transfer_prefetch ? ((logical_slots & dma_pending) == 0) :
             ((logical_slots & dma_pending) == dma_pending))))));
    assign relation_flags[16] = !rst_n || ((((!dut.u_buf.send_pending || logical_slots[dut.u_buf.rd_slot]))));
    assign relation_flags[17] = !rst_n || ((((!dut.u_buf.send_fire || logical_slots[dut.u_buf.rd_slot]))));
    assign relation_flags[18] = !rst_n || ((((!dut.discard_fire || !logical_slots[dut.u_buf.rd_slot]))));
    assign relation_flags[19] = !rst_n || ((((!dut.dma_done || logical_loading[dut.cache_hit_done ? cache_hit_slot_q : ext_dma_wr_slot]))));
    assign relation_flags[20] = !rst_n || ((((!dut.ctrl_dma_start || !logical_slots[issue_slot]))));
    assign relation_flags[21] = !rst_n || (!command_mode_seen || dut.command_mode_q == command_mode_saved);
    assign relation_flags[22] = !rst_n || (command_mode_seen || (!dut.command_mode_q && logical_slots == 0 && logical_loading == 0));
    assign relation_flags[23] = !rst_n || (dut.prefetch_state == 0 || (command_mode_seen && command_mode_saved));
    assign relation_flags[24] = !rst_n || ((dut.u_buf.slot_reserved & ~logical_slots) ==
        ((dut.prefetch_state == 2 || dut.prefetch_state == 3) ? (2'b01 << prefetch_slot_q) : 2'b00));
    assign relation_flags[25] = !rst_n || (!dut.demand_confirmed || logical_slots[demand_slot_q]);
    assign relation_flags[26] = !rst_n || (!dut.managed_mode || !dut.demand_confirmed || !dut.buf_weight_data_valid || demand_slot_q == dut.u_buf.rd_slot);
    assign relation_flags[27] = !rst_n || (!dut.cache_hit_done || (dma_pending == 0 &&
        dut.demand_confirmed && !dut.transfer_active && dut.prefetch_state == 0 && dut.u_ctrl.state == 2));
    assign relation_flags[28] = !rst_n || (dut.u_buf.wr_slot == (queue_head ^ (^dut.u_buf.slot_reserved)));
    assign relation_flags[29] = !rst_n || (dut.u_buf.slot_reserved == 0 || dut.u_buf.slot_reserved[queue_head]);
    assign relation_flags[30] = !rst_n || (!dut.managed_mode || !dut.demand_confirmed ||
        (logical_slots == (2'b01 << demand_slot_q) && demand_slot_q == queue_head));
    assign relation_flags[31] = !rst_n || (!dut.managed_mode || dut.demand_confirmed ||
        logical_slots == (dut.u_buf.send_pending ? (2'b01 << dut.u_buf.rd_slot) : 2'b00));
    assign relation_flags[32] = !rst_n || dut.top_state != 3;
    assign relation_flags[33] = !rst_n || dut.u_ctrl.state != 2 || dut.top_state == 2;
    assign relation_flags[34] = !rst_n || dut.top_state != 1 || dut.u_ctrl.state == 0 || dut.u_ctrl.state == 3;
    assign relation_flags[35] = !rst_n || !dut.cfg_valid || dut.top_state == 2;
    assign relation_flags[36] = !rst_n || dut.prefetch_state != 2 ||
        (dma_pending[prefetch_slot_q] || (dut.u_buf.load_done_q && dut.u_buf.done_slot_q == prefetch_slot_q) ||
         (dut.buf_load_commit && dut.u_buf.load_commit_slot == prefetch_slot_q));
    assign relation_flags[37] = !rst_n || dut.prefetch_state != 3 || dut.u_buf.slot_loaded[prefetch_slot_q];
    assign relation_flags[38] = !rst_n || !dut.managed_mode || !dut.transfer_active || dut.transfer_discard || !dut.transfer_prefetch ||
        (dut.prefetch_state == 2 && (dma_pending == (2'b01 << prefetch_slot_q) ||
         (dma_pending == 0 && ((dut.u_buf.load_done_q && dut.u_buf.done_slot_q == prefetch_slot_q) ||
          (dut.buf_load_commit && dut.u_buf.load_commit_slot == prefetch_slot_q)))));
    assign relation_flags[39] = !rst_n || !dut.managed_mode || !dut.transfer_active || dut.transfer_discard || dut.transfer_prefetch ||
        (dut.demand_confirmed && (dma_pending == (2'b01 << demand_slot_q) ||
         (dma_pending == 0 && ((dut.u_buf.load_done_q && dut.u_buf.done_slot_q == demand_slot_q) ||
          (dut.buf_load_commit && dut.u_buf.load_commit_slot == demand_slot_q)))));
    assign relation_flags[40] = !rst_n || !dut.u_ctrl.all_loads_done || dut.u_ctrl.all_loads_issued;
    assign relation_flags[41] = !rst_n || dut.u_ctrl.state != 3 || (dut.u_ctrl.all_loads_done && dut.u_ctrl.all_loads_issued);
    assign relation_flags[42] = !rst_n || (dut.prefetch_state != 2 && dut.prefetch_state != 3) || !dut.transfer_discard;
    assign relation_flags[43] = !rst_n || !dut.cache_hit_done || !dut.transfer_discard;
    assign relation_flags[44] = !rst_n || dut.prefetch_state != 3 || !dut.transfer_active;
    assign relation_flags[45] = !rst_n || command_mode_seen || (dut.top_state == 0 && dut.u_ctrl.state == 0);
    assign relation_flags[46] = !rst_n || !dut.buf_load_commit ||
        (dut.u_buf.slot_reserved[dut.buf_load_commit_slot] &&
         dut.u_buf.slot_loaded[dut.buf_load_commit_slot] && !dma_pending[dut.buf_load_commit_slot]);
    assign relation_flags[47] = !rst_n || !dut.transfer_active || command_mode_seen || dut.transfer_discard;
    assign relation = &relation_flags;
    assign pending_loads = dut.u_ctrl.issued_count - dut.u_ctrl.loaded_count;
    assign pending_sends = dut.u_ctrl.issued_count - dut.u_ctrl.sent_count;
    assign bounds = !rst_n || dut.u_ctrl.state != 2'd2 ||
        (pending_loads <= 2 && pending_sends <= 3 && pending_loads <= pending_sends);
    assign event_relation = !rst_n || cache_flush || dut.u_ctrl.state != 2 || (
        (!dut.ctrl_dma_start || (pending_loads < 2 && pending_sends < 3)) &&
        (!dut.dma_done || pending_loads != 0) &&
        (!dut.weight_sending_done || pending_sends > pending_loads));
    logic o_prefetch_quiescent;
    kernel_loader #(.DATA_WIDTH(16),.SIZE(16),.BUS_WIDTH(BUS_WIDTH),.REG_WIDTH(32),.COUNT_WIDTH(COUNT_WIDTH)) dut (.*);
    assign dbg_top_state=dut.top_state;
    assign dbg_ctrl_state=dut.u_ctrl.state;
    assign dbg_prefetch_state=dut.prefetch_state;
    assign dbg_valid_count={1'b0,dut.u_buf.slot_loaded[0]}+{1'b0,dut.u_buf.slot_loaded[1]};
    assign dbg_transfer_active=dut.transfer_active;
    assign dbg_transfer_prefetch=dut.transfer_prefetch;
    assign dbg_transfer_discard=dut.transfer_discard;
    assign dbg_prefetch_capture=dut.prefetch_capture;
    assign dbg_prefetch_start=dut.prefetch_dma_start;
    assign dbg_cache_hit=dut.cache_hit_fire;
    assign dbg_discard=dut.discard_fire;
    assign dbg_load_commit=dut.buf_load_commit;
    assign dbg_buf_send_start=dut.buf_send_start;
    assign dbg_load_busy=|dut.response_slots_active;
    assign dbg_raw_done=dut.raw_dma_done;
    assign dbg_window_open=dut.prefetch_window_open;
    assign dbg_demand_confirmed=dut.demand_confirmed;
    assign dbg_managed_mode=dut.managed_mode;
    assign dbg_tile_packed=dut.port_descriptor.tile_packed;
    assign dbg_dma_valid_cols=dut.port_descriptor.cols;
    assign dbg_loaded_count=dut.u_ctrl.loaded_count;
    assign dbg_sent_count=dut.u_ctrl.sent_count;
    for(genvar bank=0;bank<16;bank=bank+1) begin : g_monitor
        assign dbg_ram_write_en[bank]=dut.u_buf.column_i_wr_en;
        assign dbg_ram_read_en[bank]=dut.u_buf.emit_fire && !cache_flush;
    end
endmodule
