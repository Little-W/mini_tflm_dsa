`timescale 1ns/1ps
module tb_regfile_wrapper_equivalence #(
    parameter int WIDTH = 32,
    parameter int DEPTH = 128,
    parameter int CYCLES = 100000
);
    localparam int AW = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
    logic clk = 0, rst_n = 0, wr_en = 0, rd_en = 0, ps_enable = 0;
    logic [AW-1:0] wr_addr = 0, rd_addr = 0;
    logic [WIDTH-1:0] wr_data = 0;
    logic [WIDTH/8-1:0] wr_mask = 0;
    logic [WIDTH-1:0] ia_actual, ia_expected, ps_actual, ps_expected;
    logic [31:0] random_state = 32'h5b7e2319;
    int unsigned checks = 0;
    ia_buffer_wrapper #(.DATA_WIDTH(WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) u_ia (
        .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_addr(wr_addr), .wr_data(wr_data),
        .wr_mask(wr_mask), .rd_en(rd_en), .rd_addr(rd_addr), .rd_data(ia_actual)
    );
    ia_buffer_wrapper_ref #(.DATA_WIDTH(WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) u_ia_ref (
        .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_addr(wr_addr), .wr_data(wr_data),
        .wr_mask(wr_mask), .rd_en(rd_en), .rd_addr(rd_addr), .rd_data(ia_expected)
    );
    ps_buffer_exact_ram #(.DATA_WIDTH(WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) u_ps (
        .clk(clk), .ena(ps_enable), .enb(rd_en), .wea(wr_en),
        .addra(wr_addr), .addrb(rd_addr), .dia(wr_data), .dob(ps_actual)
    );
    ps_buffer_exact_ram_ref #(.DATA_WIDTH(WIDTH), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) u_ps_ref (
        .clk(clk), .ena(ps_enable), .enb(rd_en), .wea(wr_en),
        .addra(wr_addr), .addrb(rd_addr), .dia(wr_data), .dob(ps_expected)
    );
    function automatic logic [31:0] random_word();
        random_state ^= random_state << 13;
        random_state ^= random_state >> 17;
        random_state ^= random_state << 5;
        return random_state;
    endfunction
    task automatic check_outputs();
        if ((ia_actual !== ia_expected) || (ps_actual !== ps_expected)) begin
            $fatal(1, "WRAPPER_EQ_FAIL check=%0d width=%0d depth=%0d", checks, WIDTH, DEPTH);
        end
        checks++;
    endtask
    initial begin
        #1; clk = 1; #1; clk = 0; #1;
        for (int cycle = 0; cycle < CYCLES; cycle++) begin
            rst_n = (random_word() % 73) != 0;
            wr_en = 1'(random_word()); rd_en = 1'(random_word()); ps_enable = 1'(random_word());
            wr_addr = AW'(random_word() % DEPTH); rd_addr = AW'(random_word() % DEPTH);
            if (cycle % 5 == 0) rd_addr = wr_addr;
            for (int byte_index = 0; byte_index < WIDTH/8; byte_index++) begin
                wr_data[byte_index*8 +: 8] = 8'(random_word());
                wr_mask[byte_index] = 1'(random_word());
            end
            #1; check_outputs(); clk = 1;
            #1; check_outputs(); clk = 0; #1;
        end
        $display("WRAPPER_EQ_PASS cycles=%0d checks=%0d", CYCLES, checks);
        $finish;
    end
endmodule
