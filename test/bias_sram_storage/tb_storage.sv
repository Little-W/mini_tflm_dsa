`timescale 1ns/1ps

module tb_bias_sram_storage #(
    parameter integer p_bus_width = 64,
    parameter integer p_group_blocks = 32,
    parameter integer p_cycles = 32768
);
    localparam integer SIZE = 16;
    localparam integer BYTES = p_bus_width / 8;
    localparam integer GROUP_ADDR_W = $clog2(p_group_blocks * SIZE);
    logic clk = 1'b0;
    always #5 clk = ~clk;
    logic rst_n = 1'b0;
    logic init_cfg = 1'b0, load_start = 1'b0, load_bank = 1'b0;
    logic [28:0] load_block_idx = '0, load_blocks_count = p_group_blocks;
    logic [28:0] group_blocks_needed = 1, current_block_idx = '0;
    logic load_word_valid [BYTES];
    logic [31:0] load_word_row = '0;
    logic [5:0] load_word_col_base = '0;
    logic signed [7:0] load_word_data [BYTES];
    logic load_done = 1'b0, active_bank = 1'b0;
    logic is_mode = 1'b1, group_read_start = 1'b0;
    logic [GROUP_ADDR_W-1:0] group_read_idx = '0;
    wire dut_bias_valid, dut_load_block_valid, dut_load_block_bank;
    wire ref_bias_valid, ref_load_block_valid, ref_load_block_bank;
    wire signed [31:0] dut_data_out [SIZE], ref_data_out [SIZE];
    wire signed [31:0] dut_group_data_scalar, ref_group_data_scalar;
    integer cycles = 0, comparisons = 0, partial_writes = 0;
    integer unknown_inputs = 0, mode_changes = 0, random_seed = 32'h513892ab;
    integer write_reads_same_bank = 0, single_byte_writes = 0;
    integer reset_cycles = 0, init_cycles = 0;
    logic [BYTES-1:0] mask;
    logic last_mode = 1'b1;

    bias_loader_buffer #(
        .SIZE(SIZE), .BUS_WIDTH(p_bus_width), .COUNT_WIDTH(29),
        .GROUP_BLOCKS_MAX(p_group_blocks)
    ) dut (
        .clk, .rst_n, .init_cfg, .load_start, .load_bank,
        .load_block_idx, .load_blocks_count, .group_blocks_needed,
        .load_word_valid, .load_word_row, .load_word_col_base, .load_word_data,
        .load_done, .active_bank, .current_block_idx, .is_mode,
        .group_read_start, .group_read_idx,
        .bias_valid(dut_bias_valid), .load_block_valid(dut_load_block_valid),
        .load_block_bank(dut_load_block_bank), .data_out(dut_data_out),
        .group_data_scalar(dut_group_data_scalar)
    );

    bias_loader_buffer_reference #(
        .SIZE(SIZE), .BUS_WIDTH(p_bus_width), .COUNT_WIDTH(29),
        .GROUP_BLOCKS_MAX(p_group_blocks)
    ) reference (
        .clk, .rst_n, .init_cfg, .load_start, .load_bank,
        .load_block_idx, .load_blocks_count, .group_blocks_needed,
        .load_word_valid, .load_word_row, .load_word_col_base, .load_word_data,
        .load_done, .active_bank, .current_block_idx, .is_mode,
        .group_read_start, .group_read_idx,
        .bias_valid(ref_bias_valid), .load_block_valid(ref_load_block_valid),
        .load_block_bank(ref_load_block_bank), .data_out(ref_data_out),
        .group_data_scalar(ref_group_data_scalar)
    );

    task automatic tick;
        @(posedge clk);
        #1;
        cycles++;
        if ({dut_bias_valid, dut_load_block_valid, dut_load_block_bank} !==
            {ref_bias_valid, ref_load_block_valid, ref_load_block_bank})
            $fatal(1, "Bias control mismatch cycle=%0d", cycles);
        if (dut_group_data_scalar !== ref_group_data_scalar)
            $fatal(1, "Bias scalar mismatch cycle=%0d got=%h expected=%h",
                   cycles, dut_group_data_scalar, ref_group_data_scalar);
        for (integer lane = 0; lane < SIZE; lane++) begin
            if (dut_data_out[lane] !== ref_data_out[lane])
                $fatal(1, "Bias vector mismatch cycle=%0d lane=%0d got=%h expected=%h",
                       cycles, lane, dut_data_out[lane], ref_data_out[lane]);
        end
        comparisons += SIZE + 2;
        if (!rst_n) reset_cycles++;
        if (init_cfg) init_cycles++;
        @(negedge clk);
    endtask

    task automatic set_mask(input logic [BYTES-1:0] value);
        for (integer byte_i = 0; byte_i < BYTES; byte_i++)
            load_word_valid[byte_i] = value[byte_i];
    endtask

    task automatic random_data;
        for (integer byte_i = 0; byte_i < BYTES; byte_i++)
            load_word_data[byte_i] = 8'($random(random_seed));
    endtask

    initial begin
        set_mask('0);
        random_data();
        repeat (2) tick();
        rst_n = 1'b1;
        init_cfg = 1'b1;
        tick();
        init_cfg = 1'b0;

        // 两个 bank 的所有逻辑行都执行写入，读取地址同时覆盖首尾位置。
        for (integer bank = 0; bank < 2; bank++) begin
            load_bank = 1'(bank);
            load_start = 1'b1;
            tick();
            load_start = 1'b0;
            for (integer row = 0; row < p_group_blocks; row++) begin
                for (integer col = 0; col < SIZE * 4; col += BYTES) begin
                    load_word_row = 32'(row);
                    load_word_col_base = 6'(col);
                    set_mask('1);
                    random_data();
                    active_bank = 1'(bank);
                    group_read_start = col == 0;
                    current_block_idx = 29'(row);
                    group_read_idx = GROUP_ADDR_W'(col / 4);
                    tick();
                end
            end
            set_mask('0);
            load_done = 1'b1;
            tick();
            load_done = 1'b0;
            tick();
        end

        // 任意字节掩码与反复写入同一行检查部分数据保存，期间持续切换读 bank。
        for (integer sample = 0; sample < p_cycles; sample++) begin
            rst_n = (sample % 1021) != 0;
            init_cfg = (sample % 257) == 0;
            load_start = (sample % 127) == 0;
            load_done = (sample % 29) == 0;
            load_bank = 1'($random(random_seed));
            active_bank = 1'($random(random_seed));
            load_block_idx = 29'($random(random_seed));
            load_blocks_count = 29'($unsigned($random(random_seed)) % (p_group_blocks + 1));
            group_blocks_needed = 29'($unsigned($random(random_seed)) % (p_group_blocks + 1));
            current_block_idx = 29'($random(random_seed));
            load_word_row = 32'($unsigned($random(random_seed)) % (p_group_blocks + 2));
            load_word_col_base = 6'(($unsigned($random(random_seed)) % (SIZE * 4 / BYTES)) * BYTES);
            is_mode = (sample / 31) % 2;
            group_read_start = (sample % 13) == 0;
            group_read_idx = GROUP_ADDR_W'($random(random_seed));
            mask = BYTES'($random(random_seed));
            if (sample % 7 == 0) mask = BYTES'(1) << (sample % BYTES);
            if (sample % 9 == 0) mask = '1;
            if (sample % 11 == 0) mask = '0;
            set_mask(mask);
            random_data();
            if (sample % 3 == 0) begin
                load_word_row = 0;
                load_word_col_base = 0;
                active_bank = load_bank;
                current_block_idx = load_block_idx;
                group_read_start = 1'b1;
                group_read_idx = 0;
            end
            if ((|mask) && !(&mask)) partial_writes++;
            if ($countones(mask) == 1) single_byte_writes++;
            if ((|mask) && active_bank == load_bank) write_reads_same_bank++;
            if (last_mode != is_mode) mode_changes++;
            last_mode = is_mode;
            // 四态输入影响数据、有效位、行号和读取索引；对所有输出使用严格比较。
            if (sample % 37 == 0) begin
                load_word_data[sample % BYTES][sample % 8] = 1'bx;
                unknown_inputs++;
            end
            if (sample % 41 == 0) begin
                load_word_valid[sample % BYTES] = 1'bx;
                unknown_inputs++;
            end
            if (sample % 43 == 0) begin
                load_word_row[sample % 32] = 1'bx;
                unknown_inputs++;
            end
            if (sample % 47 == 0) begin
                group_read_idx[sample % GROUP_ADDR_W] = 1'bz;
                unknown_inputs++;
            end
            if (sample % 53 == 0) begin
                load_word_col_base[sample % 6] = 1'bx;
                unknown_inputs++;
            end
            tick();
        end
        set_mask('0);
        init_cfg = 1'b0;
        load_start = 1'b0;
        load_done = 1'b0;
        repeat (8) tick();
        if (partial_writes == 0 || single_byte_writes == 0 || mode_changes == 0 ||
            unknown_inputs == 0 || write_reads_same_bank == 0)
            $fatal(1, "Missing Bias storage coverage");
        $display("BIAS_STORAGE_PASS cycles=%0d comparisons=%0d partial_writes=%0d single_byte_writes=%0d unknown_inputs=%0d mode_changes=%0d same_bank_cycles=%0d resets=%0d initializations=%0d",
                 cycles, comparisons, partial_writes, single_byte_writes, unknown_inputs,
                 mode_changes, write_reads_same_bank, reset_cycles, init_cycles);
        $finish;
    end
endmodule
