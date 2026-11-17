module single_port_ram #(
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
            dout <= ram[addr];  // 读操作（修改：无论读写都更新输出）
        end
    end

endmodule
