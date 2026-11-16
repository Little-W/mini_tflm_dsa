/* SPDX-License-Identifier: Apache-2.0 */
#include "backend.h"

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::vector<uint8_t> memory;
std::ofstream commands;
constexpr uint64_t physical_base = 0x10000000;
size_t cursor = 64;
size_t records = 0;

void *allocate(size_t size) {
  const size_t offset = (cursor + 63) & ~size_t(63);
  cursor = offset + size;
  if (cursor > memory.size()) throw std::runtime_error("Memory image capacity exceeded");
  return memory.data() + offset;
}

uint64_t physical(uint64_t pointer) {
  if (!pointer) return 0;
  const uint64_t begin = reinterpret_cast<uintptr_t>(memory.data());
  if (pointer < begin || pointer >= begin + memory.size())
    throw std::runtime_error("Command pointer outside memory image");
  return physical_base + pointer - begin;
}

void write_binary(const std::filesystem::path &path, const void *data, size_t bytes) {
  std::ofstream file(path, std::ios::binary);
  file.write(static_cast<const char *>(data), bytes);
  if (!file) throw std::runtime_error("Cannot write " + path.string());
}

void load_binary(const std::string &path, void *data, size_t bytes) {
  std::ifstream file(path, std::ios::binary);
  file.read(static_cast<char *>(data), bytes);
  if (!file || file.peek() != std::char_traits<char>::eof())
    throw std::runtime_error("Tensor length mismatch: " + path);
}

std::vector<int32_t> reference(const GemminiLayer &p, const int8_t *input, bool centered) {
  const size_t elements = gemmini_raw_output_bytes(p) / 4;
  std::vector<int32_t> result(elements);
  for (int y = 0; y < p.output_height; ++y)
    for (int x = 0; x < p.output_width; ++x)
      for (int c = 0; c < p.output_channels; ++c) {
        int64_t sum = p.bias ? p.bias[c] : 0;
        for (int ky = 0; ky < p.kernel_height; ++ky)
          for (int kx = 0; kx < p.kernel_width; ++kx) {
            const int iy = y * p.stride_height + ky - p.padding_height;
            const int ix = x * p.stride_width + kx - p.padding_width;
            if (iy < 0 || iy >= p.input_height || ix < 0 || ix >= p.input_width) continue;
            if (p.operation == GEMMINI_DEPTHWISE) {
              const int8_t weight = p.weights[(ky * p.kernel_width + kx) * p.output_channels + c];
              const int value = input[(iy * p.input_width + ix) * p.input_channels + c];
              sum += int64_t(value + (centered ? p.input_offset : 0)) * weight;
            } else {
              for (int k = 0; k < p.input_channels; ++k) {
                const int8_t weight = p.weights[((c * p.kernel_height + ky) * p.kernel_width + kx) * p.input_channels + k];
                const int value = input[(iy * p.input_width + ix) * p.input_channels + k];
                sum += int64_t(value + (centered ? p.input_offset : 0)) * weight;
              }
            }
          }
        if (sum < INT32_MIN || sum > INT32_MAX) throw std::runtime_error("Reference accumulator overflow");
        result[(y * p.output_width + x) * p.output_channels + c] = static_cast<int32_t>(sum);
      }
  return result;
}
}  // namespace

void gemmini_host_command(unsigned funct, uint64_t rs1, uint64_t rs2) {
  switch (funct) {
    case 1: case 2: case 3: case 14:
      rs1 = physical(rs1);
      break;
    case 10: case 11: case 20: case 21: case 25: case 29:
      rs1 = physical(rs1);
      rs2 = physical(rs2);
      break;
  }
  commands << std::dec << funct << " 0x" << std::hex << rs1 << " 0x" << rs2 << '\n';
  ++records;
}

void gemmini_host_fence() {
  commands << "FENCE\n";
  ++records;
}

int main(int argc, char **argv) {
  try {
    if (argc != 3 && argc != 26) throw std::runtime_error(
        "Usage: trace_backend output_dir {dw|dw_stride2|dw_rect|conv|conv_rect|gemm} OR output_dir kind ih iw ic oh ow oc kh kw sh sw ph pw input weights bias multipliers shifts input_offset output_offset activation_min activation_max reserved");
    const std::filesystem::path directory(argv[1]);
    std::filesystem::create_directories(directory);
    GemminiLayer p{};
    p.batches = 1;
    p.dilation_height = p.dilation_width = 1;
    p.stride_height = p.stride_width = 1;
    p.input_offset = 128;
    p.output_offset = -31;
    p.activation_min = -128;
    p.activation_max = 127;
    p.multiplier = 1476395008;
    p.shift = -11;
    const std::string kind(argv[2]);
    if (argc == 26) {
      p.operation = kind == "dw" ? GEMMINI_DEPTHWISE : kind == "fc" ? GEMMINI_FULLY_CONNECTED : GEMMINI_CONV;
      int *fields[] = {&p.input_height, &p.input_width, &p.input_channels,
        &p.output_height, &p.output_width, &p.output_channels,
        &p.kernel_height, &p.kernel_width, &p.stride_height, &p.stride_width,
        &p.padding_height, &p.padding_width};
      for (unsigned i = 0; i < 12; ++i) *fields[i] = std::stoi(argv[i + 3]);
      p.input_offset = std::stoi(argv[20]);
      p.output_offset = std::stoi(argv[21]);
      p.activation_min = std::stoi(argv[22]);
      p.activation_max = std::stoi(argv[23]);
      p.per_channel = true;
    } else if (kind == "gemm") {
      p.operation = GEMMINI_FULLY_CONNECTED;
      p.input_height = p.output_height = 1;
      p.input_width = p.output_width = 16;
      p.input_channels = p.output_channels = 16;
      p.kernel_height = p.kernel_width = 1;
    } else {
      p.operation = kind.rfind("dw", 0) == 0 ? GEMMINI_DEPTHWISE : GEMMINI_CONV;
      p.input_height = p.output_height = 14;
      p.input_width = p.output_width = 14;
      p.input_channels = 32;
      p.output_channels = p.operation == GEMMINI_DEPTHWISE ? 32 : 48;
      p.kernel_height = p.kernel_width = 3;
      p.padding_height = p.padding_width = 1;
      if (kind == "dw_rect") {
        p.input_height = p.output_height = 25;
        p.input_width = p.output_width = 5;
        p.input_channels = p.output_channels = 64;
        p.input_offset = -83;
      }
      if (kind == "dw_stride2") {
        p.output_height = p.output_width = 7;
        p.stride_height = p.stride_width = 2;
        p.padding_height = p.padding_width = 0;
      }
      if (kind == "conv_rect") {
        p.input_height = 49;
        p.input_width = 10;
        p.output_height = 25;
        p.output_width = 5;
        p.input_channels = 1;
        p.output_channels = 64;
        p.kernel_height = 10;
        p.kernel_width = 4;
        p.padding_height = 4;
        p.padding_width = 1;
        p.stride_height = p.stride_width = 2;
        p.input_offset = -83;
      }
    }
    if (!gemmini_layer_supported(p)) throw std::runtime_error("Unsupported test configuration");
    memory.resize(8 * 1024 * 1024);
    const size_t input_bytes = size_t(p.input_height) * p.input_width * p.input_channels;
    const size_t weight_bytes = size_t(p.kernel_height) * p.kernel_width * p.output_channels *
        (p.operation == GEMMINI_DEPTHWISE ? 1 : p.input_channels);
    int8_t *input = static_cast<int8_t *>(allocate(input_bytes));
    int8_t *weights = static_cast<int8_t *>(allocate(weight_bytes));
    int32_t *bias = static_cast<int32_t *>(allocate(p.output_channels * 4));
    p.weights = weights;
    p.bias = bias;
    p.packed_weights = static_cast<int8_t *>(allocate(gemmini_packed_weight_bytes(p)));
    p.weight_sums = static_cast<int32_t *>(allocate(p.output_channels * 4));
    if (gemmini_kernel_prefix_bytes(p))
      p.kernel_prefix = static_cast<int32_t *>(allocate(gemmini_kernel_prefix_bytes(p)));
    int32_t *multipliers = static_cast<int32_t *>(allocate(p.output_channels * 4));
    int32_t *shifts = static_cast<int32_t *>(allocate(p.output_channels * 4));
    p.multipliers = multipliers;
    p.shifts = shifts;
    const size_t output_bytes = kind == "dw_vendor" ? gemmini_raw_output_bytes(p) / 4 : gemmini_raw_output_bytes(p);
    int32_t *raw = static_cast<int32_t *>(allocate(output_bytes));
    if (argc == 26) {
      load_binary(argv[15], input, input_bytes);
      load_binary(argv[16], weights, weight_bytes);
      load_binary(argv[17], bias, p.output_channels * 4);
      load_binary(argv[18], multipliers, p.output_channels * 4);
      load_binary(argv[19], shifts, p.output_channels * 4);
    } else {
      uint32_t random = 0x81765432;
      auto next = [&]() { random ^= random << 13; random ^= random >> 17; random ^= random << 5; return random; };
      for (size_t i = 0; i < input_bytes; ++i) input[i] = int8_t(next());
      for (size_t i = 0; i < weight_bytes; ++i) weights[i] = int8_t(int(next() % 63) - 31);
      for (int i = 0; i < p.output_channels; ++i) bias[i] = int32_t(next() % 8001) - 4000;
      input[0] = -128;
      input[input_bytes - 1] = 127;
    }
    gemmini_prepare_layer(&p);
    if (!p.supported) throw std::runtime_error("No legal hardware tile fits");
    if (const char *value = std::getenv("GEMMINI_TILE_HEIGHT")) p.tile_height = std::stoi(value);
    if (const char *value = std::getenv("GEMMINI_TILE_WIDTH")) p.tile_width = std::stoi(value);
    if (const char *value = std::getenv("GEMMINI_TILE_CHANNELS")) p.tile_channels = std::stoi(value);
    auto expected = reference(p, input, false);
    auto centered = reference(p, input, true);
    for (size_t i = 0; i < expected.size(); ++i) {
      const int c = i % p.output_channels;
      const int x = (i / p.output_channels) % p.output_width;
      const int y = i / (p.output_channels * p.output_width);
      if (int64_t(expected[i]) + p.input_offset * gemmini_valid_weight_sum(p, y, x, c) != centered[i])
        throw std::runtime_error("Padding and input zero point correction differ");
    }
    std::vector<int8_t> quantized(expected.size());
    gemmini_requantize_output(p, expected.data(), quantized.data());
    commands.open(directory / "commands.txt");
    gemmini_reset_accelerator();
    if (kind == "dw_vendor") {
      gemmini_run_vendor_depthwise(p, input, reinterpret_cast<int8_t *>(raw));
      p.input_offset = 0;
      p.output_offset = 0;
      p.multiplier = 1073741824;
      p.shift = -4;
      gemmini_requantize_output(p, expected.data(), quantized.data());
    } else {
      gemmini_run_raw(p, input, raw);
    }
    commands.close();
    write_binary(directory / "memory.bin", memory.data(), (cursor + 4095) & ~size_t(4095));
    write_binary(directory / "expected.bin", kind == "dw_vendor" ? static_cast<const void *>(quantized.data()) : expected.data(), output_bytes);
    write_binary(directory / "expected_int8.bin", quantized.data(), quantized.size());
    std::ofstream metadata(directory / "case.json");
    metadata << "{\n  \"kind\":\"" << kind << "\",\n  \"memory_base\":" << physical_base
      << ",\n  \"output_base\":" << physical(reinterpret_cast<uintptr_t>(raw))
      << ",\n  \"output_bytes\":" << output_bytes << ",\n  \"timed_start\":2,\n  \"command_records\":" << records
      << ",\n  \"tile\":[" << p.tile_height << ',' << p.tile_width << ',' << p.tile_channels
      << "],\n  \"input_offset\":" << p.input_offset
      << ",\n  \"independent_im2col\":" << (p.independent_im2col ? "true" : "false")
      << ",\n  \"padding_correction_passed\":true\n}\n";
    std::cout << directory << " " << records << " records\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
