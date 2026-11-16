/* SPDX-License-Identifier: Apache-2.0 */
#include "backend.h"

#include <limits.h>
#include <string.h>

#include "include/gemmini.h"
#include "include/gemmini_model_config.h"
#include "im2col.h"

namespace {
int minimum(int a, int b) { return a < b ? a : b; }
int maximum(int a, int b) { return a > b ? a : b; }
int divide_up(int a, int b) { return (a + b - 1) / b; }
bool previous_depthwise;

void choose_tiles(GemminiLayer *p) {
  const int max_spad = BANK_NUM * BANK_ROWS / 2;
  const int max_acc = ACC_ROWS / 2;
  uint64_t best_cost = UINT64_MAX;
  int best_volume = 0;
  int max_height = p->operation == GEMMINI_DEPTHWISE ?
      minimum(p->output_height, 2 * ((DIM / p->kernel_height - p->kernel_height) /
                                  p->stride_height + 1)) : p->output_height;
  if (p->operation == GEMMINI_CONV && p->output_width <= DIM / 2)
    max_height = minimum(max_height, maximum(1, p->output_width / 2));
  for (int channels = minimum(DIM, p->output_channels);;
       channels = minimum(channels + DIM, p->output_channels)) {
    for (int width = p->output_width; width >= 1;
         width = width == 1 ? 0 : (width + 1) / 2) {
      for (int height = 1; height <= max_height; ++height) {
        const int in_h = height * p->stride_height + p->kernel_height - 1;
        const int in_w = width * p->stride_width + p->kernel_width - 1;
        const int channel_blocks = divide_up(channels, DIM);
        const int input_blocks = p->operation == GEMMINI_DEPTHWISE ?
            channel_blocks : divide_up(p->input_channels, DIM);
        const int weights = p->operation == GEMMINI_DEPTHWISE ? channels :
            channel_blocks * p->kernel_height * p->kernel_width * p->input_channels;
        const int accumulators = channel_blocks * height * width;
        const int inputs = input_blocks * in_h * in_w;
        if (accumulators > max_acc || inputs + weights > max_spad) break;
        const int tile_count = divide_up(p->output_height, height) *
            divide_up(p->output_width, width) * divide_up(p->output_channels, channels);
        const uint64_t cost = uint64_t(tile_count) *
            (uint64_t(inputs + weights) * DIM + uint64_t(accumulators) * DIM * 4 + 512);
        const int volume = height * width * channels;
        if (cost < best_cost || (cost == best_cost && volume > best_volume)) {
          best_cost = cost;
          best_volume = volume;
          p->tile_height = height;
          p->tile_width = width;
          p->tile_channels = channels;
        }
      }
    }
    if (channels == p->output_channels || p->operation == GEMMINI_DEPTHWISE) break;
  }
  p->supported = best_volume != 0;
}

void raw_convolution(const GemminiLayer &p, const int8_t *input, int32_t *raw) {
  const bool dw = p.operation == GEMMINI_DEPTHWISE;
  gemmini_extended3_config_ex(WEIGHT_STATIONARY, 0, 0, ACC_SCALE_IDENTITY,
      0, 1, p.stride_width, false, false, 0, 0, 0, 0, 0, 0, 0, 0, 0, false);
  const int32_t *bias = p.bias ? p.bias : p.zero_bias;
  for (int y = 0; y < p.output_height; y += p.tile_height) {
    const int rows = minimum(p.tile_height, p.output_height - y);
    for (int x = 0; x < p.output_width; x += p.tile_width) {
      const int cols = minimum(p.tile_width, p.output_width - x);
      const int iy = y * p.stride_height - p.padding_height;
      const int ix = x * p.stride_width - p.padding_width;
      const int in_rows = dw ? (rows - 1) * p.stride_height + p.kernel_height :
          rows * p.stride_height + p.kernel_height - 1;
      const int in_cols = dw ? (cols - 1) * p.stride_width + p.kernel_width :
          cols * p.stride_width + p.kernel_width - 1;
      const int up = maximum(-iy, 0), left = maximum(-ix, 0);
      const int down = maximum(iy + in_rows - p.input_height, 0);
      const int right = maximum(ix + in_cols - p.input_width, 0);
      for (int c = 0; c < p.output_channels; c += p.tile_channels) {
        const int channels = minimum(p.tile_channels, p.output_channels - c);
        const int8_t *in = input + ((iy + up) * p.input_width + ix + left) * p.input_channels;
        if (dw) {
          in += c;
          const int frame_height = DIM / p.kernel_height;
          const int atomic_rows = (frame_height - p.kernel_height) / p.stride_height + 1;
          gemmini_loop_dwconv_dw_ws(p.input_width, p.input_channels,
              p.output_width, p.stride_width, p.kernel_width,
              p.kernel_height, p.kernel_width, channels,
              left, right, up, down, rows, cols, rows * cols,
              in_rows, in_cols, in_rows * in_cols, divide_up(channels, DIM),
              atomic_rows, frame_height * in_cols, frame_height * p.kernel_width,
              frame_height, p.packed_weights + c * DIM, 0, bias + c, in,
              false, NO_ACTIVATION);
        } else {
          const int repeat = minimum(p.kernel_width,
              p.input_channels <= DIM ? DIM / p.input_channels : 1);
          gemmini_loop_conv_ws(1, p.input_width, p.input_channels,
              p.output_channels, p.output_width, p.output_width,
              p.stride_width, 0, p.kernel_width, 1, 1, 1, 0,
              1, rows, cols, channels, p.kernel_height, p.kernel_width,
              p.input_channels, left, right, up, down, 0, 0, 0, 0, rows, cols,
              p.packed_weights + c, 0, bias + c, in, false, true, false,
              false, false, NO_ACTIVATION, false, false, false, false, repeat);
        }
        gemmini_fence();
        gemmini_extended_config_st((dw ? p.output_width : 1) *
            p.output_channels * sizeof(int32_t), NO_ACTIVATION, ACC_SCALE_IDENTITY);
        for (int cc = 0; cc < channels; cc += DIM) {
          if (dw) {
            for (int xx = 0; xx < cols; ++xx) {
              for (int yy = 0; yy < rows; yy += DIM) {
                const uint32_t accumulator = 0xe0000000u +
                    (cc / DIM) * rows * cols + xx * rows + yy;
                int32_t *destination = raw + ((y + yy) * p.output_width + x + xx) *
                    p.output_channels + c + cc;
                gemmini_extended_mvout(destination, accumulator,
                    minimum(DIM, channels - cc), minimum(DIM, rows - yy));
              }
            }
          } else {
            for (int yy = 0; yy < rows; ++yy) {
              for (int xx = 0; xx < cols; xx += DIM) {
                const uint32_t accumulator = 0xe0000000u +
                    (cc / DIM) * rows * cols + yy * cols + xx;
                int32_t *destination = raw + ((y + yy) * p.output_width + x + xx) *
                    p.output_channels + c + cc;
                gemmini_extended_mvout(destination, accumulator,
                    minimum(DIM, channels - cc), minimum(DIM, cols - xx));
              }
            }
          }
        }
        gemmini_fence();
      }
    }
  }
}
}  // namespace

bool gemmini_layer_supported(const GemminiLayer &p) {
  if (p.batches < 1 || p.input_channels < 1 || p.output_channels < 1 ||
      p.output_height < 1 || p.output_width < 1 ||
      p.dilation_height != 1 || p.dilation_width != 1) return false;
  if (p.operation == GEMMINI_FULLY_CONNECTED) return true;
  if (p.batches != 1 || p.stride_height != p.stride_width ||
      p.stride_height < 1 || p.stride_height > 2) return false;
  if (p.operation == GEMMINI_DEPTHWISE) {
    return p.input_channels == p.output_channels && p.kernel_height == 3 &&
        p.kernel_width == 3 && p.padding_height <= 1 && p.padding_width <= 1 &&
        p.input_width < 1024 && p.output_width < 512 && p.output_height < 512 &&
        p.input_channels < 4096;
  }
  return p.kernel_height > 0 && p.kernel_width > 0 &&
      p.kernel_height <= 15 && p.kernel_width <= 15;
}

size_t gemmini_packed_weight_bytes(const GemminiLayer &p) {
  return p.operation == GEMMINI_DEPTHWISE ? size_t(p.output_channels) * DIM :
      size_t(p.kernel_height) * p.kernel_width * p.input_channels * p.output_channels;
}

size_t gemmini_raw_output_bytes(const GemminiLayer &p) {
  return size_t(p.batches) * p.output_height * p.output_width * p.output_channels * sizeof(int32_t);
}

size_t gemmini_kernel_prefix_bytes(const GemminiLayer &p) {
  return p.operation != GEMMINI_CONV || (p.kernel_height == 1 && p.kernel_width == 1) ? 0 :
      size_t(p.kernel_height + 1) * (p.kernel_width + 1) * p.output_channels * sizeof(int32_t);
}

void gemmini_prepare_layer(GemminiLayer *p) {
  p->supported = gemmini_layer_supported(*p);
  if (!p->supported) return;
  const int channels = p->output_channels, inputs = p->input_channels;
  const int kh = p->kernel_height, kw = p->kernel_width;
  const int depth = kh * kw * inputs;
  const int frame_height = DIM / kh;
  const bool dw = p->operation == GEMMINI_DEPTHWISE;
  const int8_t *const weights = p->weights;
  int8_t *const packed = p->packed_weights;
  int32_t *const sums = p->weight_sums;
  int32_t *const prefixes = p->kernel_prefix;
  const int prefix_stride = kw + 1, prefix_size = (kh + 1) * prefix_stride;
  if (dw) memset(packed, 0, gemmini_packed_weight_bytes(*p));
  if (prefixes) memset(prefixes, 0, gemmini_kernel_prefix_bytes(*p));
  if (p->zero_bias) memset(p->zero_bias, 0, channels * sizeof(int32_t));
  for (int c = 0; c < channels; ++c) {
    int32_t sum = 0;
    int32_t *const prefix = prefixes ? prefixes + c * prefix_size : nullptr;
    for (int ky = 0; ky < kh; ++ky) {
      for (int kx = 0; kx < kw; ++kx) {
        int32_t tap_sum = 0;
        if (dw) {
          const int8_t value = weights[(ky * kw + kx) * channels + c];
          packed[c * DIM + (kw - 1 - kx) * frame_height + frame_height - 1 - ky] = value;
          tap_sum = value;
        } else {
          const int offset = (ky * kw + kx) * inputs;
          const int8_t *source = weights + c * depth + offset;
          int8_t *destination = packed + offset * channels + c;
          for (int k = 0; k < inputs; ++k) {
            const int8_t value = *source++;
            *destination = value;
            destination += channels;
            tap_sum += value;
          }
        }
        sum += tap_sum;
        if (prefix) {
          const int offset = (ky + 1) * prefix_stride + kx + 1;
          prefix[offset] = tap_sum + prefix[offset - 1] +
              prefix[offset - prefix_stride] - prefix[offset - prefix_stride - 1];
        }
      }
    }
    sums[c] = sum;
  }
  if (p->operation != GEMMINI_FULLY_CONNECTED) choose_tiles(p);
  const bool pointwise = p->kernel_height == 1 && p->kernel_width == 1 &&
      p->stride_height == 1 && p->stride_width == 1 &&
      p->padding_height == 0 && p->padding_width == 0;
  p->independent_im2col = gemmini_im2col::supported(*p) && !pointwise &&
      (GEMMINI_CONV_POLICY == 2 || (GEMMINI_CONV_POLICY == 0 &&
       !p->supported));
  if (p->independent_im2col) gemmini_im2col::choose_tiles(p);
}

void gemmini_reset_accelerator() {
  gemmini_flush(0);
  gemmini_fence();
}

void gemmini_run_raw(const GemminiLayer &p, const int8_t *input, int32_t *raw) {
  if (previous_depthwise && p.operation != GEMMINI_DEPTHWISE) {
#ifndef GEMMINI_HOST_COMMANDS
    volatile uint32_t *const registers = (volatile uint32_t *)GEMMINI_MMIO_BASE;
    registers[0x28 / 4] = 1;
    __asm__ volatile("" ::: "memory");
#endif
  }
  previous_depthwise = p.operation == GEMMINI_DEPTHWISE;
  const bool pointwise = p.operation == GEMMINI_CONV &&
      p.kernel_height == 1 && p.kernel_width == 1 &&
      p.stride_height == 1 && p.padding_height == 0 && p.padding_width == 0;
  if (p.operation == GEMMINI_FULLY_CONNECTED || pointwise) {
    const int rows = p.batches * p.output_height * p.output_width;
    tiled_matmul_auto(rows, p.output_channels, p.input_channels,
        input, p.packed_weights, p.bias ? p.bias : p.zero_bias, raw,
        p.input_channels, p.output_channels, p.output_channels, p.output_channels,
        MVIN_SCALE_IDENTITY, MVIN_SCALE_IDENTITY, 1,
        NO_ACTIVATION, ACC_SCALE_IDENTITY, 0, true,
        false, false, true, false, 0, WS);
    gemmini_fence();
  } else if (p.independent_im2col) {
    gemmini_im2col::run_raw(p, input, raw);
  } else {
    raw_convolution(p, input, raw);
  }
}

int32_t gemmini_requantize_rne(int32_t value, int32_t multiplier, int shift) {
  const int64_t product = int64_t(value) * multiplier;
  const int exponent = 31 - shift;
  const int64_t base = product >> exponent;
  const uint64_t mask = (uint64_t(1) << exponent) - 1;
  const uint64_t remainder = uint64_t(product) & mask;
  const uint64_t half = uint64_t(1) << (exponent - 1);
  const int64_t rounded = base + (remainder > half || (remainder == half && (base & 1)));
  return rounded > INT32_MAX ? INT32_MAX : rounded < INT32_MIN ? INT32_MIN : int32_t(rounded);
}

int32_t gemmini_valid_weight_sum(const GemminiLayer &p, int y, int x, int channel) {
  if (p.operation == GEMMINI_FULLY_CONNECTED) return p.weight_sums[channel];
  const int top = y * p.stride_height - p.padding_height;
  const int left = x * p.stride_width - p.padding_width;
  if (top >= 0 && left >= 0 && top + p.kernel_height <= p.input_height &&
      left + p.kernel_width <= p.input_width) return p.weight_sums[channel];
  if (p.kernel_prefix) {
    const int stride = p.kernel_width + 1;
    const int32_t *prefix = p.kernel_prefix + channel * (p.kernel_height + 1) * stride;
    const int y0 = maximum(-top, 0), y1 = minimum(p.kernel_height, p.input_height - top);
    const int x0 = maximum(-left, 0), x1 = minimum(p.kernel_width, p.input_width - left);
    return prefix[y1 * stride + x1] - prefix[y0 * stride + x1] -
        prefix[y1 * stride + x0] + prefix[y0 * stride + x0];
  }
  int32_t sum = 0;
  for (int ky = maximum(-top, 0); ky < minimum(p.kernel_height, p.input_height - top); ++ky)
    for (int kx = maximum(-left, 0); kx < minimum(p.kernel_width, p.input_width - left); ++kx) {
      if (p.operation == GEMMINI_DEPTHWISE) {
        sum += p.weights[(ky * p.kernel_width + kx) * p.output_channels + channel];
      } else {
        const int8_t *weights = p.weights +
            ((channel * p.kernel_height + ky) * p.kernel_width + kx) * p.input_channels;
        for (int c = 0; c < p.input_channels; ++c) sum += weights[c];
      }
    }
  return sum;
}

void gemmini_requantize_output(const GemminiLayer &p, const int32_t *raw, int8_t *output) {
  const int channels = p.output_channels, height = p.output_height, width = p.output_width;
  const int input_offset = p.input_offset, output_offset = p.output_offset;
  const int lower = p.activation_min - output_offset, upper = p.activation_max - output_offset;
  const int kh = p.kernel_height, kw = p.kernel_width;
  const int stride_h = p.stride_height, stride_w = p.stride_width;
  const int input_h = p.input_height, input_w = p.input_width;
  const int prefix_stride = kw + 1, prefix_size = (kh + 1) * prefix_stride;
  const bool fc = p.operation == GEMMINI_FULLY_CONNECTED;
  for (int c = 0; c < channels; ++c) {
    const int32_t multiplier = p.per_channel ? p.multipliers[c] : p.multiplier;
    const int shift = p.per_channel ? p.shifts[c] : p.shift;
    const int high_shift = shift < -1 ? -shift - 1 : 0;
    const uint32_t high_mask = high_shift ? (uint32_t(1) << high_shift) - 1 : 0;
    const uint32_t high_half = high_shift ? uint32_t(1) << (high_shift - 1) : 0;
    const int32_t full_correction = input_offset * p.weight_sums[c];
    int32_t depthwise_prefix[16] = {};
    const int32_t *prefix = p.kernel_prefix ? p.kernel_prefix + c * prefix_size : nullptr;
    if (p.operation == GEMMINI_DEPTHWISE) {
      const int8_t *weights = p.weights + c;
      for (int ky = 0; ky < 3; ++ky)
        for (int kx = 0; kx < 3; ++kx) {
          const int index = (ky + 1) * 4 + kx + 1;
          depthwise_prefix[index] = weights[(ky * 3 + kx) * channels] +
              depthwise_prefix[index - 1] + depthwise_prefix[index - 4] - depthwise_prefix[index - 5];
        }
      prefix = depthwise_prefix;
    }
    const int32_t *source = raw + c;
    int8_t *destination = output + c;
    for (int batch = 0; batch < p.batches; ++batch) {
      int top = -p.padding_height;
      for (int y = 0; y < height; ++y, top += stride_h) {
        const int y0 = maximum(-top, 0), y1 = minimum(kh, input_h - top);
        const bool full_row = fc || (y0 == 0 && y1 == kh);
        const int32_t *top_prefix = prefix ? prefix + y0 * prefix_stride : nullptr;
        const int32_t *bottom_prefix = prefix ? prefix + y1 * prefix_stride : nullptr;
        int left = -p.padding_width;
        for (int x = 0; x < width; ++x, left += stride_w) {
          int32_t correction = full_correction;
          if (!fc && !(full_row && left >= 0 && left + kw <= input_w)) {
            if (prefix) {
              const int x0 = maximum(-left, 0), x1 = minimum(kw, input_w - left);
              correction = input_offset * (bottom_prefix[x1] - top_prefix[x1] -
                  bottom_prefix[x0] + top_prefix[x0]);
            } else {
              correction = input_offset * gemmini_valid_weight_sum(p, y, x, c);
            }
          }
          const int32_t accumulator = *source + correction;
          int32_t scaled;
          if (shift <= 0 && multiplier >= 0) {
            const int64_t product = int64_t(accumulator) * multiplier;
            const uint32_t low = uint32_t(product);
            const int32_t high = int32_t(product >> 32);
            if (shift == 0) {
              scaled = int32_t((uint32_t(high) << 1) | (low >> 31));
              const uint32_t remainder = low & 0x7fffffffu;
              scaled += remainder > 0x40000000u || (remainder == 0x40000000u && (scaled & 1));
            } else if (shift == -1) {
              scaled = high;
              scaled += low > 0x80000000u || (low == 0x80000000u && (scaled & 1));
            } else {
              scaled = high >> high_shift;
              const uint32_t remainder = uint32_t(high) & high_mask;
              scaled += remainder > high_half ||
                  (remainder == high_half && (low != 0 || (scaled & 1)));
            }
          } else {
            scaled = gemmini_requantize_rne(accumulator, multiplier, shift);
          }
          const int32_t clipped = scaled < lower ? lower : scaled > upper ? upper : scaled;
          *destination = int8_t(clipped + output_offset);
          source += channels;
          destination += channels;
        }
      }
    }
  }
}

void gemmini_run(const GemminiLayer &p, const int8_t *input, int32_t *raw, int8_t *output) {
  gemmini_run_raw(p, input, raw);
  gemmini_requantize_output(p, raw, output);
}

void gemmini_run_vendor_depthwise(const GemminiLayer &p, const int8_t *input, int8_t *output) {
  tiled_conv_dw_auto(1, p.input_width, p.input_channels, p.output_width,
      p.stride_width, p.padding_width, p.kernel_width, const_cast<int8_t *>(input), p.packed_weights,
      const_cast<int32_t *>(p.bias), output, NO_ACTIVATION, 0.03125f, 0, 1, 0, 0, WS);
  gemmini_fence();
}
