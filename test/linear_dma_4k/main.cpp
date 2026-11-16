// SPDX-License-Identifier: Apache-2.0
#include "Vlinear_dma_4k_top.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef TEST_BUS_WIDTH
#define TEST_BUS_WIDTH 32
#endif
constexpr unsigned BusBytes = TEST_BUS_WIDTH / 8;
constexpr unsigned BusSize = TEST_BUS_WIDTH == 64 ? 3 : 2;

#ifndef TEST_DMA_MAX_BYTES
#define TEST_DMA_MAX_BYTES (256 * BusBytes)
#endif

struct Command {
    uint32_t address, stride, rows, words, valid_cols;
    int32_t zero_point;
    unsigned slot;
    bool linear, use16, expect_error = false;
};
struct Burst { uint32_t address; unsigned words, beat = 0; };
struct Output { uint64_t data; unsigned row, col, slot, valid_cols; int32_t zero_point; bool use16; };

class Simulation {
    VerilatedContext context;
    Vlinear_dma_4k_top top{&context};
    std::vector<uint8_t> memory;
    std::deque<Burst> requested;
    std::deque<uint32_t> expected_addresses;
    std::deque<Output> expected_outputs;
    uint32_t random_state = 0x45c7a21u;
    bool random_delay, held = false;
    unsigned outstanding_limit;
    uint64_t cycles = 0, commands = 0, bursts = 0, beats = 0, outputs = 0, elements = 0, completions = 0;
    unsigned maximum_outstanding = 0;

    uint32_t random() {
        random_state ^= random_state << 13;random_state ^= random_state >> 17;
        random_state ^= random_state << 5;return random_state;
    }
    void require(bool condition, const char* message) const {
        if (!condition) throw std::runtime_error(std::string(message) + " at cycle " + std::to_string(cycles));
    }
    uint64_t read(uint32_t address) const {
        uint64_t value = 0;
        for (unsigned i = 0; i < BusBytes; ++i)
            if (uint64_t(address) + i < memory.size()) value |= uint64_t(memory[address+i]) << (8*i);
        return value;
    }
    void set_command(const Command& command) {
        top.rd_start = 1;top.rd_base_addr = command.address;top.rd_row_stride = command.stride;
        top.rd_rows_to_read = command.rows;top.rd_valid_cols = command.valid_cols;
        top.rd_burst_len_m1 = command.words-1;top.rd_slot_id = command.slot;
        top.rd_use_16bits = command.use16;top.rd_lhs_zp = command.zero_point;
        top.rd_linear_read_mode = command.linear;
    }
    void expect(const Command& command) {
        ++commands;
        for (unsigned row = 0; row < command.rows; ++row) {
            uint32_t base = command.address + row * command.stride;
            unsigned words = command.linear ? 1 : command.words;
            uint32_t aligned = base & ~(BusBytes-1u);
            unsigned physical_words = words + unsigned((base&(BusBytes-1u)) != 0);
            for (unsigned word = 0; word < physical_words; ++word)
                expected_addresses.push_back(aligned + word*BusBytes);
            for (unsigned word = 0; word < words; ++word) {
                unsigned col = ((command.linear ? row : word) * (command.use16 ? BusBytes/2 : BusBytes)) & 15u;
                expected_outputs.push_back({read(base+word*BusBytes), command.linear ? 0u : row,
                                            col, command.slot, command.valid_cols ? command.valid_cols : 16,
                                            command.zero_point, command.use16});
            }
        }
    }
    void check_output() {
        if (!top.rd_raw_valid) {
            for (unsigned i=0; i<BusBytes; ++i) require(!top.wr_valid[i], "unpack valid without raw data");
            return;
        }
        require(!expected_outputs.empty(), "unexpected read output");
        const auto e = expected_outputs.front();expected_outputs.pop_front();++outputs;
        if (top.rd_raw_data != e.data) {
            std::fprintf(stderr, "raw actual=%016llx expected=%016llx row=%u col=%u\n",(unsigned long long)top.rd_raw_data,(unsigned long long)e.data,e.row,e.col);
            require(false, "raw read data mismatch");
        }
        require(top.rd_raw_row==e.row && top.rd_raw_col_base==e.col, "raw row/column mismatch");
        require(top.wr_row==e.row && top.wr_col_base==e.col && top.wr_slot==e.slot && top.wr_use_16bits==e.use16,
                "unpack metadata mismatch");
        for (unsigned i=0; i<BusBytes; ++i) {
            const bool valid = i < (e.use16 ? BusBytes/2 : BusBytes) && e.col+i < 16;
            require(bool(top.wr_valid[i])==valid, "unpack lane validity mismatch");
            if (!valid) continue;
            ++elements;
            int32_t value = 0;
            if (e.col+i < e.valid_cols) {
                value = e.use16 ? int32_t(int16_t(e.data >> (16*i))) : int32_t(int8_t(e.data >> (8*i)));
                value += e.zero_point;
            }
            require(uint16_t(top.wr_data[i])==uint16_t(value), "unpacked signed value mismatch");
        }
    }

public:
    Simulation(bool random_delay_, unsigned outstanding, int argc, char** argv) : memory(2u*1024*1024),
        random_delay(random_delay_), outstanding_limit(outstanding) {
        context.commandArgs(argc,argv);
        for (uint32_t i=0; i<memory.size(); ++i) memory[i]=uint8_t((i*73u+(i>>8)*31u)^0xa5u);
        top.clk=0;top.rst_n=0;top.rd_start=0;top.m_axi_arready=0;top.m_axi_rvalid=0;
        top.m_axi_rdata=0;top.m_axi_rresp=0;top.m_axi_rlast=0;
        for (unsigned i=0; i<BusBytes; ++i) {top.clk=0;top.eval();top.clk=1;top.eval();}
        top.clk=0;top.rst_n=1;top.eval();
    }
    bool tick(const Command* chain=nullptr) {
        top.clk=0;
        top.m_axi_arready=!random_delay || random()%4 != 0;
        if (!held && !requested.empty() && (!random_delay || random()%3 != 0)) {
            auto& b=requested.front();const uint32_t address=b.address+b.beat*BusBytes;
            top.m_axi_rvalid=1;top.m_axi_rdata=read(address);
            top.m_axi_rresp=uint64_t(address)+BusBytes > memory.size() ? 2 : 0;
            top.m_axi_rlast=b.beat+1==b.words;held=true;
        }
        top.eval();
        bool chained=false;
        if (chain && top.rd_finish_beat) {
            set_command(*chain);expect(*chain);chained=true;top.eval();
        }
        if (top.rd_start) require(top.rd_start_ready, "descriptor was not accepted");
        const bool ar=top.m_axi_arvalid && top.m_axi_arready;
        const bool r=top.m_axi_rvalid && top.m_axi_rready;
        Burst accepted{top.m_axi_araddr,unsigned(top.m_axi_arlen)+1};
        if (ar) {
            require(top.m_axi_arsize==BusSize && top.m_axi_arburst==1, "unexpected AXI request attributes");
            require(accepted.words*BusBytes<=TEST_DMA_MAX_BYTES, "AXI read exceeds configured byte limit");
            require((accepted.address&(BusBytes-1u))==0, "unaligned physical AXI request");
            require((accepted.address&4095u)+accepted.words*BusBytes<=4096, "AXI burst crosses 4 KiB");
            for (unsigned word=0; word<accepted.words; ++word) {
                require(!expected_addresses.empty(), "unexpected AXI request");
                const auto address=expected_addresses.front();expected_addresses.pop_front();
                require(accepted.address+word*BusBytes==address, "AXI read address mismatch");
            }
        }
        top.clk=1;context.timeInc(1);top.eval();++cycles;
        if (r) {
            require(!requested.empty(), "AXI response without accepted address");
            auto& b=requested.front();++b.beat;++beats;
            if (b.beat==b.words) requested.pop_front();
            held=false;top.m_axi_rvalid=0;
        }
        if (ar) {requested.push_back(accepted);++bursts;}
        maximum_outstanding=std::max(maximum_outstanding,unsigned(requested.size()));
        require(requested.size()<=outstanding_limit, "outstanding limit exceeded");
        check_output();
        if (top.rd_done) ++completions;
        require(cycles<10000000, "simulation timeout");
        return chained;
    }
    void run(const Command& command, unsigned expected_bursts=0) {
        require(!top.rd_busy && requested.empty() && expected_outputs.empty() && expected_addresses.empty(),
                "previous command still active");
        const auto target=completions+1;
        const auto start_bursts=bursts;
        set_command(command);expect(command);tick();top.rd_start=0;
        while (completions<target) tick();
        require(!top.rd_busy && requested.empty() && expected_addresses.empty() && expected_outputs.empty(),
                "completion before descriptor drained");
        if (expected_bursts) require(bursts-start_bursts==expected_bursts, "unexpected contiguous read burst count");
        require(bool(top.rd_error)==command.expect_error, "incorrect read error status");
        tick();
    }
    void run_chained(const Command& first, const Command& second) {
        const auto target=completions+2;
        set_command(first);expect(first);tick();top.rd_start=0;
        bool chained=false;
        while (completions<target) {
            if (tick(chained ? nullptr : &second)) chained=true;
            top.rd_start=0;
        }
        require(chained && !top.rd_busy && requested.empty() && expected_addresses.empty() && expected_outputs.empty(),
                "back-to-back command did not drain");
        require(!top.rd_error, "unexpected chained read error");tick();
    }
    void finish() {
        require(commands==completions, "command/completion mismatch");
        if (outstanding_limit>1) require(maximum_outstanding>1, "no concurrent AXI reads exercised");
        std::printf("LINEAR_DMA_4K_PASS commands=%llu bursts=%llu beats=%llu raw_words=%llu outputs=%llu max_outstanding=%u random=%u cycles=%llu\n",
            (unsigned long long)commands,(unsigned long long)bursts,(unsigned long long)beats,
            (unsigned long long)outputs,(unsigned long long)elements,maximum_outstanding,
            unsigned(random_delay),(unsigned long long)cycles);
        top.final();
    }
};

int main(int argc, char** argv) {
    bool random=false;unsigned outstanding=4;
    for (int i=1; i<argc; ++i) {
        if (std::string(argv[i])=="--random") random=true;
        else if (std::string(argv[i])=="--outstanding" && i+1<argc) outstanding=std::stoul(argv[++i]);
        else return 2;
    }
    try {
        Simulation sim(random,outstanding,argc,argv);
        // The FC weights have 64 output channels and a 784-byte row stride.
        for (unsigned output=0; output<64; output+=16)
            for (unsigned k=0; k<784; k+=16)
                sim.run({0x1007b4u+output*784u+k,784,16,16/BusBytes,16,-127,output/16,false,false});
        for (unsigned offset=0; offset<BusBytes; ++offset)
            for (unsigned words : {1u,2u,4u,8u,256u})
                for (bool use16 : {false,true})
                    sim.run({0x20ffcu+offset,words*BusBytes+3u,3,words,11, use16 ? -300 : 128,
                             offset%4,false,use16});
        for (unsigned offset=0; offset<BusBytes; ++offset)
            for (unsigned stride : {4u,7u,784u})
                for (bool use16 : {false,true})
                    sim.run({0x30ffcu+offset,stride,16,256,13, use16 ? 1234 : -91,
                             offset%4,true,use16});
        sim.run({0x200000u-BusBytes,BusBytes,2,1,16,0,0,false,false,true},2);
        for (unsigned words : {1u,4u,8u,16u})
            for (bool linear : {false,true})
                for (bool use16 : {false,true}) {
                    const unsigned row_words=linear ? 1u : words;
                    sim.run({0x12340u,row_words*BusBytes,16,words,0,0,1,linear,use16},
                        (row_words*BusBytes*16u+TEST_DMA_MAX_BYTES-1u)/TEST_DMA_MAX_BYTES);
                    sim.run({0x13000u-BusBytes,row_words*BusBytes,16,words,11,37,2,linear,use16},
                        1u+(row_words*BusBytes*16u-BusBytes+TEST_DMA_MAX_BYTES-1u)/TEST_DMA_MAX_BYTES);
                }
        sim.run_chained({0x40fffu,8,1,4,7,-128,3,false,false},
                        {0x51ffdu,15,3,8,13,12345,1,false,true});
        sim.run_chained({0x60fe0u,16,16,4,16,-13,0,false,false},
                        {0x71ffdu,15,3,8,13,12345,1,false,true});
        sim.run_chained({0x80fffu,8,1,4,7,-128,3,false,false},
                        {0x91fe0u,32,16,8,15,-94,2,false,true});
        sim.finish();return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr,"LINEAR_DMA_4K_FAIL %s\n",error.what());return 1;
    }
}
