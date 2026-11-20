// SPDX-License-Identifier: Apache-2.0
#include "Vaxi_write_page_guard.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr unsigned Bytes = TEST_DATA_W / 8;
static constexpr unsigned Size = Bytes == 8 ? 3 : 2;
static constexpr unsigned Outstanding = TEST_OUTSTANDING;
struct Request { uint32_t address, beats, at = 0, response = 0; };

static void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t data_at(uint32_t address) {
    uint64_t value = uint64_t(address) * 0x735f429d843c61abULL;
    return value ^ (value >> 17) ^ 0xe903d841ac62b75fULL;
}

static bool crossing(const Request &request) {
    return (request.address & 4095u) + request.beats * Bytes > 4096u;
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    try {
        bool random = false, faults = false;
        for (int index = 1; index < argc; ++index) {
            std::string option = argv[index];
            if (option == "--random") random = true;
            else if (option == "--errors") faults = true;
            else throw std::runtime_error("Unknown simulation option");
        }
        Vaxi_write_page_guard dut;
        std::mt19937 rng(18723);
        auto allow = [&]() { return !random || (rng() % 4) != 0; };
        std::vector<Request> requests;
        for (unsigned index = 0; index < 256; ++index) {
            unsigned beats = index % 17 == 0 ? 256u : 1u + rng() % 32u;
            unsigned offset = index % 4 == 0 ? 4096u - Bytes :
                              index % 4 == 1 ? 4096u - 3 * Bytes :
                              index % 4 == 2 ? 4096u - 256 * Bytes : 0x400u;
            requests.push_back({0x10000u + index * 0x2000u + offset, beats});
        }
        requests[0] = {0x10400, 64}; requests[1] = {0x12400, 16};
        requests[2] = {0x14400, 32}; requests[3] = {0x16400, 16};
        requests[4] = {0x19000u - 3 * Bytes, 8};
        requests[5] = {0x1b000u - Bytes, 1};
        requests[6] = {0x1d000u - 256 * Bytes, 256};
        requests.back() = {0xfffffff0u, 16};
        std::map<uint32_t, unsigned> write_faults;
        if (faults) {
            for (unsigned index = 4; index < requests.size(); index += 13) {
                const auto &request = requests[index];
                write_faults[request.address + Bytes * (request.beats / 2)] = 2;
                if (crossing(request)) write_faults[request.address] = 3;
            }
            write_faults[requests.back().address] = 2;
        }
        auto response_for = [&](const Request &request) {
            for (unsigned at = 0; at < request.beats; ++at) {
                auto found = write_faults.find(request.address + Bytes * at);
                if (found != write_faults.end()) return found->second;
            }
            return 0u;
        };
        std::deque<Request> physical_writes, logical_writes, logical_responses;
        for (const auto &request : requests) logical_writes.push_back(request);
        std::deque<unsigned> physical_responses;
        std::map<uint32_t, uint8_t> written, expected;
        unsigned next = 0, done = 0, physical = 0, errors = 0, max_outstanding = 0;
        unsigned cycles = 0, beats_written = 0, split_commands = 0;
        unsigned aw_stalls = 0, w_stalls = 0, b_stalls = 0;
        bool response_held = false, split_active = false;
        auto edge = [&]() { dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval(); };
        dut.rst_n = 0; dut.s_awvalid = 0; dut.s_wvalid = 0; dut.m_bvalid = 0;
        dut.s_bready = 0; dut.m_awready = 0; dut.m_wready = 0;
        dut.s_awsize = Size; dut.s_awburst = 1;
        for (unsigned count = 0; count < 5; ++count) edge();
        dut.rst_n = 1;
        while (done < requests.size()) {
            require(cycles++ < 2000000, "Write page guard timeout");
            dut.s_awvalid = next < requests.size() && logical_responses.size() < Outstanding;
            if (dut.s_awvalid) {
                dut.s_awaddr = requests[next].address;
                dut.s_awlen = requests[next].beats - 1;
            }
            dut.s_wvalid = !logical_writes.empty();
            if (dut.s_wvalid) {
                const auto &request = logical_writes.front();
                dut.s_wdata = data_at(request.address + Bytes * request.at);
                dut.s_wstrb = request.at % 7 == 0 ? 0 :
                              request.at % 5 == 0 ? 0x55u & ((1u << Bytes) - 1u) : (1u << Bytes) - 1u;
                dut.s_wlast = request.at + 1 == request.beats;
            }
            dut.m_awready = physical_writes.size() + physical_responses.size() < Outstanding && allow();
            dut.m_wready = !physical_writes.empty() && allow();
            dut.s_bready = allow();
            if (!response_held && !physical_responses.empty() && allow()) {
                dut.m_bresp = physical_responses.front();
                response_held = true;
            }
            dut.m_bvalid = response_held;
            dut.clk = 0;
            dut.eval();
            if (!split_active && dut.s_awvalid && !crossing(requests[next])) {
                require(dut.m_awvalid && dut.s_awready == dut.m_awready &&
                        dut.m_awaddr == dut.s_awaddr && dut.m_awlen == dut.s_awlen,
                        "Page-local AW propagation mismatch");
            }
            bool slave_aw = dut.s_awvalid && dut.s_awready;
            bool master_aw = dut.m_awvalid && dut.m_awready;
            bool slave_w = dut.s_wvalid && dut.s_wready;
            bool master_w = dut.m_wvalid && dut.m_wready;
            bool slave_b = dut.s_bvalid && dut.s_bready;
            bool master_b = dut.m_bvalid && dut.m_bready;
            aw_stalls += dut.m_awvalid && !dut.m_awready;
            w_stalls += dut.m_wvalid && !dut.m_wready;
            b_stalls += dut.s_bvalid && !dut.s_bready;
            if (slave_aw) {
                Request request = requests[next++];
                if (crossing(request)) {
                    require(logical_responses.empty(), "Crossing AW overtook an unfinished command");
                    split_active = true;
                    ++split_commands;
                }
                request.response = response_for(request);
                logical_responses.push_back(request);
                max_outstanding = std::max(max_outstanding, unsigned(logical_responses.size()));
            }
            if (master_aw) {
                Request request{dut.m_awaddr, uint32_t(dut.m_awlen) + 1};
                require(!crossing(request) && dut.m_awsize == Size && dut.m_awburst == 1 &&
                        !(request.address & (Bytes - 1)), "Invalid physical write address");
                request.response = response_for(request);
                physical_writes.push_back(request);
                ++physical;
            }
            require(slave_w == master_w, "Write data handshake mismatch");
            if (slave_w) {
                require(!logical_writes.empty(), "Extra logical write beat");
                auto &request = logical_writes.front();
                for (unsigned lane = 0; lane < Bytes; ++lane)
                    if (dut.s_wstrb & (1u << lane))
                        expected[request.address + Bytes * request.at + lane] =
                            uint8_t(uint64_t(dut.s_wdata) >> (8 * lane));
                if (++request.at == request.beats) logical_writes.pop_front();
            }
            if (master_w) {
                require(!physical_writes.empty(), "Write data without a physical AW");
                auto &request = physical_writes.front();
                require(bool(dut.m_wlast) == (request.at + 1 == request.beats), "Physical WLAST mismatch");
                require(dut.m_wdata == dut.s_wdata && dut.m_wstrb == dut.s_wstrb,
                        "Physical write payload mismatch");
                for (unsigned lane = 0; lane < Bytes; ++lane)
                    if (dut.m_wstrb & (1u << lane))
                        written[request.address + Bytes * request.at + lane] =
                            uint8_t(uint64_t(dut.m_wdata) >> (8 * lane));
                ++beats_written;
                if (++request.at == request.beats) {
                    physical_responses.push_back(request.response);
                    physical_writes.pop_front();
                }
            }
            if (slave_b) {
                require(!logical_responses.empty(), "Extra logical B response");
                const auto request = logical_responses.front();
                require(dut.s_bresp == request.response, "Combined BRESP order or priority mismatch");
                if (request.response) ++errors;
                if (crossing(request)) split_active = false;
                logical_responses.pop_front();
                ++done;
            }
            if (master_b) {
                require(!physical_responses.empty(), "Extra physical B response");
                physical_responses.pop_front();
                response_held = false;
            }
            dut.clk = 1;
            dut.eval();
        }
        require(written == expected, "Byte address, mask or write data mismatch");
        require(dut.idle && physical_writes.empty() && physical_responses.empty() &&
                logical_writes.empty() && logical_responses.empty(), "Write commands did not drain");
        require(max_outstanding == Outstanding && split_commands > 0, "Required concurrency or page coverage absent");
        require(faults ? errors > 0 : errors == 0, "Required response coverage absent");
        if (random) require(aw_stalls && w_stalls && b_stalls, "Required backpressure coverage absent");
        dut.s_awvalid = 0; dut.s_wvalid = 0; dut.m_bvalid = 0;
        dut.rst_n = 0; edge(); dut.rst_n = 1; edge();
        require(dut.idle, "Reset did not restore idle");
        std::cout << "WRITE_PAGE_ADDRESS_PASS commands=" << done << " physical=" << physical
                  << " beats=" << beats_written << " bytes=" << written.size() << " errors=" << errors
                  << " split=" << split_commands << " max_outstanding=" << max_outstanding
                  << " aw_stalls=" << aw_stalls << " w_stalls=" << w_stalls << " b_stalls=" << b_stalls
                  << " cycles=" << cycles << "\n";
        return 0;
    } catch (const std::exception &exception) {
        std::cerr << exception.what() << "\n";
        return 1;
    }
}
