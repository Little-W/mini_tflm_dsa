// SPDX-License-Identifier: Apache-2.0
#include "Vconv_axi_read_mux.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <tuple>

static void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}
struct Request { uint32_t address, len, size; };
struct Burst { Request request; unsigned owner, index, beat; };
static Request request_at(unsigned owner, unsigned index) {
  return {0x10000u + owner * 0x100000u + index * 1024u,
          (index % 9 == 0) ? 255u : (index * 5u % 17u), index % 3 == 0 ? 0u : 2u};
}
static uint32_t value_at(unsigned owner, unsigned index, unsigned beat) {
  return 0x78130000u ^ (owner << 31) ^ (index << 10) ^ beat;
}

int main(int argc, char **argv) {
  Verilated::commandArgs(argc, argv);
  try {
    Vconv_axi_read_mux dut;
    std::mt19937 rng{20261117};
    uint64_t total_bursts = 0, total_handoffs = 0, total_owner_changes = 0;
    uint64_t total_stalled_retirements = 0, total_error_beats = 0;
    for (unsigned mode = 0; mode < 6; ++mode) {
      const bool randomized = mode & 1;
      const bool enabled = mode >= 2;
      const bool both = mode >= 4;
      const std::array<unsigned, 2> target = {96, both ? 96u : 0u};
      std::array<unsigned, 2> issued{}, completed{};
      std::deque<Burst> outstanding;
      dut.rst_n = 0; dut.enable = enabled;
      dut.a_arvalid = 0; dut.b_arvalid = 0; dut.m_rvalid = 0;
      dut.a_rready = 0; dut.b_rready = 0; dut.m_arready = 0;
      for (unsigned i = 0; i < 3; ++i) {
        dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval(); Verilated::timeInc(1);
      }
      dut.rst_n = 1;
      bool held_response = false, stalled_ar = false;
      std::tuple<uint32_t, uint32_t, uint32_t, uint32_t> old_ar;
      uint64_t cycles = 0, handoffs = 0, owner_changes = 0, stalled_retirements = 0;
      uint64_t error_beats = 0;
      auto allow = [&] { return !randomized || rng() % 4 != 0; };
      while (completed != target && cycles < 1000000) {
        dut.clk = 0;
        auto a = request_at(0, issued[0]); auto b = request_at(1, issued[1]);
        dut.a_arvalid = issued[0] < target[0] && (enabled || outstanding.empty());
        dut.b_arvalid = issued[1] < target[1];
        dut.a_araddr = a.address; dut.a_arlen = a.len; dut.a_arsize = a.size; dut.a_arburst = 1;
        dut.b_araddr = b.address; dut.b_arlen = b.len; dut.b_arsize = b.size; dut.b_arburst = 1;
        dut.a_rready = allow(); dut.b_rready = allow();
        if (!held_response && !outstanding.empty() && allow()) {
          const auto &burst = outstanding.front();
          dut.m_rdata = value_at(burst.owner, burst.index, burst.beat);
          dut.m_rresp = burst.index % 13 == 0 && burst.beat == 0 ? 2 : 0;
          dut.m_rlast = burst.beat == burst.request.len;
          held_response = true;
        }
        dut.m_rvalid = held_response;
        // Periodic final-beat address stalls exercise the retained owner grant.
        const bool block_retirement = held_response && dut.m_rlast &&
          !outstanding.empty() && outstanding.front().index % 5 == 0;
        dut.m_arready = allow() && !block_retirement;
        dut.eval();
        if (enabled && (!outstanding.empty() || stalled_ar))
          require(!dut.idle, "mux reports idle with a retained transaction or grant");
        auto ar = std::make_tuple(uint32_t(dut.m_araddr), uint32_t(dut.m_arlen),
                                 uint32_t(dut.m_arsize), uint32_t(dut.m_arburst));
        if (stalled_ar) require(dut.m_arvalid && ar == old_ar, "mux AR changed under backpressure");
        stalled_ar = dut.m_arvalid && !dut.m_arready; old_ar = ar;
        const bool af = dut.a_arvalid && dut.a_arready;
        const bool bf = dut.b_arvalid && dut.b_arready;
        const bool address = dut.m_arvalid && dut.m_arready;
        require(!(af && bf) && address == (af || bf), "address grant count differs");
        bool retirement = false;
        unsigned retiring_owner = 0;
        if (held_response) {
          require(!outstanding.empty(), "memory response without accepted address");
          const auto &burst = outstanding.front();
          require(bool(dut.a_rvalid) == (burst.owner == 0) &&
                  bool(dut.b_rvalid) == (burst.owner == 1), "response delivered to wrong owner");
          const uint32_t data = burst.owner ? dut.b_rdata : dut.a_rdata;
          const uint32_t resp = burst.owner ? dut.b_rresp : dut.a_rresp;
          const uint32_t last = burst.owner ? dut.b_rlast : dut.a_rlast;
          require(data == dut.m_rdata && resp == dut.m_rresp && last == dut.m_rlast,
                  "response payload differs");
          require(bool(dut.m_rready) == bool(burst.owner ? dut.b_rready : dut.a_rready),
                  "response readiness differs");
          if (dut.m_rready) {
            error_beats += dut.m_rresp != 0;
            retirement = dut.m_rlast; retiring_owner = burst.owner;
            if (retirement) {
              ++completed[burst.owner]; outstanding.pop_front();
              if (dut.m_arvalid && !dut.m_arready) ++stalled_retirements;
            } else {
              ++outstanding.front().beat;
            }
            held_response = false;
          }
        } else {
          require(!dut.a_rvalid && !dut.b_rvalid, "response without memory validity");
        }
        if (address) {
          const unsigned owner = bf ? 1 : 0;
          const auto request = owner ? b : a;
          require(outstanding.empty(), "more than one physical burst remains outstanding");
          require(ar == std::make_tuple(request.address, request.len, request.size, 1u),
                  "selected address payload differs");
          outstanding.push_back({request, owner, issued[owner]++, 0});
          if (retirement) {
            ++handoffs; owner_changes += retiring_owner != owner;
          }
        }
        dut.clk = 1; dut.eval(); Verilated::timeInc(1); ++cycles;
      }
      require(completed == target && issued == target, "mux sequence did not complete");
      require(outstanding.empty() && !held_response, "last response did not drain");
      if (enabled) require(handoffs > 40 && stalled_retirements > 10, "retirement paths not exercised");
      if (both) require(owner_changes > 40, "owner-changing handoff not exercised");
      total_bursts += target[0] + target[1]; total_handoffs += handoffs;
      total_owner_changes += owner_changes; total_stalled_retirements += stalled_retirements;
      total_error_beats += error_beats;
      std::printf("READ_MUX_CASE mode=%u bursts=%u cycles=%llu handoffs=%llu owner_changes=%llu stalled_retirements=%llu errors=%llu\n",
                  mode, target[0] + target[1], (unsigned long long)cycles, (unsigned long long)handoffs,
                  (unsigned long long)owner_changes, (unsigned long long)stalled_retirements,
                  (unsigned long long)error_beats);
    }
    std::printf("READ_MUX_PASS cases=6 bursts=%llu handoffs=%llu owner_changes=%llu stalled_retirements=%llu errors=%llu\n",
                (unsigned long long)total_bursts, (unsigned long long)total_handoffs,
                (unsigned long long)total_owner_changes, (unsigned long long)total_stalled_retirements,
                (unsigned long long)total_error_beats);
    return 0;
  } catch (const std::exception &error) {
    std::fprintf(stderr, "READ_MUX_FAIL %s\n", error.what()); return 1;
  }
}
