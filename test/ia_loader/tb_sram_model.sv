/*
 * tb_sram_model — 简单 ICB SRAM 模型
 * ============================================================
 * 单拍读写应答的 ICB slave 存储器模型。
 * 可参数化深度，从 init.mem 文件初始化。
 */

module tb_sram_model #(
    parameter int unsigned DEPTH     = 4096,
    parameter int unsigned DATA_W    = 32,
    parameter int unsigned ADDR_W    = 32,
    parameter string       INIT_FILE = "out/init.mem"
) (
    input  logic                clk,
    input  logic                rst_n,
    // ICB slave
    input  logic                cmd_valid,
    output logic                cmd_ready,
    input  logic [ADDR_W-1:0]   cmd_addr,
    input  logic                cmd_read,
    input  logic [DATA_W-1:0]   cmd_wdata,
    input  logic [DATA_W/8-1:0] cmd_wmask,
    output logic                rsp_valid,
    input  logic                rsp_ready,
    output logic [DATA_W-1:0]   rsp_rdata,
    output logic                rsp_err
);

  logic [DATA_W-1:0] mem [DEPTH];

  initial begin
    $readmemh(INIT_FILE, mem);
    $display("[SRAM] Loaded %0d words from %s", DEPTH, INIT_FILE);
  end

  logic        rsp_valid_r;
  logic [DATA_W-1:0] rsp_rdata_r;

  assign cmd_ready = !rsp_valid_r || rsp_ready;
  assign rsp_valid = rsp_valid_r;
  assign rsp_rdata = rsp_rdata_r;
  assign rsp_err   = 1'b0;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rsp_valid_r <= 1'b0;
      rsp_rdata_r <= '0;
    end else begin
      if (cmd_valid && cmd_ready) begin
        rsp_valid_r <= 1'b1;
        if (cmd_read) begin
          automatic logic [ADDR_W-1:0] widx = cmd_addr >> $clog2(DATA_W/8);
          rsp_rdata_r <= (widx < DEPTH) ? mem[widx] : {DATA_W{1'b1}};
        end else begin
          automatic logic [ADDR_W-1:0] widx = cmd_addr >> $clog2(DATA_W/8);
          if (widx < DEPTH) begin
            for (int b = 0; b < DATA_W/8; b++)
              if (cmd_wmask[b]) mem[widx][b*8 +: 8] <= cmd_wdata[b*8 +: 8];
          end
          rsp_rdata_r <= '0;
        end
      end else if (rsp_ready && rsp_valid_r) begin
        rsp_valid_r <= 1'b0;
      end
    end
  end

endmodule
