/* SPDX-License-Identifier: Apache-2.0 */
#ifndef GEMMINI_MODEL_IM2COL_H
#define GEMMINI_MODEL_IM2COL_H

#include "backend.h"
#include "include/gemmini.h"

namespace gemmini_im2col {
inline int minimum(int a, int b) { return a < b ? a : b; }
inline int divide_up(int a, int b) { return (a + b - 1) / b; }

inline bool supported(const GemminiLayer &p) {
  return p.operation == GEMMINI_CONV && p.batches == 1 &&
      p.kernel_height == p.kernel_width && p.kernel_height > 0 &&
      p.kernel_height <= 15 && p.stride_height == p.stride_width &&
      p.stride_height > 0 && p.stride_height <= 2 &&
      p.dilation_height == 1 && p.dilation_width == 1;
}

inline int channel_tile(const GemminiLayer &p) {
  const int capacity = BANK_ROWS / (p.kernel_height * p.kernel_width);
  const int channels = capacity >= DIM ? capacity / DIM * DIM : capacity;
  return minimum(p.input_channels, channels);
}

inline void choose_tiles(GemminiLayer *p) {
  const int channels = channel_tile(*p);
  const int input_blocks = divide_up(channels, DIM);
  const int kernel_area = p->kernel_height * p->kernel_width;
  uint64_t best_cost = UINT64_MAX;
  int best_volume = 0;
  for (int width = minimum(p->output_width, 255); width > 0;
       width = width == 1 ? 0 : (width + 1) / 2) {
    for (int height = 1; height <= p->output_height; ++height) {
      const int input_height = (height - 1) * p->stride_height + p->kernel_height;
      const int input_width = (width - 1) * p->stride_width + p->kernel_width;
      const int pixels = height * width;
      if (pixels > ACC_ROWS || input_width > 511 ||
          input_height * input_width * input_blocks > (BANK_NUM - 1) * BANK_ROWS)
        break;
      const uint64_t tile_count = uint64_t(divide_up(p->output_height, height)) *
          divide_up(p->output_width, width) * divide_up(p->output_channels, DIM);
      const uint64_t input_bytes = uint64_t(input_height) * input_width * p->input_channels;
      const uint64_t weight_bytes = uint64_t(kernel_area) * p->input_channels * DIM;
      const uint64_t compute_cycles = uint64_t(divide_up(pixels, DIM)) * kernel_area *
          divide_up(p->input_channels, DIM) * 64;
      const uint64_t cost = tile_count * (input_bytes + weight_bytes + compute_cycles + 128);
      if (cost < best_cost || (cost == best_cost && pixels > best_volume)) {
        best_cost = cost;
        best_volume = pixels;
        p->tile_height = height;
        p->tile_width = width;
        p->tile_channels = minimum(DIM, p->output_channels);
      }
    }
  }
  p->supported = best_volume > 0;
}

inline void configure(int columns, int pixels, int kernel, int stride, int channels) {
  const int remainder = pixels % DIM;
  const int row_turn = remainder ? pixels / DIM : pixels / DIM - 1;
  gemmini_extended3_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0,
      ACC_SCALE_IDENTITY, 0, 1, 1, false, false, columns, row_turn,
      kernel, stride, channels, remainder, kernel * kernel, false, false, false);
}

inline void disable() {
  gemmini_extended3_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0,
      ACC_SCALE_IDENTITY, 0, 1, 1, false, false, 0, 0, 0, 0, 0, 0, 0,
      false, false, false);
  gemmini_fence();
}

inline void run_raw(const GemminiLayer &p, const int8_t *input, int32_t *raw) {
  const int kernel_area = p.kernel_height * p.kernel_width;
  const int input_channel_tile = channel_tile(p);
  constexpr uint32_t weight_base = (BANK_NUM - 1) * BANK_ROWS;
  const int32_t *bias = p.bias ? p.bias : p.zero_bias;
  disable();
  for (int y = 0; y < p.output_height; y += p.tile_height) {
    const int rows = minimum(p.tile_height, p.output_height - y);
    for (int x = 0; x < p.output_width; x += p.tile_width) {
      const int columns = minimum(p.tile_width, p.output_width - x);
      const int pixels = rows * columns;
      const int input_rows = (rows - 1) * p.stride_height + p.kernel_height;
      const int input_columns = (columns - 1) * p.stride_width + p.kernel_width;
      const int input_pixels = input_rows * input_columns;
      const int top = y * p.stride_height - p.padding_height;
      const int left = x * p.stride_width - p.padding_width;
      for (int oc = 0; oc < p.output_channels; oc += DIM) {
        const int output_channels = minimum(DIM, p.output_channels - oc);
        gemmini_config_ld(0);
        for (int pixel = 0; pixel < pixels; pixel += DIM)
          gemmini_extended_mvin(bias + oc, 0x80000000u + pixel,
              output_channels, minimum(DIM, pixels - pixel));
        for (int input_start = 0; input_start < p.input_channels;
             input_start += input_channel_tile) {
          const int channels = minimum(input_channel_tile, p.input_channels - input_start);
          configure(columns, pixels, p.kernel_height, p.stride_height, channels);
          gemmini_config_ld(p.output_channels);
          for (int ic = 0; ic < channels; ic += DIM) {
            const int depth = minimum(DIM, channels - ic);
            for (int position = 0; position < kernel_area; ++position)
              gemmini_extended_mvin(p.packed_weights +
                  (position * p.input_channels + input_start + ic) * p.output_channels + oc,
                  weight_base + ic * kernel_area + position * depth,
                  output_channels, depth);
          }
          gemmini_config_ld(p.input_channels);
          const bool load_inputs = oc == 0 || p.input_channels > input_channel_tile;
          for (int iy = 0; load_inputs && iy < input_rows; ++iy) {
            const int source_y = top + iy;
            for (int ix = 0; ix < input_columns;) {
              const int source_x = left + ix;
              int count = minimum(DIM, input_columns - ix);
              if (source_x < 0) count = minimum(count, -source_x);
              else if (source_x < p.input_width)
                count = minimum(count, p.input_width - source_x);
              const bool padding = source_y < 0 || source_y >= p.input_height ||
                  source_x < 0 || source_x >= p.input_width;
              for (int ic = 0; ic < channels; ic += DIM) {
                const int8_t *source = padding ? nullptr : input +
                    (source_y * p.input_width + source_x) * p.input_channels + input_start + ic;
                gemmini_extended_mvin(source,
                    (ic / DIM) * input_pixels + iy * input_columns + ix,
                    minimum(DIM, channels - ic), count);
              }
              ix += count;
            }
          }
          gemmini_fence();
          for (int ic = 0; ic < channels; ic += DIM) {
            const int depth = minimum(DIM, channels - ic);
            for (int pixel = 0; pixel < pixels; pixel += DIM) {
              const int output_rows = minimum(DIM, pixels - pixel);
              for (int position = 0; position < kernel_area; ++position) {
                gemmini_extended_preload(weight_base + ic * kernel_area + position * depth,
                    0xc0000000u + pixel, output_channels, depth, output_channels, output_rows);
                gemmini_extended_compute_preloaded((ic / DIM) * input_pixels, GARBAGE_ADDR,
                    depth, DIM, output_channels, DIM);
                gemmini_fence();
              }
            }
          }
          disable();
        }
        gemmini_extended_config_st(p.output_channels * sizeof(int32_t),
            NO_ACTIVATION, ACC_SCALE_IDENTITY);
        for (int yy = 0; yy < rows; ++yy)
          for (int xx = 0; xx < columns; xx += DIM)
            gemmini_extended_mvout(raw +
                ((y + yy) * p.output_width + x + xx) * p.output_channels + oc,
                0xe0000000u + yy * columns + xx, output_channels,
                minimum(DIM, columns - xx));
        gemmini_fence();
      }
    }
  }
}
}  // namespace gemmini_im2col

#endif
