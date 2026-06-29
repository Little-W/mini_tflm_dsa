// Pseudo dual-port RAM.
// Port A: synchronous write port.
// Port B: synchronous read port with registered output.
module pseudo_dual_port_ram #(
    parameter DATA_WIDTH = 8,    // 数据宽度
    parameter ADDR_WIDTH = 6     // 地址宽度
) (
    input  wire                  clk,    // 时钟信号
    input  wire                  ena,    // 端口A使能信号
    input  wire                  enb,    // 端口B使能信号
    input  wire                  wea,    // 端口A写使能信号
    input  wire [ADDR_WIDTH-1:0] addra,  // 端口A地址
    input  wire [DATA_WIDTH-1:0] dia,    // 端口A数据输入
    input  wire [ADDR_WIDTH-1:0] addrb,  // 端口B地址
    output reg  [DATA_WIDTH-1:0] dob     // 端口B数据输出
);
    localparam int unsigned RAM_DEPTH = 1 << ADDR_WIDTH;

    // In FPGA flows this coding style can be inferred as distributed RAM or
    // block RAM depending on depth, target device, and synthesis attributes.
    reg [DATA_WIDTH-1:0] ram [0:RAM_DEPTH-1];

    always @(posedge clk) begin
        if (ena && wea) begin
            ram[addra] <= dia;
        end

        if (enb) begin
            dob <= ram[addrb];
        end
    end
endmodule
