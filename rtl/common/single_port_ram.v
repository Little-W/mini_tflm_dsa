/* 单端口同步读写存储器，写入时返回写入前的数据，访问禁止时保持输出。 */ module single_port_ram #(
    parameter DATA_WIDTH = 8,    // 数据宽度
    parameter ADDR_WIDTH = 6     // 地址宽度
)(
    input                        clk,   // 时钟信号
    input                        en,    // 使能信号
    input                        we,    // 写使能信号
    input      [ADDR_WIDTH-1:0]  addr,  // 地址信号
    input      [DATA_WIDTH-1:0]  di,    // 数据输入
    output reg [DATA_WIDTH-1:0]  dout   // 数据输出
);

    reg [DATA_WIDTH-1:0] ram[(1<<ADDR_WIDTH)-1:0]; // RAM 存储器

    always @(posedge clk) begin
        if (en) begin
            if (we) begin
                ram[addr] <= di; // 写操作
            end
            dout <= ram[addr];  // 当前边沿返回写入前的存储值。
        end
    end

endmodule
