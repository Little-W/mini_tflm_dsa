#include "Via_loader_cache_mgr.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int kSize = 16;
using Tile = std::array<std::array<std::int16_t, kSize>, kSize>;
std::array<Tile, 8> expected{};
std::uint64_t checks = 0, padding_checks = 0, cycles = 0;
std::uint64_t compact_groups = 0, wide_groups = 0, simultaneous_writes = 0;

std::int16_t signed16(std::uint16_t value) {
  return static_cast<std::int16_t>(value < 32768U ? static_cast<int>(value)
                                                : static_cast<int>(value) - 65536);
}
void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}
void tick(Via_loader_cache_mgr& dut) {
  dut.clk = 0;
  dut.eval();
  dut.clk = 1;
  dut.eval();
  dut.clk = 0;
  dut.eval();
  ++cycles;
}
void clear_write(Via_loader_cache_mgr& dut) {
  for (int i = 0; i < 4; ++i) dut.wr_valid[i] = 0;
}
void drive_write(Via_loader_cache_mgr& dut, int slot, int row, int column) {
  dut.wr_slot = slot;
  dut.wr_row = row;
  dut.wr_col_base = column;
  for (int i = 0; i < 4; ++i) {
    dut.wr_valid[i] = 1;
    dut.wr_data[i] = static_cast<std::uint16_t>(expected[slot][row][column + i]);
  }
}
void write_slots(Via_loader_cache_mgr& dut, int slots) {
  for (int slot = 0; slot < slots; ++slot)
    for (int row = 0; row < kSize; ++row)
      for (int column = 0; column < kSize; column += 4) {
        drive_write(dut, slot, row, column);
        tick(dut);
      }
  clear_write(dut);
}
void read_group(Via_loader_cache_mgr& dut, int first, int last,
                const std::function<void(int)>& concurrent = {}) {
  const int slots = dut.compact_mode ? 8 : 4;
  std::vector<std::pair<int, int>> order;
  for (int slot = first;; slot = (slot + 1) % slots) {
    for (int row = 0; row < dut.slot_rows[slot]; ++row) order.emplace_back(slot, row);
    if (slot == last) break;
  }
  dut.l1_slot_start = first;
  dut.l1_slot_end = last;
  dut.l1_is_init = 1;
  dut.l1_calc_done = 1;
  int valid_rows = 0, completed = 0;
  for (int step = 0; step < static_cast<int>(order.size()) + 3; ++step) {
    dut.l1_start = step == 0;
    if (concurrent) concurrent(step);
    tick(dut);
    for (int lane = 0; lane < kSize; ++lane) {
      const int index = step - 1;
      const bool valid = index >= 0 && index < static_cast<int>(order.size());
      const auto value = valid ? expected[order[index].first][order[index].second][lane] : 0;
      if (signed16(dut.ia_out[lane]) != value)
        throw std::runtime_error("RAM mismatch at step=" + std::to_string(step) +
                                 " lane=" + std::to_string(lane) + " first=" +
                                 std::to_string(first) + " expected=" + std::to_string(value) +
                                 " got=" + std::to_string(signed16(dut.ia_out[lane])));
      if (valid) {
        ++checks;
        if (value == 0) ++padding_checks;
      }
      if (lane == kSize - 1) {
        require(bool(dut.ia_row_valid) == valid, "Complete-row valid timing mismatch");
        require(bool(dut.ia_is_init_data) == valid, "Init timing mismatch");
        require(bool(dut.ia_calc_done) == valid, "Final timing mismatch");
        require(bool(dut.l1_done) == (valid && index + 1 == static_cast<int>(order.size())),
                "Group completion must accompany its final row");
        require(bool(dut.tile_done) == (valid && order[index].second + 1 == dut.slot_rows[order[index].first]),
                "Tile completion must accompany its final row");
        valid_rows += valid;
      }
    }
    completed += dut.l1_done;
  }
  dut.l1_start = 0;
  clear_write(dut);
  require(valid_rows == static_cast<int>(order.size()), "Missing complete rows");
  require(completed == 1, "L1 completion count mismatch");
  if (dut.compact_mode) ++compact_groups;
  else ++wide_groups;
}
}  // namespace

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  try {
    Via_loader_cache_mgr dut;
    dut.rst_n = 0;
    tick(dut);
    tick(dut);
    dut.rst_n = 1;
    tick(dut);
    for (int slot = 0; slot < 8; ++slot) dut.slot_rows[slot] = kSize;

    // Every source byte at every legal additive offset is stored in both banks.
    dut.compact_mode = 1;
    for (int offset = -127; offset <= 128; ++offset) {
      dut.compact_offset = static_cast<std::uint16_t>(offset);
      for (int slot = 0; slot < 8; ++slot)
        for (int row = 0; row < kSize; ++row)
          for (int lane = 0; lane < kSize; ++lane) {
            const int raw = (row * kSize + lane + 31 * slot) & 255;
            expected[slot][row][lane] = static_cast<std::int16_t>(
                (raw < 128 ? raw : raw - 256) + offset);
          }
      write_slots(dut, 8);
      read_group(dut, 0, 7);
    }

    // Every S16 bit pattern passes through the two byte banks unchanged.
    dut.compact_mode = 0;
    for (int batch = 0; batch < 64; ++batch) {
      for (int slot = 0; slot < 4; ++slot)
        for (int row = 0; row < kSize; ++row)
          for (int lane = 0; lane < kSize; ++lane)
            expected[slot][row][lane] = signed16(static_cast<std::uint16_t>(
                batch * 1024 + slot * 256 + row * kSize + lane));
      write_slots(dut, 4);
      read_group(dut, 0, 3);
    }

    for (int compact = 0; compact <= 1; ++compact) {
      dut.compact_mode = compact;
      dut.compact_offset = static_cast<std::uint16_t>(compact ? -127 : 0);
      const int slots = compact ? 8 : 4;
      for (int slot = 0; slot < slots; ++slot) {
        dut.slot_rows[slot] = 1 + (slot * 5 % 16);
        for (int row = 0; row < kSize; ++row)
          for (int lane = 0; lane < kSize; ++lane) {
            const int raw = ((row * 17 + lane + slot) & 255) - 128;
            expected[slot][row][lane] = (lane > (slot * 3 % 16) || row >= dut.slot_rows[slot])
                ? 0 : static_cast<std::int16_t>(compact ? raw - 127 : raw * 251);
          }
      }
      write_slots(dut, slots);
      read_group(dut, slots - 2, 1);
    }

    // Writes to the other compact half overlap a continuous read from slots 0..3.
    dut.compact_mode = 1;
    dut.compact_offset = 128;
    for (int slot = 0; slot < 8; ++slot) {
      dut.slot_rows[slot] = 16;
      for (int row = 0; row < kSize; ++row)
        for (int lane = 0; lane < kSize; ++lane)
          expected[slot][row][lane] = static_cast<std::int16_t>((slot + row * 19 + lane) & 255);
    }
    write_slots(dut, 8);
    read_group(dut, 0, 3, [&](int step) {
      if (step < 64) {
        const int row = step / 4;
        const int column = (step % 4) * 4;
        for (int i = 0; i < 4; ++i) expected[4][row][column + i] ^= 255;
        drive_write(dut, 4, row, column);
        ++simultaneous_writes;
      } else clear_write(dut);
    });
    read_group(dut, 4, 7);
    dut.final();
    std::cout << "{\"passed\":true,\"data_ram_bytes\":2048,\"compact_slots\":8,"
              << "\"wide_slots\":4,\"s8_offsets\":256,\"s16_bit_patterns\":65536,"
              << "\"value_checks\":" << checks << ",\"zero_checks\":" << padding_checks
              << ",\"compact_groups\":" << compact_groups << ",\"wide_groups\":" << wide_groups
              << ",\"simultaneous_write_cycles\":" << simultaneous_writes
              << ",\"cycles\":" << cycles << "}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
