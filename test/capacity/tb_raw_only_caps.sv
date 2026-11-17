module tb_raw_only_caps #(
    parameter int unsigned AXI_DATA_BITS = 32,
    parameter logic [31:0] CAP_NORMAL = 0,
    parameter logic [31:0] CAP_GEMMORA_RAW = 0,
    parameter logic [31:0] CAP_LEGACY_RAW = 0
);
    localparam logic [31:0] CAPS [3] = '{CAP_NORMAL, CAP_GEMMORA_RAW, CAP_LEGACY_RAW};
    logic clk = 0, rst_n = 0;
    always #5 clk = ~clk;
    logic [15:0] awaddr = 0, araddr = 0;
    logic [31:0] wdata = 0;
    logic [3:0] wstrb = 0;
    logic awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    wire [2:0] awready, wready, bvalid, arready, rvalid;
    wire [1:0] bresp [3], rresp [3];
    wire [31:0] rdata [3];
    integer checks = 0, register_reads = 0;

    for (genvar i = 0; i < 3; ++i) begin : g_registers
        npu_axil_reg_if #(
            .AXI_DATA_BITS(AXI_DATA_BITS),
            .PS_CAPS(CAPS[i]), .PS_POOL_BYTES(12288), .IA_CACHE_BYTES(2048),
            .SHARED_TOTAL_BYTES(14336), .SHARED_BANK_BYTES(2048),
            .SHARED_IA_BANK_MASK(32'h16), .PS_DIRECTORY_ROWS(1024)
        ) dut (
            .clk, .rst_n,
            .s_axil_awaddr(awaddr), .s_axil_awprot(3'b0),
            .s_axil_awvalid(awvalid), .s_axil_awready(awready[i]),
            .s_axil_wdata(wdata), .s_axil_wstrb(wstrb),
            .s_axil_wvalid(wvalid), .s_axil_wready(wready[i]),
            .s_axil_bresp(bresp[i]), .s_axil_bvalid(bvalid[i]), .s_axil_bready(bready),
            .s_axil_araddr(araddr), .s_axil_arprot(3'b0),
            .s_axil_arvalid(arvalid), .s_axil_arready(arready[i]),
            .s_axil_rdata(rdata[i]), .s_axil_rresp(rresp[i]),
            .s_axil_rvalid(rvalid[i]), .s_axil_rready(rready),
            .npu_sa_ready(1'b1), .npu_done_valid(1'b0), .npu_err_code(2'b0),
            .ps_stat_commands(32'b0), .ps_stat_pressure_events(32'b0),
            .ps_stat_early_finish_frames(32'b0),
            .vector_stat_cycles(32'b0), .vector_stat_compute(32'b0), .vector_stat_dma_wait(32'b0)
        );
    end

    task automatic check(input logic condition, input string message);
        if (!condition) $fatal(1, "%s", message);
        checks++;
    endtask

    task automatic read_register(input logic [15:0] address,
                                 input logic [31:0] expected [3]);
        @(negedge clk); araddr = address; arvalid = 1;
        do @(posedge clk); while (arready != 3'b111);
        @(negedge clk); arvalid = 0;
        wait (rvalid == 3'b111);
        repeat (3) begin
            @(negedge clk);
            for (int i = 0; i < 3; ++i)
                check(rvalid[i] && rresp[i] == 0 && rdata[i] == expected[i],
                      $sformatf("capability read profile=%0d address=%h", i, address));
        end
        rready = 1;
        @(posedge clk); @(negedge clk); rready = 0;
        register_reads += 3;
    endtask

    task automatic write_capability(input logic [31:0] value);
        @(negedge clk); awaddr = 16'h0124; awvalid = 1;
        do @(posedge clk); while (awready != 3'b111);
        @(negedge clk); awvalid = 0; wdata = value; wstrb = 4'hf; wvalid = 1;
        do @(posedge clk); while (wready != 3'b111);
        @(negedge clk); wvalid = 0;
        wait (bvalid == 3'b111);
        @(negedge clk);
        for (int i = 0; i < 3; ++i) check(bresp[i] == 0, "capability write response");
        bready = 1;
        @(posedge clk); @(negedge clk); bready = 0;
    endtask

    initial begin
        check(CAP_NORMAL == 32'h01100037, "adaptive capabilities");
        check(CAP_GEMMORA_RAW == 32'h0110003f, "GEMMORA RAW capabilities");
        check(CAP_LEGACY_RAW == CAP_GEMMORA_RAW, "RAW macro capability agreement");
        repeat (5) @(negedge clk);
        rst_n = 1;
        read_register(16'h0124, CAPS);
        write_capability(32'hffffffff);
        read_register(16'h0124, CAPS);
        write_capability(32'b0);
        read_register(16'h0124, CAPS);
        read_register(16'h0134, '{32'd12288, 32'd12288, 32'd12288});
        read_register(16'h0138, '{32'd2048, 32'd2048, 32'd2048});
        read_register(16'h0100, '{32'd14336, 32'd14336, 32'd14336});
        read_register(16'h0104, '{32'd2048, 32'd2048, 32'd2048});
        read_register(16'h0108, '{32'd1, 32'd1, 32'd1});
        read_register(16'h010c, '{32'h16, 32'h16, 32'h16});
        read_register(16'h0110, '{32'd1024, 32'd1024, 32'd1024});
        read_register(16'h00f4, '{AXI_DATA_BITS, AXI_DATA_BITS, AXI_DATA_BITS});
        read_register(16'h00f0, '{3{32'(256 * (AXI_DATA_BITS / 8))}});
        $display("{\"passed\":true,\"profiles\":3,\"register_reads\":%0d,\"checks\":%0d}",
                 register_reads, checks);
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "register test timeout");
    end
endmodule
