`timescale 1ns/1ps
module tb_regfile_asic #(
    parameter int p_width = 32,
    parameter int p_depth = 256,
    parameter int p_unit = 32,
    parameter int p_ports = 1,
    parameter bit p_sync = 1,
    parameter int p_address_width = (p_depth <= 1) ? 1 : $clog2(p_depth)
);
    logic clk = 0;
    always #5 clk = ~clk;
    logic write_enable;
    logic [p_address_width-1:0] write_address;
    logic [p_width-1:0] write_data;
    logic [p_width/p_unit-1:0] write_mask;
    logic [p_ports-1:0] read_enable;
    logic [p_ports-1:0][p_address_width-1:0] read_address;
    wire [p_ports-1:0][p_width-1:0] output_data;
    logic [p_width-1:0] reference_memory [0:p_depth-1];
    logic [p_ports-1:0][p_width-1:0] reference_output;
    int checks = 0, collisions = 0, held = 0, unknown_controls = 0, invalid_reads = 0;
    int seed;

    regfile #(
        .p_data_width(p_width), .p_depth(p_depth), .p_addr_width(p_address_width),
        .p_write_unit(p_unit), .p_read_ports(p_ports), .p_sync_read(p_sync)
    ) dut (
        .clk(clk), .i_wr_en(write_enable), .i_wr_addr(write_address),
        .i_wr_data(write_data), .i_wr_mask(write_mask),
        .i_rd_en(read_enable), .i_rd_addr(read_address), .o_rd_data(output_data)
    );

    // 参考数组直接在接受写入的边沿更新，同步读取采样该边沿之前的内容。
    always @(posedge clk) begin
        for (int port_index = 0; port_index < p_ports; port_index++) begin
            if (read_enable[port_index]) reference_output[port_index] <= reference_memory[read_address[port_index]];
        end
        if (write_enable) begin
            for (int segment = 0; segment < p_width/p_unit; segment++) begin
                if (write_mask[segment])
                    reference_memory[write_address][segment*p_unit +: p_unit] <=
                        write_data[segment*p_unit +: p_unit];
            end
        end
        #1;
        for (int port_index = 0; port_index < p_ports; port_index++) begin
            if (p_sync) begin
                if (output_data[port_index] !== reference_output[port_index])
                    $fatal(1, "Read mismatch check=%0d port=%0d got=%h expected=%h", checks,
                        port_index, output_data[port_index], reference_output[port_index]);
            end else begin
                if (output_data[port_index] !== reference_memory[read_address[port_index]])
                    $fatal(1, "Async read mismatch check=%0d port=%0d", checks, port_index);
            end
            checks++;
        end
    end

    initial begin
        seed = 32'h618f27b9;
        seed = $urandom(seed);
        write_enable = 0;
        write_address = 0;
        write_data = 0;
        write_mask = 0;
        read_enable = 0;
        read_address = 0;
        // 连续写入每个逻辑地址，每拍同时读取当前写入位置和相邻地址。
        for (int address = 0; address < p_depth; address++) begin
            @(negedge clk);
            write_enable = 1;
            write_address = p_address_width'(address);
            write_data = p_width'({$urandom, $urandom});
            write_mask = '1;
            read_enable = '1;
            for (int port_index = 0; port_index < p_ports; port_index++)
                read_address[port_index] = p_address_width'((address + port_index) % p_depth);
        end
        for (int cycle = 0; cycle < 12000; cycle++) begin
            @(negedge clk);
            write_enable = 1'($urandom);
            write_address = p_address_width'($urandom);
            write_data = p_width'({$urandom, $urandom});
            write_mask = (p_width/p_unit)'($urandom);
            if (cycle % 31 == 0) begin write_enable = 1'bx; unknown_controls++; end
            if (cycle % 37 == 0) begin write_enable = 1'bz; unknown_controls++; end
            if (cycle % 41 == 0) write_address[cycle % p_address_width] = 1'bx;
            if (cycle % 43 == 0) write_mask[cycle % (p_width/p_unit)] = 1'bx;
            if (cycle % 47 == 0) write_data[cycle % p_width] = 1'bx;
            for (int port_index = 0; port_index < p_ports; port_index++) begin
                read_enable[port_index] = 1'($urandom);
                read_address[port_index] = p_address_width'($urandom);
                if (cycle % 3 == 0) begin
                    read_enable[port_index] = 1;
                    read_address[port_index] = write_address;
                end
                if (cycle % 53 == 0) begin read_enable[port_index] = 1'bx; unknown_controls++; end
                if (cycle % 59 == 0) begin read_enable[port_index] = 1'bz; unknown_controls++; end
                if (read_enable[port_index] === 1'b0) held++;
                if (write_enable === 1'b1 && read_enable[port_index] === 1'b1 &&
                    (|write_mask) === 1'b1 && write_address < p_depth &&
                    read_address[port_index] == write_address) collisions++;
                if (read_enable[port_index] === 1'b1 && !(read_address[port_index] < p_depth)) invalid_reads++;
            end
        end
        // 最后一次写入后立刻读取，随后长时间保持读输出。
        @(negedge clk); write_enable = 1; write_address = p_address_width'(p_depth-1);
        write_mask = '1; write_data = '1; read_enable = '0;
        @(negedge clk); write_enable = 0; read_enable = '1;
        for (int port_index = 0; port_index < p_ports; port_index++) read_address[port_index] = write_address;
        @(negedge clk); read_enable = '0;
        repeat (5) @(negedge clk);
        if (checks == 0 || collisions == 0 || held == 0 || unknown_controls == 0)
            $fatal(1, "Insufficient coverage");
        $display("ASIC_REGFILE_PASS width=%0d depth=%0d unit=%0d ports=%0d sync=%0d checks=%0d collisions=%0d held=%0d unknown=%0d invalid=%0d",
            p_width, p_depth, p_unit, p_ports, p_sync, checks, collisions, held, unknown_controls, invalid_reads);
        $finish;
    end
endmodule
