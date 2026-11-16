/* SPDX-License-Identifier: Apache-2.0 */
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "include/gemmini.h"

namespace {
std::vector<uint8_t> memory(1024 * 1024, 0xa5);
std::ofstream commands;
size_t cursor = 64;
constexpr uint64_t memory_base = 0x10000000;

void *allocate(size_t bytes) {
  cursor = (cursor + 63) & ~size_t(63);
  if (cursor + bytes > memory.size()) throw std::runtime_error("Memory capacity exceeded");
  void *result = memory.data() + cursor;
  cursor += bytes;
  return result;
}

uint64_t physical(uint64_t pointer) {
  if (!pointer) return 0;
  const uint64_t begin = reinterpret_cast<uintptr_t>(memory.data());
  if (pointer < begin || pointer >= begin + memory.size())
    throw std::runtime_error("Pointer outside the test memory");
  return memory_base + pointer - begin;
}

void binary(const std::filesystem::path &path, const void *data, size_t bytes) {
  std::ofstream file(path, std::ios::binary);
  file.write(static_cast<const char *>(data), bytes);
  if (!file) throw std::runtime_error("Cannot write " + path.string());
}
}  // namespace

void gemmini_host_command(unsigned funct, uint64_t rs1, uint64_t rs2) {
  if (funct == 1 || funct == 2 || funct == 3 || funct == 14) rs1 = physical(rs1);
  commands << std::dec << funct << " 0x" << std::hex << rs1 << " 0x" << rs2 << '\n';
}

void gemmini_host_fence() { commands << "FENCE\n"; }

int main(int argc, char **argv) {
  try {
    if (argc != 2 && argc != 7)
      throw std::runtime_error("Usage: im2col_trace output_dir [channels output_rows output_columns kernel stride]");
    const std::filesystem::path output(argv[1]);
    std::filesystem::create_directories(output);
    const int channels = argc == 7 ? std::stoi(argv[2]) : 16;
    const int output_rows = argc == 7 ? std::stoi(argv[3]) : 1;
    const int output_cols = argc == 7 ? std::stoi(argv[4]) : 16;
    const int kernel = argc == 7 ? std::stoi(argv[5]) : 3;
    const int stride = argc == 7 ? std::stoi(argv[6]) : 1;
    const int input_rows = (output_rows - 1) * stride + kernel;
    const int input_cols = (output_cols - 1) * stride + kernel;
    const int input_pixels = input_rows * input_cols;
    const int output_pixels = output_rows * output_cols;
    const int kernel_pixels = kernel * kernel;
    const int output_channels = 16;
    if (channels <= 0 || kernel <= 0 || stride <= 0 || output_rows <= 0 || output_cols <= 0 ||
        channels * kernel_pixels > BANK_ROWS ||
        ((channels + DIM - 1) / DIM) * input_pixels > (BANK_NUM - 1) * BANK_ROWS ||
        output_pixels > ACC_ROWS)
      throw std::runtime_error("The tile exceeds the configured memories");
    auto *input = static_cast<int8_t *>(allocate(input_pixels * channels));
    auto *weights = static_cast<int8_t *>(allocate(kernel_pixels * channels * output_channels));
    auto *bias = static_cast<int32_t *>(allocate(output_channels * 4));
    auto *result = static_cast<int32_t *>(allocate(output_pixels * output_channels * 4));
    uint32_t random = 0xb17823f1;
    auto next = [&]() { random ^= random << 13; random ^= random >> 17; random ^= random << 5; return random; };
    for (int i = 0; i < input_pixels * channels; ++i) input[i] = int(next() % 7) - 3;
    for (int i = 0; i < kernel_pixels * channels * output_channels; ++i) weights[i] = int(next() % 7) - 3;
    for (int i = 0; i < output_channels; ++i) bias[i] = int(next() % 31) - 15;
    std::vector<int32_t> expected(output_pixels * output_channels);
    for (int y = 0; y < output_rows; ++y)
      for (int x = 0; x < output_cols; ++x)
        for (int oc = 0; oc < output_channels; ++oc) {
          int32_t sum = bias[oc];
          for (int ky = 0; ky < kernel; ++ky)
            for (int kx = 0; kx < kernel; ++kx)
              for (int ic = 0; ic < channels; ++ic)
                sum += input[((y * stride + ky) * input_cols + x * stride + kx) * channels + ic] *
                    weights[((ky * kernel + kx) * channels + ic) * output_channels + oc];
          expected[(y * output_cols + x) * output_channels + oc] = sum;
        }

    commands.open(output / "commands.txt");
    gemmini_flush(0);
    gemmini_fence();
    const int remainder = output_pixels % DIM;
    const int row_turn = remainder ? output_pixels / DIM : output_pixels / DIM - 1;
    gemmini_extended3_config_ex(WEIGHT_STATIONARY, NO_ACTIVATION, 0, ACC_SCALE_IDENTITY,
        0, 1, 1, false, false, output_cols, row_turn, kernel, stride, channels,
        remainder, kernel_pixels, false, false, false);
    constexpr uint32_t weight_base = (BANK_NUM - 1) * BANK_ROWS;
    gemmini_config_ld(0);
    for (int pixel = 0; pixel < output_pixels; pixel += DIM)
      gemmini_extended_mvin(bias, 0x80000000u + pixel, output_channels,
                            std::min(DIM, output_pixels - pixel));
    gemmini_config_ld(output_channels);
    for (int ic = 0; ic < channels; ic += DIM) {
      const int depth = std::min(DIM, channels - ic);
      for (int position = 0; position < kernel_pixels; ++position)
        gemmini_extended_mvin(weights + (position * channels + ic) * output_channels,
            weight_base + ic * kernel_pixels + position * depth, output_channels, depth);
    }
    gemmini_config_ld(channels);
    for (int pixel = 0; pixel < input_pixels; pixel += DIM)
      for (int ic = 0; ic < channels; ic += DIM)
        gemmini_extended_mvin(input + pixel * channels + ic,
            (ic / DIM) * input_pixels + pixel, std::min(DIM, channels - ic),
            std::min(DIM, input_pixels - pixel));
    gemmini_fence();
    for (int ic = 0; ic < channels; ic += DIM) {
      const int depth = std::min(DIM, channels - ic);
      for (int pixel = 0; pixel < output_pixels; pixel += DIM) {
        const int rows = std::min(DIM, output_pixels - pixel);
        for (int position = 0; position < kernel_pixels; ++position) {
          gemmini_extended_preload(weight_base + ic * kernel_pixels + position * depth,
              0xc0000000u + pixel, output_channels, depth, output_channels, rows);
          gemmini_extended_compute_preloaded((ic / DIM) * input_pixels, GARBAGE_ADDR,
              depth, DIM, output_channels, DIM);
          gemmini_fence();
        }
      }
    }
    gemmini_fence();
    gemmini_extended_config_st(output_channels * 4, NO_ACTIVATION, ACC_SCALE_IDENTITY);
    for (int pixel = 0; pixel < output_pixels; pixel += DIM)
      gemmini_extended_mvout(result + pixel * output_channels, 0xe0000000u + pixel,
                            output_channels, std::min(DIM, output_pixels - pixel));
    gemmini_fence();
    commands.close();
    binary(output / "memory.bin", memory.data(), (cursor + 4095) & ~size_t(4095));
    binary(output / "expected.bin", expected.data(), expected.size() * 4);
    std::ofstream metadata(output / "case.json");
    metadata << "{\"memory_base\":" << memory_base << ",\"output_base\":"
      << physical(reinterpret_cast<uintptr_t>(result)) << ",\"output_bytes\":"
      << expected.size() * 4 << ",\"timed_start\":2,\"channels\":" << channels
      << ",\"output_rows\":" << output_rows << ",\"output_columns\":" << output_cols
      << ",\"kernel\":" << kernel << ",\"stride\":" << stride << "}\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
