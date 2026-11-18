#include "Via_prefetch_tb.h"
#include "verilated.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool valid, const std::string& message) {
  if (!valid) throw std::runtime_error(message);
}
std::int16_t signed16(std::uint16_t bits) {
  return static_cast<std::int16_t>(bits < 32768U ? static_cast<int>(bits)
                                                : static_cast<int>(bits) - 65536);
}
struct Job {
  std::uint32_t base = 0x10000, stride = 129, reduction = 35, epoch = 0;
  unsigned r = 4;
  int offset = -127;
  bool compact = true, use16 = false, source16 = false, im2col = false, is_mode = false, packed = false;
};
std::uint32_t source_address(const Job& job, std::uint32_t row, std::uint32_t col) {
  if (!job.packed) return job.base + row * job.stride + col * (job.use16 ? 2U : 1U);
  const std::uint32_t k_tiles = (job.reduction + 15U) / 16U;
  const std::uint32_t element = (row / 16U) * k_tiles * 256U +
      (col / 16U) * 256U + (row % 16U) * 16U + col % 16U;
  return job.base + element * (job.use16 ? 2U : 1U);
}
std::int16_t source(const Job& job, std::uint32_t row, std::uint32_t col) {
  const std::uint32_t address = source_address(job, row, col);
  const std::uint32_t hash = address * 17U + row * 193U + col * 29U + job.epoch * 83U;
  if (job.source16) return signed16(static_cast<std::uint16_t>(hash * 137U));
  if (job.im2col && (row + 2U * col) % 19U == 0) return 0;
  return static_cast<std::int16_t>(static_cast<int>(hash & 255U) - 128 + job.offset);
}
struct Descriptor {
  Job job;
  std::uint32_t p0 = 0, q0 = 0;
  unsigned slot = 0, rows = 0, cols = 0, row = 0, col = 0, delay = 0;
  bool prefetch = false;
};
struct Counts {
  std::uint64_t commands = 0, values = 0, cycles = 0, demand_dmas = 0, prefetch_dmas = 0;
  std::uint64_t hits = 0, hits_during_prefetch = 0, mixed_tail_hits = 0;
  std::uint64_t background_completions = 0, crossed_init = 0, overlap_rows = 0;
  std::uint64_t physical_wraps = 0, padding_values = 0, priority_checks = 0;
} totals;

class Simulation {
 public:
  Via_prefetch_tb dut;
  Job job;
  std::uint64_t cycle = 0, demands = 0, prefetches = 0, hits = 0;
  bool allow_grant = true;
  unsigned prefetch_delay = 140, demand_delay = 3;

  Simulation() {
    dut.rst_n = 0;
    for (unsigned i = 0; i < 3; ++i) edge();
    dut.rst_n = 1;
    edge();
  }

  void start_job(const Job& next) {
    drain();
    require(dut.idle, "job configuration requires an idle controller");
    job = next;
    dut.cache_flush = 1;
    step();
    dut.cache_flush = 0;
  }

  void command(const std::string& name, unsigned p0, unsigned rows, unsigned q0,
               bool enable, bool preserve = true) {
    require(dut.idle, name + ": controller must be idle");
    require(q0 < job.reduction && rows <= job.r * 16U, name + ": invalid command dimensions");
    current_name = name;
    expected_rows = rows;
    current_p0 = p0;
    current_q0 = q0;
    current_cols = std::min(16U, job.reduction - q0);
    output_counts.fill(0);
    checking = true;
    completed = false;
    group_starts = 0;
    if (active && descriptor.prefetch) ++totals.crossed_init;
    dut.cfg_im2col = job.im2col;
    dut.cfg_tile_packed = job.packed;
    dut.cfg_compact = job.compact;
    dut.cfg_compact_offset = static_cast<std::uint32_t>(job.offset);
    dut.cfg_preserve_cache = preserve;
    dut.cfg_prefetch_enable = enable;
    dut.cfg_global_reduction = job.reduction;
    dut.cfg_p0_base = p0;
    dut.cfg_q0_base = q0;
    const unsigned slots = job.compact ? 8U : 4U;
    dut.cfg_cache_slot_base = ((p0 / 16U) + (q0 / 16U) * job.r) % slots;
    dut.k = rows; dut.n = current_cols; dut.m = 16;
    dut.lhs_base = source_address(job, p0, q0);
    dut.lhs_row_stride_b = job.stride;
    dut.lhs_zp = static_cast<std::uint32_t>(job.offset);
    dut.use_16bits = job.use16;
    dut.bias_by_row_mode = job.is_mode;
    dut.ia_reuse_num = job.r; dut.w_reuse_num = 1;
    dut.row_groups = 1; dut.row_tail_tiles = (rows + 15U) / 16U;
    dut.col_groups = 1; dut.col_tail_tiles = 1;
    dut.init_cfg = 1;
    step();
    dut.init_cfg = 0;
    require(bool(dut.prefetch_enabled) == (enable && preserve), name + ": enable qualification");
    for (unsigned remaining = 100000; remaining != 0; --remaining) {
      step();
      if (completed && dut.idle) break;
      require(remaining != 1, name + ": timeout");
    }
    require(group_starts == 1, name + ": expected one full-R group");
    for (unsigned lane = 0; lane < 16; ++lane)
      require(output_counts[lane] == rows, name + ": missing output values");
    checking = false;
    dut.send_ia_trigger = 0;
    ++totals.commands;
  }

  void wait_cycles(unsigned count) {
    while (count--) step();
  }
  void drain() {
    allow_grant = true;
    for (unsigned count = 0; count < 100000; ++count) {
      step();
      if (!active && dut.prefetch_idle && !dut.ext_dma_start && !grant_owner) return;
    }
    throw std::runtime_error("prefetch drain timed out");
  }

 private:
  Descriptor descriptor;
  bool active = false, grant_owner = false, checking = false, completed = false, hit_d1 = false;
  std::string current_name;
  unsigned expected_rows = 0, current_p0 = 0, current_q0 = 0, current_cols = 0;
  unsigned group_starts = 0, previous_slot = 0;
  std::array<unsigned, 16> output_counts{};

  void edge() {
    dut.clk = 0; dut.eval();
    dut.clk = 1; dut.eval();
    dut.clk = 0; dut.eval();
    ++cycle; ++totals.cycles;
  }
  void step() {
    dut.ext_dma_busy = active;
    dut.ext_dma_done = active && descriptor.row == descriptor.rows;
    for (unsigned lane = 0; lane < 4; ++lane) dut.ext_dma_wr_valid[lane] = 0;
    const bool write = active && !dut.ext_dma_done && descriptor.delay == 0 && cycle % 11U != 3U;
    if (write) {
      dut.ext_dma_wr_slot = descriptor.slot;
      dut.ext_dma_wr_row = descriptor.row;
      dut.ext_dma_wr_col_base = descriptor.col;
      dut.ext_dma_wr_use_16bits = descriptor.job.use16 || descriptor.job.im2col;
      for (unsigned lane = 0; lane < 4; ++lane) {
        dut.ext_dma_wr_valid[lane] = 1;
        dut.ext_dma_wr_data[lane] = static_cast<std::uint16_t>(source(
            descriptor.job, descriptor.p0 + descriptor.row, descriptor.q0 + descriptor.col + lane));
      }
      require(dut.active_valid_cols == descriptor.cols,
              current_name + ": a cache hit changed the active DMA tail mask");
    }
    dut.send_ia_trigger = checking;
    dut.load_ia_granted = grant_owner;
    dut.clk = 0; dut.eval();
    if (!active && !grant_owner && allow_grant && cycle % 7U != 2U && dut.load_ia_req)
      dut.load_ia_granted = 1;
    dut.eval();
    const bool launch = dut.ext_dma_start;
    const bool done = dut.ext_dma_done;
    const bool granted = dut.load_ia_req && dut.load_ia_granted;
    const bool hit = dut.cache_hit;
    if (dut.ia_data_valid && dut.send_ia_trigger)
      require(dut.ps_frame_rows == expected_rows,
              current_name + ": PS frame length must equal the valid input rows");
    if (dut.prefetch_issue) {
      require(!dut.demand_request, current_name + ": prefetch displaced a demand");
      ++totals.priority_checks;
    }
    if (hit) {
      ++hits; ++totals.hits;
      if (active && descriptor.prefetch) {
        ++totals.hits_during_prefetch;
        if (descriptor.cols != current_cols) ++totals.mixed_tail_hits;
      }
    }
    if (done && descriptor.prefetch) {
      ++totals.background_completions;
      require(!dut.demand_complete || hit_d1,
              current_name + ": background DMA incorrectly completed a controller load");
    }
    if (dut.group_start) {
      require(checking, "unexpected group start");
      ++group_starts;
    }
    Descriptor next;
    if (launch) {
      require(!active, current_name + ": overlapping DMA commands");
      require(grant_owner || granted, current_name + ": DMA launch lacks a grant");
      next.job = job;
      next.slot = dut.ext_dma_slot_id;
      next.rows = dut.ext_dma_rows_to_read;
      next.p0 = dut.ext_dma_p0;
      next.q0 = dut.ext_dma_q0;
      next.prefetch = dut.prefetch_launch;
      next.cols = std::min(16U, job.reduction - next.q0);
      next.delay = next.prefetch ? prefetch_delay : demand_delay;
      require(next.q0 < job.reduction, current_name + ": DMA exceeds global K");
      require(next.rows >= 1 && next.rows <= 16, current_name + ": invalid DMA row count");
      require(next.slot == ((next.p0 / 16U) + (next.q0 / 16U) * job.r) % (job.compact ? 8U : 4U),
              current_name + ": incorrect physical slot mapping");
      require(dut.ext_dma_base_addr == source_address(job, next.p0, next.q0),
              current_name + ": incorrect DMA address got=" + std::to_string(dut.ext_dma_base_addr) + " expected=" + std::to_string(source_address(job, next.p0, next.q0)) + " p=" + std::to_string(next.p0) + " q=" + std::to_string(next.q0));
      require(dut.ext_dma_row_stride == (job.packed ? 16U * (job.use16 ? 2U : 1U) : job.stride) &&
              dut.ext_dma_lhs_zp == static_cast<std::uint32_t>(job.offset) &&
              bool(dut.ext_dma_use_16bits) == job.use16 && bool(dut.ext_dma_im2col) == job.im2col,
              current_name + ": incorrect DMA source properties");
      require(dut.ext_dma_burst_len_m1 == (((job.packed ? 16U : next.cols) * (job.use16 ? 2U : 1U) + 3U) / 4U) - 1U,
              current_name + ": incorrect DMA burst length");
      if (next.slot < previous_slot) ++totals.physical_wraps;
      previous_slot = next.slot;
    }
    edge();
    hit_d1 = hit;
    if (write) {
      descriptor.col += 4;
      if (descriptor.col == 16) { descriptor.col = 0; ++descriptor.row; }
    }
    if (active && descriptor.delay) --descriptor.delay;
    if (done) active = false;
    if (launch) {
      descriptor = next; active = true; grant_owner = false;
      if (next.prefetch) { ++prefetches; ++totals.prefetch_dmas; }
      else { ++demands; ++totals.demand_dmas; }
    } else if (granted) grant_owner = true;
    else if (!dut.load_ia_req) grant_owner = false;
    bool any_value = false;
    for (unsigned lane = 0; lane < 16; ++lane) {
      require(bool(dut.lane_valid[lane]) == bool(dut.ia_row_valid),
              current_name + ": every input lane must share the complete-row valid cycle");
      if (dut.lane_valid[lane]) {
        require(checking && output_counts[lane] < expected_rows, current_name + ": unexpected output row");
        const unsigned row = current_p0 + output_counts[lane]++;
        const std::int16_t expected = lane < current_cols ? source(job, row, current_q0 + lane) : 0;
        const std::int16_t actual = signed16(dut.ia_out[lane]);
        require(actual == expected, current_name + ": output mismatch at row " + std::to_string(row) +
                " lane " + std::to_string(lane) + ": expected " + std::to_string(expected) +
                ", got " + std::to_string(actual));
        ++totals.values;
        if (job.im2col && lane < current_cols && (row + 2U * (current_q0 + lane)) % 19U == 0)
          ++totals.padding_values;
        any_value = true;
      } else require(dut.ia_out[lane] == 0, current_name + ": invalid output lane is nonzero");
    }
    if (any_value && active && descriptor.prefetch) ++totals.overlap_rows;
    completed = completed || bool(dut.complete);
  }
};

void repeated_columns(Simulation& sim, const Job& job, const std::string& name,
                      unsigned p0, unsigned rows) {
  sim.start_job(job);
  sim.command(name + "_k0", p0, rows, 0, true);
  require(!sim.dut.prefetch_idle, name + ": no background work at first command completion");
  const auto demand_before = sim.demands, hits_before = sim.hits;
  sim.allow_grant = false;
  sim.command(name + "_cached_without_grant", p0, rows, 0, true);
  require(sim.demands == demand_before && sim.hits - hits_before == (rows + 15U) / 16U,
          name + ": cached column required DMA grant");
  sim.allow_grant = true;
  for (unsigned q0 = 16; q0 < job.reduction; q0 += 16) {
    sim.command(name + "_next_k_" + std::to_string(q0), p0, rows, q0, true);
    if (q0 + 16 < job.reduction) {
      const auto before = sim.demands;
      sim.allow_grant = false;
      sim.command(name + "_reuse_" + std::to_string(q0), p0, rows, q0, true);
      require(sim.demands == before, name + ": repeated K group caused demand DMA");
      sim.allow_grant = true;
    }
  }
  sim.drain();
  require(sim.dut.prefetch_idle, name + ": last K block left prefetch work");
}
}  // namespace

int main(int argc, char** argv) {
  Verilated::commandArgs(argc, argv);
  try {
    Simulation sim;
    Job j;
    repeated_columns(sim, j, "s8_ws_full_r4", 0, 64);
    j.offset = 128; j.im2col = true;
    repeated_columns(sim, j, "conv_corrected_s8_r4_tail", 64, 61);
    j.is_mode = true; j.offset = 0; j.im2col = false; j.reduction = 49;
    repeated_columns(sim, j, "is_weight_s8_r4", 128, 64);
    j.compact = false; j.source16 = true; j.use16 = true; j.is_mode = false;
    j.r = 2; j.reduction = 35; j.stride = 173;
    repeated_columns(sim, j, "s16_ws_r2", 32, 29);
    j.compact = true; j.source16 = false; j.use16 = false; j.r = 4;
    j.offset = -127; j.stride = 137; j.reduction = 65;
    repeated_columns(sim, j, "compact_small_tail_group", 64, 7);

    // Rewind while a future K block is in flight; exact tags protect the
    // current group and unissued requests from the old sequence are cancelled.
    sim.start_job(j);
    sim.command("rewind_k0", 0, 61, 0, true);
    sim.command("rewind_k16", 0, 61, 16, true);
    sim.command("rewind_k0_again", 0, 61, 0, true);
    sim.command("row_group_change", 64, 31, 0, true);
    sim.drain();

    // The job identity is held across a background transfer. A following
    // command with a new source address must miss even with identical shape.
    sim.start_job(j);
    sim.command("source_initial", 0, 64, 0, true);
#ifdef ORDERED_JOB_TEST
    sim.drain();
#endif
    sim.job.base += 0x1000;
#ifdef ORDERED_JOB_TEST
    sim.start_job(sim.job);
#endif
    sim.command("source_base_change", 0, 64, 0, true);
    sim.drain();
#ifdef ORDERED_JOB_TEST
    sim.drain();
#endif
    sim.job.stride += 17;
#ifdef ORDERED_JOB_TEST
    sim.start_job(sim.job);
#endif
    sim.command("source_stride_change", 0, 64, 0, true);
    sim.drain();

    // Default-disabled operation leaves no speculative data request.
    sim.start_job(j);
    const auto before = sim.prefetches;
    sim.command("disabled", 0, 64, 0, false);
    sim.command("disabled_preserved", 0, 64, 0, false);
    sim.command("preserve_disabled", 0, 64, 0, true, false);
    require(sim.prefetches == before && sim.dut.prefetch_idle,
            "disabled prefetch issued a speculative DMA");
    sim.drain();

    // Different tail widths, signed offsets and circular slot bases.
    for (unsigned seed = 0; seed < 24; ++seed) {
      Job varied;
      varied.compact = seed % 3 != 0;
      varied.source16 = !varied.compact;
      varied.use16 = !varied.compact;
      varied.r = varied.compact ? 4U : 2U;
      varied.offset = varied.compact ? static_cast<int>((seed * 47U) & 255U) - 127 : 0;
      varied.im2col = varied.compact && seed % 2 == 0;
      varied.is_mode = seed % 5 == 0;
      varied.epoch = seed + 1;
      varied.reduction = 32U + seed % 16U + 1U;
      varied.stride = 193U + seed;
      const unsigned rows = varied.r * 16U - seed % 16U;
      sim.prefetch_delay = 15U + seed * 11U;
      repeated_columns(sim, varied, "varied_" + std::to_string(seed), (seed % 4U) * 16U, rows);
    }
    for (unsigned seed = 0; seed < 12; ++seed) {
      Job packed;
      packed.packed = true;
      packed.compact = seed % 2U == 0;
      packed.source16 = !packed.compact;
      packed.use16 = !packed.compact;
      packed.r = packed.compact ? 4U : 2U;
      packed.offset = packed.compact ? int(seed * 19U) - 127 : 0;
      packed.epoch = 100U + seed;
      packed.reduction = 33U + seed * 5U;
      packed.is_mode = seed % 3U == 0;
      sim.prefetch_delay = 30U + seed * 9U;
      repeated_columns(sim, packed, "packed_" + std::to_string(seed),
                       (seed % 4U) * 16U, packed.r * 16U - seed);
    }
    require(totals.hits_during_prefetch != 0 && totals.mixed_tail_hits != 0 &&
            totals.crossed_init != 0 && totals.overlap_rows != 0 && totals.padding_values != 0,
            "required concurrent/tail/padding scenarios were not exercised");
    std::cout << "{\"passed\":true,\"commands\":" << totals.commands
              << ",\"value_checks\":" << totals.values << ",\"cycles\":" << totals.cycles
              << ",\"demand_dma_requests\":" << totals.demand_dmas
              << ",\"prefetch_dma_requests\":" << totals.prefetch_dmas
              << ",\"cache_hits\":" << totals.hits
              << ",\"cache_hits_during_prefetch\":" << totals.hits_during_prefetch
              << ",\"different_k_tail_hits\":" << totals.mixed_tail_hits
              << ",\"background_completions\":" << totals.background_completions
              << ",\"init_while_prefetch_active\":" << totals.crossed_init
              << ",\"output_cycles_during_prefetch\":" << totals.overlap_rows
              << ",\"slot_wraps\":" << totals.physical_wraps
              << ",\"padding_value_checks\":" << totals.padding_values
              << ",\"prefetch_priority_checks\":" << totals.priority_checks
              << ",\"physical_data_bytes\":2048}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
