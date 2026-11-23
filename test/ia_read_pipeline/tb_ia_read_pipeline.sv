// 检查本地与外部 RAM 的连续读出、相邻组属性及复位清空。
module tb_ia_read_pipeline #(
    parameter bit COMPACT_ENABLE = 1'b1,
    parameter bit SHARED_WRITE_STAGE = 1'b1
);
    localparam int CACHE_BLOCKS = 4;
    localparam int SLOT_BLOCKS = COMPACT_ENABLE ? 2 * CACHE_BLOCKS : CACHE_BLOCKS;
    localparam int SLOT_WIDTH = $clog2(SLOT_BLOCKS);
    localparam int RAM_WORDS = CACHE_BLOCKS * 32;
    localparam int WORD_WIDTH = $clog2(RAM_WORDS);
    localparam int READ_STAGES = COMPACT_ENABLE ? 3 : 2;
    logic clk = 0, rst_n = 0;
    logic compact_mode = 0;
    logic signed [15:0] compact_offset = 0;
    logic [SLOT_WIDTH-1:0] wr_slot, l1_slot_start, l1_slot_end;
    logic [3:0] wr_row, wr_col_base;
    logic signed [15:0] wr_data [8];
    logic wr_valid [8];
    logic l1_start = 0, l1_is_init, l1_calc_done;
    logic [4:0] slot_rows [SLOT_BLOCKS];
    logic [1:0] write_enable, read_enable;
    logic [WORD_WIDTH-1:0] write_address [2], read_address [2];
    logic [127:0] write_data [2], read_data [2], memory [RAM_WORDS];
    logic [15:0] write_mask [2];
    logic signed [15:0] data [2][16];
    logic valid [2], is_init [2], calc_done [2];
    logic tile_done [2], group_done [2], tile_start [2];
    logic signed [15:0] reference_data [SLOT_BLOCKS][16][16];
    int written_columns [SLOT_BLOCKS];
    int write_offset, cycle_count = 0, queue_count = 0;
    int value_checks = 0, row_checks = 0, reset_checks = 0;

    typedef struct {
        int due_cycle;
        bit first;
        bit last;
        bit group_last;
        bit init_flag;
        bit final_flag;
        logic signed [15:0] values [16];
    } expected_row_t;
    expected_row_t expected_rows [1024];

    for (genvar implementation = 0; implementation < 2; implementation++) begin : g_manager
        ia_loader_cache_mgr #(
            .DATA_WIDTH(16), .SIZE(16), .BUS_WIDTH(64), .DMA_LANES(8),
            .CACHE_BLOCKS(CACHE_BLOCKS), .COMPACT_S8(32'(COMPACT_ENABLE)),
            .EXTERNAL_RAM(implementation == 1), .RAM_WORD_ADDR_WIDTH(WORD_WIDTH),
            .p_compact_offset_width(9), .p_dma_source_layout(1'b1),
            .p_shared_write_stage(SHARED_WRITE_STAGE)
        ) u_manager (
            .clk, .rst_n, .compact_mode, .compact_offset,
            .cfg_cache_blocks(32'd0), .cfg_slot_mask('0), .slot_base('0),
            .ram_port_wr_en(local_write_enable),
            .ram_port_wr_addr(local_write_address),
            .ram_port_wr_data(local_write_data),
            .ram_port_wr_mask(local_write_mask),
            .ram_shared_wr_data(),
            .ram_port_rd_en(local_read_enable),
            .ram_port_rd_addr(local_read_address),
            .ram_port_rd_data(read_data),
            .wr_slot, .wr_row, .wr_col_base, .wr_data, .wr_valid, .wr_use_16bits(1'b0),
            .l1_start, .l1_slot_start, .l1_slot_end, .l1_is_init, .l1_calc_done,
            .slot_rows, .row_table_index(), .row_table_value('{default:'0}),
            .tile_done(tile_done[implementation]), .l1_done(group_done[implementation]),
            .ia_tile_start(tile_start[implementation]), .ia_out(data[implementation]),
            .ia_row_valid(valid[implementation]), .ia_is_init_data(is_init[implementation]),
            .ia_calc_done(calc_done[implementation])
        );
        logic [1:0] local_write_enable, local_read_enable;
        logic [WORD_WIDTH-1:0] local_write_address [2], local_read_address [2];
        logic [127:0] local_write_data [2];
        logic [15:0] local_write_mask [2];
        if (implementation == 1) begin : g_external_ports
            assign write_enable = local_write_enable;
            assign write_address = local_write_address;
            assign write_data = local_write_data;
            assign write_mask = local_write_mask;
            assign read_enable = local_read_enable;
            assign read_address = local_read_address;
        end
    end

    // 外部接口使用同拍独立读写和字节写掩码，物理容量固定为 2048 字节。
    always @(posedge clk) begin
        for (int port_index = 0; port_index < 2; port_index++) begin
            if (write_enable[port_index]) begin
                assert (int'(write_address[port_index]) < RAM_WORDS);
                for (int byte_index = 0; byte_index < 16; byte_index++)
                    if (write_mask[port_index][byte_index])
                        memory[write_address[port_index]][byte_index*8 +: 8] <=
                            write_data[port_index][byte_index*8 +: 8];
            end
            if (read_enable[port_index]) begin
                assert (int'(read_address[port_index]) < RAM_WORDS);
                read_data[port_index] <= memory[read_address[port_index]];
            end
        end
    end

    task automatic tick;
        bit expected_first;
        int expected_index;
        clk = 0;
        #1;
        expected_first = 0;
        for (int index = 0; index < queue_count; index++)
            expected_first |= expected_rows[index].first &&
                expected_rows[index].due_cycle - 2 == cycle_count;
        if (rst_n)
            for (int implementation = 0; implementation < 2; implementation++)
                assert (tile_start[implementation] == expected_first)
                    else $fatal(1, "Tile start cycle=%0d implementation=%0d", cycle_count, implementation);
        clk = 1;
        #1;
        cycle_count++;
        expected_index = -1;
        for (int index = 0; index < queue_count; index++)
            if (expected_rows[index].due_cycle == cycle_count) expected_index = index;
        for (int implementation = 0; implementation < 2; implementation++) begin
            assert (valid[implementation] == (expected_index >= 0 && rst_n))
                else $fatal(1, "Row valid cycle=%0d implementation=%0d", cycle_count, implementation);
            if (expected_index >= 0 && rst_n) begin
                assert (is_init[implementation] == expected_rows[expected_index].init_flag);
                assert (calc_done[implementation] == expected_rows[expected_index].final_flag);
                assert (tile_done[implementation] == expected_rows[expected_index].last);
                assert (group_done[implementation] == expected_rows[expected_index].group_last);
                for (int lane = 0; lane < 16; lane++) begin
                    assert (data[implementation][lane] == expected_rows[expected_index].values[lane])
                        else $fatal(1, "Data cycle=%0d implementation=%0d lane=%0d actual=%0d expected=%0d",
                            cycle_count, implementation, lane, data[implementation][lane],
                            expected_rows[expected_index].values[lane]);
                    value_checks++;
                end
                row_checks++;
            end else begin
                assert (!is_init[implementation] && !calc_done[implementation] &&
                    !tile_done[implementation] && !group_done[implementation]);
                for (int lane = 0; lane < 16; lane++) assert (data[implementation][lane] == 0);
                if (!rst_n) reset_checks++;
            end
        end
        clk = 0;
        #1;
    endtask

    task automatic fill_cache;
        int value, columns;
        for (int slot = 0; slot < (COMPACT_ENABLE && compact_mode ? SLOT_BLOCKS : CACHE_BLOCKS); slot++) begin
            slot_rows[slot] = 5'(1 + (slot * 5) % 16);
            columns = 1 + (slot * 7) % 16;
            written_columns[slot] = columns;
            for (int row = 0; row < int'(slot_rows[slot]); row++) begin
                for (int column = 0; column < columns; column += 8) begin
                    wr_slot = SLOT_WIDTH'(slot);
                    wr_row = 4'(row);
                    wr_col_base = 4'(column);
                    for (int lane = 0; lane < 8; lane++) begin
                        wr_valid[lane] = column + lane < columns;
                        value = COMPACT_ENABLE && compact_mode ?
                            ((slot * 31 + row * 17 + (column + lane) * 13) % 256) - 128 + write_offset :
                            32'h5a80 + slot * 131 + row * 511 + (column + lane) * 37;
                        if ((column + lane) % 3 == 0) value = 0;
                        wr_data[lane] = 16'(value);
                        if (wr_valid[lane]) reference_data[slot][row][column + lane] = 16'(value);
                    end
                    tick();
                end
            end
        end
        wr_valid = '{default:0};
        repeat (2) tick();
    endtask

    task automatic send_group(input int first_slot, last_slot, input bit init_flag, final_flag);
        int slot, rows;
        slot = first_slot;
        rows = 0;
        do begin
            for (int row = 0; row < int'(slot_rows[slot]); row++) begin
                assert (queue_count < 1024);
                expected_rows[queue_count].due_cycle = cycle_count + READ_STAGES + rows;
                expected_rows[queue_count].first = row == 0;
                expected_rows[queue_count].last = row + 1 == int'(slot_rows[slot]);
                expected_rows[queue_count].group_last = slot == last_slot &&
                    row + 1 == int'(slot_rows[slot]);
                expected_rows[queue_count].init_flag = init_flag;
                expected_rows[queue_count].final_flag = final_flag;
                for (int lane = 0; lane < 16; lane++)
                    expected_rows[queue_count].values[lane] = lane >= written_columns[slot] ? 16'd0 :
                        reference_data[slot][row][lane] +
                        (COMPACT_ENABLE && compact_mode ? compact_offset - 16'(write_offset) : 16'd0);
                queue_count++;
                rows++;
            end
            if (slot == last_slot) break;
            slot = (slot + 1) % (COMPACT_ENABLE && compact_mode ? SLOT_BLOCKS : CACHE_BLOCKS);
        end while (1);
        l1_slot_start = SLOT_WIDTH'(first_slot);
        l1_slot_end = SLOT_WIDTH'(last_slot);
        l1_is_init = init_flag;
        l1_calc_done = final_flag;
        l1_start = 1;
        tick();
        l1_start = 0;
        repeat (rows - 1) tick();
    endtask

    initial begin
        wr_valid = '{default:0};
        read_data = '{default:'0};
        tick();
        rst_n = 1;
        tick();
        for (int mode = 0; mode < 3; mode++) begin
            compact_mode = mode != 0;
            write_offset = mode == 1 ? -127 : 128;
            compact_offset = 16'(write_offset);
            fill_cache();
            send_group(0, (COMPACT_ENABLE && compact_mode ? SLOT_BLOCKS : CACHE_BLOCKS) - 1, 1, 0);
            send_group(2, 1, 0, 1);
            repeat (READ_STAGES + 1) tick();
            slot_rows[0] = 1;
            slot_rows[1] = 1;
            slot_rows[2] = 1;
            send_group(0, 0, 1, 0);
            compact_offset = 16'(mode == 1 ? 128 : -127);
            send_group(1, 1, 0, 1);
            compact_offset = 16'(write_offset);
            send_group(2, 2, 1, 1);
            repeat (READ_STAGES + 1) tick();
            send_group(0, 0, 0, 0);
            queue_count = 0;
            rst_n = 0;
            tick();
            rst_n = 1;
            repeat (READ_STAGES + 1) tick();
        end
        assert (value_checks > 1000 && row_checks > 100 && reset_checks == 8);
        $display("{\"passed\":true,\"compact_enabled\":%0d,\"shared_write_stage\":%0d,\"value_checks\":%0d,\"row_checks\":%0d,\"reset_checks\":%0d,\"physical_ram_bytes\":2048}",
            COMPACT_ENABLE, SHARED_WRITE_STAGE, value_checks, row_checks, reset_checks);
        $finish;
    end
endmodule
