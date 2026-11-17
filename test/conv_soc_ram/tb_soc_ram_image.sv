module tb_soc_ram_image;
    parameter int DW = 64;
    parameter int MEM_WORD_WIDTH = 32;
    parameter string MEM_PATH = "";
    logic clk = 0, rst_n = 0, mem_reload_req = 0;
    always #5 clk = ~clk;
    logic arvalid = 0, arready, rvalid, rlast;
    logic [31:0] araddr = 0;
    logic [DW-1:0] rdata;
    logic [1:0] rresp;
    soc_axi_ram #(.DP(32*32/DW), .DW(DW), .MEM_WORD_WIDTH(MEM_WORD_WIDTH), .MEM_PATH(MEM_PATH), .INIT_EN(1)) dut (
        .clk, .rst_n, .mem_reload_req,
        .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_araddr(araddr),
        .s_axi_arcache(4'd0), .s_axi_arprot(3'd0), .s_axi_arlock(2'd0),
        .s_axi_arburst(2'd1), .s_axi_arlen(8'd0), .s_axi_arsize(3'd2),
        .s_axi_rvalid(rvalid), .s_axi_rready(1'b1), .s_axi_rdata(rdata),
        .s_axi_rresp(rresp), .s_axi_rlast(rlast),
        .s_axi_awvalid(1'b0), .s_axi_awready(), .s_axi_awaddr(32'd0),
        .s_axi_awcache(4'd0), .s_axi_awprot(3'd0), .s_axi_awlock(2'd0),
        .s_axi_awburst(2'd1), .s_axi_awlen(8'd0), .s_axi_awsize(3'd2),
        .s_axi_wvalid(1'b0), .s_axi_wready(), .s_axi_wdata({DW{1'b0}}),
        .s_axi_wstrb({DW/8{1'b0}}), .s_axi_wlast(1'b0),
        .s_axi_bvalid(), .s_axi_bready(1'b1), .s_axi_bresp());

    function automatic logic [31:0] memory_word32(input int unsigned word_addr);
        return dut.mem_r[word_addr/(DW/32)][32*(word_addr%(DW/32)) +: 32];
    endfunction
    task automatic check_word(input int unsigned word_addr, input logic [31:0] expected);
        if (memory_word32(word_addr) !== expected)
            $fatal(1, "Image word %0d differs: %h / %h", word_addr,
                   memory_word32(word_addr), expected);
        @(negedge clk);
        araddr = word_addr * 4;
        arvalid = 1;
        do @(posedge clk); while (!arready);
        @(negedge clk); arvalid = 0;
        do @(posedge clk); while (!rvalid);
        if (rresp != 0 || !rlast || rdata[32*(word_addr%(DW/32)) +: 32] !== expected)
            $fatal(1, "AXI memory word %0d differs", word_addr);
    endtask

    initial begin
        integer mismatches;
        string expected_path;
        if (!$value$plusargs("EXPECTED_IMAGE=%s", expected_path))
            $fatal(1, "EXPECTED_IMAGE is required");
        repeat (3) @(negedge clk);
        rst_n = 1;
        check_word(0, 32'h01020304);
        check_word(1, 32'haabbccdd);
        check_word(2, 32'h33333333);
        check_word(3, 32'h00000000);
        check_word(4, 32'h44444444);
        check_word(5, 32'h55555555);
        check_word(6, 32'h66666666);
        check_word(15, 32'hffffffff);
        check_word(31, 32'hfedcba98);
`ifndef SYNTHESIS
        @(negedge clk);
        dut.mem_r[1/(DW/32)][32*(1%(DW/32)) +: 32] = 32'hdeaddead;
        dut.mem_r[7/(DW/32)][32*(7%(DW/32)) +: 32] = 32'hcafebabe;
        mem_reload_req = 1;
        @(negedge clk); mem_reload_req = 0;
        check_word(1, 32'haabbccdd);
        check_word(2, 32'h33333333);
        check_word(7, 32'hcafebabe);
        dut.check_mem_file(expected_path, 0, 31, mismatches);
        if (mismatches != 0) $fatal(1, "Image comparison failed");
`else
        check_word(7, 32'hcafebabe);
`endif
        $display("SOC_RAM_IMAGE_PASS data_bits=%0d checked_words=12", DW);
        $finish;
    end
    initial begin #10000; $fatal(1, "Memory image test timeout"); end
endmodule
