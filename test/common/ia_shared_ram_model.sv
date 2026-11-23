// IA 共享端口的独立存储模型：两个 128 位端口，同步读取及字节写使能。
module ia_shared_ram_model #(
    parameter int unsigned WORD_COUNT = 128,
    parameter int unsigned ADDRESS_WIDTH = 10
) (
    input logic clk,
    input logic [1:0] ram_port_wr_en,
    input logic [ADDRESS_WIDTH-1:0] ram_port_wr_addr [0:1],
    input logic [127:0] ram_port_wr_data [0:1],
    input logic [15:0] ram_port_wr_mask [0:1],
    input logic [1:0] ram_port_rd_en,
    input logic [ADDRESS_WIDTH-1:0] ram_port_rd_addr [0:1],
    output logic [127:0] ram_port_rd_data [0:1]
);
    localparam int INDEX_WIDTH = WORD_COUNT <= 1 ? 1 : $clog2(WORD_COUNT);
    logic [127:0] memory [WORD_COUNT];
    always @(posedge clk) begin
        for (int port_index = 0; port_index < 2; port_index++) begin
            if (ram_port_wr_en[port_index]) begin
                assert (int'(ram_port_wr_addr[port_index]) < WORD_COUNT);
                for (int byte_index = 0; byte_index < 16; byte_index++)
                    if (ram_port_wr_mask[port_index][byte_index])
                        memory[INDEX_WIDTH'(ram_port_wr_addr[port_index])][byte_index*8 +: 8] <=
                            ram_port_wr_data[port_index][byte_index*8 +: 8];
            end
            if (ram_port_rd_en[port_index]) begin
                assert (int'(ram_port_rd_addr[port_index]) < WORD_COUNT);
                ram_port_rd_data[port_index] <= memory[INDEX_WIDTH'(ram_port_rd_addr[port_index])];
            end
        end
    end
endmodule
