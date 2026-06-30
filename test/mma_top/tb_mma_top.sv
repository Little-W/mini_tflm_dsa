`timescale 1ns / 1ps
`include "icb_types.svh"

module tb_mma_top;
    // 时钟复位
    logic clk = 0;
    always #5 clk = ~clk;  // 100MHz
    logic rst_n = 0;
    initial begin
        rst_n = 0;
        repeat (5) @(posedge clk);
        rst_n = 1;
    end

`ifndef TB_SIZE
`define TB_SIZE 4
`endif
`ifndef TB_IA_CACHE_BLOCKS
`define TB_IA_CACHE_BLOCKS 4
`endif
`ifndef TB_PS_FRAME_COUNT
`define TB_PS_FRAME_COUNT 8
`endif

    localparam int unsigned SIZE = `TB_SIZE;
    localparam int unsigned IA_CACHE_BLOCKS = `TB_IA_CACHE_BLOCKS;
    localparam int unsigned PS_FRAME_COUNT = `TB_PS_FRAME_COUNT;
    localparam int unsigned REGW = 32;

    localparam int unsigned CFG_WORDS = 32;
    localparam logic [31:0] CFG_MAGIC = 32'h4d4d4131; // "MMA1"
    localparam int CFG_MAGIC_IDX             = 0;
    localparam int CFG_SIZE_IDX              = 1;
    localparam int CFG_IA_CACHE_BLOCKS_IDX   = 2;
    localparam int CFG_K_IDX                 = 3;
    localparam int CFG_N_IDX                 = 4;
    localparam int CFG_M_IDX                 = 5;
    localparam int CFG_IA_REUSE_NUM_IDX      = 6;
    localparam int CFG_W_REUSE_NUM_IDX       = 7;
    localparam int CFG_DATAFLOW_MODE_IDX     = 8;
    localparam int CFG_PS_FRAME_COUNT_IDX    = 9;
    localparam int CFG_COMPARE_WORDS_IDX     = 10;
    localparam int CFG_MEM_WORDS_IDX         = 11;
    localparam int CFG_16BITS_IA_IDX         = 12;
    localparam int CFG_USE_PER_CHANNEL_IDX   = 13;
    localparam int CFG_LHS_BASE_IDX          = 14;
    localparam int CFG_RHS_BASE_IDX          = 15;
    localparam int CFG_BIAS_BASE_IDX         = 16;
    localparam int CFG_DST_BASE_IDX          = 17;
    localparam int CFG_LHS_ROW_STRIDE_B_IDX  = 18;
    localparam int CFG_RHS_ROW_STRIDE_B_IDX  = 19;
    localparam int CFG_DST_ROW_STRIDE_B_IDX  = 20;
    localparam int CFG_LHS_ZP_IDX            = 21;
    localparam int CFG_RHS_ZP_IDX            = 22;
    localparam int CFG_DST_ZP_IDX            = 23;
    localparam int CFG_QMUL_IDX              = 24;
    localparam int CFG_QSHIFT_IDX            = 25;
    localparam int CFG_ACT_MIN_IDX           = 26;
    localparam int CFG_ACT_MAX_IDX           = 27;

    logic [31:0] case_cfg_mem[0:CFG_WORDS-1];
    logic [REGW-1:0] compare_words;
    logic [REGW-1:0] case_mem_words;

    function automatic logic signed [31:0] cfg_s32(input int idx);
        cfg_s32 = $signed(case_cfg_mem[idx]);
    endfunction

    logic                       calc_start;
    logic                       cfg_16bits_ia;
    logic                       cfg_dataflow_mode;
    logic [REGW-1:0]            cfg_ia_reuse_num;
    logic [REGW-1:0]            cfg_w_reuse_num;
    logic                       sa_ready;
    logic [REGW-1:0]            lhs_base;
    logic [REGW-1:0]            rhs_base;
    logic [REGW-1:0]            dst_base;
    logic [REGW-1:0]            bias_base;
    logic signed [REGW-1:0]     lhs_zp;
    logic signed [REGW-1:0]     rhs_zp;
    logic signed [REGW-1:0]     dst_zp;
    logic signed [REGW-1:0]     q_mult_pt;
    logic signed [REGW-1:0]     q_shift_pt;
    logic                       use_per_channel;
    logic [REGW-1:0]            k;
    logic [REGW-1:0]            n;
    logic [REGW-1:0]            m;
    logic [REGW-1:0]            lhs_row_stride_b;
    logic [REGW-1:0]            dst_row_stride_b;
    logic [REGW-1:0]            rhs_row_stride_b;
    logic signed [REGW-1:0]     act_min;
    logic signed [REGW-1:0]     act_max;
    wire        wb_valid;
    wire        wb_ready = 1'b1;
    wire [ 1:0] err_code;

    wire        icb_cmd_valid;
    wire        icb_cmd_ready;
    wire [18:0] icb_cmd_addr;
    wire        icb_cmd_read;
    wire [ 3:0] icb_cmd_len;
    wire [31:0] icb_cmd_wdata;
    wire [ 3:0] icb_cmd_wmask;
    wire        icb_w_valid;
    wire        icb_w_ready;
    wire        icb_rsp_valid;
    wire        icb_rsp_ready;
    wire [31:0] icb_rsp_rdata;
    wire        icb_rsp_err;

    // DUT 实例
    mma_top #(
        .SIZE(SIZE),
        .ICB_LEN_W(4),
        .IA_CACHE_BLOCKS(IA_CACHE_BLOCKS),
        .PS_FRAME_COUNT(PS_FRAME_COUNT)
    ) u_dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .calc_start   (calc_start),
        .cfg_16bits_ia(cfg_16bits_ia),
        .cfg_dataflow_mode(cfg_dataflow_mode),
        .cfg_ia_reuse_num(cfg_ia_reuse_num),
        .cfg_w_reuse_num (cfg_w_reuse_num),
        .sa_ready     (sa_ready),
        .wb_valid     (wb_valid),
        .wb_ready     (wb_ready),
        .err_code     (err_code),

        .lhs_base (lhs_base),
        .rhs_base (rhs_base),
        .dst_base (dst_base),
        .bias_base(bias_base),

        .lhs_zp         (lhs_zp),
        .rhs_zp         (rhs_zp),
        .dst_zp         (dst_zp),
        .q_mult_pt      (q_mult_pt),
        .q_shift_pt     (q_shift_pt),
        .use_per_channel(use_per_channel),

        .k(k),
        .n(n),
        .m(m),

        .lhs_row_stride_b(lhs_row_stride_b),
        .dst_row_stride_b(dst_row_stride_b),
        .rhs_col_stride_b(rhs_row_stride_b),

        .act_min(act_min),
        .act_max(act_max),

        .sa_icb_cmd_valid(icb_cmd_valid),
        .sa_icb_cmd_ready(icb_cmd_ready),
        .sa_icb_cmd_addr (icb_cmd_addr),
        .sa_icb_cmd_read (icb_cmd_read),
        .sa_icb_cmd_len  (icb_cmd_len),
        .sa_icb_cmd_wdata(icb_cmd_wdata),
        .sa_icb_cmd_wmask(icb_cmd_wmask),
        .sa_icb_w_valid  (icb_w_valid),
        .sa_icb_w_ready  (icb_w_ready),
        .sa_icb_rsp_valid(icb_rsp_valid),
        .sa_icb_rsp_ready(icb_rsp_ready),
        .sa_icb_rsp_rdata(icb_rsp_rdata),
        .sa_icb_rsp_err  (icb_rsp_err)
    );

    // 直接 DDR 行为模型：支持独立写数据通道和随机 cmd/write/response 延迟。
    ddr_icb_mem_model #(
        .WIDTH (32),
        .ADDR_W(19),
        .LEN_W (4),
        .MW    (4),
        .DP    (131072)
    ) u_mem (
        .clk              (clk),
        .rst_n            (rst_n),
        .sa_icb_cmd_valid(icb_cmd_valid),
        .sa_icb_cmd_ready(icb_cmd_ready),
        .sa_icb_cmd_addr (icb_cmd_addr),
        .sa_icb_cmd_read (icb_cmd_read),
        .sa_icb_cmd_len  (icb_cmd_len),
        .sa_icb_cmd_wdata(icb_cmd_wdata),
        .sa_icb_cmd_wmask(icb_cmd_wmask),
        .sa_icb_w_valid  (icb_w_valid),
        .sa_icb_w_ready  (icb_w_ready),
        .sa_icb_rsp_valid(icb_rsp_valid),
        .sa_icb_rsp_ready(icb_rsp_ready),
        .sa_icb_rsp_rdata(icb_rsp_rdata),
        .sa_icb_rsp_err  (icb_rsp_err)
    );

    // 使用 clocking block 初始化配置
    initial begin
        calc_start        <= 1'b0;
        cfg_16bits_ia    <= 1'b0;
        cfg_dataflow_mode <= 1'b0;
        cfg_ia_reuse_num <= '0;
        cfg_w_reuse_num  <= '0;
        lhs_base         <= '0;
        rhs_base         <= '0;
        dst_base         <= '0;
        bias_base        <= '0;
        lhs_zp           <= '0;
        rhs_zp           <= '0;
        dst_zp           <= '0;
        q_mult_pt        <= '0;
        q_shift_pt       <= '0;
        use_per_channel  <= 1'b0;
        k                <= '0;
        n                <= '0;
        m                <= '0;
        lhs_row_stride_b <= '0;
        dst_row_stride_b <= '0;
        rhs_row_stride_b <= '0;
        act_min          <= '0;
        act_max          <= '0;

        @(posedge rst_n);
        @(posedge clk);
        cfg_16bits_ia    <= case_cfg_mem[CFG_16BITS_IA_IDX][0];
        cfg_dataflow_mode <= case_cfg_mem[CFG_DATAFLOW_MODE_IDX][0];
        cfg_ia_reuse_num <= case_cfg_mem[CFG_IA_REUSE_NUM_IDX];
        cfg_w_reuse_num  <= case_cfg_mem[CFG_W_REUSE_NUM_IDX];
        lhs_base         <= case_cfg_mem[CFG_LHS_BASE_IDX];
        rhs_base         <= case_cfg_mem[CFG_RHS_BASE_IDX];
        dst_base         <= case_cfg_mem[CFG_DST_BASE_IDX];
        bias_base        <= case_cfg_mem[CFG_BIAS_BASE_IDX];
        lhs_zp           <= cfg_s32(CFG_LHS_ZP_IDX);
        rhs_zp           <= cfg_s32(CFG_RHS_ZP_IDX);
        dst_zp           <= cfg_s32(CFG_DST_ZP_IDX);
        q_mult_pt        <= cfg_s32(CFG_QMUL_IDX);
        q_shift_pt       <= cfg_s32(CFG_QSHIFT_IDX);
        use_per_channel  <= case_cfg_mem[CFG_USE_PER_CHANNEL_IDX][0];
        k                <= case_cfg_mem[CFG_K_IDX];
        n                <= case_cfg_mem[CFG_N_IDX];
        m                <= case_cfg_mem[CFG_M_IDX];
        lhs_row_stride_b <= case_cfg_mem[CFG_LHS_ROW_STRIDE_B_IDX];
        dst_row_stride_b <= case_cfg_mem[CFG_DST_ROW_STRIDE_B_IDX];
        rhs_row_stride_b <= case_cfg_mem[CFG_RHS_ROW_STRIDE_B_IDX];
        act_min          <= cfg_s32(CFG_ACT_MIN_IDX);
        act_max          <= cfg_s32(CFG_ACT_MAX_IDX);
    end

    // 层级引用加载内存
    string init_mem_path, golden_mem_path, case_mem_path;
    localparam int MEMW = 32;
    localparam int MEMDP = 131072;
    reg [MEMW-1:0] golden_mem[0:MEMDP-1];
    integer err;
    integer acc_valid_count;
    integer requant_valid_count;
    integer fifo_req_count;
    integer write_done_count;
    integer tile_calc_over_count;
    integer ia_row_valid_rise_count;
    integer ia_calc_done_count;
    logic   ia_row_valid_q;
    bit     debug_stream;
    bit     full_mem_check;

    initial begin
        debug_stream = $test$plusargs("DEBUG_STREAM");
        full_mem_check = $test$plusargs("FULL_MEM_CHECK");
    end

    function automatic logic [7:0] pick_byte(input logic [31:0] word, input int unsigned byte_sel);
        case (byte_sel[1:0])
            2'd0: pick_byte = word[7:0];
            2'd1: pick_byte = word[15:8];
            2'd2: pick_byte = word[23:16];
            default: pick_byte = word[31:24];
        endcase
    endfunction

    function automatic logic [7:0] actual_mem_byte(input int unsigned byte_addr);
        actual_mem_byte = pick_byte(u_mem.mem_r[byte_addr >> 2], byte_addr);
    endfunction

    function automatic logic [7:0] golden_mem_byte(input int unsigned byte_addr);
        golden_mem_byte = pick_byte(golden_mem[byte_addr >> 2], byte_addr);
    endfunction

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_valid_count       <= 0;
            requant_valid_count   <= 0;
            fifo_req_count        <= 0;
            write_done_count      <= 0;
            tile_calc_over_count  <= 0;
            ia_row_valid_rise_count <= 0;
            ia_calc_done_count     <= 0;
            ia_row_valid_q         <= 1'b0;
        end else begin
            ia_row_valid_q <= u_dut.ia_row_valid;
            if (u_dut.acc_data_valid) acc_valid_count <= acc_valid_count + 1;
            if (u_dut.requant_out_valid) requant_valid_count <= requant_valid_count + 1;
            if (u_dut.fifo_output_req) fifo_req_count <= fifo_req_count + 1;
            if (u_dut.write_done) write_done_count <= write_done_count + 1;
            if (u_dut.tile_calc_over) tile_calc_over_count <= tile_calc_over_count + 1;
            if (u_dut.ia_row_valid && !ia_row_valid_q) ia_row_valid_rise_count <= ia_row_valid_rise_count + 1;
            if (u_dut.ia_row_valid && u_dut.ia_calc_done) ia_calc_done_count <= ia_calc_done_count + 1;
            if (debug_stream && u_dut.store_weight_req) begin
                $display("[DBG][WGT] t=%0t store=%0b w=%0d,%0d,%0d,%0d",
                         $time, u_dut.store_weight_req,
                         u_dut.weight_out[0], u_dut.weight_out[1],
                         u_dut.weight_out[2], u_dut.weight_out[3]);
            end
            if (debug_stream && (u_dut.ia_dma_wr_valid[0] || u_dut.ia_dma_done)) begin
                $display("[DBG][IADMA] t=%0t done=%0b slot=%0d row=%0d col=%0d v=%b data=%0d,%0d,%0d,%0d",
                         $time, u_dut.ia_dma_done, u_dut.ia_dma_wr_slot,
                         u_dut.ia_dma_wr_row, u_dut.ia_dma_wr_col_base,
                         {u_dut.ia_dma_wr_valid[3], u_dut.ia_dma_wr_valid[2],
                          u_dut.ia_dma_wr_valid[1], u_dut.ia_dma_wr_valid[0]},
                         u_dut.ia_dma_wr_data[0], u_dut.ia_dma_wr_data[1],
                         u_dut.ia_dma_wr_data[2], u_dut.ia_dma_wr_data[3]);
            end
            if (debug_stream && u_dut.u_ia_loader.u_ctrl.cache_l1_start) begin
                $display("[DBG][IASTART] t=%0t slot_start=%0d slot_end=%0d l2=%0d l1=%0d wg=%0d w=%0d ia=%0d valid=%b bias_valid=%0b group_valid=%0b bias=%0d,%0d latched=%0d,%0d",
                         $time,
                         u_dut.u_ia_loader.u_ctrl.cache_l1_slot_start,
                         u_dut.u_ia_loader.u_ctrl.cache_l1_slot_end,
                         u_dut.u_ia_loader.u_ctrl.l2_idx,
                         u_dut.u_ia_loader.u_ctrl.l1_idx,
                         u_dut.u_ia_loader.u_ctrl.w_group_idx,
                         u_dut.u_ia_loader.u_ctrl.w_cnt,
                         u_dut.u_ia_loader.u_ctrl.ia_idx,
                         u_dut.u_ia_loader.u_ctrl.cache_blk_valid,
                         u_dut.bias_valid,
                         u_dut.bias_group_valid,
                         u_dut.bias_data_out[0],
                         u_dut.bias_data_out[1],
                         u_dut.compute_bias_latched[0],
                         u_dut.compute_bias_latched[1]);
            end
            if (debug_stream && (u_dut.bias_switch || u_dut.load_bias_granted ||
                                 u_dut.load_bias_done || u_dut.u_bias_loader.u_ctrl.switch_pending)) begin
                $display("[DBG][BIAS] t=%0t state=%0d sw=%0b sleep=%0b last=%0b req=%0b grant=%0b done=%0b pending=%0b cur=%0d load=%0d next=%0d act_bank=%0b load_bank=%0b valid=%0b next_valid=%0b group=%0b data=%0d,%0d next_data=%0d,%0d",
                         $time,
                         u_dut.u_bias_loader.u_ctrl.state,
                         u_dut.bias_switch,
                         u_dut.bias_sleep,
                         u_dut.bias_last_loop,
                         u_dut.load_bias_req,
                         u_dut.load_bias_granted,
                         u_dut.load_bias_done,
                         u_dut.u_bias_loader.u_ctrl.switch_pending,
                         u_dut.u_bias_loader.u_ctrl.current_block_idx,
                         u_dut.u_bias_loader.u_ctrl.load_block_idx,
                         u_dut.u_bias_loader.u_ctrl.next_block_idx,
                         u_dut.u_bias_loader.u_ctrl.active_bank,
                         u_dut.u_bias_loader.u_ctrl.load_bank,
                         u_dut.bias_valid,
                         u_dut.next_bias_valid,
                         u_dut.bias_group_valid,
                         u_dut.bias_data_out[0],
                         u_dut.bias_data_out[1],
                         u_dut.next_bias_data_out[0],
                         u_dut.next_bias_data_out[1]);
            end
            if (debug_stream && u_dut.ia_row_valid) begin
                $display("[DBG][IA]  t=%0t done=%0b init=%0b tile_start=%0b bias_valid=%0b bias=%0d,%0d ia=%0d,%0d,%0d,%0d",
                         $time, u_dut.ia_calc_done, u_dut.ia_is_init_data, u_dut.ia_tile_start,
                         u_dut.bias_valid, u_dut.bias_data_out[0], u_dut.bias_data_out[1],
                         u_dut.ia_out[0], u_dut.ia_out[1],
                         u_dut.ia_out[2], u_dut.ia_out[3]);
            end
            if (debug_stream && (u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.replay_data_valid ||
                                 u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.ram_write_en ||
                                 u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.send_ia_trigger_i)) begin
                $write("[DBG][PS]  t=%0t trig=%0b replay=%0b rcnt=%0d wren=%0b len=%0d ps=",
                         $time,
                         u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.send_ia_trigger_i,
                         u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.replay_data_valid,
                         u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.replay_count,
                         u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.ram_write_en,
                         u_dut.u_compute_core.u_ps_buffer.gen_ps_buffer_fifo[0].u_ps_buffer_fifo.frame_len);
                for (int dbg_i = 0; dbg_i < SIZE; dbg_i++) begin
                    $write("%0d%s", u_dut.u_compute_core.ps_data_out[dbg_i],
                           (dbg_i == SIZE - 1) ? "" : ",");
                end
                $write(" sum=");
                for (int dbg_i = 0; dbg_i < SIZE; dbg_i++) begin
                    $write("%0d%s", u_dut.u_compute_core.systolic_sum[dbg_i],
                           (dbg_i == SIZE - 1) ? "" : ",");
                end
                $write("\n");
            end
            if (debug_stream && u_dut.acc_data_valid) begin
                $write("[DBG][ACC] t=%0t done=%0b row_idx=%0d bias=%0d acc=",
                       $time, u_dut.tile_calc_over, u_dut.is_bias_row_idx,
                       u_dut.is_bias_scalar);
                for (int dbg_i = 0; dbg_i < SIZE; dbg_i++) begin
                    $write("%0d%s", u_dut.acc_data_out[dbg_i],
                           (dbg_i == SIZE - 1) ? "" : ",");
                end
                $write(" sys=");
                for (int dbg_i = 0; dbg_i < SIZE; dbg_i++) begin
                    $write("%0d%s", u_dut.u_compute_core.systolic_sum[dbg_i],
                           (dbg_i == SIZE - 1) ? "" : ",");
                end
                $write("\n");
            end
            if (debug_stream && u_dut.requant_out_valid) begin
                $write("[DBG][RQ]  t=%0t done=%0b out=",
                       $time, u_dut.requant_tile_done);
                for (int dbg_i = 0; dbg_i < SIZE; dbg_i++) begin
                    $write("%0d%s", u_dut.requant_out[dbg_i],
                           (dbg_i == SIZE - 1) ? "" : ",");
                end
                $write("\n");
            end
            if (debug_stream && u_dut.fifo_output_valid && u_dut.fifo_output_ready) begin
                $display("[DBG][WR]  t=%0t tile=(%0d,%0d) row=%0d addr=%h data=%h mask=%b sw=%0b",
                         $time, u_dut.u_oa_writer.tile_row_idx, u_dut.u_oa_writer.tile_col_idx,
                         u_dut.u_oa_writer.row_in_tile, u_dut.u_oa_writer.cur_addr,
                         u_dut.fifo_output_data, u_dut.fifo_output_mask,
                         u_dut.fifo_output_switch_row);
            end
        end
    end

    initial begin
        if (!$value$plusargs("INIT_MEM=%s", init_mem_path)) init_mem_path = "out/init.mem";
        if (!$value$plusargs("GOLDEN_MEM=%s", golden_mem_path)) golden_mem_path = "out/golden.mem";
        if (!$value$plusargs("CASE_MEM=%s", case_mem_path)) case_mem_path = "out/config.mem";
        $display("[TB] INIT_MEM=%s", init_mem_path);
        $display("[TB] GOLDEN_MEM=%s", golden_mem_path);
        $display("[TB] CASE_MEM=%s", case_mem_path);

        for (int cfg_i = 0; cfg_i < CFG_WORDS; cfg_i++) begin
            case_cfg_mem[cfg_i] = '0;
        end
        $readmemh(case_mem_path, case_cfg_mem);

        if (case_cfg_mem[CFG_MAGIC_IDX] != CFG_MAGIC) begin
            $display("[TB] FATAL: bad config magic %08x in %s", case_cfg_mem[CFG_MAGIC_IDX], case_mem_path);
            $finish;
        end
        if (case_cfg_mem[CFG_SIZE_IDX] != SIZE) begin
            $display("[TB] FATAL: case SIZE=%0d but compiled TB_SIZE=%0d",
                     case_cfg_mem[CFG_SIZE_IDX], SIZE);
            $finish;
        end
        if (case_cfg_mem[CFG_IA_CACHE_BLOCKS_IDX] != IA_CACHE_BLOCKS) begin
            $display("[TB] FATAL: case IA_CACHE_BLOCKS=%0d but compiled TB_IA_CACHE_BLOCKS=%0d",
                     case_cfg_mem[CFG_IA_CACHE_BLOCKS_IDX], IA_CACHE_BLOCKS);
            $finish;
        end
        if (case_cfg_mem[CFG_PS_FRAME_COUNT_IDX] > PS_FRAME_COUNT) begin
            $display("[TB] FATAL: case PS_FRAME_COUNT=%0d exceeds compiled TB_PS_FRAME_COUNT=%0d",
                     case_cfg_mem[CFG_PS_FRAME_COUNT_IDX], PS_FRAME_COUNT);
            $finish;
        end
        compare_words = case_cfg_mem[CFG_COMPARE_WORDS_IDX];
        case_mem_words = case_cfg_mem[CFG_MEM_WORDS_IDX];

        $display("[TB] CASE SIZE=%0d CACHE=%0d K=%0d N=%0d M=%0d cfg_16bits_ia=%0b mode=%s R=%0d W=%0d compare_words=%0d check=%s",
                 SIZE, IA_CACHE_BLOCKS,
                 case_cfg_mem[CFG_K_IDX], case_cfg_mem[CFG_N_IDX], case_cfg_mem[CFG_M_IDX],
                 case_cfg_mem[CFG_16BITS_IA_IDX][0],
                 case_cfg_mem[CFG_DATAFLOW_MODE_IDX][0] ? "IS" : "WS",
                 case_cfg_mem[CFG_IA_REUSE_NUM_IDX], case_cfg_mem[CFG_W_REUSE_NUM_IDX],
                 compare_words, full_mem_check ? "full" : "dst");

        if ($test$plusargs("WAVE")) begin
            $dumpfile("wave.vcd");
            $dumpvars(0, tb_mma_top);
        end

        $readmemh(init_mem_path, u_mem.mem_r);
        $readmemh(golden_mem_path, golden_mem);
    end

    // 使用 clocking block 触发计算
    initial begin
        wait (rst_n);
        repeat (5) @(posedge clk);
        calc_start <= 1'b1;
        @(posedge clk);
        calc_start <= 1'b0;
    end

    // 校验
    initial begin
        @(posedge rst_n);

        // 等待 calc_start 被触发
        @(posedge calc_start);
        $display("[TB] calc_start triggered at time %0t", $time);

        // 等待 sa_ready 变为 0（计算开始）
        wait (sa_ready == 1'b0);
        $display("[TB] Computation started (sa_ready=0) at time %0t", $time);

        // 等待 sa_ready 恢复为 1（计算完成）
        wait (sa_ready == 1'b1);
        $display("[TB] Computation done (sa_ready=1) at time %0t", $time);
        if (err_code != 2'b00) begin
            $display("[TB] FAIL, err_code=%0b", err_code);
            $finish;
        end

        // 额外等待几个周期确保结果写入完成
        repeat (10) @(posedge clk);

        err = 0;
        if (full_mem_check) begin
            for (int i = 0; i < int'(compare_words); i++) begin
                if (u_mem.mem_r[i] !== golden_mem[i]) begin
                    if (err < 32) begin
                        $display("[TB][MISMATCH] word %0d: got=%08x exp=%08x", i,
                                 u_mem.mem_r[i], golden_mem[i]);
                    end
                    err++;
                end
            end
        end else begin
            for (int row = 0; row < int'(case_cfg_mem[CFG_K_IDX]); row++) begin
                for (int col = 0; col < int'(case_cfg_mem[CFG_M_IDX]); col++) begin
                    int unsigned byte_addr;
                    logic [7:0] got_byte;
                    logic [7:0] exp_byte;
                    byte_addr = case_cfg_mem[CFG_DST_BASE_IDX] +
                                row * case_cfg_mem[CFG_DST_ROW_STRIDE_B_IDX] + col;
                    got_byte = actual_mem_byte(byte_addr);
                    exp_byte = golden_mem_byte(byte_addr);
                    if (got_byte !== exp_byte) begin
                        if (err < 32) begin
                            $display("[TB][MISMATCH] dst[%0d,%0d] addr=%08x got=%02x exp=%02x",
                                     row, col, byte_addr, got_byte, exp_byte);
                        end
                        err++;
                    end
                end
            end
        end
        if (err == 0) $display("[TB] PASS");
        else $display("[TB] FAIL, err=%0d", err);
        $finish;
    end

    initial begin
        #20000000;
        $display("[TB] FATAL: timeout, sa_ready=%0b wb_valid=%0b err_code=%0b",
                 sa_ready, wb_valid, err_code);
        $display("[TB][DBG] ctrl_state=%0d icb_sel=%0d ia_valid=%0b ia_done=%0b w_valid=%0b w_done=%0b bias_valid=%0b bias_sleep=%0b quant_valid=%0b tile_calc_over=%0b oa_calc_over=%0b",
                 u_dut.u_mma_controller.current_state,
                 u_dut.icb_sel,
                 u_dut.ia_data_valid,
                 u_dut.ia_sending_done,
                 u_dut.weight_data_valid,
                 u_dut.weight_sending_done,
                 u_dut.bias_valid,
                 u_dut.bias_sleep,
                 u_dut.quant_params_valid,
                 u_dut.tile_calc_over,
                 u_dut.oa_calc_over);
        $display("[TB][DBG] ia_ctrl_state=%0d ia_l2=%0d ia_l1=%0d ia_w=%0d ia_idx=%0d ia_all_done=%0b",
                 u_dut.u_ia_loader.u_ctrl.state,
                 u_dut.u_ia_loader.u_ctrl.l2_idx,
                 u_dut.u_ia_loader.u_ctrl.l1_idx,
                 u_dut.u_ia_loader.u_ctrl.w_cnt,
                 u_dut.u_ia_loader.u_ctrl.ia_idx,
                 u_dut.u_ia_loader.ctrl_all_done);
        $display("[TB][DBG] w_ctrl_state=%0d w_tile_row=%0d w_l2=%0d w_col=%0d w_rep=%0d w_all_done=%0b",
                 u_dut.u_kernel_loader.u_ctrl.state,
                 u_dut.u_kernel_loader.u_ctrl.cur_tile_row,
                 u_dut.u_kernel_loader.u_ctrl.cur_l2,
                 u_dut.u_kernel_loader.u_ctrl.cur_col_in_group,
                 u_dut.u_kernel_loader.u_ctrl.cur_repeat,
                 u_dut.u_kernel_loader.ctrl_all_done);
        $display("[TB][DBG] oa_state=%0d tiles_done=%0d tile_row=%0d tile_col=%0d write_req=%0b write_done=%0b",
                 u_dut.u_oa_writer.state,
                 u_dut.u_oa_writer.tiles_done,
                 u_dut.u_oa_writer.tile_row_idx,
                 u_dut.u_oa_writer.tile_col_idx,
                 u_dut.write_oa_req,
                 u_dut.write_done);
        $display("[TB][DBG] oa has_grant=%0b cmd_pending=%0b cmd_inflight=%0b rsp_inflight=%0b tile_done_pending=%0b beats_in_row=%0d beats_per_row=%0d row_in_tile=%0d out_ready_cond=%0b cmd_fire=%0b beat_fire=%0b rsp_fire=%0b",
                 u_dut.u_oa_writer.has_grant,
                 u_dut.u_oa_writer.cmd_pending,
                 u_dut.u_oa_writer.cmd_inflight,
                 u_dut.u_oa_writer.rsp_inflight,
                 u_dut.u_oa_writer.tile_done_pending,
                 u_dut.u_oa_writer.beats_in_row,
                 u_dut.u_oa_writer.beats_per_row,
                 u_dut.u_oa_writer.row_in_tile,
                 u_dut.u_oa_writer.writer_ready_cond,
                 u_dut.u_oa_writer.cmd_fire,
                 u_dut.u_oa_writer.beat_fire,
                 u_dut.u_oa_writer.rsp_fire);
        $display("[TB][DBG] fifo req=%0b full=%0b stream=%0b ready0=%0b ready1=%0b read_sel=%0b write_sel=%0b out_v=%0b out_r=%0b bank_count0=%0d bank_count1=%0d",
                 u_dut.fifo_output_req,
                 u_dut.fifo_full_flag,
                 u_dut.u_vec_s8_to_fifo.stream_active,
                 u_dut.u_vec_s8_to_fifo.bank_ready0,
                 u_dut.u_vec_s8_to_fifo.bank_ready1,
                 u_dut.u_vec_s8_to_fifo.read_sel,
                 u_dut.u_vec_s8_to_fifo.write_sel,
                 u_dut.fifo_output_valid,
                 u_dut.fifo_output_ready,
                 u_dut.u_vec_s8_to_fifo.bank_count0,
                 u_dut.u_vec_s8_to_fifo.bank_count1);
        $display("[TB][DBG] dma_arb active=%0b client=%0d started=%0b dma_busy=%0b dma_done=%0b icb_cmd_v=%0b icb_cmd_r=%0b icb_rsp_v=%0b icb_rsp_r=%0b",
                 u_dut.u_block_dma_arbiter.active,
                 u_dut.u_block_dma_arbiter.active_client,
                 u_dut.u_block_dma_arbiter.dma_started,
                 u_dut.u_block_dma_arbiter.dma_busy,
                 u_dut.u_block_dma_arbiter.dma_done,
                 u_dut.u_block_dma_arbiter.icb_cmd_valid,
                 icb_cmd_ready,
                 icb_rsp_valid,
                 icb_rsp_ready);
        $display("[TB][DBG] dma row cmd=%0d rsp_row=%0d rsp_beat=%0d rd_inflight=%0b active=%0b tile_done=%0b",
                 u_dut.u_block_dma_arbiter.u_dma.cmd_row_cnt,
                 u_dut.u_block_dma_arbiter.u_dma.rsp_row_cnt,
                 u_dut.u_block_dma_arbiter.u_dma.rsp_beat_cnt,
                 u_dut.u_block_dma_arbiter.u_dma.rd_cmd_inflight,
                 u_dut.u_block_dma_arbiter.u_dma.active,
                 u_dut.u_block_dma_arbiter.u_dma.tile_done);
        $display("[TB][DBG] ddr state=%0d wait=%0d rsp_left=%0d cmd_v=%0b cmd_r=%0b w_v=%0b w_r=%0b rsp_v=%0b rsp_r=%0b read=%0b addr=%h",
                 u_mem.state,
                 u_mem.wait_cnt,
                 u_mem.rsp_left,
                 icb_cmd_valid,
                 icb_cmd_ready,
                 icb_w_valid,
                 icb_w_ready,
                 icb_rsp_valid,
                 icb_rsp_ready,
                 u_mem.cmd_read_r,
                 u_mem.cmd_addr_r);
        $display("[TB][DBG] counts acc=%0d requant=%0d fifo_req=%0d write_done=%0d tile_calc_over=%0d ia_rise=%0d ia_calc_done_cycles=%0d",
                 acc_valid_count,
                 requant_valid_count,
                 fifo_req_count,
                 write_done_count,
                 tile_calc_over_count,
                 ia_row_valid_rise_count,
                 ia_calc_done_count);
        $finish;
    end

endmodule
