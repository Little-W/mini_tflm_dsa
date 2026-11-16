/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GEMMINI_MODEL_BACKEND_H
#define GEMMINI_MODEL_BACKEND_H

#include <stddef.h>
#include <stdint.h>

enum GemminiOperation { GEMMINI_CONV, GEMMINI_DEPTHWISE, GEMMINI_FULLY_CONNECTED };

struct GemminiLayer {
  GemminiOperation operation;
  int batches;
  int input_height, input_width, input_channels;
  int output_height, output_width, output_channels;
  int kernel_height, kernel_width;
  int stride_height, stride_width, padding_height, padding_width;
  int dilation_height, dilation_width;
  int input_offset, output_offset, activation_min, activation_max;
  const int8_t *weights;
  const int32_t *bias;
  const int32_t *multipliers, *shifts;
  int32_t multiplier, shift;
  bool per_channel;
  int8_t *packed_weights;
  int32_t *weight_sums;
  int32_t *kernel_prefix;
  int32_t *zero_bias;
  int tile_height, tile_width, tile_channels;
  int scratch_index;
  bool supported;
  bool independent_im2col;
};

bool gemmini_layer_supported(const GemminiLayer &layer);
size_t gemmini_packed_weight_bytes(const GemminiLayer &layer);
size_t gemmini_raw_output_bytes(const GemminiLayer &layer);
size_t gemmini_kernel_prefix_bytes(const GemminiLayer &layer);
void gemmini_prepare_layer(GemminiLayer *layer);
void gemmini_reset_accelerator();
void gemmini_run_raw(const GemminiLayer &layer, const int8_t *input,
                     int32_t *raw_output);
void gemmini_requantize_output(const GemminiLayer &layer, const int32_t *raw,
                               int8_t *output);
void gemmini_run(const GemminiLayer &layer, const int8_t *input, int32_t *raw,
                 int8_t *output);
void gemmini_run_vendor_depthwise(const GemminiLayer &layer, const int8_t *input,
                                  int8_t *output);
int32_t gemmini_requantize_rne(int32_t value, int32_t multiplier, int shift);
int32_t gemmini_valid_weight_sum(const GemminiLayer &layer, int y, int x,
                                int channel);

#endif
