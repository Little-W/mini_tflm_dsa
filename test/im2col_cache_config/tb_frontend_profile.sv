// SPDX-License-Identifier: Apache-2.0
// Exercise the production frontend with independent direct-im2col vectors.
module tb_frontend_profile;
  parameter int CACHE_BYTES=4096;
  tb_conv_im2col_frontend #(.SIZE(16),.LANES(4),.CACHE_POLICY(3),
    .CACHE_SETS(CACHE_BYTES/32),.CACHE_WAYS(2),.LINE_BYTES(16),
    .PREFETCH(1),.WINDOWED(1)) u_suite();
  initial begin
    if ($bits(u_suite.g_direct.dut.u_cache.g_window.u_window.u_data.g_bank[0].mem)
        != CACHE_BYTES*8) $fatal(1,"Input cache data RAM capacity mismatch");
    $display("IM2COL_RAM_CAPACITY_PASS bytes=%0d sets=%0d ways=2 line_bytes=16",
             CACHE_BYTES,CACHE_BYTES/32);
  end
endmodule
