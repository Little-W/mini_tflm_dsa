`timescale 1ns/1ps

module tb_execution #(parameter logic [31:0] RESET_ADDR = 32'd0);
    logic clk = 0;
    logic resetn = 0;
    logic mem_ready = 0;
    logic [31:0] mem_rdata = 0;
    wire [1:0] trap, mem_valid, mem_instr, la_read, la_write;
    wire [31:0] mem_addr [0:1], mem_wdata [0:1], la_addr [0:1], la_wdata [0:1];
    wire [3:0] mem_wstrb [0:1], la_wstrb [0:1];
    logic [31:0] code [0:2047];
    logic [31:0] ram_sum = 0, ram_marker = 0, random_state = 32'h41627aca;
    logic pending = 0, seen_sum = 0, finished = 0;
    logic [31:0] pending_address, pending_data;
    logic [3:0] pending_mask;
    logic pending_instruction;
    integer delay_count = 0, cycles = 0, fetches = 0, transactions = 0, checks = 0;
    integer stability_checks = 0, firmware_words;
    string firmware;

    always #5 clk = ~clk;

    picorv32_reference #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(0), .ENABLE_REGS_16_31(1),
        .ENABLE_REGS_DUALPORT(1), .TWO_STAGE_SHIFT(1), .BARREL_SHIFTER(0), .COMPRESSED_ISA(0),
        .CATCH_MISALIGN(1), .CATCH_ILLINSN(1), .ENABLE_MUL(1), .ENABLE_FAST_MUL(0), .ENABLE_DIV(1),
        .ENABLE_IRQ(0), .PROGADDR_RESET(RESET_ADDR), .STACKADDR(32'h40000)
    ) u_reference (
        .clk(clk), .resetn(resetn), .trap(trap[0]), .mem_valid(mem_valid[0]),
        .mem_instr(mem_instr[0]), .mem_ready(mem_ready), .mem_addr(mem_addr[0]),
        .mem_wdata(mem_wdata[0]), .mem_wstrb(mem_wstrb[0]), .mem_rdata(mem_rdata),
        .mem_la_read(la_read[0]), .mem_la_write(la_write[0]), .mem_la_addr(la_addr[0]),
        .mem_la_wdata(la_wdata[0]), .mem_la_wstrb(la_wstrb[0]),
        .pcpi_wr(1'b0), .pcpi_rd(32'd0), .pcpi_wait(1'b0), .pcpi_ready(1'b0), .irq(32'd0)
    );
    picorv32 #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(0), .ENABLE_REGS_16_31(1),
        .ENABLE_REGS_DUALPORT(1), .TWO_STAGE_SHIFT(1), .BARREL_SHIFTER(0), .COMPRESSED_ISA(0),
        .CATCH_MISALIGN(1), .CATCH_ILLINSN(1), .ENABLE_MUL(1), .ENABLE_FAST_MUL(0), .ENABLE_DIV(1),
        .ENABLE_IRQ(0), .PROGADDR_RESET(RESET_ADDR), .STACKADDR(32'h40000)
    ) u_current (
        .clk(clk), .resetn(resetn), .trap(trap[1]), .mem_valid(mem_valid[1]),
        .mem_instr(mem_instr[1]), .mem_ready(mem_ready), .mem_addr(mem_addr[1]),
        .mem_wdata(mem_wdata[1]), .mem_wstrb(mem_wstrb[1]), .mem_rdata(mem_rdata),
        .mem_la_read(la_read[1]), .mem_la_write(la_write[1]), .mem_la_addr(la_addr[1]),
        .mem_la_wdata(la_wdata[1]), .mem_la_wstrb(la_wstrb[1]),
        .pcpi_wr(1'b0), .pcpi_rd(32'd0), .pcpi_wait(1'b0), .pcpi_ready(1'b0), .irq(32'd0)
    );

    function automatic logic [31:0] read_word(input logic [31:0] address);
        logic [31:0] offset;
        begin
            offset = address - RESET_ADDR;
            if (address == 32'h1000) read_word = ram_sum;
            else if (address == 32'h1004) read_word = ram_marker;
            else if (offset < 32'd8192) read_word = code[offset >> 2];
            else $fatal(1, "Unexpected CPU address %h", address);
        end
    endfunction

    initial begin
        if (!$value$plusargs("firmware=%s", firmware) ||
            !$value$plusargs("firmware_words=%d", firmware_words) ||
            firmware_words <= 0 || firmware_words > 2048)
            $fatal(1, "Missing program image or invalid word count");
        for (integer n = 0; n < 2048; n++) code[n] = 32'h00000013;
        $readmemh(firmware, code, 0, firmware_words - 1);
        repeat (5) @(negedge clk);
        #1;
        resetn = 1;
    end

    // 独立存储器检查实际执行的累加结果和最终完成标志。
    always @(posedge clk) begin
        if (resetn && mem_valid[0] && mem_ready) begin
            transactions++;
            if (mem_instr[0]) fetches++;
            if (|mem_wstrb[0]) begin
                if (mem_wstrb[0] !== 4'hf) $fatal(1, "Unexpected write mask");
                case (mem_addr[0])
                    32'h1000: begin
                        if (mem_wdata[0] !== 32'd5050) $fatal(1, "Incorrect accumulated sum");
                        ram_sum = mem_wdata[0];
                        seen_sum = 1;
                    end
                    32'h1004: begin
                        if (!seen_sum || mem_wdata[0] !== 32'h55) $fatal(1, "Incorrect completion marker");
                        ram_marker = mem_wdata[0];
                        finished = 1;
                    end
                    default: $fatal(1, "Unexpected store address");
                endcase
            end
        end
    end

    always @(negedge clk) begin
        if (resetn) begin
            cycles++;
            checks++;
            if (trap[0] !== trap[1] || mem_valid[0] !== mem_valid[1] ||
                la_read[0] !== la_read[1] || la_write[0] !== la_write[1])
                $fatal(1, "CPU control timing differs cycle=%0d", cycles);
            if (mem_valid[0]) begin
                if (mem_addr[0] !== mem_addr[1] || mem_instr[0] !== mem_instr[1] ||
                    mem_wstrb[0] !== mem_wstrb[1] ||
                    ((|mem_wstrb[0]) && mem_wdata[0] !== mem_wdata[1]))
                    $fatal(1, "CPU memory transaction differs cycle=%0d", cycles);
            end
            if ((la_read[0] || la_write[0]) && la_addr[0] !== la_addr[1])
                $fatal(1, "CPU lookahead address differs");
            if (la_write[0] && (la_wstrb[0] !== la_wstrb[1] || la_wdata[0] !== la_wdata[1]))
                $fatal(1, "CPU lookahead write differs");
            if (trap[0]) begin
                if (!finished || stability_checks == 0) $fatal(1, "CPU program did not complete all checks");
                $display("CPU_EXECUTION_PASS {\"passed\":true,\"reset_address\":%0d,\"cycles\":%0d,\"instruction_fetches\":%0d,\"transactions\":%0d,\"checks\":%0d,\"stability_checks\":%0d,\"sum\":%0d,\"marker\":%0d}",
                         RESET_ADDR, cycles, fetches, transactions, checks, stability_checks, ram_sum, ram_marker);
                $finish;
            end
            if (cycles > 100000) $fatal(1, "CPU program timed out");
            if (mem_ready) begin
                pending = 0;
                mem_ready = 0;
            end
            if (!pending && mem_valid[0]) begin
                pending = 1;
                pending_address = mem_addr[0];
                pending_data = mem_wdata[0];
                pending_mask = mem_wstrb[0];
                pending_instruction = mem_instr[0];
                random_state = {random_state[30:0], random_state[31] ^ random_state[21] ^
                                                    random_state[1] ^ random_state[0]};
                delay_count = int'(random_state[2:0]);
            end
            if (pending) begin
                if (!mem_valid[0] || pending_address !== mem_addr[0] || pending_mask !== mem_wstrb[0] ||
                    pending_instruction !== mem_instr[0] || ((|pending_mask) && pending_data !== mem_wdata[0]))
                    $fatal(1, "CPU changed stalled request");
                stability_checks++;
                if (delay_count == 0) begin
                    mem_ready = 1;
                    mem_rdata = read_word(pending_address);
                end else delay_count--;
            end
        end
    end
endmodule
