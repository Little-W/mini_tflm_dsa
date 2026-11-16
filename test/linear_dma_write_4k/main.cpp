// SPDX-License-Identifier: Apache-2.0
#include "Vlinear_dma_write_4k_top.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

struct Command {
    std::string name;
    uint32_t address, stride;
    unsigned rows, words, mask_mode = 0;
    int error_burst = -1;
    unsigned error_response = 2;
};
struct Word { uint32_t data; uint8_t mask; };
struct PhysicalWord { uint32_t address, data; uint8_t mask; };
struct Burst { uint32_t address; unsigned words, index, beat = 0; };
struct Response { uint64_t ready_cycle; unsigned response; };

class Simulation {
    VerilatedContext context;
    Vlinear_dma_write_4k_top top{&context};
    std::vector<uint8_t> memory, expected_memory;
    std::deque<Word> source;
    std::deque<PhysicalWord> expected_addresses, expected_data;
    std::deque<Burst> writes;
    std::deque<Response> responses;
    uint32_t random_state = 0x8a0bf251u;
    bool random_delay, source_held = false, response_held = false;
    bool aw_held = false, w_held = false;
    uint32_t held_aw_address = 0, held_w_data = 0;
    unsigned held_aw_len = 0, held_w_mask = 0, held_w_last = 0;
    unsigned outstanding_limit, outstanding = 0, maximum_outstanding = 0;
    uint64_t cycles = 0, commands = 0, bursts = 0, beats = 0, source_words = 0;
    uint64_t responses_seen = 0, completions = 0, bytes_written = 0;
    uint64_t aw_stalls = 0, w_stalls = 0, source_stalls = 0;
    unsigned command_burst_index = 0, expected_bursts = 0;
    int inject_error = -1;
    unsigned error_response = 2;
    std::string current_case;

    uint32_t random() {
        random_state ^= random_state << 13;
        random_state ^= random_state >> 17;
        random_state ^= random_state << 5;
        return random_state;
    }
    void require(bool condition, const std::string& message) const {
        if (!condition) throw std::runtime_error(current_case + ": " + message +
                                                 " at cycle " + std::to_string(cycles));
    }
    static uint32_t pattern(unsigned command, unsigned row, unsigned word) {
        uint32_t x = 0x51f7a329u + command * 0x6d2b79f5u + row * 0x9e3779b9u + word;
        x ^= x >> 16;x *= 0x7feb352du;x ^= x >> 15;x *= 0x846ca68bu;x ^= x >> 16;
        return x;
    }
    void expect(const Command& command) {
        expected_memory = memory;
        expected_bursts = 0;
        for (unsigned row = 0; row < command.rows; ++row) {
            const uint32_t base = command.address + row * command.stride;
            const unsigned offset = base & 3u;
            std::vector<PhysicalWord> physical(command.words + unsigned(offset != 0));
            for (unsigned p = 0; p < physical.size(); ++p)
                physical[p] = {(base & ~3u) + p * 4, 0, 0};
            for (unsigned word = 0; word < command.words; ++word) {
                const uint32_t value = pattern(unsigned(commands), row, word);
                uint8_t mask = 15;
                if (command.mask_mode == 1) mask = uint8_t((value >> 17) & 15u);
                if (command.mask_mode == 2) mask = 0;
                if (command.mask_mode == 3 && word + 1 == command.words) mask = uint8_t((1u << (row % 3u + 1)) - 1);
                source.push_back({value, mask});
                for (unsigned byte = 0; byte < 4; ++byte) {
                    const uint32_t address = base + word * 4 + byte;
                    require(address < memory.size(), "logical output exceeds test memory");
                    const unsigned p = (offset + word * 4 + byte) / 4;
                    const unsigned lane = (offset + byte) & 3u;
                    const uint8_t datum = uint8_t(value >> (byte * 8));
                    physical[p].data |= uint32_t(datum) << (lane * 8);
                    if ((mask >> byte) & 1u) {
                        physical[p].mask |= uint8_t(1u << lane);
                        expected_memory[address] = datum;
                    }
                }
            }
            for (const auto& p : physical) {
                expected_addresses.push_back(p);expected_data.push_back(p);
            }
            unsigned remaining = unsigned(physical.size());
            uint32_t address = base & ~3u;
            while (remaining) {
                const unsigned count = std::min({remaining, 256u, (4096u - (address & 4095u)) / 4});
                require(count > 0, "empty reference segment");
                ++expected_bursts;remaining -= count;address += count * 4;
            }
        }
        inject_error = command.error_burst == -2 ? int(expected_bursts) - 1 : command.error_burst;
        require(inject_error < int(expected_bursts), "error index exceeds burst count");
        error_response = command.error_response;
    }

public:
    Simulation(bool random_delay_, unsigned limit, int argc, char** argv)
        : memory(2u * 1024u * 1024u), random_delay(random_delay_), outstanding_limit(limit) {
        context.commandArgs(argc, argv);
        for (uint32_t i = 0; i < memory.size(); ++i)
            memory[i] = uint8_t((i * 73u + (i >> 8) * 31u) ^ 0xa5u);
        top.clk = 0;top.rst_n = 0;top.wr_start = 0;
        top.src_wvalid = 0;top.src_wdata = 0;top.src_wmask = 0;
        top.m_axi_awready = 0;top.m_axi_wready = 0;top.m_axi_bvalid = 0;top.m_axi_bresp = 0;
        for (unsigned i = 0; i < 4; ++i) {top.clk = 0;top.eval();top.clk = 1;top.eval();}
        top.clk = 0;top.rst_n = 1;top.eval();
    }

    void tick() {
        top.clk = 0;
        top.m_axi_awready = !random_delay || random() % 4 != 0;
        top.m_axi_wready = !random_delay || random() % 3 != 0;
        if (!source_held && !source.empty() && (!random_delay || random() % 4 != 0)) {
            top.src_wvalid = 1;top.src_wdata = source.front().data;
            top.src_wmask = source.front().mask;source_held = true;
        }
        if (!response_held && !responses.empty() && cycles >= responses.front().ready_cycle &&
            (!random_delay || random() % 4 != 0)) {
            top.m_axi_bvalid = 1;top.m_axi_bresp = responses.front().response;response_held = true;
        }
        top.eval();
        if (aw_held) {
            require(top.m_axi_awvalid && top.m_axi_awaddr == held_aw_address &&
                    top.m_axi_awlen == held_aw_len, "AW changed under backpressure");
        }
        if (w_held) {
            require(top.m_axi_wvalid && top.m_axi_wdata == held_w_data &&
                    top.m_axi_wstrb == held_w_mask && top.m_axi_wlast == held_w_last,
                    "W changed under backpressure");
        }
        const bool aw = top.m_axi_awvalid && top.m_axi_awready;
        const bool w = top.m_axi_wvalid && top.m_axi_wready;
        const bool b = top.m_axi_bvalid && top.m_axi_bready;
        const bool s = top.src_wvalid && top.src_wready;
        aw_held = top.m_axi_awvalid && !top.m_axi_awready;
        held_aw_address = top.m_axi_awaddr;held_aw_len = top.m_axi_awlen;
        w_held = top.m_axi_wvalid && !top.m_axi_wready;
        held_w_data = top.m_axi_wdata;held_w_mask = top.m_axi_wstrb;held_w_last = top.m_axi_wlast;
        aw_stalls += aw_held;w_stalls += w_held;
        source_stalls += top.src_wvalid && !top.src_wready;

        if (aw) {
            const Burst burst{top.m_axi_awaddr, unsigned(top.m_axi_awlen) + 1, command_burst_index++};
            require(top.m_axi_awsize == 2 && top.m_axi_awburst == 1, "incorrect AW attributes");
            require((burst.address & 3u) == 0, "physical AW address is not a word boundary");
            require(burst.words <= 256, "physical burst exceeds 256 beats");
            require((burst.address & 4095u) + burst.words * 4 <= 4096, "physical burst crosses 4 KiB");
            for (unsigned word = 0; word < burst.words; ++word) {
                require(!expected_addresses.empty(), "unexpected physical write address");
                require(expected_addresses.front().address == burst.address + word * 4,
                        "physical write address sequence mismatch");
                expected_addresses.pop_front();
            }
            writes.push_back(burst);++bursts;++outstanding;
        }
        if (w) {
            require(!writes.empty(), "W accepted before its AW");
            auto& burst = writes.front();
            require(!expected_data.empty(), "unexpected W data");
            const auto expected = expected_data.front();expected_data.pop_front();
            const uint32_t address = burst.address + burst.beat * 4;
            require(address == expected.address, "W address sequence mismatch");
            require(top.m_axi_wstrb == expected.mask, "W byte mask mismatch");
            require(bool(top.m_axi_wlast) == (burst.beat + 1 == burst.words), "WLAST does not match AWLEN");
            for (unsigned lane = 0; lane < 4; ++lane) if ((top.m_axi_wstrb >> lane) & 1u) {
                const uint8_t datum = uint8_t(top.m_axi_wdata >> (lane * 8));
                require(datum == uint8_t(expected.data >> (lane * 8)), "W byte mismatch");
                memory.at(address + lane) = datum;++bytes_written;
            }
            ++burst.beat;++beats;
            if (burst.beat == burst.words) {
                const unsigned response = int(burst.index) == inject_error ? error_response : 0;
                responses.push_back({cycles + 32 + (random_delay ? random() % 19 : 0), response});
                writes.pop_front();
            }
        }
        if (b) {
            require(!responses.empty() && outstanding != 0, "unexpected B response");
            responses.pop_front();--outstanding;++responses_seen;
        }
        maximum_outstanding = std::max(maximum_outstanding, outstanding);
        require(outstanding <= outstanding_limit, "physical outstanding limit exceeded");
        if (s) {
            require(!source.empty(), "source consumed after logical row end");
            source.pop_front();++source_words;
        }

        top.clk = 1;context.timeInc(1);top.eval();++cycles;
        if (s) {source_held = false;top.src_wvalid = 0;}
        if (b) {response_held = false;top.m_axi_bvalid = 0;}
        if (top.wr_done) {
            require(outstanding == 0 && writes.empty() && responses.empty(), "completion before B responses drained");
            require(source.empty() && expected_addresses.empty() && expected_data.empty(), "completion before logical stream drained");
            ++completions;
        }
        require(cycles < 30000000, "simulation timeout");
    }

    void run(const Command& command) {
        current_case = command.name;
        require(!top.wr_busy && source.empty() && writes.empty() && responses.empty() && outstanding == 0,
                "previous command is active");
        require(!source_held && !response_held && !aw_held && !w_held, "interface retains an unfinished handshake");
        ++commands;command_burst_index = 0;expect(command);
        const uint64_t begin = cycles, previous_bursts = bursts, previous_beats = beats;
        const uint64_t previous_source = source_words, target = completions + 1;
        top.wr_start = 1;top.wr_base_addr = command.address;top.wr_row_stride = command.stride;
        top.wr_rows_to_write = command.rows;top.wr_burst_len_m1 = command.words - 1;
        tick();top.wr_start = 0;
        top.wr_base_addr = 0xdeadbeef;top.wr_row_stride = 0xffffffff;
        top.wr_rows_to_write = 0;top.wr_burst_len_m1 = 0;
        while (completions < target) {
            tick();require(cycles - begin < 1000000, "command timeout");
        }
        require(bool(top.wr_error) == (inject_error >= 0), "write error status mismatch");
        require(bursts - previous_bursts == expected_bursts, "physical segment count mismatch");
        require(source_words - previous_source == uint64_t(command.rows) * command.words,
                "source logical word count mismatch");
        require(memory == expected_memory, "complete memory image mismatch");
        tick();require(!top.wr_busy, "write engine remains busy after completion");
        std::printf("CASE name=%s cycles=%llu bursts=%llu beats=%llu source_words=%llu error=%u\n",
                    command.name.c_str(), (unsigned long long)(cycles-begin),
                    (unsigned long long)(bursts-previous_bursts), (unsigned long long)(beats-previous_beats),
                    (unsigned long long)(source_words-previous_source), unsigned(inject_error>=0));
    }

    void finish() {
        require(commands == completions, "command count mismatch");
        if (outstanding_limit > 1) require(maximum_outstanding == outstanding_limit, "outstanding capacity was not exercised");
        if (random_delay) require(aw_stalls && w_stalls, "AXI backpressure was not exercised");
        require(source_stalls != 0, "source backpressure was not exercised");
        std::printf("LINEAR_DMA_WRITE_4K_PASS commands=%llu bursts=%llu beats=%llu source_words=%llu responses=%llu "
                    "bytes_written=%llu max_outstanding=%u random=%u cycles=%llu aw_stalls=%llu w_stalls=%llu source_stalls=%llu\n",
                    (unsigned long long)commands, (unsigned long long)bursts, (unsigned long long)beats,
                    (unsigned long long)source_words, (unsigned long long)responses_seen,
                    (unsigned long long)bytes_written, maximum_outstanding, unsigned(random_delay),
                    (unsigned long long)cycles, (unsigned long long)aw_stalls,
                    (unsigned long long)w_stalls, (unsigned long long)source_stalls);
        top.final();
    }
};

int main(int argc, char** argv) {
    bool random = false, single_segment = false;unsigned outstanding = 4;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) == "--random") random = true;
        if (std::string(argv[i]) == "--single-segment") single_segment = true;
        if (std::string(argv[i]) == "--outstanding" && i + 1 < argc) outstanding = unsigned(std::stoul(argv[++i]));
    }
    try {
        Simulation simulation(random, outstanding, argc, argv);
        for (unsigned offset = 0; offset < 4; ++offset) {
            for (unsigned words : {1u, 2u, 4u, 16u, 255u}) {
                for (unsigned mask : {0u, 1u, 3u}) {
                    const auto name = "single_o" + std::to_string(offset) + "_w" + std::to_string(words) + "_m" + std::to_string(mask);
                    simulation.run({name, 0x10000u + offset, 2048u, 3u, words, mask});
                }
            }
            simulation.run({"zero_mask_o" + std::to_string(offset), 0x20000u + offset, 32u, 16u, 4u, 2u});
        }
        simulation.run({"rows_256", 0x20000u, 16u, 256u, 4u, 1u});
        simulation.run({"error_single", 0x24000u, 32u, 8u, 4u, 1u, 0});
        simulation.run({"after_error_single", 0x28000u, 32u, 16u, 4u, 0u});
        if (!single_segment) {
            for (unsigned offset = 0; offset < 4; ++offset) {
                for (unsigned words : {1u, 2u, 4u, 16u, 64u, 255u, 256u}) {
                    for (unsigned stride : {4096u, 1037u}) {
                        const auto name = "page_o" + std::to_string(offset) + "_w" + std::to_string(words) + "_s" + std::to_string(stride);
                        simulation.run({name, 0x30ffcu + offset, stride, 3u, words, 1u});
                    }
                }
                simulation.run({"max_o" + std::to_string(offset), 0x50000u + offset, 2048u, 3u, 256u, 0u});
                simulation.run({"max_page_o" + std::to_string(offset), 0x50c00u + offset, 1027u, 16u, 256u, 3u});
                simulation.run({"same_row_o" + std::to_string(offset), 0x60ffcu + offset, 0u, 4u, 256u, 1u});
            }
            for (int error : {0, 1, 3, -2}) {
                const auto name = "segmented_error_" + std::to_string(error);
                simulation.run({name, 0x70ffdu, 4097u, 3u, 256u, 1u, error, error == 1 ? 3u : 2u});
                simulation.run({name + "_recovery", 0x80ffeu, 131u, 7u, 32u, 3u});
            }
            simulation.run({"rows_256_split", 0x90fffu, 17u, 256u, 4u, 1u});
        }
        simulation.finish();return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "LINEAR_DMA_WRITE_4K_FAIL %s\n", error.what());return 1;
    }
}
