`timescale 1ns/1ps
`ifndef TB_BUS_WIDTH
`define TB_BUS_WIDTH 64
`endif

module tb_writeback_bus;
    localparam int BUS_WIDTH = `TB_BUS_WIDTH;
    localparam int BYTES = BUS_WIDTH / 8;
    localparam int VLEN = 16;
    localparam int BANKS = 16;
    logic clk = 0;
    always #5 clk = !clk;
    logic rst_n = 0;
    logic in_valid = 0, in_tile_done = 0;
    logic [127:0] in_vec_s8 = 0;
    logic [255:0] in_vec_s16 = 0;
    logic transpose_mode = 0, coalesce_enable = 0, coalesce_group_start = 0;
    logic [31:0] coalesce_rows = 1, coalesce_cols = 1;
    logic [3:0] valid_col = 0, valid_row = 0;
    logic output_ready = 0;
    wire [BUS_WIDTH-1:0] full_data, linear_data, s16_data;
    wire [BYTES-1:0] full_mask, linear_mask, s16_mask;
    wire full_valid, linear_valid, s16_valid;
    wire full_switch, linear_switch, s16_switch;
    wire full_req, linear_req, s16_req;
    wire full_full, linear_full, s16_full;
    int select_fifo = 0;
    wire [BUS_WIDTH-1:0] data = select_fifo == 0 ? full_data :
        select_fifo == 1 ? linear_data : s16_data;
    wire [BYTES-1:0] mask = select_fifo == 0 ? full_mask :
        select_fifo == 1 ? linear_mask : s16_mask;
    wire valid = select_fifo == 0 ? full_valid :
        select_fifo == 1 ? linear_valid : s16_valid;
    wire row_switch = select_fifo == 0 ? full_switch :
        select_fifo == 1 ? linear_switch : s16_switch;

    vec_s8_to_fifo #(.VLEN(VLEN), .BANKS(BANKS), .BUS_WIDTH(BUS_WIDTH)) full_fifo (
        .clk, .rst_n, .in_valid(in_valid && select_fifo == 0), .in_tile_done,
        .in_vec_s8, .oa_fifo_req(full_req), .transpose_mode, .coalesce_enable,
        .coalesce_group_start, .coalesce_rows, .coalesce_cols, .reserve_banks(32'd1),
        .vec_valid_num_col(valid_col), .vec_valid_num_row(valid_row),
        .output_valid(full_valid), .output_ready(output_ready && select_fifo == 0),
        .output_row_switch(full_switch), .output_mask(full_mask), .output_data(full_data),
        .fifo_full_flag(full_full)
    );
    vec_s8_to_fifo #(.VLEN(VLEN), .BANKS(BANKS), .BUS_WIDTH(BUS_WIDTH),
        .ENABLE_TRANSPOSE(0)) linear_fifo (
        .clk, .rst_n, .in_valid(in_valid && select_fifo == 1), .in_tile_done,
        .in_vec_s8, .oa_fifo_req(linear_req), .transpose_mode(1'b0),
        .coalesce_enable(1'b0), .coalesce_group_start(1'b0),
        .coalesce_rows(32'd1), .coalesce_cols(32'd1), .reserve_banks(32'd1),
        .vec_valid_num_col(valid_col), .vec_valid_num_row(valid_row),
        .output_valid(linear_valid), .output_ready(output_ready && select_fifo == 1),
        .output_row_switch(linear_switch), .output_mask(linear_mask), .output_data(linear_data),
        .fifo_full_flag(linear_full)
    );
    vec_s16_to_fifo #(.VLEN(VLEN), .BANKS(BANKS), .BUS_WIDTH(BUS_WIDTH)) s16_fifo (
        .clk, .rst_n, .in_valid(in_valid && select_fifo == 2), .in_tile_done,
        .in_vec_s16, .oa_fifo_req(s16_req), .reserve_banks(32'd1),
        .vec_valid_num_col(valid_col), .output_valid(s16_valid),
        .output_ready(output_ready && select_fifo == 2), .output_row_switch(s16_switch),
        .output_mask(s16_mask), .output_data(s16_data), .fifo_full_flag(s16_full)
    );

    int tests = 0;
    int total_bytes = 0;
    int expected_rows, expected_cols, element_bytes;
    int received_row, received_col, received_bytes;
    bit checking = 0;
    bit held = 0;
    logic [BUS_WIDTH-1:0] held_data;
    logic [BYTES-1:0] held_mask;

    function automatic int value_at(input int row, input int col, input int width);
        return (row*137 + col*19 + 41) & (width == 1 ? 255 : 65535);
    endfunction

    always @(posedge clk) begin
        if (!rst_n || !checking) begin
            held = 0;
        end else begin
            if (held) begin
                assert(valid && data == held_data && mask == held_mask)
                    else $fatal(1, "output changed while backpressured");
            end
            held = valid && !output_ready;
            held_data = data;
            held_mask = mask;
            if (valid && output_ready) begin
                int accepted;
                accepted = 0;
                for (int lane = 0; lane < BYTES; ++lane) begin
                    bit expected_valid;
                    int expected_byte;
                    expected_valid = received_col*element_bytes + lane < expected_cols*element_bytes;
                    assert(mask[lane] == expected_valid)
                        else $fatal(1, "mask width=%0d fifo=%0d row=%0d col=%0d lane=%0d", BUS_WIDTH, select_fifo, received_row, received_col, lane);
                    if (expected_valid) begin
                        expected_byte = value_at(received_row, received_col + lane/element_bytes,
                            element_bytes) >> ((lane%element_bytes)*8);
                        assert(data[lane*8+:8] == 8'(expected_byte))
                            else $fatal(1, "data width=%0d fifo=%0d transpose=%0d coalesce=%0d row=%0d col=%0d lane=%0d actual=%0d expected=%0d",
                                BUS_WIDTH, select_fifo, transpose_mode, coalesce_enable,
                                received_row, received_col, lane, data[lane*8+:8], 8'(expected_byte));
                        accepted++;
                    end
                end
                received_bytes += accepted;
                received_col += accepted/element_bytes;
                assert(row_switch == (received_col == expected_cols))
                    else $fatal(1, "row completion differs from output dimensions");
                if (received_col == expected_cols) begin
                    received_col = 0;
                    received_row++;
                end
            end
        end
    end

    task automatic run_case(input int fifo, input bit transpose,
        input bit coalesce, input int rows, input int cols, input int row_tiles, input int col_tiles);
        int ticks, source_rows, global_row, global_col;
        @(negedge clk);
        rst_n = 0; checking = 0; output_ready = 0; in_valid = 0; in_tile_done = 0;
        repeat(3) @(negedge clk);
        select_fifo = fifo; transpose_mode = transpose; coalesce_enable = coalesce;
        coalesce_group_start = 0; coalesce_rows = row_tiles; coalesce_cols = col_tiles;
        expected_rows = rows; expected_cols = cols; element_bytes = fifo == 2 ? 2 : 1;
        received_row = 0; received_col = 0; received_bytes = 0;
        valid_col = 4'((transpose ? rows : cols)-1);
        valid_row = 4'(rows-1);
        rst_n = 1;
        for (int ct = 0; ct < col_tiles; ++ct) begin
            for (int rt = 0; rt < row_tiles; ++rt) begin
                source_rows = transpose ? (coalesce ? 16 : cols) :
                    ((rows-rt*16 < 16) ? rows-rt*16 : 16);
                for (int sr = 0; sr < source_rows; ++sr) begin
                    @(negedge clk);
                    in_valid = 1; in_tile_done = sr == source_rows-1;
                    for (int sc = 0; sc < 16; ++sc) begin
                        global_row = transpose ? sc : rt*16+sr;
                        global_col = transpose ? ct*16+sr : ct*16+sc;
                        in_vec_s8[sc*8+:8] = 8'(value_at(global_row, global_col, 1));
                        in_vec_s16[sc*16+:16] = 16'(value_at(global_row, global_col, 2));
                    end
                end
            end
        end
        @(negedge clk); in_valid = 0; in_tile_done = 0;
        repeat(3) @(negedge clk);
        coalesce_group_start = coalesce;
        checking = 1; ticks = 0;
        while (received_row < rows && ticks < 10000) begin
            output_ready = ticks%7 != 0 && ticks%7 != 3 && ticks%7 != 4;
            @(negedge clk);
            ticks++;
            if (ticks == 4) coalesce_group_start = 0;
        end
        assert(received_row == rows && received_col == 0 &&
            received_bytes == rows*cols*element_bytes)
            else $fatal(1, "FIFO case timeout or incorrect byte count");
        checking = 0; output_ready = 0;
        tests++; total_bytes += received_bytes;
    endtask

    initial begin
        for (int fifo = 0; fifo < 3; ++fifo) begin
            for (int rows = 1; rows <= 16; rows += 5) begin
                run_case(fifo, 0, 0, rows, 1, 1, 1);
                run_case(fifo, 0, 0, rows, 7, 1, 1);
                run_case(fifo, 0, 0, rows, 8, 1, 1);
                run_case(fifo, 0, 0, rows, 10, 1, 1);
                run_case(fifo, 0, 0, rows, 15, 1, 1);
                run_case(fifo, 0, 0, rows, 16, 1, 1);
            end
        end
        run_case(0, 1, 0, 1, 2, 1, 1);
        run_case(0, 1, 0, 1, 10, 1, 1);
        run_case(0, 1, 0, 7, 12, 1, 1);
        run_case(0, 1, 0, 16, 16, 1, 1);
        run_case(0, 0, 1, 1, 32, 1, 2);
        run_case(0, 0, 1, 21, 64, 2, 4);
        run_case(0, 0, 1, 64, 32, 4, 2);
        run_case(0, 1, 1, 1, 32, 1, 2);
        run_case(0, 1, 1, 13, 64, 1, 4);
        $display("WRITEBACK_BUS_PASS bus_width=%0d cases=%0d checked_bytes=%0d", BUS_WIDTH, tests, total_bytes);
        $finish;
    end
endmodule
