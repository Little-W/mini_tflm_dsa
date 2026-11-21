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
#ifndef TEST_SIZE
#define TEST_SIZE 16
#endif
#ifndef TEST_CACHE_BLOCKS
#define TEST_CACHE_BLOCKS 4
#endif

#ifndef TEST_DMA_MAX_BYTES
#define TEST_DMA_MAX_BYTES (256 * BusBytes)
#endif

struct Command {
    uint32_t address, stride, rows, words, valid_cols;
    int32_t zero_point;
    unsigned slot;
    bool linear, use16, expect_error = false;
    unsigned tag = 0;
};
struct Burst { uint32_t address; unsigned words, beat = 0; uint64_t ready_cycle = 0; };
struct Address { uint32_t address; unsigned command; };
struct Output { uint64_t data; unsigned row, col, slot, valid_cols; int32_t zero_point; bool use16; unsigned tag; };

class Simulation {
    VerilatedContext context;
    Vlinear_dma_4k_top top{&context};
    std::vector<uint8_t> memory;
    std::deque<Burst> requested;
    std::deque<Address> expected_addresses;
    std::deque<std::pair<unsigned,bool>> expected_completions;
    std::deque<Output> expected_outputs;
    uint32_t random_state = 0x45c7a21u;
    bool random_delay, held = false;
    unsigned outstanding_limit;
    uint64_t cycles = 0, commands = 0, bursts = 0, beats = 0, outputs = 0, elements = 0, completions = 0;
    unsigned maximum_outstanding = 0, maximum_commands_pending = 0;
    uint64_t early_descriptor_accepts = 0, early_ar_requests = 0;
    uint64_t accept_with_finish = 0, ar_with_last_r = 0, error_completions = 0, address_stalls = 0;
    bool previous_ar_stall = false;
    uint32_t held_araddr = 0; unsigned held_arlen = 0;

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
        top.rd_linear_read_mode = command.linear;top.rd_tag=command.tag;
    }
    void expect(const Command& command) {
        ++commands;expected_completions.push_back({command.tag,command.expect_error});
        for (unsigned row = 0; row < command.rows; ++row) {
            uint32_t base = command.address + row * command.stride;
            unsigned words = command.linear ? 1 : command.words;
            uint32_t aligned = base & ~(BusBytes-1u);
            unsigned physical_words = words + unsigned((base&(BusBytes-1u)) != 0);
            for (unsigned word = 0; word < physical_words; ++word)
                expected_addresses.push_back({aligned + word*BusBytes,unsigned(commands)});
            for (unsigned word = 0; word < words; ++word) {
                unsigned col = ((command.linear ? row : word) * (command.use16 ? BusBytes/2 : BusBytes)) & (TEST_SIZE-1u);
                expected_outputs.push_back({read(base+word*BusBytes), command.linear ? 0u : row,
                                            col, command.slot, command.valid_cols ? command.valid_cols : TEST_SIZE,
                                            command.zero_point, command.use16,command.tag});
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
        require(top.rd_response_tag==e.tag,"response tag mismatch");
        require(top.rd_raw_row==e.row && top.rd_raw_col_base==e.col, "raw row/column mismatch");
        require(top.wr_row==e.row && top.wr_col_base==e.col && top.wr_slot==e.slot && top.wr_use_16bits==e.use16,
                "unpack metadata mismatch");
        for (unsigned i=0; i<BusBytes; ++i) {
            const bool valid = i < (e.use16 ? BusBytes/2 : BusBytes) && e.col+i < TEST_SIZE;
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
        for (unsigned i=0; i<8; ++i) {top.clk=0;top.eval();top.clk=1;top.eval();}
        top.clk=0;top.rst_n=1;top.eval();
    }
    bool tick(const Command* next=nullptr) {
        top.clk=0;
        if(next)set_command(*next);else top.rd_start=0;
        top.m_axi_arready=!random_delay || random()%4 != 0;
        if (!held && !requested.empty() && cycles>=requested.front().ready_cycle &&
            (!random_delay || random()%3 != 0)) {
            auto& b=requested.front();const uint32_t address=b.address+b.beat*BusBytes;
            top.m_axi_rvalid=1;top.m_axi_rdata=read(address);
            top.m_axi_rresp=uint64_t(address)+BusBytes > memory.size() ? 2 : 0;
            top.m_axi_rlast=b.beat+1==b.words;held=true;
        }
        top.eval();
        const bool accepted=top.rd_start && top.rd_start_ready;
        if(accepted){
            early_descriptor_accepts+=commands>completions+unsigned(top.rd_finish_beat);
            accept_with_finish+=top.rd_finish_beat;
            expect(*next);
        }
        if(previous_ar_stall)require(top.m_axi_arvalid && top.m_axi_araddr==held_araddr &&
                                     top.m_axi_arlen==held_arlen,"AR changed while stalled");
        previous_ar_stall=top.m_axi_arvalid && !top.m_axi_arready;
        address_stalls+=previous_ar_stall;
        held_araddr=top.m_axi_araddr;held_arlen=top.m_axi_arlen;
        const bool ar=top.m_axi_arvalid && top.m_axi_arready;
        const bool r=top.m_axi_rvalid && top.m_axi_rready;
        ar_with_last_r+=ar && r && top.m_axi_rlast;
        Burst burst{top.m_axi_araddr,unsigned(top.m_axi_arlen)+1,0,cycles+8};
        if (ar) {
            require(top.m_axi_arsize==BusSize && top.m_axi_arburst==1,"AXI request attributes");
            require(burst.words*BusBytes<=TEST_DMA_MAX_BYTES,"AXI transaction length");
            require((burst.address&(BusBytes-1u))==0,"physical AXI address alignment");
            require((burst.address&4095u)+burst.words*BusBytes<=4096,"AXI page boundary");
            require(!expected_addresses.empty(),"unexpected AXI request");
            const unsigned owner=expected_addresses.front().command;
            early_ar_requests+=owner>completions+1;
            for(unsigned word=0;word<burst.words;word++){
                require(!expected_addresses.empty(),"unexpected AXI beat");
                auto e=expected_addresses.front();expected_addresses.pop_front();
                require(burst.address+word*BusBytes==e.address && owner==e.command,"read address sequence");
            }
        }
        if(top.rd_finish_beat){
            require(!expected_completions.empty(),"unexpected finish");
            require(top.rd_finish_tag==expected_completions.front().first,"finish tag mismatch");
        }
        top.clk=1;context.timeInc(1);top.eval();++cycles;
        if(r){
            require(!requested.empty(),"response without AR");
            auto& b=requested.front();b.beat++;beats++;
            if(b.beat==b.words)requested.pop_front();
            held=false;top.m_axi_rvalid=0;
        }
        if(ar){requested.push_back(burst);bursts++;}
        maximum_outstanding=std::max(maximum_outstanding,unsigned(requested.size()));
        require(requested.size()<=outstanding_limit,"AXI outstanding limit");
        check_output();
        if(top.rd_done){
            require(!expected_completions.empty(),"unexpected descriptor completion");
            auto e=expected_completions.front();expected_completions.pop_front();
            require(top.rd_response_tag==e.first,"completion tag mismatch");
            require(bool(top.rd_error)==e.second,"descriptor error attribution");
            error_completions+=e.second;
            completions++;
        }
        maximum_commands_pending=std::max(maximum_commands_pending,unsigned(commands-completions));
        require(cycles<10000000,"simulation timeout");
        return accepted;
    }
    void run(const std::vector<Command>& stream) {
        size_t index=0;
        while(index<stream.size() || completions<commands){
            if(tick(index<stream.size()?&stream[index]:nullptr))index++;
        }
        tick();
        require(!top.rd_busy && requested.empty() && expected_outputs.empty() &&
                expected_addresses.empty() && expected_completions.empty(),"response drain incomplete");
    }
    void finish(unsigned context_depth) {
        require(commands==completions,"command/completion count");
        require(error_completions==2,"error descriptor coverage");
        if(context_depth==1)require(accept_with_finish>0,"no simultaneous descriptor completion and acceptance");
        if(random_delay)require(address_stalls>0,"no AXI address backpressure");
        if(outstanding_limit>1 && context_depth>1){
            require(early_ar_requests>0 && maximum_outstanding>1,"no overlapping logical commands");
        }
        std::printf("LINEAR_CONTEXT_PASS commands=%llu bursts=%llu beats=%llu raw_words=%llu outputs=%llu max_outstanding=%u max_contexts=%u early_accepts=%llu early_ar=%llu accept_with_finish=%llu ar_with_last_r=%llu error_completions=%llu ar_stalls=%llu random=%u cycles=%llu\n",
            (unsigned long long)commands,(unsigned long long)bursts,(unsigned long long)beats,
            (unsigned long long)outputs,(unsigned long long)elements,maximum_outstanding,maximum_commands_pending,
            (unsigned long long)early_descriptor_accepts,(unsigned long long)early_ar_requests,
            (unsigned long long)accept_with_finish,(unsigned long long)ar_with_last_r,
            (unsigned long long)error_completions,(unsigned long long)address_stalls,
            unsigned(random_delay),(unsigned long long)cycles);
        top.final();
    }
};

int main(int argc,char** argv){
    bool random=false;unsigned outstanding=4,depth=4;
    for(int i=1;i<argc;i++){
        if(std::string(argv[i])=="--random")random=true;
        else if(std::string(argv[i])=="--outstanding" && i+1<argc)outstanding=std::stoul(argv[++i]);
        else if(std::string(argv[i])=="--contexts" && i+1<argc)depth=std::stoul(argv[++i]);
        else return 2;
    }
    try{
        std::vector<Command> commands;
        for(unsigned i=0;i<64;i++)commands.push_back({0x20000u+i*256u,16,16,16/BusBytes,16,-127,i%4,false,false});
        for(unsigned offset=0;offset<BusBytes;offset++)
            for(unsigned words:{1u,2u,4u,256u})
                for(bool use16:{false,true})
                    commands.push_back({0x40ffcu+offset,words*BusBytes+3u,3,words,11,use16?-300:128,
                                        offset%4,false,use16});
        for(unsigned i=0;i<24;i++){
            commands.push_back({0x50000u+i*0x100u,16,16,16/BusBytes,16,0,i%4,false,false});
            commands.push_back({0x60000u+i*0x100u,BusBytes,1,1,7,-51,(i+1)%4,false,false});
            commands.push_back({0x70000u+i*0x100u,BusBytes,4,256,13,155,(i+2)%4,true,true});
        }
        commands.push_back({0x200000u-BusBytes,BusBytes,2,1,16,0,0,false,false,true});
        commands.push_back({0x80000u,16,16,16/BusBytes,15,-98,2,false,false});
        commands.push_back({0x200000u+8,16,3,2,13,7123,1,false,true,true});
        commands.push_back({0x90007u,29,7,3,16,-347,3,false,true});
        if (TEST_SIZE > 16) {
            // 覆盖完整生产块的行计数、列范围及全部缓存槽编号。
            for (unsigned slot=0;slot<TEST_CACHE_BLOCKS;++slot) {
                commands.push_back({0xa0000u+slot*0x1000u,TEST_SIZE+slot%BusBytes,
                    TEST_SIZE,TEST_SIZE/BusBytes,TEST_SIZE,-211,slot,false,false});
                commands.push_back({0x100ffdu+slot*0x1000u,2*TEST_SIZE+3u,
                    TEST_SIZE,2*TEST_SIZE/BusBytes,TEST_SIZE-3,617,slot,false,true});
            }
        }
        for(unsigned i=0;i<commands.size();i++)commands[i].tag=(i*5u+3u)%8;
        Simulation sim(random,outstanding,argc,argv);sim.run(commands);sim.finish(depth);return 0;
    }catch(const std::exception& e){std::fprintf(stderr,"LINEAR_CONTEXT_FAIL %s\n",e.what());return 1;}
}
