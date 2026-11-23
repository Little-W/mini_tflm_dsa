// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
`ifndef TB_SIZE
`define TB_SIZE 4
`endif
`ifndef TB_BUS_WIDTH
`define TB_BUS_WIDTH 32
`endif
`ifndef TB_NPU_ADDR_WIDTH
`define TB_NPU_ADDR_WIDTH 19
`endif
`ifndef TB_VECTOR_PE_COUNT
`define TB_VECTOR_PE_COUNT ((`TB_SIZE < 16) ? `TB_SIZE : 16)
`endif
`ifndef TB_READ_BEAT_CYCLES
`define TB_READ_BEAT_CYCLES 1
`endif
`ifndef TB_READ_FIRST_LATENCY
`define TB_READ_FIRST_LATENCY 8
`endif
`ifndef TB_PIPELINED_READ
`define TB_PIPELINED_READ 1
`endif
`ifndef TB_DMA_MAX_BYTES
`define TB_DMA_MAX_BYTES (256*(`TB_BUS_WIDTH/8))
`endif
`ifndef TB_CONV_CACHE_SETS
`define TB_CONV_CACHE_SETS 32
`endif
`ifndef TB_CONV_LINE_BYTES
`define TB_CONV_LINE_BYTES 16
`endif
`ifndef TB_CONV_CACHE_POLICY
`define TB_CONV_CACHE_POLICY 2
`endif
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 4
`endif
`ifndef TB_SHARED_BANK_BYTES
`define TB_SHARED_BANK_BYTES 2048
`endif
`ifndef TB_SHARED_BANK_COUNT
`define TB_SHARED_BANK_COUNT 0
`endif
`ifndef TB_PS_STORAGE_ROWS
`define TB_PS_STORAGE_ROWS 0
`endif
`ifndef TB_PS_FRAME_COUNT
`define TB_PS_FRAME_COUNT 16
`endif
`ifndef TB_OA_S16_FIFO_BANKS_MAX
`define TB_OA_S16_FIFO_BANKS_MAX 0
`endif
module tb_conv_npu;
    import conv_im2col_pkg::*;
    localparam int SIZE=`TB_SIZE;
    localparam int WORDS=131072;
    logic clk=0;
    always #5 clk=~clk;
    logic rst_n=0,calc_start=0,done_ready=0,new_job=0;
    wire sa_ready,done_valid;
    wire [1:0] err_code;
    logic [31:0] cfg[64], saved_cfg[64],golden[WORDS];
    logic [31:0] initial_reference[WORDS];
    logic [31:0] accumulator_reference[WORDS];
    conv_cfg_t conv_cfg;
    wire [31:0] hits,misses,conv_bytes,conv_cycles;
    longint unsigned cycle=0;
    longint unsigned ps_observer_job=0;
    wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    always @(posedge clk) if(rst_n && calc_start && sa_ready) ps_observer_job <= ps_observer_job + 1;
    always @(posedge clk)if(rst_n)cycle<=cycle+1;
    integer debug_events=0;
    integer padding_reads=0;
    integer ia_im2col_commands=0,kernel_im2col_commands=0;
    integer ar_stall_cycles=0,r_wait_cycles=0;
    integer accumulator_checks=0;
    integer accumulator_row_base=0,accumulator_col_base=0;
    integer accumulator_row_offset=0,accumulator_col_tile=0;
    typedef struct packed {
        logic [SIZE-1:0] lane_valid;
        logic [SIZE-1:0][31:0] data;
        logic [SIZE-1:0][31:0] index;
        logic [31:0] row;
        logic tile_done;
        logic [63:0] captured_cycle;
    } accumulator_row_t;
    accumulator_row_t expected_accumulator_rows[$];
    wire accumulator_clear = !u_dut.core_rst_n ||
        u_dut.u_matrix_engine.u_output_pipeline.i_exec_init_requant ||
        u_dut.u_matrix_engine.u_output_pipeline.i_ps_capacity_fault;
    integer ps_blocked_cycles=0;
    integer ps_committed_rows=0,ps_raw_records=0,ps_payload_words=0;
    wire ps_encode_valid;
    wire [2:0] ps_encode_opcode,ps_encode_words;
    bit capacity_injected=0;
    bit late_error_active=0,late_error_seen=0;
`ifdef GEMPACT_PS_COMPRESS
    localparam int SHARED_TEST_BYTES = `TB_SHARED_BANK_COUNT != 0 ?
        `TB_SHARED_BANK_COUNT * `TB_SHARED_BANK_BYTES :
        `TB_IA_CACHE_BLOCKS * SIZE * SIZE * 2 + `GEMMORA_PS_POOL_BYTES;
    localparam bit PS_MONITOR_SHARED = SIZE == 16 &&
        (`TB_BUS_WIDTH == 32 || `TB_BUS_WIDTH == 64) &&
        (`TB_SHARED_BANK_BYTES == 2048 || `TB_SHARED_BANK_BYTES == 4096 || `TB_SHARED_BANK_BYTES == 8192) &&
        SHARED_TEST_BYTES >= 6 * `TB_SHARED_BANK_BYTES &&
        SHARED_TEST_BYTES <= 9 * `TB_SHARED_BANK_BYTES &&
        SHARED_TEST_BYTES % `TB_SHARED_BANK_BYTES == 0;
    localparam int PS_MONITOR_BANKS = PS_MONITOR_SHARED ? SHARED_TEST_BYTES / `TB_SHARED_BANK_BYTES - 1 : 4;
    localparam int PS_MONITOR_IA_BANKS = SHARED_TEST_BYTES / `TB_SHARED_BANK_BYTES >= 8 ? 4 : 2;
`ifdef TB_IA_COMPACT_ENABLE
    localparam int PS_MONITOR_IA_DIVISOR = `TB_IA_COMPACT_ENABLE != 0 ? 1 : 2;
`else
    localparam int PS_MONITOR_IA_DIVISOR = 1;
`endif
    localparam int PS_MONITOR_ROWS = (PS_MONITOR_SHARED ?
        PS_MONITOR_IA_BANKS * `TB_SHARED_BANK_BYTES / (SIZE * SIZE * 2) : `TB_IA_CACHE_BLOCKS) * SIZE / PS_MONITOR_IA_DIVISOR;
    generate if(SIZE==16)begin : g_ps_monitor
        initial begin
            assert (PS_MONITOR_SHARED == u_dut.SHARED_RAM_ENABLED &&
                    PS_MONITOR_ROWS == u_dut.u_matrix_engine.IA_REUSE_NUM_MAX * SIZE &&
                    PS_MONITOR_BANKS == u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.BANKS)
                else $fatal(1,"PS monitor dimensions differ from the configured NPU");
        end
        always @(posedge clk) if(rst_n && u_dut.cfg_stage2_fire)
            $display("PS_WINDOW_SELECT task=%0d micro=%0d cap=%0d force_raw=%0d raw_fits=%0d long_fits=%0d bound24=%0d rows=%0d frames=%0d bank_reserve=%0d retained_k=%0d product_exp=%0d",
                ps_observer_job,u_dut.u_matrix_engine.use_frame_commands_s2,u_dut.u_matrix_engine.u_task_configuration.ps_config_word_cap,
                u_dut.u_matrix_engine.u_task_configuration.ps_config_force_raw,u_dut.u_matrix_engine.u_task_configuration.ps_raw_capacity_fits,u_dut.u_matrix_engine.u_task_configuration.ps_long_capacity_fits,
                u_dut.u_matrix_engine.u_task_configuration.ps_s24_bound_s2,u_dut.u_matrix_engine.u_task_configuration.ps_max_frame_rows,u_dut.u_matrix_engine.u_task_configuration.ps_live_frames,
                u_dut.u_matrix_engine.u_task_configuration.ps_long_frame_bank_words,u_dut.u_matrix_engine.u_task_configuration.ps_retained_k_s2,u_dut.u_matrix_engine.u_task_configuration.ps_product_exp_s2);
        assign ps_encode_valid=u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.encode_commit_valid;
        assign ps_encode_opcode=u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.tb_observer.encode_commit_opcode;
        assign ps_encode_words=u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.tb_observer.encode_commit_words;
        initial if($test$plusargs("FORCE_PS_CODEC"))force u_dut.u_matrix_engine.u_task_configuration.ps_config_force_raw=1'b0;
        logic [31:0] occupied_payload_bytes;
        always_comb begin
            occupied_payload_bytes = 0;
            for (int bank = 0; bank < PS_MONITOR_BANKS; bank++) begin
                if (bank < u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.pool_bank_count_q)
                    occupied_payload_bytes += 16 *
                        (32'(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.pool_bank_words_q) -
                         32'(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.tb_observer.bank_free_count[bank]));
            end
        end
    ps_stream_capture #(
        .MAX_FRAME_ROWS(PS_MONITOR_ROWS),
        .PAYLOAD_BANKS(PS_MONITOR_BANKS)
    ) u_ps_capture (
        .clk(clk), .rst_n(u_dut.core_rst_n),
        .cycle(cycle), .job(ps_observer_job),
        .write_valid(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.encoder_start), .write_data(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.write_data),
        .frame_accept(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.frame_accept), .frame_complete(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.complete_now),
        .frame_id(32'(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.frame_id)), .frame_rows(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.frame_rows),
        .frame_init(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.frame_init), .frame_final(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.frame_final),
        .replay_valid(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.replay_valid), .replay_data(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.replay_data),
        .payload_write_en(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.payload_ram_write_en),
        .payload_read_en(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.payload_ram_read_en),
        .decoded_write_en(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.decoded_write_en),
        .decoded_read_en(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.decoded_read_en), .replay_bypass(u_dut.u_matrix_engine.u_compute_core.u_ps_buffer.g_compressed.u_store.replay_bypass),
        .occupied_payload_bytes(occupied_payload_bytes)
    );

    end else begin : g_small_ps_monitor
        assign ps_encode_valid=1'b0;
        assign ps_encode_opcode='0;
        assign ps_encode_words='0;
    end endgenerate
`else
    assign ps_encode_valid=1'b0;
    assign ps_encode_opcode='0;
    assign ps_encode_words='0;
`endif
    always @(posedge clk) begin : check_accumulators
        integer stream_rows,stream_cols,group_rows,group_cols;
        integer logical_row,logical_col,index;
        accumulator_row_t captured_row, expected_row;
        if(!rst_n || new_job)begin
            accumulator_checks=0;
            expected_accumulator_rows.delete();
            accumulator_row_base=0;accumulator_col_base=0;
            accumulator_row_offset=0;accumulator_col_tile=0;
            ps_blocked_cycles=0;
            ps_committed_rows=0;ps_raw_records=0;ps_payload_words=0;
        end else begin
            if (accumulator_clear) expected_accumulator_rows.delete();
            if(u_dut.u_matrix_engine.frame_command_start)accumulator_row_offset=0;
            if(ps_encode_valid)begin
                ps_committed_rows++;
                ps_payload_words+=int'(ps_encode_words);
                if(ps_encode_opcode==3)ps_raw_records++;
            end
            if(u_dut.u_matrix_engine.u_npu_controller.current_state==3 && u_dut.u_matrix_engine.ia_data_valid &&
               u_dut.u_matrix_engine.u_npu_controller.bias_ready_for_compute && u_dut.u_matrix_engine.quant_params_valid &&
               !(u_dut.u_matrix_engine.fifo_full_flag && u_dut.u_matrix_engine.ia_output_pending) && !u_dut.u_matrix_engine.ia_sending_done &&
               !u_dut.u_matrix_engine.oa_calc_over && !u_dut.u_matrix_engine.ps_frame_ready)ps_blocked_cycles++;
            if(saved_cfg[52]==0 && u_dut.u_matrix_engine.acc_data_valid && !accumulator_clear)begin
                captured_row = '0;
                captured_row.tile_done = u_dut.u_matrix_engine.u_output_pipeline.i_tile_calc_over;
                captured_row.captured_cycle = cycle;
                stream_rows=int'(u_dut.is_mode?saved_cfg[5]:saved_cfg[3]);
                stream_cols=int'(u_dut.is_mode?saved_cfg[3]:saved_cfg[5]);
                group_rows=int'(saved_cfg[6])*SIZE;
                if(group_rows>stream_rows-accumulator_row_base)group_rows=stream_rows-accumulator_row_base;
                group_cols=(stream_cols-accumulator_col_base+SIZE-1)/SIZE;
                if(group_cols>int'(saved_cfg[7]))group_cols=int'(saved_cfg[7]);
                logical_row=accumulator_row_base+accumulator_row_offset;
                if(u_dut.frame_mode_q)begin
                    group_rows=int'(u_dut.u_matrix_engine.frame_command_rows);
                    group_cols=1;
                    logical_row=int'(u_dut.u_matrix_engine.frame_command_p0)+accumulator_row_offset;
                end
                assert(group_rows>0 && group_cols>0 && logical_row<stream_rows)
                    else $fatal(1,"unexpected accumulator row");
                for(int lane=0;lane<SIZE;lane++)begin
                    logical_col=accumulator_col_base+accumulator_col_tile*SIZE+lane;
                    if(u_dut.frame_mode_q)logical_col=int'(u_dut.u_matrix_engine.frame_command_column)+lane;
                    if(logical_col<stream_cols)begin
                        index=u_dut.is_mode ? logical_col*int'(saved_cfg[5])+logical_row :
                                                     logical_row*int'(saved_cfg[5])+logical_col;
                        captured_row.lane_valid[lane] = 1'b1;
                        captured_row.data[lane] = accumulator_reference[index];
                        captured_row.index[lane] = 32'(index);
                    end
                end
                captured_row.row = 32'(logical_row);
                expected_accumulator_rows.push_back(captured_row);
                accumulator_row_offset++;
                if(!u_dut.frame_mode_q && accumulator_row_offset==group_rows)begin
                    accumulator_row_offset=0;
                    accumulator_col_tile++;
                    if(accumulator_col_tile==group_cols)begin
                        accumulator_col_tile=0;
                        accumulator_col_base+=int'(saved_cfg[7])*SIZE;
                        if(accumulator_col_base>=stream_cols)begin
                            accumulator_col_base=0;
                            accumulator_row_base+=group_rows;
                        end
                    end
                end
            end
            if (saved_cfg[52]==0 && u_dut.u_matrix_engine.u_output_pipeline.u_vec_requant.in_valid) begin
                assert (!accumulator_clear && expected_accumulator_rows.size()>0)
                    else $fatal(1,"requant input without a captured accumulator row");
                expected_row = expected_accumulator_rows.pop_front();
                assert (cycle <= expected_row.captured_cycle + 1)
                    else $fatal(1,"accumulator output latency exceeded one cycle");
                assert (u_dut.u_matrix_engine.u_output_pipeline.u_vec_requant.in_tile_done === expected_row.tile_done)
                    else $fatal(1,"accumulator tile marker differs");
                for (int lane=0; lane<SIZE; lane++) begin
                    if (expected_row.lane_valid[lane]) begin
                        assert (u_dut.u_matrix_engine.u_output_pipeline.requant_in_vec[lane] === expected_row.data[lane])
                            else $fatal(1,"INT32 accumulator differs row=%0d lane=%0d index=%0d actual=%0d expected=%0d",
                                expected_row.row,lane,expected_row.index[lane],
                                $signed(u_dut.u_matrix_engine.u_output_pipeline.requant_in_vec[lane]),
                                $signed(expected_row.data[lane]));
                        accumulator_checks++;
                    end
                end
            end
            assert (expected_accumulator_rows.size() <= 1)
                else $fatal(1,"accumulator pipeline retained more than one row");
        end
    end
    always @(posedge clk)if(rst_n && $test$plusargs("FRAME_TRACE"))begin
        if(u_dut.u_matrix_engine.frame_command_start)
            $display("FRAME_START cycle=%0d id=%0d p0=%0d q0=%0d c0=%0d rows=%0d cols=%0d k=%0d init=%0d final=%0d",cycle,
                u_dut.u_matrix_engine.frame_command_id,u_dut.u_matrix_engine.frame_command_p0,u_dut.u_matrix_engine.frame_command_q0,u_dut.u_matrix_engine.frame_command_column,
                u_dut.u_matrix_engine.frame_command_rows,u_dut.u_matrix_engine.frame_command_cols,u_dut.u_matrix_engine.frame_command_k,
                u_dut.u_matrix_engine.frame_command_init,u_dut.u_matrix_engine.frame_command_final);
        if(u_dut.frame_mode_q && u_dut.inner_done_valid)
            $display("FRAME_DONE cycle=%0d error=%0d",cycle,u_dut.inner_err_code);
    end
    always @(posedge clk)begin
        if(!rst_n || new_job)begin
            padding_reads=0;ia_im2col_commands=0;kernel_im2col_commands=0;
            ar_stall_cycles=0;r_wait_cycles=0;
        end else begin
            if(u_dut.u_block_dma_arbiter.u_dma.fe_arvalid &&
               u_dut.u_block_dma_arbiter.u_dma.fe_arready &&
               u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.pad_q)padding_reads++;
            if(u_dut.ia_dma_start && u_dut.ia_dma_im2col)begin
                assert(saved_cfg[32][0] && !saved_cfg[8][0])else $fatal(1,"IA im2col descriptor outside WS Conv");
                ia_im2col_commands++;
            end
            if(u_dut.kernel_dma_start && u_dut.kernel_dma_im2col)begin
                assert(saved_cfg[32][0] && saved_cfg[8][0])else $fatal(1,"kernel im2col descriptor outside IS Conv");
                kernel_im2col_commands++;
            end
            if(arvalid && !arready)ar_stall_cycles++;
            if(u_mem.rd_active && !rvalid && u_mem.random_wait && !u_mem.random_state[5])r_wait_cycles++;
        end
    end
    always @(posedge clk)if(rst_n && $test$plusargs("DEBUG_TILES") && debug_events<160)begin
        if(u_dut.u_matrix_engine.u_ia_loader.tl_start || u_dut.u_matrix_engine.u_ia_loader.tl_tile_done)begin
            $display("TILE cycle=%0d start=%0d done=%0d p=%0d q=%0d rows=%0d slot=%0d loaded=%0d cursor=%0d pf=%0d l2=%0d l1=%0d rd=%0d wr=%0d valid=%b",
                cycle,u_dut.u_matrix_engine.u_ia_loader.tl_start,u_dut.u_matrix_engine.u_ia_loader.tl_tile_done,
                u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tl_p0,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tl_q0,
                u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tl_rows_to_read,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tl_slot_id,
                u_dut.u_matrix_engine.u_ia_loader.u_ctrl.load_tiles_done,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.load_ia_cursor,
                u_dut.u_matrix_engine.u_ia_loader.u_ctrl.prefetch_active,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.l2_idx,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.l1_idx,
                u_dut.u_matrix_engine.u_ia_loader.u_ctrl.rd_slot_base,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.wr_slot_ptr,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tb_observer.cache_blk_valid);
            debug_events++;
        end
    end

    always_comb begin
        conv_cfg='0;
        conv_cfg.input_base=cfg[33];
        conv_cfg.input_h=cfg[34][15:0];conv_cfg.input_w=cfg[35][15:0];conv_cfg.input_c=cfg[36][15:0];
        conv_cfg.group_c=cfg[37][15:0];conv_cfg.group_offset=cfg[38][15:0];
        conv_cfg.kernel_h=cfg[39][15:0];conv_cfg.kernel_w=cfg[40][15:0];
        conv_cfg.output_h=cfg[41][15:0];conv_cfg.output_w=cfg[42][15:0];
        conv_cfg.stride_h=cfg[43][15:0];conv_cfg.stride_w=cfg[44][15:0];
        conv_cfg.dilation_h=cfg[45][15:0];conv_cfg.dilation_w=cfg[46][15:0];
        conv_cfg.pad_top=cfg[47][15:0];conv_cfg.pad_left=cfg[48][15:0];
        conv_cfg.input_offset=$signed(cfg[49][15:0]);
        conv_cfg.bypass_cache=cfg[50][0];conv_cfg.input_s16=cfg[51][0];
    end
    wire [31:0] araddr,awaddr;
    wire [`TB_BUS_WIDTH-1:0] rdata,wdata;
    wire [7:0] arlen,awlen;
    wire [2:0] arsize,awsize;
    wire [1:0] arburst,rresp,memory_rresp,awburst,bresp;
    wire hold_late_response = saved_cfg[59]==3 && !capacity_injected;
    assign rresp=(late_error_active && !late_error_seen) ? 2'b10 : memory_rresp;
    always @(posedge clk)begin
        if(!rst_n || new_job)late_error_seen<=0;
        else if(late_error_active && !late_error_seen && rvalid && rready)late_error_seen<=1;
    end
    wire [`TB_BUS_WIDTH/8-1:0] wstrb;
    wire injected;
    wire [31:0] tensor_bytes=saved_cfg[34]*saved_cfg[35]*saved_cfg[36]*(saved_cfg[51][0]?32'd2:32'd1);
    wire [31:0] other_lo[4],other_hi[4];
    assign other_lo[0]=saved_cfg[15];
    assign other_hi[0]=saved_cfg[15]+(saved_cfg[29][1] ?
        ((saved_cfg[4]+SIZE-1)/SIZE)*((saved_cfg[5]+SIZE-1)/SIZE)*SIZE*SIZE : saved_cfg[4]*saved_cfg[5]);
    assign other_lo[1]=saved_cfg[16];assign other_hi[1]=saved_cfg[16]+4*saved_cfg[5];
    assign other_lo[2]=saved_cfg[13][0]?saved_cfg[24]:0;assign other_hi[2]=saved_cfg[24]+4*saved_cfg[5];
    assign other_lo[3]=saved_cfg[13][0]?saved_cfg[25]:0;assign other_hi[3]=saved_cfg[25]+4*saved_cfg[5];
    longint unsigned read_bytes,input_read_bytes,read_requests,write_bytes;

    npu_top #(.BUS_WIDTH(`TB_BUS_WIDTH),.SIZE(SIZE),.DATA_WIDTH(16),.WEIGHT_WIDTH(16),.IA_CACHE_BLOCKS(`TB_IA_CACHE_BLOCKS),.PS_FRAME_COUNT(`TB_PS_FRAME_COUNT),.AXI_READ_OUTSTANDING(4),
`ifdef TB_IA_COMPACT_ENABLE
        .IA_COMPACT_ENABLE(`TB_IA_COMPACT_ENABLE),
`endif
        .ADDR_WIDTH(`TB_NPU_ADDR_WIDTH),.VECTOR_PE_COUNT(`TB_VECTOR_PE_COUNT),
        .SHARED_BANK_BYTES(`TB_SHARED_BANK_BYTES),.SHARED_BANK_COUNT(`TB_SHARED_BANK_COUNT),
        .DMA_MAX_BYTES(`TB_DMA_MAX_BYTES),
        .PS_STORAGE_ROWS(`TB_PS_STORAGE_ROWS),.OA_S16_FIFO_BANKS_MAX(`TB_OA_S16_FIFO_BANKS_MAX),
        .CONV_CACHE_SETS(`TB_CONV_CACHE_SETS),.CONV_CACHE_WAYS(2),.CONV_LINE_BYTES(`TB_CONV_LINE_BYTES),
        .CONV_CACHE_POLICY(`TB_CONV_CACHE_POLICY)) u_dut(
        .clk(clk),.rst_n(rst_n),.calc_start(calc_start),.sa_ready(sa_ready),.done_valid(done_valid),.done_ready(done_ready),.err_code(err_code),
        .cfg_operand_fetch64(1'b0),.cfg_16bits_ia(cfg[12][0]),.cfg_16x8(cfg[28][0]),.cfg_dataflow_mode(cfg[8][0]),
        .cfg_lhs_tile_packed(cfg[29][0]),.cfg_rhs_tile_packed(cfg[29][1]),
        .cfg_ia_reuse_num(cfg[6]),.cfg_w_reuse_num(cfg[7]),
        .cfg_row_groups({16'b0,cfg[30][15:0]}),.cfg_col_groups({16'b0,cfg[30][31:16]}),
        .cfg_row_tail_tiles({16'b0,cfg[31][15:0]}),.cfg_col_tail_tiles({16'b0,cfg[31][31:16]}),
        .cfg_conv_enable(cfg[32][0]),.cfg_conv(conv_cfg),
        .cfg_vector_enable(1'b0),.cfg_vector('0),
        .cfg_ps_control(cfg[61]), .cfg_shared_ia_banks(cfg[62]),
        .lhs_base(cfg[14]),.rhs_base(cfg[15]),.bias_base(cfg[16]),.dst_base(cfg[17]),
        .lhs_row_stride_b(cfg[18]),.rhs_col_stride_b(cfg[19]),.dst_row_stride_b(cfg[20]),
        .lhs_zp(cfg[21]),.rhs_zp(cfg[22]),.dst_zp(cfg[23]),.q_mult_pt(cfg[24]),.q_shift_pt(cfg[25]),
        .use_per_channel(cfg[13][0]),.act_min(cfg[26]),.act_max(cfg[27]),.k(cfg[3]),.n(cfg[4]),.m(cfg[5]),
        .m_axi_arvalid(arvalid),.m_axi_arready(arready),.m_axi_araddr(araddr),.m_axi_arlen(arlen),.m_axi_arsize(arsize),.m_axi_arburst(arburst),
        .m_axi_rvalid(rvalid && !hold_late_response),.m_axi_rready(rready),.m_axi_rdata(rdata),.m_axi_rresp(rresp),.m_axi_rlast(rlast),
        .m_axi_awvalid(awvalid),.m_axi_awready(awready),.m_axi_awaddr(awaddr),.m_axi_awlen(awlen),.m_axi_awsize(awsize),.m_axi_awburst(awburst),
        .m_axi_wvalid(wvalid),.m_axi_wready(wready),.m_axi_wdata(wdata),.m_axi_wstrb(wstrb),.m_axi_wlast(wlast),
        .m_axi_bvalid(bvalid),.m_axi_bready(bready),.m_axi_bresp(bresp)
    );
    assign hits=u_dut.tb_observer.conv_stat_hits;
    assign misses=u_dut.tb_observer.conv_stat_misses;
    assign conv_bytes=u_dut.tb_observer.conv_stat_read_bytes;
    assign conv_cycles=u_dut.tb_observer.conv_stat_cycles;

    conv_test_axi_memory #(.WORDS(WORDS),.BUS_WIDTH(`TB_BUS_WIDTH),
        .READ_BEAT_CYCLES(`TB_READ_BEAT_CYCLES),
        .READ_FIRST_LATENCY(`TB_READ_FIRST_LATENCY),.PIPELINED_READ(`TB_PIPELINED_READ)) u_mem(
        .clk(clk),.rst_n(rst_n),.new_job(new_job),.protect_input(saved_cfg[32][0]),.inject_error(saved_cfg[53][0]),
        .inject_write_error(saved_cfg[53][1]),
        .input_lo(saved_cfg[33]),.input_hi(saved_cfg[33]+tensor_bytes),.error_injected(injected),
        .other_lo(other_lo),.other_hi(other_hi),
        .read_bytes(read_bytes),.input_read_bytes(input_read_bytes),.read_requests(read_requests),.write_bytes(write_bytes),
        .arvalid(arvalid),.arready(arready),.araddr(araddr),.arlen(arlen),.arsize(arsize),.arburst(arburst),
        .rvalid(rvalid),.rready(rready && !hold_late_response),.rdata(rdata),.rresp(memory_rresp),.rlast(rlast),
        .awvalid(awvalid),.awready(awready),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),
        .wvalid(wvalid),.wready(wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bresp(bresp)
    );

    initial begin : run_suite
        string suite_path,cfg_path,init_path,golden_path,required_path,accumulator_path,histogram_path;
        integer f,fields,task_number,errors,histogram_file,ready_wait;
        integer unique_input,max_input_reads,required_input,unused_unique_input,covered_input;
        longint unsigned histogram_total;
        longint unsigned start_cycle,end_cycle;
        logic [1:0] observed_error;
        task_number=0;
        for(int i=0;i<64;i++)begin cfg[i]=0;saved_cfg[i]=0;end
        if(!$value$plusargs("SUITE=%s",suite_path))$fatal(1,"SUITE required");
        f=$fopen(suite_path,"r");if(f==0)$fatal(1,"cannot open suite");
        repeat(5)@(negedge clk);rst_n=1;repeat(3)@(negedge clk);
        while(!$feof(f))begin
            fields=$fscanf(f,"%s %s %s %s %s\n",cfg_path,init_path,golden_path,required_path,accumulator_path);
            if(fields==5)begin
                ready_wait=0;
                while(!sa_ready && ready_wait<10000)begin @(negedge clk);ready_wait++;end
                assert(sa_ready)else $fatal(1,"NPU not ready before task %0d: abort=%0d fault=%0b controller_ready=%0b",task_number,u_dut.abort_state,u_dut.task_fault,u_dut.ctrl_sa_ready);
                $readmemh(cfg_path,cfg);
                for(int i=0;i<64;i++)saved_cfg[i]=cfg[i];
                assert(cfg[1]==SIZE)else $fatal(1,"wrong array size");
                for(int i=0;i<WORDS;i++)begin u_mem.mem[i]=32'h5aa53cc3;golden[i]=32'h5aa53cc3;end
                $readmemh(init_path,u_mem.mem);$readmemh(golden_path,golden);
                for(int i=0;i<WORDS;i++)initial_reference[i]=u_mem.mem[i];
                $readmemh(accumulator_path,accumulator_reference);
                for(int i=0;i<65536;i++)u_mem.input_required[i]=0;
                $readmemh(required_path,u_mem.input_required);
                capacity_injected=0;late_error_active=0;
                new_job=1;@(negedge clk);new_job=0;
                start_cycle=cycle;calc_start=1;@(negedge clk);calc_start=0;
                if(saved_cfg[56]!=0)begin
                    repeat(3)@(negedge clk);
                    cfg[33]=32'h1f000;cfg[34]=1;cfg[35]=1;
                end
                while(!done_valid && cycle-start_cycle<2_000_000)begin
                    if(!capacity_injected &&
                       ((saved_cfg[59]==1 && u_dut.u_matrix_engine.u_compute_core.ps_stream_valid_d &&
                         !u_dut.u_matrix_engine.u_compute_core.ps_calc_done_d) ||
                        (saved_cfg[59]==2 && rvalid && rready && rresp[1]) ||
                        (saved_cfg[59]==3 && u_mem.rd_active && rvalid)))begin
                        force u_dut.ps_capacity_fault=1'b1;
                        capacity_injected=1;
                        @(negedge clk);
                        if(saved_cfg[59]==3)begin
                            assert(u_dut.abort_state==1 && u_dut.abort_error_code==2)
                                else $fatal(1,"capacity error was not latched before the later AXI response");
                            late_error_active=1;
                        end
                        force u_dut.ps_capacity_fault=1'b0;
                    end else @(negedge clk);
                end
                if(!done_valid)begin
                    $display("TIMEOUT FRAME mode=%0d valid=%0d active=%0d ready=%0d pressure=%0d id=%0d p0=%0d q0=%0d column=%0d init=%0d final=%0d compute=%0d store=%0d output=%0d commands=%0d",u_dut.frame_mode_q,
                        u_dut.u_matrix_engine.frame_command_valid,u_dut.u_matrix_engine.frame_command_active,u_dut.u_matrix_engine.ps_frame_ready,u_dut.u_matrix_engine.ps_frame_pressure,
                        u_dut.u_matrix_engine.frame_command_id,u_dut.u_matrix_engine.frame_command_p0,u_dut.u_matrix_engine.frame_command_q0,u_dut.u_matrix_engine.frame_command_column,
                        u_dut.u_matrix_engine.frame_command_init,u_dut.u_matrix_engine.frame_command_final,u_dut.u_matrix_engine.frame_compute_seen,
                        u_dut.u_matrix_engine.frame_store_seen,u_dut.u_matrix_engine.frame_output_seen,u_dut.tb_observer.frame_stat_commands);
                    $display("TIMEOUT state=%0d ia_state=%0d fe_state=%0d conv_enable=%0d ready=%0d busy=%0d err=%0d abort=%0d",
                        u_dut.u_matrix_engine.u_npu_controller.current_state,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.state,
                        u_dut.u_block_dma_arbiter.u_dma.g_im2col.u_frontend.state,u_dut.run_conv,
                        u_dut.u_block_dma_arbiter.u_dma.fe_tile_ready,u_dut.conv_busy,u_dut.conv_error,u_dut.abort_state);
                    $display("TIMEOUT AXI count=%0d active=%0d ar=%0d/%0d r=%0d/%0d reads=%0d inputbytes=%0d kernelbusy=%0d biasbusy=%0d quantbusy=%0d tlstart=%0d tlbusy=%0d",
                        u_mem.count,u_mem.rd_active,arvalid,arready,rvalid,rready,read_bytes,input_read_bytes,
                        u_dut.kernel_dma_busy,u_dut.bias_dma_busy,u_dut.quant_dma_busy,
                        u_dut.u_matrix_engine.u_ia_loader.tl_start,u_dut.u_matrix_engine.u_ia_loader.tl_busy);
                    $display("TIMEOUT IA loaded=%0d cursor=%0d target=%0d pf=%0d l2=%0d l1=%0d rd=%0d wr=%0d valid=%b canload=%0d req=%0d grant=%0d readygroup=%0d output=%0d wvalid=%0d biasvalid=%0d quantvalid=%0d",
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.load_tiles_done,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.load_ia_cursor,
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.load_r_target,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.prefetch_active,
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.l2_idx,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.l1_idx,
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.rd_slot_base,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.wr_slot_ptr,
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.tb_observer.cache_blk_valid,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.can_start_load,
                        u_dut.load_ia_req,u_dut.load_ia_granted,u_dut.u_matrix_engine.u_ia_loader.u_ctrl.send_group_ready_r,
                        u_dut.u_matrix_engine.u_ia_loader.u_ctrl.in_l1_output,u_dut.u_matrix_engine.weight_data_valid,u_dut.u_matrix_engine.bias_valid,u_dut.u_matrix_engine.quant_params_valid);
                    $fatal(1,"task timeout id=%0d",task_number);
                end
                if(capacity_injected) release u_dut.ps_capacity_fault;
                observed_error=err_code;
                end_cycle=cycle;
                assert(err_code==saved_cfg[52][1:0] || (saved_cfg[60]!=0 && err_code==2))
                    else $fatal(1,"task id=%0d expected error=%0d got=%0d",task_number,saved_cfg[52],err_code);
                if(saved_cfg[53][1:0]!=0)assert(injected)else $fatal(1,"requested AXI error was never injected");
                if(saved_cfg[59]!=0)assert(capacity_injected)else $fatal(1,"requested PS fault was never injected");
                if(saved_cfg[59]==3)assert(late_error_seen)else $fatal(1,"requested later AXI error was never accepted");
                if(observed_error==0)begin
                    assert(expected_accumulator_rows.size()==0)
                        else $fatal(1,"unconsumed accumulator rows at completion");
                    assert(accumulator_checks==int'(saved_cfg[3]*saved_cfg[5]))
                        else $fatal(1,"incomplete INT32 accumulator comparison count=%0d",accumulator_checks);
                    if(saved_cfg[4]<=SIZE)assert(ps_committed_rows==0)
                        else $fatal(1,"single-K command wrote partial-sum storage");
                end else begin
                    assert(u_mem.count==0 && !u_mem.rd_active && !rvalid && !u_mem.wr_active && !bvalid)
                        else $fatal(1,"error completion before AXI response drain");
                end
                repeat(3)begin
                    @(negedge clk);
                    assert(done_valid && err_code==observed_error)else $fatal(1,"unstable completion under backpressure");
                end
                errors=0;
                for(int i=0;i<WORDS;i++)begin
                    if(u_mem.mem[i]!==golden[i])begin
                        bit permitted_partial;
                        bit output_address;
                        integer byte_address,output_offset;
                        permitted_partial=observed_error==2 && saved_cfg[60]!=0;
                        for(int lane=0;lane<4;lane++)begin
                            byte_address=4*i+lane;
                            output_offset=byte_address-int'(saved_cfg[17]);
                            output_address=0;
                            if(output_offset>=0 && saved_cfg[20]!=0)begin
                                output_address=(output_offset/int'(saved_cfg[20]))<int'(saved_cfg[3]) &&
                                    (output_offset%int'(saved_cfg[20]))<int'(saved_cfg[5])*(saved_cfg[28][0]?2:1);
                            end
                            if(u_mem.mem[i][8*lane+:8]!==golden[i][8*lane+:8] &&
                               (!output_address || u_mem.mem[i][8*lane+:8]!==initial_reference[i][8*lane+:8]))
                                permitted_partial=0;
                        end
                        if(!permitted_partial)begin
                            if(errors<12)$display("MISMATCH task=%0d word=%h got=%h expected=%h",task_number,i,u_mem.mem[i],golden[i]);
                            errors++;
                        end
                    end
                end
                assert(errors==0)else $fatal(1,"memory mismatch count=%0d",errors);
                if(saved_cfg[32][0] && saved_cfg[52]==0)
                    assert(64'(conv_bytes)==input_read_bytes)else $fatal(1,"read-byte counter mismatch RTL=%0d AXI=%0d",conv_bytes,input_read_bytes);
                if(saved_cfg[32][0] && saved_cfg[52]==0)begin
                    if(saved_cfg[8][0])assert(kernel_im2col_commands>0 && ia_im2col_commands==0)
                        else $fatal(1,"IS did not use the kernel DMA im2col path");
                    else assert(ia_im2col_commands>0 && kernel_im2col_commands==0)
                        else $fatal(1,"WS did not use the IA DMA im2col path");
                end
                if(saved_cfg[32][0] && saved_cfg[52]==1)
                    assert(read_requests==0 && write_bytes==0 && ia_im2col_commands==0 && kernel_im2col_commands==0)
                        else $fatal(1,"invalid Conv issued memory or im2col commands");
                unique_input=0;max_input_reads=0;required_input=0;unused_unique_input=0;covered_input=0;histogram_total=0;
                histogram_path={suite_path,$sformatf(".task%0d.input_reads.csv",task_number)};
                histogram_file=$fopen(histogram_path,"w");
                assert(histogram_file!=0)else $fatal(1,"cannot create input histogram");
                $fdisplay(histogram_file,"byte_address,allocation_offset,required_by_window,axi_read_count");
                for(int i=0;i<65536;i++)begin
                    histogram_total+=64'(u_mem.input_hist[i]);
                    if(u_mem.input_hist[i]>0)unique_input++;
                    if(u_mem.input_hist[i]>max_input_reads)max_input_reads=int'(u_mem.input_hist[i]);
                    if(u_mem.input_required[i])begin
                        required_input++;
                        if(u_mem.input_hist[i]>0)covered_input++;
                    end else if(u_mem.input_hist[i]>0)unused_unique_input++;
                    if(saved_cfg[32][0] && 32'(i)+32'h10000>=saved_cfg[33] &&
                       32'(i)+32'h10000<saved_cfg[33]+tensor_bytes)begin
                        $fdisplay(histogram_file,"0x%08h,%0d,%0d,%0d",32'(i)+32'h10000,
                            32'(i)+32'h10000-saved_cfg[33],u_mem.input_required[i],u_mem.input_hist[i]);
                        if(saved_cfg[58]!=0)assert(u_mem.input_hist[i]==1)
                            else $fatal(1,"resident input byte %h read %0d times, expected exactly once",32'(i)+32'h10000,u_mem.input_hist[i]);
                    end
                end
                $fclose(histogram_file);
                assert(histogram_total==input_read_bytes)else $fatal(1,"input histogram byte sum mismatch");
                assert(padding_reads==0)else $fatal(1,"padding caused an external input read");
                if(saved_cfg[32][0] && observed_error==0)
                    assert(covered_input==required_input)else $fatal(1,"required input bytes were not fetched");
                $display("CONV_TASK_PASS task=%0d conv=%0d dataflow=%0d bypass=%0d error=%0d cycles=%0d hits=%0d misses=%0d input_bytes=%0d input_unique=%0d input_duplicate=%0d input_max_reads=%0d input_required=%0d input_prefetched_unused=%0d padding_reads=%0d ar_bytes=%0d ar_requests=%0d write_bytes=%0d device_cycles=%0d ia_im2col_commands=%0d kernel_im2col_commands=%0d ar_stall_cycles=%0d r_wait_cycles=%0d int32_checks=%0d ps_blocked_cycles=%0d capacity_injected=%0d ps_committed_rows=%0d ps_raw_records=%0d ps_payload_words=%0d frame_commands=%0d pressure_events=%0d early_finish_frames=%0d ia_banks=%0d ia_bytes=%0d ps_bytes=%0d r=%0d w=%0d ps_control=%0d ia_compact_capable=%0d ia_compact_active=%0d",task_number,saved_cfg[32],saved_cfg[8],saved_cfg[50],observed_error,end_cycle-start_cycle,hits,misses,input_read_bytes,unique_input,input_read_bytes-64'(unique_input),max_input_reads,required_input,unused_unique_input,padding_reads,read_bytes,read_requests,write_bytes,conv_cycles,ia_im2col_commands,kernel_im2col_commands,ar_stall_cycles,r_wait_cycles,accumulator_checks,ps_blocked_cycles,capacity_injected,ps_committed_rows,ps_raw_records,ps_payload_words,u_dut.tb_observer.ps_stat_commands,u_dut.tb_observer.ps_stat_pressure_events,u_dut.tb_observer.ps_stat_early_finish_frames,u_dut.SHARED_RAM_ENABLED ? u_dut.shared_ia_banks_q : 0,u_dut.u_matrix_engine.active_ia_cache_blocks*512,u_dut.u_matrix_engine.u_task_configuration.active_ps_pool_bytes,saved_cfg[6],saved_cfg[7],saved_cfg[61],u_dut.IA_COMPACT_ENABLE,u_dut.run_compact);
                done_ready=1;@(negedge clk);done_ready=0;
                repeat(8)@(negedge clk);
                task_number++;
            end else if(fields!=-1)$fatal(1,"malformed suite entry fields=%0d",fields);
        end
        $fclose(f);
        assert(task_number>0)else $fatal(1,"empty test suite");
        $display("CONV_NPU_PASS tasks=%0d size=%0d",task_number,SIZE);
        $finish;
    end
endmodule
