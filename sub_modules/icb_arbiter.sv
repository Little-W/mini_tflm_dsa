// ICB总线仲裁器
// 优先级：s4(oa_writer) > s1(kernel_loader) > s0(ia_loader) > s3(vec_requant) > s2(bias_loader)
module icb_arbiter (
    input  wire clk,
    input  wire rst_n,

    // Slave 0: IA Loader
    input  wire s0_req,
    output reg  s0_granted,
    input  wire s0_done,

    // Slave 1: Kernel Loader
    input  wire s1_req,
    output reg  s1_granted,
    input  wire s1_done,

    // Slave 2: Bias Loader
    input  wire s2_req,
    output reg  s2_granted,
    input  wire s2_done,

    // Slave 3: Vec Requant
    input  wire s3_req,
    output reg  s3_granted,
    input  wire s3_done,

    // Slave 4: OA Writer
    input  wire s4_req,
    output reg  s4_granted,
    input  wire s4_done,

    // ICB选择信号
    output reg [2:0] icb_sel
);

    // 当前授权的主机
    reg [2:0] current_master;
    reg       bus_busy;

    // 检测总线是否空闲
    wire bus_idle = !bus_busy || (bus_busy && current_done);

    // 检测当前主机是否完成
    wire current_done = (current_master == 3'd0 && s0_done) ||
                       (current_master == 3'd1 && s1_done) ||
                       (current_master == 3'd2 && s2_done) ||
                       (current_master == 3'd3 && s3_done) ||
                       (current_master == 3'd4 && s4_done);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s0_granted <= 1'b0;
            s1_granted <= 1'b0;
            s2_granted <= 1'b0;
            s3_granted <= 1'b0;
            s4_granted <= 1'b0;
            icb_sel <= 3'd0;
            current_master <= 3'd0;
            bus_busy <= 1'b0;
        end else begin
            // 如果当前主机完成，释放总线
            if (bus_busy && current_done) begin
                s0_granted <= 1'b0;
                s1_granted <= 1'b0;
                s2_granted <= 1'b0;
                s3_granted <= 1'b0;
                s4_granted <= 1'b0;
                bus_busy <= 1'b0;
            end
            // 如果总线空闲，按优先级仲裁
            if (bus_idle) begin
                // 优先级: s4 > s1 > s0 > s3 > s2
                if (s4_req) begin
                    s4_granted <= 1'b1;
                    icb_sel <= 3'd4;
                    current_master <= 3'd4;
                    bus_busy <= 1'b1;
                end else if (s1_req) begin
                    s1_granted <= 1'b1;
                    icb_sel <= 3'd1;
                    current_master <= 3'd1;
                    bus_busy <= 1'b1;
                end else if (s0_req) begin
                    s0_granted <= 1'b1;
                    icb_sel <= 3'd0;
                    current_master <= 3'd0;
                    bus_busy <= 1'b1;
                end else if (s3_req) begin
                    s3_granted <= 1'b1;
                    icb_sel <= 3'd3;
                    current_master <= 3'd3;
                    bus_busy <= 1'b1;
                end else if (s2_req) begin
                    s2_granted <= 1'b1;
                    icb_sel <= 3'd2;
                    current_master <= 3'd2;
                    bus_busy <= 1'b1;
                end
            end
        end
    end

endmodule
