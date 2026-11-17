// SPDX-License-Identifier: Apache-2.0
package conv_im2col_pkg;
  // One immutable NHWC input tensor (one batch) per configuration.
  // Weights, accumulation and requantization remain in the existing NPU.
  typedef struct packed {
    logic [31:0] input_base;
    logic [15:0] input_h, input_w, input_c;
    logic [15:0] group_c, group_offset;
    logic [15:0] kernel_h, kernel_w;
    logic [15:0] output_h, output_w;
    logic [15:0] stride_h, stride_w;
    logic [15:0] dilation_h, dilation_w;
    logic [15:0] pad_top, pad_left;
    logic signed [15:0] input_offset; // ADD offset, not the zero point itself
    logic bypass_cache;             // word-demand mode for sparse/no-reuse access
    logic input_s16;                // s16 requires offset=0 and 2-byte alignment
    logic windowed;                // Spatial window requests from the vector engine
    logic prefetch_enable;         // Read future convolution data before demand
  } conv_cfg_t;
endpackage
