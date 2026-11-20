#include "Vvector_writeback.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <type_traits>

static constexpr unsigned kBusBytes = TEST_BUS_WIDTH / 8;
static constexpr unsigned kTile = 16;
static uint32_t rng_state = 0x6b58d213U;
static uint32_t random_value() {
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}
static void check(bool value, const char* text) {
    if (!value) throw std::runtime_error(text);
}
template <class T> static uint8_t byte_at(const T& value, unsigned lane) {
    if constexpr (std::is_integral_v<T>) return uint8_t(value >> (8 * lane));
    else return uint8_t(value[lane / 4] >> (8 * (lane % 4)));
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    Vvector_writeback top;
    uint64_t cycles = 0, requests = 0, checked_bytes = 0, beats = 0, stalled = 0, errors = 0;
    auto tick = [&]() {
        top.clk = 0; top.eval();
        top.clk = 1; top.eval();
        top.clk = 0; top.eval();
        ++cycles;
    };
    top.rst_n = 0;
    top.request_valid = 0;
    top.wr_granted = 0;
    top.src_wready = 0;
    top.wr_done = 0;
    top.wr_error = 0;
    tick(); tick();
    top.rst_n = 1;
    tick();
    for (unsigned mode = 0; mode < 2; ++mode) {
        for (unsigned offset = 0; offset < kBusBytes; ++offset) {
            for (unsigned length = 1; length <= 4 * kTile; ++length) {
                std::array<uint32_t, kTile> words;
                for (unsigned i = 0; i < kTile; ++i) {
                    words[i] = random_value();
                    top.result_words[i] = words[i];
                }
                const uint32_t address = 0x10000U + uint32_t(requests * 256U) + offset;
                const unsigned expected_beats = (offset + length + kBusBytes - 1) / kBusBytes;
                check(top.request_ready && !top.busy, "Request storage is not available");
                top.request_address = address;
                top.request_bytes = length;
                top.request_byte_output = mode;
                top.request_valid = 1;
                tick();
                top.request_valid = 0;
                top.eval();
                check(top.wr_req && top.busy && !top.request_ready, "Request state differs");
                check(top.wr_base_addr == address - offset && top.wr_row_stride == 0 &&
                      top.wr_rows_to_write == 1 && top.wr_burst_len_m1 == expected_beats - 1,
                      "Write descriptor differs from the byte range");
                for (unsigned delay = 0; delay < requests % 4; ++delay) tick();
                top.wr_granted = 1;
                top.eval();
                check(top.wr_start, "Granted request did not start");
                tick();
                top.wr_granted = 0;
                std::array<uint8_t, 4 * kTile + 2 * kBusBytes> memory;
                memory.fill(0x5a);
                unsigned accepted = 0, timeout = 0;
                bool was_stalled = false;
                uint32_t held_mask = 0;
                std::array<uint8_t, kBusBytes> held_data{};
                while (accepted < expected_beats) {
                    top.src_wready = (random_value() & 3U) != 0;
                    top.eval();
                    check(top.src_wvalid, "Write data ended before the complete range");
                    if (was_stalled) {
                        check(top.src_wmask == held_mask, "Mask changed while stalled");
                        for (unsigned lane = 0; lane < kBusBytes; ++lane)
                            check(byte_at(top.src_wdata, lane) == held_data[lane], "Data changed while stalled");
                    }
                    uint32_t expected_mask = 0;
                    for (unsigned lane = 0; lane < kBusBytes; ++lane) {
                        const unsigned position = accepted * kBusBytes + lane;
                        if (position >= offset && position < offset + length) expected_mask |= 1U << lane;
                    }
                    check(top.src_wmask == expected_mask, "Write mask differs from the requested range");
                    was_stalled = !top.src_wready;
                    held_mask = top.src_wmask;
                    for (unsigned lane = 0; lane < kBusBytes; ++lane) held_data[lane] = byte_at(top.src_wdata, lane);
                    if (top.src_wready) {
                        for (unsigned lane = 0; lane < kBusBytes; ++lane) {
                            if ((top.src_wmask >> lane) & 1U) {
                                const unsigned position = accepted * kBusBytes + lane;
                                const unsigned payload = position - offset;
                                const uint8_t expected = mode ?
                                    (payload < kTile ? uint8_t(words[payload]) : uint8_t(0)) :
                                    uint8_t(words[payload / 4] >> (8 * (payload % 4)));
                                check(held_data[lane] == expected, "Payload differs from the independent byte model");
                                memory[position] = held_data[lane];
                                ++checked_bytes;
                            }
                        }
                        ++accepted;
                        ++beats;
                    } else ++stalled;
                    tick();
                    check(++timeout < 1000, "Write data did not complete");
                }
                top.src_wready = 0;
                top.eval();
                check(!top.src_wvalid && top.busy && !top.done, "Response state differs");
                for (unsigned position = 0; position < memory.size(); ++position)
                    if (position < offset || position >= offset + length)
                        check(memory[position] == 0x5a, "Padding bytes changed");
                for (unsigned delay = 0; delay < requests % 5; ++delay) tick();
                const bool response_error = requests % 17 == 0;
                top.wr_done = 1;
                top.wr_error = response_error;
                top.eval();
                check(top.done && bool(top.error) == response_error, "Completion or error result differs");
                errors += response_error;
                tick();
                top.wr_done = 0;
                top.wr_error = 0;
                top.eval();
                check(top.request_ready && !top.busy && !top.done, "Completed request retained state");
                ++requests;
            }
        }
    }
    top.final();
    std::cout << "{\"passed\":true,\"bus_width\":" << TEST_BUS_WIDTH
              << ",\"requests\":" << requests << ",\"checked_bytes\":" << checked_bytes
              << ",\"accepted_beats\":" << beats << ",\"stalled_cycles\":" << stalled
              << ",\"error_completions\":" << errors << ",\"cycles\":" << cycles << "}\n";
}
