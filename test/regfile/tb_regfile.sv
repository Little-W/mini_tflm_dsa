`timescale 1ns/1ps
module tb_regfile #(
    parameter int DATA_WIDTH = 32,
    parameter int DEPTH = 64,
    parameter int WRITE_UNIT = 8,
    parameter int READ_PORTS = 3,
    parameter int ADDR_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
);
    logic clk = 1'b0;
    always #5 clk = ~clk;
    logic wr_en;
    logic [ADDR_WIDTH-1:0] wr_addr;
    logic [DATA_WIDTH-1:0] wr_data;
    logic [DATA_WIDTH/WRITE_UNIT-1:0] wr_mask;
    logic [READ_PORTS-1:0] rd_en;
    logic [READ_PORTS-1:0][ADDR_WIDTH-1:0] rd_addr;
    logic [READ_PORTS-1:0][DATA_WIDTH-1:0] sync_data, async_data;
    logic [DATA_WIDTH-1:0] expected [DEPTH];
    logic [READ_PORTS-1:0][DATA_WIDTH-1:0] expected_sync;
    integer checks = 0;
    integer collisions = 0;
    integer held_reads = 0;
    regfile #(.p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_write_unit(WRITE_UNIT),
        .p_read_ports(READ_PORTS), .p_sync_read(1'b1)) u_sync (
        .clk(clk), .i_wr_en(wr_en), .i_wr_addr(wr_addr), .i_wr_data(wr_data),
        .i_wr_mask(wr_mask), .i_rd_en(rd_en), .i_rd_addr(rd_addr), .o_rd_data(sync_data));
    regfile #(.p_data_width(DATA_WIDTH), .p_depth(DEPTH), .p_write_unit(WRITE_UNIT),
        .p_read_ports(READ_PORTS), .p_sync_read(1'b0)) u_async (
        .clk(clk), .i_wr_en(wr_en), .i_wr_addr(wr_addr), .i_wr_data(wr_data),
        .i_wr_mask(wr_mask), .i_rd_en(rd_en), .i_rd_addr(rd_addr), .o_rd_data(async_data));

    if (WRITE_UNIT == DATA_WIDTH && DEPTH == (1 << ADDR_WIDTH)) begin : g_wrapper
        logic [DATA_WIDTH-1:0] wrapper_data;
        pseudo_dual_port_ram #(.DATA_WIDTH(DATA_WIDTH), .ADDR_WIDTH(ADDR_WIDTH)) u_wrapper (
            .clk(clk), .ena(wr_en), .wea(wr_mask[0]), .enb(rd_en[0]),
            .addra(wr_addr), .dia(wr_data), .addrb(rd_addr[0]), .dob(wrapper_data));
        always @(posedge clk) begin
            #2;
            if (checks != 0 && wrapper_data !== expected_sync[0]) begin
                $fatal(1, "compatibility wrapper mismatch");
            end
        end
    end

    initial begin
        int seed;
        seed = 32'h521b96a3;
        seed = $urandom(seed);
        wr_en = 0;
        wr_addr = 0;
        wr_data = 0;
        wr_mask = 0;
        rd_en = 0;
        rd_addr = 0;
        // 通过写端口建立已知内容，检查不依赖存储器的仿真初始化值。
        for (int address = 0; address < DEPTH; address++) begin
            @(negedge clk);
            wr_en = 1;
            wr_addr = ADDR_WIDTH'(address);
            wr_mask = '1;
            wr_data = DATA_WIDTH'({$urandom, $urandom});
            expected[address] = wr_data;
            @(posedge clk);
            #1;
        end
        @(negedge clk);
        wr_en = 0;
        rd_en = '1;
        rd_addr = '0;
        @(posedge clk);
        #1;
        for (int port_index = 0; port_index < READ_PORTS; port_index++) begin
            expected_sync[port_index] = expected[0];
        end
        for (int cycle = 0; cycle < 5000; cycle++) begin
            @(negedge clk);
            wr_en = ($urandom_range(0, 3) != 0);
            wr_addr = ADDR_WIDTH'($urandom_range(0, DEPTH-1));
            wr_mask = (DATA_WIDTH/WRITE_UNIT)'($urandom);
            wr_data = DATA_WIDTH'({$urandom, $urandom});
            for (int port_index = 0; port_index < READ_PORTS; port_index++) begin
                rd_en[port_index] = 1'($urandom);
                rd_addr[port_index] = ADDR_WIDTH'($urandom_range(0, DEPTH-1));
                if (cycle % 7 == 0) begin
                    rd_addr[port_index] = wr_addr;
                    rd_en[port_index] = 1;
                end
                if (rd_en[port_index]) begin
                    expected_sync[port_index] = expected[rd_addr[port_index]];
                    if (wr_en && rd_addr[port_index] == wr_addr) collisions++;
                end else held_reads++;
            end
            @(posedge clk);
            if (wr_en) begin
                for (int segment = 0; segment < DATA_WIDTH/WRITE_UNIT; segment++) begin
                    if (wr_mask[segment]) begin
                        expected[wr_addr][segment*WRITE_UNIT +: WRITE_UNIT] =
                            wr_data[segment*WRITE_UNIT +: WRITE_UNIT];
                    end
                end
            end
            #1;
            for (int port_index = 0; port_index < READ_PORTS; port_index++) begin
                if (sync_data[port_index] !== expected_sync[port_index]) begin
                    $fatal(1, "sync mismatch cycle=%0d port=%0d", cycle, port_index);
                end
                if (async_data[port_index] !== expected[rd_addr[port_index]]) begin
                    $fatal(1, "async mismatch cycle=%0d port=%0d", cycle, port_index);
                end
                checks += 2;
            end
        end
        if (collisions == 0 || held_reads == 0) $fatal(1, "insufficient event coverage");
        $display("REGFILE_PASS width=%0d depth=%0d write_unit=%0d ports=%0d checks=%0d collisions=%0d held_reads=%0d",
            DATA_WIDTH, DEPTH, WRITE_UNIT, READ_PORTS, checks, collisions, held_reads);
        $finish;
    end
endmodule
