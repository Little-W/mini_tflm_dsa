#include "Via_compact_loader_tb.h"
#include "verilated.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Case {
  std::string name;
  unsigned rows = 61, reduction = 13, columns = 16, r = 4, w = 1;
  unsigned base = 0x10000, stride = 37, p0 = 101, q0 = 32, epoch = 0, slot_base = 0;
  int offset = -127, zp = -127;
  bool compact = true, preserve = true, flush = false, im2col = false;
  bool use16 = false, source16 = false, is_mode = false, packed = false;
};
struct Descriptor {
  unsigned slot = 0, rows = 0, p0 = 0, q0 = 0, row = 0, column = 0;
  unsigned delay = 0;
};
struct Counts {
  std::uint64_t cases = 0, requests = 0, hits = 0, values = 0, cycles = 0;
  std::uint64_t compact_cases = 0, wide_cases = 0, wrap_requests = 0, frame_ids = 0;
} counts;
std::int16_t signed16(std::uint16_t value) {
  return static_cast<std::int16_t>(value < 32768U ? static_cast<int>(value)
                                                : static_cast<int>(value) - 65536);
}
std::uint32_t source_address(const Case& c, unsigned row, unsigned column) {
  const unsigned p = row - c.p0, q = column - c.q0;
  if (!c.packed) return c.base + p * c.stride + q * (c.use16 ? 2U : 1U);
  const unsigned element = (p / 16U) * ((c.reduction + 15U) / 16U) * 256U +
      (q / 16U) * 256U + (p % 16U) * 16U + q % 16U;
  return c.base + element * (c.use16 ? 2U : 1U);
}
std::int16_t source(const Case& c, unsigned row, unsigned column) {
  const std::uint32_t address = source_address(c, row, column);
  const std::uint32_t hash = row * 193U + column * 29U + address * 17U +
                             c.stride * 7U + c.epoch * 83U;
  if (c.source16) return signed16(static_cast<std::uint16_t>(hash * 137U));
  const int raw = static_cast<int>(hash & 255U) - 128;
  return signed16(static_cast<std::uint16_t>(raw + c.offset));
}
void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}
void tick(Via_compact_loader_tb& dut) {
  dut.clk = 0; dut.eval();
  dut.clk = 1; dut.eval();
  dut.clk = 0; dut.eval();
  ++counts.cycles;
}
std::array<std::vector<std::int16_t>, 16> make_expected(const Case& c) {
  std::array<std::vector<std::int16_t>, 16> result;
  const unsigned column_tiles = (c.columns + 15) / 16;
  for (unsigned row_base = 0; row_base < c.rows; row_base += c.r * 16)
    for (unsigned wg = 0; wg < column_tiles; wg += c.w)
      for (unsigned red = 0; red < c.reduction; red += 16)
        for (unsigned wi = 0; wi < std::min(c.w, column_tiles - wg); ++wi)
          for (unsigned row = row_base; row < std::min(c.rows, row_base + c.r * 16); ++row)
            for (unsigned lane = 0; lane < 16; ++lane)
              result[lane].push_back(red + lane < c.reduction
                  ? source(c, c.p0 + row, c.q0 + red + lane) : 0);
  return result;
}
void execute(Via_compact_loader_tb& dut, const Case& c,
             int expected_requests = -1, int expected_hits = -1) {
  require(dut.idle, c.name + ": loader must be idle before configuration");
  dut.cfg_im2col = c.im2col;
  dut.cfg_tile_packed = c.packed;
  dut.cfg_compact = c.compact;
  dut.cfg_compact_offset = static_cast<std::uint32_t>(c.offset);
  dut.cfg_preserve_cache = c.preserve;
  dut.cfg_p0_base = c.p0;
  dut.cfg_q0_base = c.q0;
  dut.cfg_cache_slot_base = c.slot_base;
  dut.k = c.rows; dut.n = c.reduction; dut.m = c.columns;
  dut.lhs_base = c.base; dut.lhs_row_stride_b = c.stride;
  dut.lhs_zp = static_cast<std::uint32_t>(c.zp);
  dut.use_16bits = c.use16; dut.bias_by_row_mode = c.is_mode;
  dut.ia_reuse_num = c.r; dut.w_reuse_num = c.w;
  const unsigned row_tiles = (c.rows + 15) / 16;
  const unsigned column_tiles = (c.columns + 15) / 16;
  dut.row_groups = (row_tiles + c.r - 1) / c.r;
  dut.row_tail_tiles = row_tiles % c.r ? row_tiles % c.r : c.r;
  dut.col_groups = (column_tiles + c.w - 1) / c.w;
  dut.col_tail_tiles = column_tiles % c.w ? column_tiles % c.w : c.w;
  dut.cache_flush = c.flush;
  dut.init_cfg = 1;
  tick(dut);
  dut.init_cfg = 0;
  dut.cache_flush = 0;
  const bool compact = c.compact && c.offset >= -127 && c.offset <= 128;
  require(bool(dut.compact_active) == compact, c.name + ": compact qualification mismatch");
  const auto expected = make_expected(c);
  std::vector<std::array<unsigned, 4>> expected_frames;
  for (unsigned row_base = 0; row_base < c.rows; row_base += c.r * 16)
    for (unsigned wg = 0; wg < column_tiles; wg += c.w)
      for (unsigned red = 0; red < c.reduction; red += 16)
        for (unsigned wi = 0; wi < std::min(c.w, column_tiles - wg); ++wi)
          expected_frames.push_back({wi, std::min(c.rows - row_base, c.r * 16),
                                     unsigned(red == 0), unsigned(red + 16 >= c.reduction)});
  std::size_t frame_index = 0;
  std::array<std::size_t, 16> output_index{};
  Descriptor descriptor;
  bool active = false, completed = false;
  unsigned requests = 0, hits = 0, previous_slot = 0;
  for (unsigned cycle = 0; cycle < 100000; ++cycle) {
    dut.ext_dma_busy = active;
    dut.ext_dma_done = active && descriptor.row >= descriptor.rows;
    for (unsigned i = 0; i < 4; ++i) dut.ext_dma_wr_valid[i] = 0;
    const bool write = active && !dut.ext_dma_done && descriptor.delay == 0 && (cycle % 11 != 3);
    if (write) {
      dut.ext_dma_wr_slot = descriptor.slot;
      dut.ext_dma_wr_row = descriptor.row;
      dut.ext_dma_wr_col_base = descriptor.column;
      dut.ext_dma_wr_use_16bits = c.use16;
      for (unsigned i = 0; i < 4; ++i) {
        dut.ext_dma_wr_valid[i] = 1;
        // Supply nonzero values beyond the K tail; the loader must clear them.
        dut.ext_dma_wr_data[i] = static_cast<std::uint16_t>(source(
            c, descriptor.p0 + descriptor.row, descriptor.q0 + descriptor.column + i));
      }
    }
    dut.send_ia_trigger = 1;
    dut.clk = 0; dut.eval();
    dut.load_ia_granted = dut.load_ia_req;
    dut.eval();
    const bool launch = dut.ext_dma_start;
    const bool done = dut.ext_dma_done;
    const bool hit = dut.cache_hit;
    if (dut.send_ia_trigger && dut.ia_data_valid) {
      require(frame_index < expected_frames.size(), c.name + ": unexpected frame");
      const auto frame = expected_frames[frame_index++];
      require(dut.ps_frame_id == frame[0] && dut.ps_frame_rows == frame[1] &&
              unsigned(dut.ps_frame_init) == frame[2] && unsigned(dut.ps_frame_final) == frame[3],
              c.name + ": frame ID, length or reduction flags mismatch");
      ++counts.frame_ids;
    }
    Descriptor next;
    if (launch) {
      require(!active, c.name + ": DMA command launched while active");
      next.slot = dut.ext_dma_slot_id;
      next.rows = dut.ext_dma_rows_to_read;
      next.p0 = dut.ext_dma_p0;
      next.q0 = dut.ext_dma_q0;
      next.delay = 2;
      require(next.slot < (compact ? 8U : 4U), c.name + ": slot exceeds mode capacity");
      require(next.slot == (requests + hits + c.slot_base) % (compact ? 8U : 4U),
              c.name + ": physical slot remapping mismatch");
      require(next.p0 >= c.p0 && next.q0 >= c.q0, c.name + ": global coordinates lost");
      const unsigned valid_columns = std::min(16U, c.reduction - (next.q0 - c.q0));
      require(dut.ext_dma_burst_len_m1 == ((c.packed ? 16U : valid_columns) * (c.use16 ? 2U : 1U) + 3U) / 4U - 1U,
              c.name + ": DMA burst length mismatch");
      require(dut.ext_dma_base_addr == source_address(c, next.p0, next.q0), c.name + ": DMA source address mismatch");
      require(dut.ext_dma_row_stride == (c.packed ? 16U * (c.use16 ? 2U : 1U) : c.stride),
              c.name + ": DMA row stride mismatch");
      if (requests && next.slot < previous_slot) ++counts.wrap_requests;
      previous_slot = next.slot;
    }
    tick(dut);
    if (write) {
      descriptor.column += 4;
      if (descriptor.column == 16) { descriptor.column = 0; ++descriptor.row; }
    }
    if (active && descriptor.delay) --descriptor.delay;
    if (done) active = false;
    if (launch) { descriptor = next; active = true; ++requests; }
    if (hit) ++hits;
    for (unsigned lane = 0; lane < 16; ++lane) {
      require(bool(dut.lane_valid[lane]) == bool(dut.ia_row_valid),
              c.name + ": every input lane must share the complete-row valid cycle");
      if (dut.lane_valid[lane]) {
        const auto index = output_index[lane]++;
        require(index < expected[lane].size(), c.name + ": unexpected output row");
        const auto value = signed16(dut.ia_out[lane]);
        if (value != expected[lane][index])
          throw std::runtime_error(c.name + ": output mismatch lane=" + std::to_string(lane) +
              " index=" + std::to_string(index) + " expected=" + std::to_string(expected[lane][index]) +
              " got=" + std::to_string(value));
        ++counts.values;
      } else require(dut.ia_out[lane] == 0, c.name + ": invalid lane must output zero");
    }
    completed = completed || bool(dut.complete);
    if (completed && dut.idle && !active) break;
    require(cycle != 99999, c.name + ": timeout");
  }
  for (unsigned lane = 0; lane < 16; ++lane)
    require(output_index[lane] == expected[lane].size(), c.name + ": missing output values");
  require(frame_index == expected_frames.size(), c.name + ": missing frame command");
  if (expected_requests >= 0)
    require(requests == static_cast<unsigned>(expected_requests), c.name + ": expected " +
        std::to_string(expected_requests) + " DMA requests, got " + std::to_string(requests));
  if (expected_hits >= 0)
    require(hits == static_cast<unsigned>(expected_hits), c.name + ": cache hit count mismatch");
  counts.requests += requests; counts.hits += hits; ++counts.cases;
  if (compact) ++counts.compact_cases; else ++counts.wide_cases;
  dut.ext_dma_busy = 0; dut.ext_dma_done = 0;
  dut.load_ia_granted = 0; dut.send_ia_trigger = 0;
  for (unsigned i = 0; i < 4; ++i) dut.ext_dma_wr_valid[i] = 0;
  tick(dut);
  tick(dut);
}
}  // namespace

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  try {
    Via_compact_loader_tb dut;
    dut.rst_n = 0; tick(dut); tick(dut); dut.rst_n = 1; tick(dut);
    Case c; c.name = "compact_initial"; execute(dut, c, 4, 0);
    c.name = "compact_preserved"; execute(dut, c, 0, 4);
    c.name = "tail_same_burst"; c.reduction = 14; execute(dut, c, 4, 0);
    c.name = "tail_preserved"; execute(dut, c, 0, 4);
    c.name = "global_p"; c.p0 += 16; execute(dut, c, 4, 0);
    c.name = "global_q"; ++c.q0; execute(dut, c, 4, 0);
    c.name = "base"; ++c.base; execute(dut, c, 4, 0);
    c.name = "stride"; ++c.stride; execute(dut, c, 4, 0);
    c.name = "dma_offset"; ++c.zp; execute(dut, c, 4, 0);
    c.name = "storage_offset"; c.offset = 128; execute(dut, c, 4, 0);
    c.name = "dma_width"; c.use16 = true; execute(dut, c, 4, 0);
    c.name = "im2col_source"; c.im2col = true; execute(dut, c, 4, 0);
    c.name = "row_tail"; --c.rows; execute(dut, c, 1, 3);
    c.name = "explicit_flush"; c.flush = true; ++c.epoch; execute(dut, c, 4, 0); c.flush = false;
    c.name = "preserve_disabled"; c.preserve = false; execute(dut, c, 4, 0); c.preserve = true;
    c.name = "preserve_after_load"; execute(dut, c, 0, 4);

    c.name = "compact_wrap_ws"; c.rows = 139; c.reduction = 35; c.columns = 49;
    c.r = 4; c.w = 2; c.flush = true; execute(dut, c, 54, 0);
    c.name = "compact_wrap_is"; c.is_mode = true; c.im2col = false; c.use16 = false;
    c.offset = 0; c.zp = 0; execute(dut, c, 54, 0);

    c.name = "offset_fallback"; c.rows = 31; c.reduction = 15; c.columns = 16;
    c.r = 2; c.w = 1; c.offset = 129; c.zp = 129; c.flush = false;
    execute(dut, c, 2, 0);
    c.name = "fallback_preserved"; execute(dut, c, 0, 2);
    c.name = "wide_wrap"; c.source16 = true; c.compact = false; c.use16 = true;
    c.rows = 91; c.reduction = 33; c.columns = 49; c.r = 2; c.w = 2;
    c.offset = 0; c.zp = 0; c.flush = true; c.is_mode = false; execute(dut, c, 36, 0);

    for (unsigned tail : {1U, 2U, 3U, 4U, 7U, 13U, 15U, 16U, 17U, 31U}) {
      c = Case{};
      c.name = "tail_" + std::to_string(tail);
      c.reduction = tail; c.rows = 57; c.flush = true;
      c.use16 = tail & 1U; c.im2col = c.use16;
      execute(dut, c, 4 * ((tail + 15) / 16), 0);
    }

    for (bool compact : {true, false}) {
      std::vector<Case> slices;
      const unsigned global_r = compact ? 4U : 2U;
      const unsigned slots = 2 * global_r;
      for (unsigned kt = 0; kt < 2; ++kt)
        for (unsigned pt = 0; pt < global_r; ++pt) {
          c = Case{};
          c.name = std::string(compact ? "s8" : "s16") + "_slice_" + std::to_string(kt * global_r + pt);
          c.compact = compact; c.source16 = !compact; c.use16 = !compact;
          c.offset = compact ? 17 : 0; c.zp = c.offset;
          c.rows = 16; c.reduction = 16; c.columns = 16; c.r = 1; c.w = 1;
          c.stride = 128; c.p0 = pt * 16; c.q0 = kt * 16;
          c.base = 0x20000 + c.p0 * c.stride + c.q0 * (c.use16 ? 2U : 1U);
          c.slot_base = (pt + kt * global_r) % slots;
          c.flush = kt == 0 && pt == 0;
          execute(dut, c, 1, 0);
          c.flush = false;
          slices.push_back(c);
        }
      for (auto slice = slices.rbegin(); slice != slices.rend(); ++slice) {
        slice->name += "_reuse";
        execute(dut, *slice, 0, 1);
      }
      c.name = compact ? "s8_slice_wrap" : "s16_slice_wrap";
      c.rows = 29; c.r = 2; c.slot_base = slots - 1;
      c.p0 = 224; c.q0 = 16; c.base = 0x20000 + c.p0 * c.stride + c.q0 * (c.use16 ? 2U : 1U);
      c.flush = false;
      execute(dut, c, 2, 0);
      c.name += "_reuse";
      execute(dut, c, 0, 2);
    }
    for (unsigned seed = 0; seed < 16; ++seed) {
      c = Case{};
      c.name = "packed_group_" + std::to_string(seed);
      c.packed = true; c.flush = true;
      c.compact = seed % 2U == 0; c.source16 = !c.compact; c.use16 = !c.compact;
      c.offset = c.compact ? 128 : 0; c.zp = c.offset;
      c.r = c.compact ? 4U : 2U; c.w = 2;
      c.rows = 33U + seed * 7U; c.reduction = 17U + seed * 3U; c.columns = 49;
      execute(dut, c);
    }
    dut.final();
    std::cout << "{\"passed\":true,\"cases\":" << counts.cases
              << ",\"compact_cases\":" << counts.compact_cases
              << ",\"wide_cases\":" << counts.wide_cases
              << ",\"dma_requests\":" << counts.requests
              << ",\"cache_hits\":" << counts.hits
              << ",\"value_checks\":" << counts.values
              << ",\"slot_wraps\":" << counts.wrap_requests
              << ",\"frame_id_checks\":" << counts.frame_ids
              << ",\"cycles\":" << counts.cycles << "}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
