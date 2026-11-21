`timescale 1ns/1ps

module tb_vector_shared_store #(
    parameter int p_bank_bytes = 2048,
    parameter int p_banks = 7,
    parameter bit p_fixed_ps_channels = 1'b1,
    parameter bit p_shared_write_stage = 1'b1,
    parameter int p_cycles = 2000
);
    localparam int p_rows = p_bank_bytes / 16;
    localparam int p_words = p_banks * p_rows;
    localparam int p_addr_width = $clog2(p_words);
    localparam int p_count_width = $clog2(p_banks + 1);
    localparam int p_max_ia_banks = p_banks >= 8 ? 4 : 2;

    logic clk = 0, rst_n = 0, cfg_valid = 0, enable = 0, flush = 0;
    logic [p_count_width-1:0] cfg_ia_banks = 1;
    logic idle, error, ram_fault;
    logic weight_read_en = 0, weight_write_en = 0, weight_read_valid;
    logic [p_addr_width-1:0] weight_read_addr = 0, weight_write_addr = 0;
    logic [127:0] weight_read_data, weight_write_data = 0;
    logic [15:0] weight_write_mask = 0;
    logic ps_read_en = 0, ps_write_en = 0, ps_read_valid;
    logic [p_addr_width-1:0] ps_read_addr = 0, ps_write_addr = 0;
    logic [511:0] ps_read_data, ps_write_data = 0;
    logic [1:0] ia_read_en, ia_write_en;
    logic [p_addr_width-1:0] ia_read_addr[2], ia_write_addr[2];
    logic [127:0] ia_read_data[2], ia_write_data[2], ia_shared_write_data;
    logic [15:0] ia_write_mask[2];
    logic [3:0] ram_ps_read_en, ram_ps_write_en;
    logic [p_addr_width-1:0] ram_ps_read_addr[4], ram_ps_write_addr[4];
    logic [127:0] ram_ps_read_data[4], ram_ps_write_data[4];

    // 手动端口代表任务切换后的矩阵所有者，用于检查双方访问同一物理存储。
    logic host_write = 0, host_ps = 0;
    logic [p_addr_width-1:0] host_addr = 0;
    logic [511:0] host_data = 0;
    logic [1:0] memory_ia_write_en;
    logic [p_addr_width-1:0] memory_ia_write_addr[2];
    logic [127:0] memory_ia_write_data[2], memory_shared_write_data;
    logic [15:0] memory_ia_write_mask[2];
    logic [3:0] memory_ps_write_en;
    logic [p_addr_width-1:0] memory_ps_write_addr[4];
    logic [127:0] memory_ps_write_data[4];

    logic [127:0] memory[p_words];
    bit [15:0] known[p_words];
    bit configured = 0, fault = 0;
    int allocation = 1;
    longint cycles = 0, read_checks = 0, checked_bytes = 0, writes = 0;
    longint concurrent_reads = 0, concurrent_writes = 0, simultaneous_rw = 0;
    longint fault_events = 0, configurations = 0, flushes = 0, host_writes = 0;
    bit held_weight_known = 0, held_ps_known = 0;
    logic [127:0] held_weight;
    logic [511:0] held_ps;

    vector_shared_store #(
        .p_bank_bytes(p_bank_bytes), .p_total_bytes(p_bank_bytes * p_banks),
        .p_fixed_ps_channels(p_fixed_ps_channels)
    ) dut (
        .clk(clk), .rst_n(rst_n), .i_cfg_valid(cfg_valid), .i_cfg_ia_banks(cfg_ia_banks),
        .i_enable(enable), .i_flush(flush), .o_idle(idle), .o_error(error),
        .i_weight_read_en(weight_read_en), .i_weight_read_addr(weight_read_addr),
        .o_weight_read_valid(weight_read_valid), .o_weight_read_data(weight_read_data),
        .i_weight_write_en(weight_write_en), .i_weight_write_addr(weight_write_addr),
        .i_weight_write_data(weight_write_data), .i_weight_write_mask(weight_write_mask),
        .i_ps_read_en(ps_read_en), .i_ps_read_addr(ps_read_addr),
        .o_ps_read_valid(ps_read_valid), .o_ps_read_data(ps_read_data),
        .i_ps_write_en(ps_write_en), .i_ps_write_addr(ps_write_addr), .i_ps_write_data(ps_write_data),
        .o_ia_read_en(ia_read_en), .o_ia_write_en(ia_write_en),
        .o_ia_read_addr(ia_read_addr), .o_ia_write_addr(ia_write_addr), .i_ia_read_data(ia_read_data),
        .o_ia_write_data(ia_write_data), .o_ia_write_mask(ia_write_mask),
        .o_ia_shared_write_data(ia_shared_write_data),
        .o_ps_read_en(ram_ps_read_en), .o_ps_write_en(ram_ps_write_en),
        .o_ps_read_addr(ram_ps_read_addr), .o_ps_write_addr(ram_ps_write_addr),
        .i_ps_read_data(ram_ps_read_data), .o_ps_write_data(ram_ps_write_data)
    );

    always_comb begin
        memory_ia_write_en = ia_write_en;
        memory_shared_write_data = ia_shared_write_data;
        memory_ps_write_en = ram_ps_write_en;
        for (int port_index = 0; port_index < 2; port_index++) begin
            memory_ia_write_addr[port_index] = ia_write_addr[port_index];
            memory_ia_write_data[port_index] = ia_write_data[port_index];
            memory_ia_write_mask[port_index] = ia_write_mask[port_index];
        end
        for (int port_index = 0; port_index < 4; port_index++) begin
            memory_ps_write_addr[port_index] = ram_ps_write_addr[port_index];
            memory_ps_write_data[port_index] = ram_ps_write_data[port_index];
        end
        if (host_write) begin
            if (host_ps) begin
                memory_ps_write_en = 4'b1111;
                for (int channel = 0; channel < 4; channel++) begin
                    memory_ps_write_addr[channel] = p_fixed_ps_channels ? host_addr :
                        p_addr_width'(channel * p_rows + int'(host_addr));
                    memory_ps_write_data[channel] = host_data[128*channel +: 128];
                end
            end else begin
                memory_ia_write_en = 2'b10;
                memory_ia_write_addr[1] = host_addr;
                memory_ia_write_data[1] = host_data[127:0];
                memory_ia_write_mask[1] = '1;
                memory_shared_write_data = host_data[127:0];
            end
        end
    end

    if (p_fixed_ps_channels) begin : g_fixed
        ia_ps_channel_ram #(
            .p_bank_bytes(p_bank_bytes), .p_total_bytes(p_bank_bytes * p_banks),
            .p_shared_write_stage(p_shared_write_stage)
        ) u_memory (
            .clk(clk), .rst_n(rst_n), .i_cfg_valid(cfg_valid), .i_cfg_ia_banks(cfg_ia_banks),
            .o_capacity_fault(ram_fault), .i_ia_read_en(ia_read_en), .i_ia_write_en(memory_ia_write_en),
            .i_ia_read_addr(ia_read_addr), .i_ia_write_addr(memory_ia_write_addr), .o_ia_read_data(ia_read_data),
            .i_ia_write_data(memory_ia_write_data), .i_ia_write_mask(memory_ia_write_mask),
            .i_ia_shared_write_data(memory_shared_write_data),
            .i_ps_read_en(ram_ps_read_en), .i_ps_write_en(memory_ps_write_en),
            .i_ps_read_addr(ram_ps_read_addr), .i_ps_write_addr(memory_ps_write_addr),
            .o_ps_read_data(ram_ps_read_data), .i_ps_write_data(memory_ps_write_data)
        );
    end else begin : g_rotating
        ia_ps_shared_ram #(
            .BANK_BYTES(p_bank_bytes), .TOTAL_BYTES(p_bank_bytes * p_banks)
        ) u_memory (
            .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ia_banks(cfg_ia_banks),
            .capacity_fault(ram_fault), .ia_read_en(ia_read_en), .ia_write_en(memory_ia_write_en),
            .ia_read_addr(ia_read_addr), .ia_write_addr(memory_ia_write_addr), .ia_read_data(ia_read_data),
            .ia_write_data(memory_ia_write_data), .ia_write_mask(memory_ia_write_mask),
            .ps_read_en(ram_ps_read_en), .ps_write_en(memory_ps_write_en),
            .ps_read_addr(ram_ps_read_addr), .ps_write_addr(memory_ps_write_addr),
            .ps_read_data(ram_ps_read_data), .ps_write_data(memory_ps_write_data)
        );
    end

    function automatic int weight_location(input int address);
        return (address % allocation) * p_rows + address / allocation;
    endfunction

    function automatic int ps_location(input int address, input int channel);
        if (p_fixed_ps_channels) begin
            return (allocation + address / (p_rows/4)) * p_rows +
                channel * (p_rows/4) + address % (p_rows/4);
        end
        return (allocation + channel) * p_rows + address;
    endfunction

    function automatic logic [511:0] random_data;
        for (int word_index = 0; word_index < 16; word_index++) begin
            random_data[32*word_index +: 32] = $urandom;
        end
    endfunction

    task automatic clear_requests;
        cfg_valid = 0;
        flush = 0;
        weight_read_en = 0;
        weight_write_en = 0;
        ps_read_en = 0;
        ps_write_en = 0;
    endtask

    task automatic check_word(input logic [127:0] actual, input logic [127:0] expected,
                              input bit [15:0] valid_bytes, input int kind);
        for (int byte_index = 0; byte_index < 16; byte_index++) begin
            if (valid_bytes[byte_index]) begin
                if (actual[8*byte_index +: 8] !== expected[8*byte_index +: 8]) begin
                    $fatal(1, "数据不匹配 cycle=%0d kind=%0d byte=%0d got=%0h expected=%0h",
                        cycles, kind, byte_index, actual, expected);
                end
                checked_bytes++;
            end
        end
        read_checks++;
    endtask

    task automatic step;
        bit active, weight_bad, ps_bad, new_error, cfg_ok, effective_write;
        bit read_weight, write_weight, read_ps, write_ps;
        logic [127:0] expected_weight, expected_ps[4];
        bit [15:0] expected_weight_known, expected_ps_known[4];
        int location;
        clk = 0;
        #1;
        effective_write = weight_write_en && (weight_write_mask != 0);
        cfg_ok = (int'(cfg_ia_banks) == 1 || int'(cfg_ia_banks) == 2 || int'(cfg_ia_banks) == 4) &&
            int'(cfg_ia_banks) <= p_banks - 4;
        active = rst_n && enable && configured && !fault && !cfg_valid && !flush;
        weight_bad = (weight_read_en && int'(weight_read_addr) >= allocation*p_rows) ||
            (effective_write && int'(weight_write_addr) >= allocation*p_rows) ||
            (weight_read_en && effective_write && weight_read_addr == weight_write_addr);
        ps_bad = (ps_read_en && int'(ps_read_addr) >= p_rows) ||
            (ps_write_en && int'(ps_write_addr) >= p_rows) ||
            (ps_read_en && ps_write_en && ps_read_addr == ps_write_addr);
        new_error = enable && !cfg_valid && !flush && !fault &&
            ((!configured && (weight_read_en || effective_write || ps_read_en || ps_write_en)) ||
             (configured && (weight_bad || ps_bad)));
        read_weight = active && weight_read_en && !weight_bad;
        write_weight = active && effective_write && !weight_bad;
        read_ps = active && ps_read_en && !ps_bad;
        write_ps = active && ps_write_en && !ps_bad;
        if (ia_read_en !== {1'b0, read_weight} || ia_write_en !== {1'b0, write_weight} ||
            ram_ps_read_en !== {4{read_ps}} || ram_ps_write_en !== {4{write_ps}}) begin
            $fatal(1, "物理使能不匹配 cycle=%0d", cycles);
        end
        if (read_weight) begin
            location = weight_location(int'(weight_read_addr));
            expected_weight = memory[location];
            expected_weight_known = known[location];
        end
        if (read_ps) begin
            for (int channel = 0; channel < 4; channel++) begin
                location = ps_location(int'(ps_read_addr), channel);
                expected_ps[channel] = memory[location];
                expected_ps_known[channel] = known[location];
            end
        end
        if (write_weight) begin
            location = weight_location(int'(weight_write_addr));
            for (int byte_index = 0; byte_index < 16; byte_index++) begin
                if (weight_write_mask[byte_index]) begin
                    memory[location][8*byte_index +: 8] = weight_write_data[8*byte_index +: 8];
                    known[location][byte_index] = 1;
                end
            end
            writes++;
        end
        if (write_ps) begin
            for (int channel = 0; channel < 4; channel++) begin
                location = ps_location(int'(ps_write_addr), channel);
                memory[location] = ps_write_data[128*channel +: 128];
                known[location] = '1;
            end
            writes += 4;
        end
        if (read_weight && read_ps) concurrent_reads++;
        if (write_weight && write_ps) concurrent_writes++;
        if ((read_weight && write_weight) || (read_ps && write_ps)) simultaneous_rw++;
        if (!rst_n) begin
            configured = 0;
            fault = 0;
            held_weight_known = 0;
            held_ps_known = 0;
        end else if (flush) begin
            configured = 0;
            fault = 0;
            flushes++;
        end else if (cfg_valid) begin
            configured = cfg_ok;
            fault = !cfg_ok;
            held_weight_known = 0;
            held_ps_known = 0;
            if (cfg_ok) allocation = int'(cfg_ia_banks);
            configurations++;
        end else if (new_error) begin
            fault = 1;
            fault_events++;
        end
        clk = 1;
        #1;
        if (error !== fault || weight_read_valid !== read_weight || ps_read_valid !== read_ps) begin
            $fatal(1, "同步返回或错误状态不匹配 cycle=%0d error=%0b/%0b weight=%0b/%0b ps=%0b/%0b",
                cycles, error, fault, weight_read_valid, read_weight, ps_read_valid, read_ps);
        end
        if (configured && ram_fault) $fatal(1, "合法配置出现物理 RAM 错误 cycle=%0d", cycles);
        if (read_weight) begin
            check_word(weight_read_data, expected_weight, expected_weight_known, 0);
            held_weight = weight_read_data;
            held_weight_known = 1;
        end else if (held_weight_known && !cfg_valid && !flush && rst_n && weight_read_data !== held_weight) begin
            $fatal(1, "权重同步输出在无读取时改变 cycle=%0d", cycles);
        end
        if (read_ps) begin
            for (int channel = 0; channel < 4; channel++) begin
                check_word(ps_read_data[128*channel +: 128], expected_ps[channel], expected_ps_known[channel], channel+1);
            end
            held_ps = ps_read_data;
            held_ps_known = 1;
        end else if (held_ps_known && !cfg_valid && !flush && rst_n && ps_read_data !== held_ps) begin
            $fatal(1, "部分和同步输出在无读取时改变 cycle=%0d", cycles);
        end
        clk = 0;
        #1;
        cycles++;
    endtask

    task automatic configure(input int banks);
        clear_requests();
        cfg_valid = 1;
        cfg_ia_banks = p_count_width'(banks);
        step();
        clear_requests();
        enable = 1;
        step();
        if (!idle) $fatal(1, "空闲状态错误");
    endtask

    task automatic host_store(input bit select_ps, input int address, input logic [511:0] data);
        int location;
        clear_requests();
        enable = 0;
        step();
        host_write = 1;
        host_ps = select_ps;
        host_addr = p_addr_width'(address);
        host_data = data;
        if (select_ps) begin
            for (int channel = 0; channel < 4; channel++) begin
                location = ps_location(address, channel);
                memory[location] = data[128*channel +: 128];
                known[location] = '1;
            end
        end else begin
            location = weight_location(address);
            memory[location] = data[127:0];
            known[location] = '1;
        end
        #1;
        clk = 1;
        #1;
        if (ram_fault || error || weight_read_valid || ps_read_valid) begin
            $fatal(1, "其他任务访问共享 RAM 失败");
        end
        clk = 0;
        #1;
        host_write = 0;
        enable = 1;
        held_weight_known = 0;
        held_ps_known = 0;
        host_writes++;
    endtask

    initial begin
        step();
        rst_n = 1;
        enable = 1;
        weight_read_en = 1;
        step();
        if (!error) $fatal(1, "未配置访问没有报告错误");

        for (int banks = 1; banks <= p_max_ia_banks; banks *= 2) begin
            configure(banks);
            // 写满所有 VCE 可访问地址，覆盖每个 IA bank 和四个 PS 通道的边界。
            for (int address = 0; address < allocation*p_rows; address++) begin
                clear_requests();
                weight_write_en = 1;
                weight_write_addr = p_addr_width'(address);
                weight_write_data = 128'(random_data());
                weight_write_mask = '1;
                if (address < p_rows) begin
                    ps_write_en = 1;
                    ps_write_addr = p_addr_width'(address);
                    ps_write_data = random_data();
                end
                step();
            end
            for (int address = 0; address < allocation*p_rows; address++) begin
                clear_requests();
                weight_read_en = 1;
                weight_read_addr = p_addr_width'(address);
                ps_read_en = 1;
                ps_read_addr = p_addr_width'(address % p_rows);
                step();
            end

            // 连续随机访问验证不同地址读写并行，包含 AXI32、AXI64 和尾部字节掩码。
            for (int iteration = 0; iteration < p_cycles; iteration++) begin
                clear_requests();
                weight_read_en = 1'($urandom);
                weight_write_en = 1'($urandom);
                ps_read_en = 1'($urandom);
                ps_write_en = 1'($urandom);
                weight_read_addr = p_addr_width'($urandom_range(allocation*p_rows-1));
                weight_write_addr = p_addr_width'((int'(weight_read_addr)+1+$urandom_range(allocation*p_rows-2)) % (allocation*p_rows));
                ps_read_addr = p_addr_width'($urandom_range(p_rows-1));
                ps_write_addr = p_addr_width'((int'(ps_read_addr)+1+$urandom_range(p_rows-2)) % p_rows);
                weight_write_data = 128'(random_data());
                ps_write_data = random_data();
                case (iteration % 5)
                    0: weight_write_mask = 16'h000f << (4*$urandom_range(3));
                    1: weight_write_mask = 16'h00ff << (8*$urandom_range(1));
                    default: weight_write_mask = 16'($urandom);
                endcase
                step();
            end

            host_store(0, 3, random_data());
            host_store(1, p_rows-1, random_data());
            clear_requests();
            weight_read_en = 1;
            weight_read_addr = p_addr_width'(3);
            ps_read_en = 1;
            ps_read_addr = p_addr_width'(p_rows-1);
            step();
            for (int hold_cycle = 0; hold_cycle < 8; hold_cycle++) begin
                clear_requests();
                step();
            end

            // 零掩码写入不占用写端口，允许同地址读取。
            weight_read_en = 1;
            weight_write_en = 1;
            weight_write_addr = weight_read_addr;
            weight_write_mask = 0;
            step();
            if (error) $fatal(1, "零掩码写入造成错误");

            // 每项错误都检查拒绝访问、错误保持和重新配置后的数据完整性。
            for (int fault_kind = 0; fault_kind < 6; fault_kind++) begin
                configure(banks);
                clear_requests();
                weight_read_addr = p_addr_width'(3);
                weight_write_addr = p_addr_width'(3);
                weight_write_mask = '1;
                ps_read_addr = p_addr_width'(p_rows-1);
                ps_write_addr = p_addr_width'(p_rows-1);
                case (fault_kind)
                    0: begin weight_read_en = 1; weight_write_en = 1; end
                    1: begin ps_read_en = 1; ps_write_en = 1; end
                    2: begin weight_read_en = 1; weight_read_addr = p_addr_width'(banks*p_rows); end
                    3: begin weight_write_en = 1; weight_write_addr = p_addr_width'(banks*p_rows); end
                    4: begin ps_read_en = 1; ps_read_addr = p_addr_width'(p_rows); end
                    5: begin ps_write_en = 1; ps_write_addr = p_addr_width'(p_rows); end
                endcase
                if (fault_kind == 0 || fault_kind == 2 || fault_kind == 3) begin
                    ps_read_en = 1;
                end else begin
                    weight_read_en = 1;
                end
                step();
                if (!error) $fatal(1, "非法访问未报告错误 kind=%0d", fault_kind);
                clear_requests();
                weight_write_en = 1;
                weight_write_addr = 0;
                weight_write_mask = '1;
                step();
                configure(banks);
                weight_read_en = 1;
                weight_read_addr = 0;
                ps_read_en = 1;
                ps_read_addr = p_addr_width'(p_rows-1);
                step();
                weight_read_addr = p_addr_width'(3);
                step();
            end

            clear_requests();
            weight_read_en = 1;
            ps_read_en = 1;
            step();
            flush = 1;
            step();
            if (!idle || error || weight_read_valid || ps_read_valid) $fatal(1, "flush 没有取消返回");
            clear_requests();
            weight_read_en = 1;
            step();
            if (!error) $fatal(1, "flush 后未配置访问没有报告错误");
            configure(banks);

            // 配置周期抑制逻辑请求，禁用期间不产生物理访问。
            cfg_valid = 1;
            weight_write_en = 1;
            weight_write_addr = 0;
            weight_write_mask = '1;
            ps_write_en = 1;
            ps_write_addr = 0;
            step();
            clear_requests();
            enable = 0;
            weight_read_en = 1;
            weight_read_addr = '1;
            ps_write_en = 1;
            ps_write_addr = '1;
            step();
            clear_requests();
            enable = 1;
            step();
        end

        for (int invalid_banks = 0; invalid_banks < 4; invalid_banks++) begin
            configure(invalid_banks == 0 ? 0 : invalid_banks == 1 ? 3 : invalid_banks == 2 ? 5 : p_banks);
            if (!error) $fatal(1, "非法分配没有报告错误");
        end
        configure(1);
        weight_read_en = 1;
        step();
        rst_n = 0;
        clear_requests();
        step();
        rst_n = 1;
        configure(1);
        weight_read_en = 1;
        weight_read_addr = 0;
        step();
        clear_requests();
        step();
        if (!idle || error || ram_fault || concurrent_reads == 0 || concurrent_writes == 0 ||
            simultaneous_rw == 0 || host_writes == 0) $fatal(1, "覆盖计数或结束状态错误");
        $display("VECTOR_SHARED_STORE_PASS cycles=%0d reads=%0d bytes=%0d writes=%0d concurrent_reads=%0d concurrent_writes=%0d simultaneous_rw=%0d faults=%0d configurations=%0d flushes=%0d host_writes=%0d",
            cycles, read_checks, checked_bytes, writes, concurrent_reads, concurrent_writes,
            simultaneous_rw, fault_events, configurations, flushes, host_writes);
        $finish;
    end
endmodule
