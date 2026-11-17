#include "Vaxi_linear_block_dma.h"
#include "verilated.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <tuple>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

struct Bench {
    Vaxi_linear_block_dma dut;
    std::deque<unsigned> bursts;
    unsigned responses = 0, aw = 0, beats = 0, enabled = 0, done = 0;
    bool held_aw = false, held_w = false;
    std::tuple<uint32_t, unsigned> saved_aw;
    std::tuple<uint32_t, unsigned, bool> saved_w;

    Bench() {
        dut.clk = 0; dut.rst_n = 0; dut.__SYM__abort = 0;
        dut.rd_start = 0; dut.rd_linear_read_mode = 0;
        dut.rd_base_addr = 0; dut.rd_row_stride = 0;
        dut.rd_rows_to_read = 0; dut.rd_valid_cols = 16;
        dut.rd_burst_len_m1 = 0; dut.rd_slot_id = 0;
        dut.rd_use_16bits = 0; dut.rd_lhs_zp = 0;
        dut.wr_start = 0; dut.wr_base_addr = 0x1000;
        dut.wr_row_stride = 16; dut.wr_rows_to_write = 8;
        dut.wr_burst_len_m1 = 3;
        dut.src_wdata = 0xa596c3f0; dut.src_wmask = 15; dut.src_wvalid = 0;
        dut.m_axi_arready = 1; dut.m_axi_rvalid = 0;
        dut.m_axi_rdata = 0; dut.m_axi_rresp = 0; dut.m_axi_rlast = 0;
        dut.m_axi_awready = 1; dut.m_axi_wready = 1;
        dut.m_axi_bvalid = 0; dut.m_axi_bresp = 0;
        for (int i = 0; i < 3; ++i) tick();
        dut.rst_n = 1;
    }

    void tick() {
        dut.clk = 0;
        dut.m_axi_bvalid = responses != 0;
        dut.eval();
        auto a = std::make_tuple(uint32_t(dut.m_axi_awaddr), unsigned(dut.m_axi_awlen));
        auto w = std::make_tuple(uint32_t(dut.m_axi_wdata), unsigned(dut.m_axi_wstrb), bool(dut.m_axi_wlast));
        if (dut.rst_n) {
            if (held_aw) require(dut.m_axi_awvalid && a == saved_aw, "AW changed while stalled");
            if (held_w) require(dut.m_axi_wvalid && w == saved_w, "W changed while stalled");
            held_aw = dut.m_axi_awvalid && !dut.m_axi_awready;
            held_w = dut.m_axi_wvalid && !dut.m_axi_wready;
            saved_aw = a; saved_w = w;
            if (dut.m_axi_bvalid && dut.m_axi_bready) {
                require(responses != 0, "B response underflow");
                --responses;
            }
            if (dut.m_axi_awvalid && dut.m_axi_awready) {
                require((dut.m_axi_awaddr & 4095u) + (unsigned(dut.m_axi_awlen) + 1u) * 4u <= 4096u,
                        "AW burst crosses a 4 KiB page");
                bursts.push_back(unsigned(dut.m_axi_awlen) + 1);
                ++aw;
            }
            if (dut.m_axi_wvalid && dut.m_axi_wready) {
                require(!bursts.empty(), "W transfer without accepted AW");
                require(bool(dut.m_axi_wlast) == (bursts.front() == 1), "Incorrect WLAST");
                if (dut.m_axi_wstrb) ++enabled;
                ++beats;
                if (--bursts.front() == 0) {
                    bursts.pop_front();
                    ++responses;
                }
            }
            done += dut.wr_done;
        }
        dut.clk = 1; dut.eval();
    }

    void start(unsigned rows = 8, bool unaligned = false, uint32_t address = 0) {
        dut.wr_rows_to_write = rows;
        dut.wr_base_addr = address ? address : unaligned ? 0x1003 : 0x1000;
        dut.wr_start = 1; tick(); dut.wr_start = 0;
    }

    void finish() {
        for (unsigned i = 0; i < 1000; ++i) {
            tick();
            if (!dut.wr_busy && done) {
                require(bursts.empty() && responses == 0, "Outstanding AXI traffic after completion");
                return;
            }
        }
        throw std::runtime_error("DMA did not complete");
    }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    unsigned cases = 0, aw = 0, beats = 0;
    try {
        for (bool unaligned : {false, true}) {
            for (unsigned scenario = 0; scenario < 4; ++scenario) {
                Bench b;
                if (scenario == 1) b.dut.m_axi_awready = 0;
                if (scenario == 2) { b.dut.m_axi_wready = 0; b.dut.src_wvalid = 1; }
                if (scenario == 3) b.dut.src_wvalid = 1;
                b.start(8, unaligned);
                for (unsigned i = 0; i < 15; ++i) b.tick();
                b.dut.__SYM__abort = 1;
                for (unsigned i = 0; i < 5; ++i) b.tick();
                b.dut.m_axi_awready = 1; b.dut.m_axi_wready = 1;
                if (scenario != 3) b.dut.src_wvalid = 0;
                b.finish();
                if (scenario < 2) require(b.enabled == 0, "Aborted stream enabled unexpected bytes");
                if (scenario == 2) require(b.enabled == 1, "Stalled original beat was not preserved exactly once");
                require(b.beats == b.aw * (unaligned ? 5u : 4u), "Accepted bursts were not completely drained");
                const unsigned previous_aw = b.aw, previous_beats = b.beats;
                b.dut.__SYM__abort = 0; b.dut.src_wvalid = 1;
                b.tick(); b.tick(); b.done = 0;
                b.start(1, false); b.finish();
                require(b.aw == previous_aw + 1 && b.beats == previous_beats + 4,
                        "Following command failed without reset");
                ++cases; aw += b.aw; beats += b.beats;
            }
        }
        for (uint32_t address : {0x1ff0u, 0x1fffu, 0x2001u}) {
            for (bool stall_data : {false, true}) {
                Bench b;
                b.dut.wr_row_stride = 2048;
                b.dut.wr_burst_len_m1 = 255;
                b.dut.src_wvalid = stall_data;
                b.dut.m_axi_wready = !stall_data;
                b.start(2, false, address);
                for (unsigned i = 0; i < 15; ++i) b.tick();
                b.dut.__SYM__abort = 1;
                for (unsigned i = 0; i < 5; ++i) b.tick();
                b.dut.m_axi_wready = 1;
                b.dut.src_wvalid = 0;
                b.finish();
                require(b.enabled == unsigned(stall_data), "Abort changed a retained write beat");
                const unsigned previous_aw = b.aw, previous_beats = b.beats;
                b.dut.__SYM__abort = 0;
                b.dut.wr_burst_len_m1 = 3;
                b.dut.src_wvalid = 1;
                b.tick(); b.tick(); b.done = 0;
                b.start(1); b.finish();
                require(b.aw == previous_aw + 1 && b.beats == previous_beats + 4,
                        "Command after segmented abort failed");
                ++cases; aw += b.aw; beats += b.beats;
            }
        }
        std::cout << "{\"passed\":true,\"cases\":" << cases
                  << ",\"accepted_aw\":" << aw << ",\"write_beats\":" << beats << "}\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
