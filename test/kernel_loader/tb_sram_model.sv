module tb_sram_model #(
    parameter int unsigned DEPTH     = 1024,
    parameter int unsigned DATA_W    = 32,
    parameter int unsigned ADDR_W    = 32,
    parameter string       INIT_FILE = "out/init.mem"
) (
  icb_bus_if.slave bus
);

  logic [DATA_W-1:0] mem [DEPTH];

  initial begin
    $readmemh(INIT_FILE, mem);
    $display("[SRAM] Loaded %0d words from %s", DEPTH, INIT_FILE);
  end

  logic rsp_valid_r;
  logic [DATA_W-1:0] rsp_rdata_r;

  assign bus.cmd_ready = !rsp_valid_r || bus.rsp_ready;
  assign bus.rsp_valid = rsp_valid_r;
  assign bus.rsp_rdata = rsp_rdata_r;
  assign bus.rsp_err   = 1'b0;

  always_ff @(posedge bus.clk or negedge bus.rst_n) begin
    if (!bus.rst_n) begin
      rsp_valid_r <= 1'b0;
      rsp_rdata_r <= '0;
    end else begin
      if (bus.cmd_valid && bus.cmd_ready) begin
        rsp_valid_r <= 1'b1;
        if (bus.cmd_read) begin
          automatic logic [ADDR_W-1:0] widx = bus.cmd_addr >> $clog2(DATA_W/8);
          rsp_rdata_r <= (widx < DEPTH) ? mem[widx] : '0;
        end else begin
          automatic logic [ADDR_W-1:0] widx = bus.cmd_addr >> $clog2(DATA_W/8);
          if (widx < DEPTH) begin
            for (int b = 0; b < DATA_W/8; b++) begin
              if (bus.cmd_wmask[b]) begin
                mem[widx][b*8 +: 8] <= bus.cmd_wdata[b*8 +: 8];
              end
            end
          end
          rsp_rdata_r <= '0;
        end
      end else if (bus.rsp_ready && rsp_valid_r) begin
        rsp_valid_r <= 1'b0;
      end
    end
  end

endmodule
