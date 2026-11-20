`timescale 1ns/1ps

module tb_shared_ram_equivalence #(
    parameter int BANK_BYTES = 8192,
    parameter int BANK_COUNT = 7,
    parameter int RANDOM_CYCLES = 50000
);
    localparam int ROWS = BANK_BYTES/16;
    localparam int ADDR_BITS = $clog2(BANK_COUNT*ROWS);
    localparam int COUNT_BITS = $clog2(BANK_COUNT+1);
    logic clk = 0;
    logic rst_n, cfg_valid;
    logic [COUNT_BITS-1:0] cfg_ia_banks;
    logic [1:0] ia_read_en, ia_write_en;
    logic [ADDR_BITS-1:0] ia_read_addr [0:1], ia_write_addr [0:1];
    logic [127:0] ia_write_data [0:1], ia_read_data [0:1], reference_ia_read_data [0:1];
    logic [15:0] ia_write_mask [0:1];
    logic [3:0] ps_read_en, ps_write_en;
    logic [ADDR_BITS-1:0] ps_read_addr [0:3], ps_write_addr [0:3];
    logic [127:0] ps_write_data [0:3], ps_read_data [0:3], reference_ps_read_data [0:3];
    logic capacity_fault, reference_capacity_fault;
    int cycles = 0;
    int configured_banks = 1;
    int configuration_checks = 0;
    int active_checks = 0;
    int fault_checks = 0;
    int reset_checks = 0;
    int unsigned random_state = 32'h438ab726;

    ia_ps_shared_ram #(.BANK_BYTES(BANK_BYTES), .TOTAL_BYTES(BANK_COUNT*BANK_BYTES)) dut (
        .clk, .rst_n, .cfg_valid, .cfg_ia_banks, .capacity_fault,
        .ia_read_en, .ia_write_en, .ia_read_addr, .ia_write_addr,
        .ia_read_data, .ia_write_data, .ia_write_mask,
        .ps_read_en, .ps_write_en, .ps_read_addr, .ps_write_addr,
        .ps_read_data, .ps_write_data
    );
    ia_ps_shared_ram_ref #(.BANK_BYTES(BANK_BYTES), .TOTAL_BYTES(BANK_COUNT*BANK_BYTES)) reference (
        .clk, .rst_n, .cfg_valid, .cfg_ia_banks,
        .capacity_fault(reference_capacity_fault),
        .ia_read_en, .ia_write_en, .ia_read_addr, .ia_write_addr,
        .ia_read_data(reference_ia_read_data), .ia_write_data, .ia_write_mask,
        .ps_read_en, .ps_write_en, .ps_read_addr, .ps_write_addr,
        .ps_read_data(reference_ps_read_data), .ps_write_data
    );

    function automatic int unsigned random_value();
        random_state = random_state ^ (random_state << 13);
        random_state = random_state ^ (random_state >> 17);
        random_state = random_state ^ (random_state << 5);
        return random_state;
    endfunction

    task automatic tick();
        clk = 0;
        #5;
        clk = 1;
        #1;
        if (capacity_fault !== reference_capacity_fault) begin
            $fatal(1, "Fault output differs at cycle %0d", cycles);
        end
        for (int p = 0; p < 2; p++) begin
            if (ia_read_data[p] !== reference_ia_read_data[p]) begin
                $fatal(1, "IA output differs: cycle=%0d port=%0d", cycles, p);
            end
        end
        for (int p = 0; p < 4; p++) begin
            if (ps_read_data[p] !== reference_ps_read_data[p]) begin
                $fatal(1, "PS output differs: cycle=%0d port=%0d", cycles, p);
            end
        end
        cycles++;
        #4;
    endtask

    task automatic clear_requests();
        ia_read_en = 0;
        ia_write_en = 0;
        ps_read_en = 0;
        ps_write_en = 0;
    endtask

    task automatic configure(input int banks);
        clear_requests();
        cfg_valid = 1;
        cfg_ia_banks = COUNT_BITS'(banks);
        tick();
        cfg_valid = 0;
        configured_banks = banks;
        tick();
        configuration_checks++;
    endtask

    initial begin
        rst_n = 0;
        cfg_valid = 0;
        cfg_ia_banks = COUNT_BITS'(1);
        clear_requests();
        for (int p = 0; p < 2; p++) begin
            ia_read_addr[p] = 0;
            ia_write_addr[p] = 0;
            ia_write_data[p] = 0;
            ia_write_mask[p] = 0;
        end
        for (int p = 0; p < 4; p++) begin
            ps_read_addr[p] = 0;
            ps_write_addr[p] = 0;
            ps_write_data[p] = 0;
        end
        tick();
        rst_n = 1;
        configure(1);

        // 初始化每个物理地址，然后反复切换分配，检查内容保存及返回位置。
        for (int b = 0; b < BANK_COUNT; b++) begin
            for (int row = 0; row < ROWS; row++) begin
                clear_requests();
                if (b == 0) begin
                    ia_write_en = 1;
                    ia_write_addr[0] = ADDR_BITS'(row);
                    ia_write_mask[0] = 16'hffff;
                    ia_write_data[0] = {random_value(),random_value(),random_value(),random_value()};
                end else begin
                    ps_write_en = 1;
                    ps_write_addr[0] = ADDR_BITS'((b-1)*ROWS+row);
                    ps_write_data[0] = {random_value(),random_value(),random_value(),random_value()};
                end
                tick();
            end
        end

        for (int iteration = 0; iteration < RANDOM_CYCLES; iteration++) begin
            int first_bank, available, offset, row;
            if (capacity_fault || (iteration % 97 == 0)) begin
                configure(1 << (random_value()%3));
            end
            clear_requests();
            first_bank = int'(random_value()%32'(configured_banks));
            for (int p = 0; p < 2; p++) begin
                row = int'(random_value()%ROWS);
                ia_read_addr[p] = ADDR_BITS'(row*configured_banks+(first_bank+p)%configured_banks);
                ia_write_addr[p] = ADDR_BITS'(((row+1)%ROWS)*configured_banks+(first_bank+p)%configured_banks);
                ia_read_en[p] = (p < configured_banks) && (random_value()%4 != 0);
                ia_write_en[p] = (p < configured_banks) && (random_value()%4 != 0);
                ia_write_data[p] = {random_value(),random_value(),random_value(),random_value()};
                ia_write_mask[p] = 16'(random_value());
            end
            available = BANK_COUNT-configured_banks;
            first_bank = int'(random_value()%32'(available));
            for (int p = 0; p < 4; p++) begin
                row = int'(random_value()%ROWS);
                offset = ((first_bank+p)%available)*ROWS;
                ps_read_addr[p] = ADDR_BITS'(offset+row);
                ps_write_addr[p] = ADDR_BITS'(offset+(row+1)%ROWS);
                ps_read_en[p] = (p < available) && (random_value()%4 != 0);
                ps_write_en[p] = (p < available) && (random_value()%4 != 0);
                ps_write_data[p] = {random_value(),random_value(),random_value(),random_value()};
            end
            // 随机加入越界、端口争用、同地址读写和配置期间请求。
            if (iteration%19 == 0) begin
                ia_read_addr[0] = ADDR_BITS'(random_value());
                ia_read_en[0] = 1;
            end
            if (iteration%23 == 0) begin
                ps_write_addr[1] = ps_write_addr[0];
                ps_write_en[1:0] = 3;
            end
            if (iteration%29 == 0) begin
                ia_write_addr[0] = ia_read_addr[0];
                ia_read_en[0] = 1;
                ia_write_en[0] = 1;
            end
            if (iteration%31 == 0) begin
                ps_write_addr[0] = ps_read_addr[0];
                ps_read_en[0] = 1;
                ps_write_en[0] = 1;
            end
            if (iteration%37 == 0) begin
                cfg_valid = 1;
                cfg_ia_banks = COUNT_BITS'(random_value());
            end
            tick();
            cfg_valid = 0;
            active_checks++;
            if (capacity_fault) fault_checks++;
            if (iteration%101 == 0) begin
                clear_requests();
                rst_n = 0;
                tick();
                rst_n = 1;
                configure(1);
                reset_checks++;
            end
        end
        $display("SHARED_EQ_PASS cycles=%0d active=%0d configurations=%0d faults=%0d resets=%0d", cycles, active_checks, configuration_checks, fault_checks, reset_checks);
        $finish;
    end
endmodule
