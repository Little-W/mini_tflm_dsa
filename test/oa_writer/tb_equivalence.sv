`timescale 1ns/1ps
module tb_oa_writer_equivalence #(
    parameter int VLEN = 16,
    parameter int BUS_WIDTH = 64,
    parameter int COUNT_WIDTH = 16,
    parameter int SCENARIOS = 512,
    parameter int CYCLES_PER_SCENARIO = 2048
);
    logic clk = 0;
    logic rst_n = 0;
    logic init_cfg = 0;
    logic write_oa_granted = 0;
    logic [31:0] dst_base = 0, dst_row_stride_b = 0, k = 0, m = 0, ia_reuse_num = 0;
    logic is_mode = 0, output_16bits = 0, coalesce_enable = 0;
    logic [4:0] coalesce_cols = 0;
    logic oa_fifo_req = 0, output_valid = 0, switch_row = 0;
    logic [BUS_WIDTH/8-1:0] output_mask = 0;
    logic [BUS_WIDTH-1:0] output_data = 0;
    logic dma_src_wready = 0, dma_busy = 0, dma_done = 0;

    typedef struct packed {
        logic write_oa_req, coalesce_group_start;
        logic [4:0] coalesce_row_tiles;
        logic [$clog2(VLEN)-1:0] vec_valid_num_col, vec_valid_num_row;
        logic output_ready, dma_start, dma_is_write, dma_linear_read_mode;
        logic [31:0] dma_base_addr, dma_row_stride, dma_rows_to_read;
        logic [7:0] dma_burst_len_m1;
        logic dma_slot_id, dma_use_16bits;
        logic [31:0] dma_lhs_zp;
        logic [BUS_WIDTH-1:0] dma_src_wdata;
        logic [BUS_WIDTH/8-1:0] dma_src_wmask;
        logic dma_src_wvalid, write_done, oa_calc_over;
    } outputs_t;
    outputs_t actual, expected;

`define OA_PORTS(target) \
    .clk(clk), .rst_n(rst_n), .init_cfg(init_cfg), .write_oa_granted(write_oa_granted), \
    .dst_base(dst_base), .dst_row_stride_b(dst_row_stride_b), .k(k), .m(m), \
    .ia_reuse_num(ia_reuse_num), .is_mode(is_mode), .output_16bits(output_16bits), \
    .coalesce_enable(coalesce_enable), .coalesce_cols(coalesce_cols), \
    .oa_fifo_req(oa_fifo_req), .output_valid(output_valid), .switch_row(switch_row), \
    .output_mask(output_mask), .output_data(output_data), .dma_src_wready(dma_src_wready), \
    .dma_busy(dma_busy), .dma_done(dma_done), \
    .write_oa_req(target.write_oa_req), .coalesce_group_start(target.coalesce_group_start), \
    .coalesce_row_tiles(target.coalesce_row_tiles), .vec_valid_num_col(target.vec_valid_num_col), \
    .vec_valid_num_row(target.vec_valid_num_row), .output_ready(target.output_ready), \
    .dma_start(target.dma_start), .dma_is_write(target.dma_is_write), \
    .dma_linear_read_mode(target.dma_linear_read_mode), .dma_base_addr(target.dma_base_addr), \
    .dma_row_stride(target.dma_row_stride), .dma_rows_to_read(target.dma_rows_to_read), \
    .dma_burst_len_m1(target.dma_burst_len_m1), .dma_slot_id(target.dma_slot_id), \
    .dma_use_16bits(target.dma_use_16bits), .dma_lhs_zp(target.dma_lhs_zp), \
    .dma_src_wdata(target.dma_src_wdata), .dma_src_wmask(target.dma_src_wmask), \
    .dma_src_wvalid(target.dma_src_wvalid), .write_done(target.write_done), \
    .oa_calc_over(target.oa_calc_over)

    oa_writer #(.VLEN(VLEN), .BUS_WIDTH(BUS_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) u_dut (
        `OA_PORTS(actual)
    );
    oa_writer_ref #(.VLEN(VLEN), .BUS_WIDTH(BUS_WIDTH), .COUNT_WIDTH(COUNT_WIDTH)) u_ref (
        `OA_PORTS(expected)
    );
`undef OA_PORTS

    int unsigned cycle_count = 0, scenario = 0, command_count = 0;
    int unsigned group_count = 0, completion_count = 0, interrupted_count = 0;
    int unsigned dma_delay = 0, settle_cycles = 0;
    bit pending_dma = 0, finished = 0;
    logic [31:0] random_state = 32'h3b1587ad;

    function automatic logic [31:0] random_word();
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        return random_state;
    endfunction

    task automatic compare_outputs();
        if (actual !== expected) begin
            $display("OA_WRITER_EQ_FAIL scenario=%0d cycle=%0d VLEN=%0d BUS=%0d COUNT=%0d",
                     scenario, cycle_count, VLEN, BUS_WIDTH, COUNT_WIDTH);
            $display("actual=%h expected=%h", actual, expected);
            $display("row_tiles=%0d/%0d rows=%0d/%0d addr=%h/%h state=%0d/%0d",
                     actual.coalesce_row_tiles, expected.coalesce_row_tiles,
                     actual.dma_rows_to_read, expected.dma_rows_to_read,
                     actual.dma_base_addr, expected.dma_base_addr, u_dut.state, u_ref.state);
            $fatal(1, "全部公开输出必须逐周期一致");
        end
    endtask

    task automatic tick();
        #1;
        if (cycle_count != 0) compare_outputs();
        if (rst_n && !init_cfg && expected.dma_start) begin
            command_count++;
            pending_dma = 1;
            dma_delay = 1 + random_word() % 47;
        end
        if (rst_n && !init_cfg && expected.coalesce_group_start) group_count++;
        clk = 1;
        #1;
        cycle_count++;
        compare_outputs();
        if (expected.oa_calc_over) begin
            completion_count++;
            finished = 1;
        end
        clk = 0;
        #1;
    endtask

    task automatic set_configuration();
        dst_base = random_word();
        dst_row_stride_b = random_word();
        k = 1 + random_word() % 1536;
        m = 1 + random_word() % 256;
        case (scenario % 16)
            0: begin k = 0; m = 32; end
            1: begin k = 1; m = 1; end
            2: begin k = VLEN - 1; m = VLEN + 1; end
            3: begin k = VLEN; m = VLEN; end
            4: begin k = VLEN + 1; m = VLEN * 2 - 1; end
            5: begin k = 2048; m = 64; end
            6: begin k = 32'hffffffff; m = 32; end
            7: begin k = 32'hfffffffe; m = 32'hfffffff0; end
            8: begin k = 512; m = 64; end
            9: begin k = 513; m = 128; end
            10: begin k = 1024; m = 256; end
            11: begin k = 32'h00010001; m = 16; end
            default: begin end
        endcase
        case ((scenario / 3) % 12)
            0: ia_reuse_num = 0;
            1: ia_reuse_num = 1;
            2: ia_reuse_num = 2;
            3: ia_reuse_num = 4;
            4: ia_reuse_num = 8;
            5: ia_reuse_num = 16;
            6: ia_reuse_num = 25;
            7: ia_reuse_num = 32;
            8: ia_reuse_num = 64;
            9: ia_reuse_num = 256;
            10: ia_reuse_num = 32'h00010001;
            11: ia_reuse_num = 32'hffffffff;
        endcase
        is_mode = (scenario / 2) % 2;
        coalesce_enable = scenario % 2;
        output_16bits = (scenario / 4) % 2;
        coalesce_cols = 5'(1 << ((scenario / 8) % 5));
        if ((scenario % 19) == 0) coalesce_cols = 0;
        if ((scenario % 23) == 0) coalesce_cols = 31;
    endtask

    initial begin
        tick();
        tick();
        rst_n = 1;
        for (scenario = 0; scenario < SCENARIOS; scenario++) begin
            if ((scenario % 8) == 0) begin
                rst_n = 0;
                tick();
                rst_n = 1;
            end
            if (pending_dma) interrupted_count++;
            pending_dma = 0;
            dma_busy = 0;
            dma_done = 0;
            write_oa_granted = 0;
            finished = 0;
            settle_cycles = 0;
            set_configuration();
            init_cfg = 1;
            tick();
            init_cfg = 0;
            for (int step = 0; step < CYCLES_PER_SCENARIO; step++) begin
                oa_fifo_req = random_word() % 4 != 0;
                output_valid = random_word() % 3 != 0;
                switch_row = random_word()[0];
                output_data = BUS_WIDTH'({random_word(), random_word()});
                output_mask = (BUS_WIDTH/8)'(random_word());
                dma_src_wready = random_word() % 5 != 0;
                write_oa_granted = expected.write_oa_req && random_word() % 4 != 0;
                dma_done = pending_dma && dma_delay == 0;
                if (dma_done) pending_dma = 0;
                if (pending_dma) dma_delay--;
                dma_busy = pending_dma;
                // 配置只在 init_cfg 接收；运行期间变化不应影响当前传输。
                if (step == 8) begin
                    dst_base = random_word(); dst_row_stride_b = random_word();
                    k = random_word(); m = random_word(); ia_reuse_num = random_word();
                    is_mode = random_word()[0]; output_16bits = random_word()[0];
                    coalesce_enable = random_word()[0]; coalesce_cols = 5'(random_word());
                end
                tick();
                if (finished) settle_cycles++;
                if (settle_cycles == 12) break;
                // 穿插配置重载，覆盖等待授权、数据传输和响应等待阶段。
                if ((scenario % 17) == 0 && step == 71) break;
            end
        end
        $display("OA_WRITER_EQ_PASS scenarios=%0d cycles=%0d outputs=21 commands=%0d groups=%0d completions=%0d interrupted=%0d",
                 SCENARIOS, cycle_count, command_count, group_count, completion_count, interrupted_count);
        $finish;
    end
endmodule
