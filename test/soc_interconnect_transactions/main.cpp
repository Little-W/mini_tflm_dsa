#include "Vsoc_axi_interconnect.h"
#include "verilated.h"
#include "initialize.hpp"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <vector>

#ifndef TEST_DATA_WIDTH
#define TEST_DATA_WIDTH 64
#endif
#ifndef TEST_OVERLAP
#define TEST_OVERLAP 0
#endif
#ifndef TEST_OUTSTANDING
#define TEST_OUTSTANDING 4
#endif

struct Request {
    uint32_t address;
    uint8_t length, size, burst, target;
    unsigned beat = 0, delay = 0;
};

static uint32_t random_state = 0x48bd91c7;
static uint32_t next_random() {
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}
static void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static uint32_t advance_address(const Request &request) {
    if (!request.burst) return request.address;
    const uint32_t step = uint32_t(1) << request.size;
    return (request.address & ~(step-1)) + step;
}
static uint64_t memory_data(uint32_t address, unsigned bytes) {
    uint64_t result = 0;
    for (unsigned byte = 0; byte < bytes; ++byte) {
        const uint32_t location = address + byte;
        result |= uint64_t(uint8_t(location * 73U ^ (location >> 7) ^ 0x5aU)) << (8*byte);
    }
    return result;
}
static uint8_t response(const Request &request) {
    return request.target == 4 ? 3 : ((request.address & 0x200U) ? 2 : 0);
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    Vsoc_axi_interconnect dut;
    initialize(dut);
    constexpr unsigned bytes = TEST_DATA_WIDTH/8;
    constexpr unsigned bus_size = bytes == 8 ? 3 : 2;
    unsigned long cycles=0, cpu_done=0, dma_done=0, checked_beats=0, error_beats=0;
    unsigned long backpressure_cycles=0, concurrent_cycles=0;
    try {
        for (unsigned epoch=0; epoch<4; ++epoch) {
            initialize(dut);
            dut.rst_n=0;
            for(unsigned reset_cycle=0;reset_cycle<3;++reset_cycle) {
                dut.clk=0;dut.eval();dut.clk=1;dut.eval();++cycles;
            }
            dut.rst_n=1;
            std::vector<Request> cpu, dma;
            for(unsigned index=0;index<600;++index) {
                const unsigned target=index%5;
                const uint32_t base=std::array<uint32_t,5>{0,0x10000000,0x02000000,0x20000000,0x30000000}[target];
                const uint32_t offset=(next_random() & 0xffcU) + (target==0 ? next_random()%4 : 0);
                cpu.push_back({base+offset,uint8_t(target==0 ? next_random()%8 : 0),2,
                               uint8_t(next_random()%4 != 0),uint8_t(target)});
                dma.push_back({uint32_t(0x10000+(next_random()&0x7ff8U)),uint8_t(next_random()%16),
                               uint8_t(bus_size),uint8_t(next_random()%4 != 0),0});
            }
            std::deque<Request> cpu_expected,dma_expected;
            std::array<std::deque<Request>,4> slaves;
            unsigned cpu_sent=0,dma_sent=0,epoch_cpu_done=0,epoch_dma_done=0;
            unsigned local_cycles=0;
            while(epoch_cpu_done<cpu.size() || epoch_dma_done<dma.size()) {
                require(++local_cycles<200000,"interconnect transaction timeout");
                ++cycles;
                dut.clk=0;
                dut.npu_bus_lock=(next_random()%23)==0;
                dut.s0_axi_rready=(next_random()%7)!=0;
                dut.s1_axi_rready=(next_random()%5)!=0;
                dut.s0_axi_arvalid=cpu_sent<cpu.size();
                dut.s1_axi_arvalid=dma_sent<dma.size();
                if(cpu_sent<cpu.size()) {
                    const auto &r=cpu[cpu_sent];
                    dut.s0_axi_araddr=r.address;dut.s0_axi_arlen=r.length;
                    dut.s0_axi_arsize=r.size;dut.s0_axi_arburst=r.burst;
                }
                if(dma_sent<dma.size()) {
                    const auto &r=dma[dma_sent];
                    dut.s1_axi_araddr=r.address;dut.s1_axi_arlen=r.length;
                    dut.s1_axi_arsize=r.size;dut.s1_axi_arburst=r.burst;
                }
                dut.m_ram_arready=slaves[0].size()<TEST_OUTSTANDING && (next_random()%4)!=0;
                dut.m_npu_arready=slaves[1].empty() && (next_random()%3)!=0;
                dut.m_uart_arready=slaves[2].empty() && (next_random()%4)!=0;
                dut.m_ctrl_arready=slaves[3].empty() && (next_random()%5)!=0;
                for(auto &queue:slaves) if(!queue.empty() && queue.front().delay) --queue.front().delay;
                dut.m_ram_rvalid=!slaves[0].empty() && !slaves[0].front().delay;
                dut.m_npu_rvalid=!slaves[1].empty() && !slaves[1].front().delay;
                dut.m_uart_rvalid=!slaves[2].empty() && !slaves[2].front().delay;
                dut.m_ctrl_rvalid=!slaves[3].empty() && !slaves[3].front().delay;
                if(!slaves[0].empty()) {
                    const auto &r=slaves[0].front();
                    dut.m_ram_rdata=memory_data(r.address & ~(bytes-1),bytes);
                    dut.m_ram_rresp=response(r);dut.m_ram_rlast=r.beat==r.length;
                }
                if(!slaves[1].empty()) {dut.m_npu_rdata=memory_data(slaves[1].front().address,4);dut.m_npu_rresp=response(slaves[1].front());}
                if(!slaves[2].empty()) {dut.m_uart_rdata=memory_data(slaves[2].front().address,4);dut.m_uart_rresp=response(slaves[2].front());}
                if(!slaves[3].empty()) {dut.m_ctrl_rdata=memory_data(slaves[3].front().address,4);dut.m_ctrl_rresp=response(slaves[3].front());}
                dut.eval();
                if(dut.s0_axi_arvalid && dut.s0_axi_arready) cpu_expected.push_back(cpu[cpu_sent++]);
                if(dut.s1_axi_arvalid && dut.s1_axi_arready) dma_expected.push_back(dma[dma_sent++]);
                auto check=[&](std::deque<Request> &expected,bool valid,bool ready,uint64_t data,
                               unsigned resp,bool last,bool is_cpu) {
                    if(!valid) return;
                    require(!expected.empty(),"unexpected read response");
                    auto &r=expected.front();
                    const uint64_t value=r.target==4 ? 0xdeadbeefU : memory_data(
                        r.address & ~(is_cpu ? 3U : bytes-1),is_cpu ? 4 : bytes);
                    require(data==value,"read data differs from address reference");
                    require(resp==response(r),"read response code differs");
                    require(last==(r.beat==r.length),"read last marker differs");
                    if(!ready) {++backpressure_cycles;return;}
                    ++checked_beats;if(resp)++error_beats;
                    if(last) {expected.pop_front();if(is_cpu){++cpu_done;++epoch_cpu_done;}else{++dma_done;++epoch_dma_done;}}
                    else {r.address=advance_address(r);++r.beat;}
                };
                check(cpu_expected,dut.s0_axi_rvalid,dut.s0_axi_rready,dut.s0_axi_rdata,dut.s0_axi_rresp,dut.s0_axi_rlast,true);
                check(dma_expected,dut.s1_axi_rvalid,dut.s1_axi_rready,dut.s1_axi_rdata,dut.s1_axi_rresp,dut.s1_axi_rlast,false);
                if(!cpu_expected.empty()&&!dma_expected.empty())++concurrent_cycles;
                std::array<bool,4> response_fire={bool(dut.m_ram_rvalid&&dut.m_ram_rready),bool(dut.m_npu_rvalid&&dut.m_npu_rready),
                    bool(dut.m_uart_rvalid&&dut.m_uart_rready),bool(dut.m_ctrl_rvalid&&dut.m_ctrl_rready)};
                for(unsigned slave=0;slave<4;++slave) if(response_fire[slave]) {
                    auto &r=slaves[slave].front();
                    if(r.beat==r.length)slaves[slave].pop_front();
                    else{r.address=advance_address(r);++r.beat;r.delay=next_random()%3;}
                }
                if(dut.m_ram_arvalid&&dut.m_ram_arready)slaves[0].push_back({dut.m_ram_araddr,dut.m_ram_arlen,dut.m_ram_arsize,dut.m_ram_arburst,0,0,next_random()%8});
                if(dut.m_npu_arvalid&&dut.m_npu_arready)slaves[1].push_back({0x10000000U+dut.m_npu_araddr,0,2,1,1,0,next_random()%8});
                if(dut.m_uart_arvalid&&dut.m_uart_arready)slaves[2].push_back({dut.m_uart_araddr,0,2,1,2,0,next_random()%8});
                if(dut.m_ctrl_arvalid&&dut.m_ctrl_arready)slaves[3].push_back({dut.m_ctrl_araddr,0,2,1,3,0,next_random()%8});
                dut.clk=1;dut.eval();
            }
            require(cpu_expected.empty()&&dma_expected.empty(),"read transactions remain after completion");
            for(const auto &queue:slaves)require(queue.empty(),"slave transactions remain after completion");
        }
        std::cout<<"INTERCONNECT_TRANSACTIONS_PASS {\"passed\":true,\"data_width\":"<<TEST_DATA_WIDTH
                 <<",\"overlap\":"<<TEST_OVERLAP<<",\"outstanding\":"<<TEST_OUTSTANDING
                 <<",\"cycles\":"<<cycles<<",\"cpu_transactions\":"<<cpu_done
                 <<",\"dma_transactions\":"<<dma_done<<",\"checked_beats\":"<<checked_beats
                 <<",\"error_beats\":"<<error_beats<<",\"backpressure_cycles\":"<<backpressure_cycles
                 <<",\"concurrent_cycles\":"<<concurrent_cycles<<",\"resets\":4}\n";
    } catch(const std::exception &error) {
        std::cerr<<"cycle="<<cycles<<" cpu_completed="<<cpu_done<<" dma_completed="<<dma_done
                 <<" error="<<error.what()<<"\n";
        return 1;
    }
}
