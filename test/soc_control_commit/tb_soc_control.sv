`timescale 1ns/1ps
module tb_soc_control;
    parameter integer AW = 32;
    parameter integer DW = 32;
    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg [AW-1:0] awaddr = '0;
    reg [2:0] awprot = '0;
    reg awvalid = 1'b0;
    wire awready;
    reg [DW-1:0] wdata = '0;
    reg [DW/8-1:0] wstrb = '0;
    reg wvalid = 1'b0;
    wire wready;
    wire [1:0] bresp;
    wire bvalid;
    reg bready = 1'b0;
    reg [AW-1:0] araddr = '0;
    reg [2:0] arprot = '0;
    reg arvalid = 1'b0;
    wire arready;
    wire [DW-1:0] rdata;
    wire [1:0] rresp;
    wire rvalid;
    reg rready = 1'b0;
    reg cpu_trap = 1'b0;
    wire soc_finish;
    wire [31:0] soc_status, soc_progress;
    reg [31:0] expected_status = 0;
    reg [31:0] expected_progress = 0;
    reg expected_finish = 0;
    reg [31:0] random_state = 32'h569a1e72;
    integer cycles = 0;
    integer writes = 0;
    integer reads = 0;
    integer resets = 0;
    integer index, address_index;
    reg [31:0] payload;
    reg [DW/8-1:0] strobes;

    soc_axil_ctrl #(.AXIL_ADDR_WIDTH(AW), .AXIL_DATA_WIDTH(DW)) dut (
        .clk(clk), .rst_n(rst_n),
        .s_axil_awaddr(awaddr), .s_axil_awprot(awprot),
        .s_axil_awvalid(awvalid), .s_axil_awready(awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb),
        .s_axil_wvalid(wvalid), .s_axil_wready(wready),
        .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arprot(arprot),
        .s_axil_arvalid(arvalid), .s_axil_arready(arready),
        .s_axil_rdata(rdata), .s_axil_rresp(rresp),
        .s_axil_rvalid(rvalid), .s_axil_rready(rready),
        .cpu_trap(cpu_trap), .soc_finish(soc_finish),
        .soc_status(soc_status), .soc_progress(soc_progress)
    );

    function automatic [31:0] next_random(input [31:0] state);
        reg [31:0] value;
        begin
            value = state ^ (state << 13);
            value = value ^ (value >> 17);
            next_random = value ^ (value << 5);
        end
    endfunction

    // 每个周期在低电平设置输入，在上升沿后检查公开状态。
    task automatic tick;
        begin
            #4; clk = 1'b1; #1; cycles = cycles + 1;
            #4; clk = 1'b0; #1;
        end
    endtask

    task automatic check_registers;
        begin
            if (soc_status !== expected_status || soc_progress !== expected_progress ||
                soc_finish !== expected_finish)
                $fatal(1, "Register values differ at cycle %0d", cycles);
        end
    endtask

    task automatic reset_device;
        begin
            rst_n = 0; awvalid = 0; wvalid = 0; bready = 0;
            arvalid = 0; rready = 0;
            expected_status = 0; expected_progress = 0; expected_finish = 0;
            tick(); tick(); check_registers();
            if (bvalid !== 0 || rvalid !== 0) $fatal(1, "Response present during reset");
            rst_n = 1; tick(); resets = resets + 1;
        end
    endtask

    // 事务记分板按已接收的地址、数据和字节使能计算结果。
    task automatic write_register(input [1:0] target, input [31:0] value,
                                  input [DW/8-1:0] enables,
                                  input integer aw_delay, input integer w_delay,
                                  input integer response_delay);
        integer age, wait_cycles, byte_index;
        reg accepted_aw, accepted_w, handshake_aw, handshake_w;
        reg [31:0] mask;
        begin
            accepted_aw = 0; accepted_w = 0; age = 0;
            awaddr = AW'({28'h9a51121,target,2'b00});
            wdata = DW'(value); wstrb = enables;
            awvalid = 0; wvalid = 0; bready = response_delay == 0;
            mask = 0;
            for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                mask[byte_index*8 +: 8] = {8{enables[byte_index]}};
            while (!bvalid) begin
                awvalid = !accepted_aw && age >= aw_delay;
                wvalid = !accepted_w && age >= w_delay;
                #1;
                handshake_aw = awvalid && awready;
                handshake_w = wvalid && wready;
                tick();
                if (handshake_aw) begin accepted_aw = 1; awvalid = 0; awaddr = ~awaddr; end
                if (handshake_w) begin accepted_w = 1; wvalid = 0; wdata = ~wdata; wstrb = ~wstrb; end
                if (bvalid && !(accepted_aw && accepted_w))
                    $fatal(1, "Write response preceded request acceptance");
                age = age + 1;
                if (age > 100) $fatal(1, "Write response timeout");
            end
            if (bresp !== 0) $fatal(1, "Incorrect write response");
            if (target == 0) begin
                expected_status = (expected_status & ~mask) | (value & mask);
                expected_finish = 1;
            end
            if (target == 3) expected_progress = (expected_progress & ~mask) | (value & mask);
            check_registers();
            for (wait_cycles = 0; wait_cycles < response_delay; wait_cycles = wait_cycles + 1) begin
                tick(); check_registers();
                if (bvalid !== 1 || bresp !== 0 || awready !== 0 || wready !== 0)
                    $fatal(1, "Write response changed while waiting");
            end
            bready = 1; tick(); bready = 0;
            if (bvalid !== 0) $fatal(1, "Duplicate write response");
            writes = writes + 1;
        end
    endtask

    task automatic read_register(input [1:0] target, input integer response_delay);
        integer age, wait_cycles;
        reg handshake_ar;
        reg [DW-1:0] expected;
        begin
            case (target)
                0: expected = DW'(expected_status);
                1: expected = DW'(expected_finish);
                2: expected = DW'(cpu_trap);
                3: expected = DW'(expected_progress);
            endcase
            araddr = AW'({28'h5b15a30,target,2'b00}); arvalid = 1; rready = 0;
            age = 0; handshake_ar = 0;
            while (!handshake_ar) begin
                #1; handshake_ar = arvalid && arready; tick();
                age = age + 1;
                if (age > 100) $fatal(1, "Read address timeout");
            end
            arvalid = 0; araddr = ~araddr;
            if (rvalid !== 1 || rresp !== 0 || rdata !== expected)
                $fatal(1, "Read value differs at address %0d", target);
            for (wait_cycles = 0; wait_cycles < response_delay; wait_cycles = wait_cycles + 1) begin
                tick();
                if (rvalid !== 1 || rresp !== 0 || rdata !== expected)
                    $fatal(1, "Read response changed while waiting");
            end
            rready = 1; tick(); rready = 0;
            if (rvalid !== 0) $fatal(1, "Duplicate read response");
            reads = reads + 1;
        end
    endtask

    initial begin
        reset_device();
        for (index = 0; index < 2048; index = index + 1) begin
            random_state = next_random(random_state); payload = random_state;
            random_state = next_random(random_state); strobes = (DW/8)'(random_state);
            cpu_trap = random_state[0];
            write_register(index[1:0], payload, strobes,
                           int'(random_state[6:4]), int'(random_state[10:8]),
                           int'(random_state[14:12]));
            for (address_index = 0; address_index < 4; address_index = address_index + 1)
                read_register(address_index[1:0], int'(random_state[18:16]));
            if (index % 127 == 0) begin
                // 地址或数据单独接收后复位，检查未完成请求被清除。
                awaddr = 0; awvalid = 1; tick(); awvalid = 0;
                repeat (3) tick();
                if (bvalid !== 0) $fatal(1, "Response to incomplete AW request");
                reset_device();
                wdata = '1; wstrb = '1; wvalid = 1; tick(); wvalid = 0;
                repeat (3) tick();
                if (bvalid !== 0) $fatal(1, "Response to incomplete W request");
                reset_device();
            end
        end
        // 写响应等待期间与读响应等待期间分别复位。
        awaddr = AW'(12); awvalid = 1; wdata = DW'(32'h52c4a619); wstrb = '1;
        wvalid = 1; bready = 0; tick(); awvalid = 0; wvalid = 0;
        for (index = 0; index < 4; index = index + 1) tick();
        if (bvalid !== 1) $fatal(1, "Missing pending write response");
        reset_device();
        araddr = 0; arvalid = 1; rready = 0; tick(); arvalid = 0;
        if (rvalid !== 1 || rdata !== 0) $fatal(1, "Missing pending read response");
        reset_device();
        $display("SOC_CTRL_PASS writes=%0d reads=%0d resets=%0d cycles=%0d", writes, reads, resets, cycles);
        $finish;
    end
endmodule
