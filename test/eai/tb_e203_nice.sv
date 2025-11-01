/* verilator lint_off TIMESCALEMOD */
`timescale 1ns / 1ps


module tb_e203_nice;

    // Clock and reset
    logic clk;
    logic rst_n;

    // Instruction definitions
    localparam CUSTOM_1 = 7'b0101011;
    localparam MAT_MULT_FUNCT7 = 7'h01;
    localparam NICE_FUNCT3 = 3'b111;
    localparam CUSTOM_3 = 7'b1111011;
    localparam CSRWR_FUNCT3 = 3'b010;
    localparam CSRR_FUNCT3 = 3'b100;

    // Interface instantiation
    nice_if nice_if_inst (
        .clk  (clk),
        .rst_n(rst_n)
    );

    // DUT instantiation
    e203_subsys_nice_core u_nice_core (
        .nice_clk          (clk),
        .nice_rst_n        (rst_n),
        .nice_req_valid    (nice_if_inst.req_valid),
        .nice_req_ready    (nice_if_inst.req_ready),
        .nice_req_inst     (nice_if_inst.req_inst),
        .nice_req_rs1      (nice_if_inst.req_rs1),
        .nice_req_rs2      (nice_if_inst.req_rs2),
        .nice_rsp_valid    (nice_if_inst.rsp_valid),
        .nice_rsp_ready    (nice_if_inst.rsp_ready),
        .nice_rsp_rdat     (nice_if_inst.rsp_rdat),
        .nice_rsp_err      (nice_if_inst.rsp_err),
        .nice_mem_holdup   (nice_if_inst.mem_holdup),
        .nice_icb_cmd_valid(nice_if_inst.icb_cmd_valid),
        .nice_icb_cmd_ready(nice_if_inst.icb_cmd_ready),
        .nice_icb_cmd_addr (nice_if_inst.icb_cmd_addr),
        .nice_icb_cmd_read (nice_if_inst.icb_cmd_read),
        .nice_icb_cmd_wdata(nice_if_inst.icb_cmd_wdata),
        .nice_icb_cmd_wmask(nice_if_inst.icb_cmd_wmask),
        .nice_icb_rsp_valid(nice_if_inst.icb_rsp_valid),
        .nice_icb_rsp_ready(nice_if_inst.icb_rsp_ready),
        .nice_icb_rsp_rdata(nice_if_inst.icb_rsp_rdata),
        .nice_icb_rsp_err  (nice_if_inst.icb_rsp_err)
    );

    // Clock generation - use non-blocking assignment
    initial clk = 0;
    always #5 clk <= ~clk;

    // Memory response model (simple ACK)
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            nice_if_inst.icb_rsp_valid <= 1'b0;
        end else begin
            nice_if_inst.icb_rsp_valid <= nice_if_inst.icb_cmd_valid && nice_if_inst.icb_cmd_ready;
        end
    end

    assign nice_if_inst.icb_cmd_ready = 1'b1;
    assign nice_if_inst.icb_rsp_rdata = 32'h0;
    assign nice_if_inst.icb_rsp_err   = 1'b0;
    assign nice_if_inst.icb_rsp_ready = 1'b1;

    // Test sequence
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb_e203_nice);

        // Initialize
        rst_n                  = 0;
        nice_if_inst.req_valid = 0;
        nice_if_inst.rsp_ready = 1;

        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (2) @(posedge clk);

        $display("[%0t] === Test 1: CSR Write (csrwr) to MULT_LHS_ROWS (0x7C6) ===", $time);
        send_csr_write(12'h7C6, 32'd16);

        $display("[%0t] === Test 2: CSR Write (csrwr) to MULT_RHS_COLS (0x7C7) ===", $time);
        send_csr_write(12'h7C7, 32'd8);

        $display("[%0t] === Test 3: CSR Read (csrrd) from MULT_LHS_ROWS ===", $time);
        send_csr_read(12'h7C6, 32'd16);  // 期望读到16

        $display("[%0t] === Test 4: CSR Read (csrrd) from MULT_RHS_COLS ===", $time);
        send_csr_read(12'h7C7, 32'd8);  // 期望读到8

        $display("[%0t] === Test 5: Matrix Multiply (mat_mult_t) ===", $time);
        send_mat_mult(32'h1000, 32'h0);

        repeat (20) @(posedge clk);

        $display("[%0t] === Test 6: Response Backpressure Test ===", $time);
        test_response_backpressure();

        $display("[%0t] === Test 7: Request Backpressure with Pending Response ===", $time);
        test_request_backpressure();

        repeat (20) @(posedge clk);

        $display("[%0t] === All tests completed ===", $time);
        $finish;
    end

    // Task: Send CSR write instruction
    task send_csr_write(input [11:0] csr_addr, input [31:0] value);
        // Use clocking block for driving outputs
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {csr_addr, 5'b00001, CSRWR_FUNCT3, 5'b00000, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= value;
        nice_if_inst.cb.req_rs2   <= 32'h0;
        // @(nice_if_inst.cb);
        wait (nice_if_inst.req_ready);  // Direct access for input sampling
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;
        wait (nice_if_inst.rsp_valid);  // Direct access for input sampling
        $display("[%0t]   CSR[0x%03h] <= 0x%08h, err=%b", $time, csr_addr, value, nice_if_inst.rsp_err);
        @(nice_if_inst.cb);
    endtask

    // Task: Send CSR read instruction
    task send_csr_read(input [11:0] csr_addr, input [31:0] expected_value);
        reg [31:0] read_value;
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {csr_addr, 5'b00000, CSRR_FUNCT3, 5'b00001, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= 32'h0;
        nice_if_inst.cb.req_rs2   <= 32'h0;
        // @(nice_if_inst.cb);
        wait (nice_if_inst.req_ready);  // Direct access for input sampling
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;
        wait (nice_if_inst.rsp_valid);  // Direct access for input sampling
        read_value = nice_if_inst.rsp_rdat;

        if (read_value !== expected_value) begin
            $display("[%0t] ERROR: CSR[0x%03h] read mismatch! Expected: 0x%08h, Got: 0x%08h", $time, csr_addr,
                     expected_value, read_value);
            repeat (10) @(posedge clk);  // Allow some time for waveform capture
            $fatal(1, "CSR verification failed");
        end else begin
            $display("[%0t]   CSR[0x%03h] => 0x%08h (PASS), err=%b", $time, csr_addr, read_value,
                     nice_if_inst.rsp_err);
        end
        @(nice_if_inst.cb);
    endtask

    // Task: Send matrix multiply instruction
    task send_mat_mult(input [31:0] out_addr, input [31:0] cfg);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst <= {
            MAT_MULT_FUNCT7, 5'b00010, 5'b00001, NICE_FUNCT3, 5'b00011, CUSTOM_1
        };
        nice_if_inst.cb.req_rs1 <= out_addr;
        nice_if_inst.cb.req_rs2 <= cfg;
        // @(nice_if_inst.cb);
        wait (nice_if_inst.req_ready);  // Direct access for input sampling
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;
        wait (nice_if_inst.rsp_valid);  // Direct access for input sampling
        $display("[%0t]   mat_mult_t started, status=0x%08h, err=%b", $time, nice_if_inst.rsp_rdat,
                 nice_if_inst.rsp_err);
        @(nice_if_inst.cb);
    endtask

    // Task: Test response backpressure
    task test_response_backpressure();
        reg [31:0] read_value;
        $display("[%0t]   Step 1: Send CSR write with rsp_ready=1", $time);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {12'h7C8, 5'b00001, CSRWR_FUNCT3, 5'b00000, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= 32'hDEAD_BEEF;
        nice_if_inst.cb.req_rs2   <= 32'h0;
        nice_if_inst.cb.rsp_ready <= 1'b1;

        wait (nice_if_inst.req_ready);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;

        // 在响应到来前，立即拉低rsp_ready
        @(nice_if_inst.cb);
        nice_if_inst.cb.rsp_ready <= 1'b0;
        $display("[%0t]   Step 2: Deasserted rsp_ready, response should be held", $time);

        // 等待响应有效但不应该被接受
        wait (nice_if_inst.rsp_valid);
        $display("[%0t]   Step 3: Response valid asserted (rsp_valid=%b, rsp_ready=%b)",
                 $time, nice_if_inst.rsp_valid, nice_if_inst.rsp_ready);

        // 保持rsp_ready为低，同时发送新的读指令
        repeat (3) @(nice_if_inst.cb);
        $display("[%0t]   Step 4: Sending new CSR read while previous response pending", $time);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {12'h7C8, 5'b00000, CSRR_FUNCT3, 5'b00001, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= 32'h0;
        nice_if_inst.cb.req_rs2   <= 32'h0;

        wait (nice_if_inst.req_ready);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;

        // 拉高rsp_ready，完成第一个响应
        @(nice_if_inst.cb);
        nice_if_inst.cb.rsp_ready <= 1'b1;
        $display("[%0t]   Step 5: Asserted rsp_ready, completing first response", $time);
        @(nice_if_inst.cb);
        nice_if_inst.cb.rsp_ready <= 1'b0;
        @(nice_if_inst.cb);

        // 等待第二个响应并验证读取的数据
        wait (nice_if_inst.rsp_valid);
        read_value = nice_if_inst.rsp_rdat;

        if (read_value !== 32'hDEAD_BEEF) begin
            $display("[%0t]   ERROR: CSR read mismatch! Expected: 0x%08h, Got: 0x%08h", $time, 32'hDEAD_BEEF,
                     read_value);
        end else begin
            $display("[%0t]   PASS: CSR[0x7C8] => 0x%08h (correct value read)", $time, read_value);
        end
        @(nice_if_inst.cb);

        $display("[%0t]   Response backpressure test completed", $time);
    endtask

    // Task: Test request backpressure with pending response
    task test_request_backpressure();
        reg [31:0] read_value;
        $display("[%0t]   Step 1: Write test value to CSR 0x7CA", $time);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {12'h7CA, 5'b00001, CSRWR_FUNCT3, 5'b00000, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= 32'h5A5A_A5A5;
        nice_if_inst.cb.req_rs2   <= 32'h0;
        nice_if_inst.cb.rsp_ready <= 1'b1;

        wait (nice_if_inst.req_ready);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;

        wait (nice_if_inst.rsp_valid);
        @(nice_if_inst.cb);

        $display("[%0t]   Step 2: Send read instruction and hold rsp_ready low", $time);
        nice_if_inst.cb.rsp_ready <= 1'b0;
        nice_if_inst.cb.req_valid <= 1'b1;
        nice_if_inst.cb.req_inst  <= {12'h7CA, 5'b00000, CSRR_FUNCT3, 5'b00001, CUSTOM_3};
        nice_if_inst.cb.req_rs1   <= 32'h0;
        nice_if_inst.cb.req_rs2   <= 32'h0;

        wait (nice_if_inst.req_ready);
        @(nice_if_inst.cb);
        nice_if_inst.cb.req_valid <= 1'b0;

        $display("[%0t]   Step 3: Wait for response with rsp_ready=0", $time);
        wait (nice_if_inst.rsp_valid);

        repeat (10) @(posedge clk);
        if (nice_if_inst.rsp_valid && !nice_if_inst.rsp_ready) begin
            $display("[%0t]   PASS: Response held due to backpressure (valid=%b, ready=%b)",
                     $time, nice_if_inst.rsp_valid, nice_if_inst.rsp_ready);
        end

        $display("[%0t]   Step 4: Release backpressure and verify data", $time);
        @(nice_if_inst.cb);
        nice_if_inst.cb.rsp_ready <= 1'b1;

        wait (nice_if_inst.rsp_valid);
        @(nice_if_inst.cb);
        wait (nice_if_inst.rsp_valid);
        read_value = nice_if_inst.rsp_rdat;

        if (read_value !== 32'h5A5A_A5A5) begin
            $display("[%0t]   ERROR: CSR read mismatch! Expected: 0x%08h, Got: 0x%08h", $time, 32'h5A5A_A5A5,
                     read_value);
        end else begin
            $display("[%0t]   PASS: CSR[0x7CA] => 0x%08h (correct value read after backpressure)",
                     $time, read_value);
        end
        @(nice_if_inst.cb);

        $display("[%0t]   Request backpressure test completed", $time);
    endtask

endmodule
