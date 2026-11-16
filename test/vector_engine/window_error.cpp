// SPDX-License-Identifier: Apache-2.0
#include "Vwindow_error_top.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

static void require(bool value, const std::string &message) {
  if (!value) throw std::runtime_error(message);
}
struct Range { uint32_t base, bytes; };
struct Burst { uint32_t address, remaining, bytes; };
using Config=std::array<uint32_t,40>;

class Simulation {
 public:
  Vwindow_error_top dut;
  std::vector<uint8_t> memory=std::vector<uint8_t>(1<<20,0x5a);
  std::vector<Range> readable_ranges;
  std::deque<Burst> reads, writes;
  unsigned responses=0;
  bool random_wait=false, rhold=false, bhold=false;
  bool ar_stalled=false, aw_stalled=false, w_stalled=false;
  std::tuple<uint32_t,uint32_t,uint32_t> old_ar,old_aw,old_w;
  std::mt19937 random{20261116};
  uint32_t output_base=0, output_bytes=32;
  uint64_t cycles=0, aw_count=0, b_count=0, written_bytes=0;

  bool available() { return !random_wait || random()%4!=0; }
  bool readable(uint32_t address) const {
    for (auto range:readable_ranges)
      if (address>=range.base && uint64_t(address)<uint64_t(range.base)+range.bytes) return true;
    return false;
  }
  bool empty() const {
    return reads.empty() && writes.empty() && !responses && !rhold && !bhold;
  }
  void tick() {
    dut.clk=0;
    dut.m_axi_arready=reads.size()<8 && available();
    dut.m_axi_awready=writes.size()<8 && available();
    dut.m_axi_wready=!writes.empty() && available();
    if (!rhold && !reads.empty() && available()) {
      auto burst=reads.front(); uint32_t word=0;
      for (unsigned i=0;i<burst.bytes;i++)
        word|=uint32_t(memory.at(burst.address+i))<<(((burst.address+i)&3)*8);
      dut.m_axi_rdata=word; dut.m_axi_rresp=0;
      dut.m_axi_rlast=burst.remaining==1; rhold=true;
    }
    dut.m_axi_rvalid=rhold;
    if (!bhold && responses && available()) { dut.m_axi_bresp=0; bhold=true; }
    dut.m_axi_bvalid=bhold;
    dut.eval();
    auto ar=std::make_tuple(uint32_t(dut.m_axi_araddr),uint32_t(dut.m_axi_arlen),uint32_t(dut.m_axi_arsize));
    auto aw=std::make_tuple(uint32_t(dut.m_axi_awaddr),uint32_t(dut.m_axi_awlen),uint32_t(dut.m_axi_awsize));
    auto wd=std::make_tuple(uint32_t(dut.m_axi_wdata),uint32_t(dut.m_axi_wstrb),uint32_t(dut.m_axi_wlast));
    if (dut.rst_n) {
      if (ar_stalled) require(dut.m_axi_arvalid && ar==old_ar,"AR changed under backpressure");
      if (aw_stalled) require(dut.m_axi_awvalid && aw==old_aw,"AW changed under backpressure");
      if (w_stalled) require(dut.m_axi_wvalid && wd==old_w,"W changed under backpressure");
    }
    ar_stalled=dut.m_axi_arvalid && !dut.m_axi_arready; old_ar=ar;
    aw_stalled=dut.m_axi_awvalid && !dut.m_axi_awready; old_aw=aw;
    w_stalled=dut.m_axi_wvalid && !dut.m_axi_wready; old_w=wd;
    if (dut.m_axi_rvalid && dut.m_axi_rready) {
      require(!reads.empty(),"R without AR");
      auto &burst=reads.front(); burst.address+=burst.bytes;
      if (--burst.remaining==0) reads.pop_front();
      rhold=false;
    }
    if (dut.m_axi_bvalid && dut.m_axi_bready) { --responses; bhold=false; ++b_count; }
    if (dut.m_axi_arvalid && dut.m_axi_arready) {
      uint32_t address=dut.m_axi_araddr, count=dut.m_axi_arlen+1, bytes=1u<<dut.m_axi_arsize;
      require(dut.m_axi_arburst==1 && bytes<=4 && address%bytes==0,"invalid read descriptor");
      require((address&4095)+count*bytes<=4096,"AR crosses 4 KiB");
      for (uint32_t i=0;i<count*bytes;i++) require(readable(address+i),"read outside input or parameters");
      reads.push_back({address,count,bytes});
    }
    if (dut.m_axi_awvalid && dut.m_axi_awready) {
      uint32_t address=dut.m_axi_awaddr, count=dut.m_axi_awlen+1, bytes=1u<<dut.m_axi_awsize;
      require(dut.m_axi_awburst==1 && bytes==4 && address%4==0,"invalid write descriptor");
      require((address&4095)+count*bytes<=4096,"AW crosses 4 KiB");
      writes.push_back({address,count,bytes}); ++aw_count;
    }
    if (dut.m_axi_wvalid && dut.m_axi_wready) {
      require(!writes.empty(),"W without AW"); auto &burst=writes.front();
      require(bool(dut.m_axi_wlast)==(burst.remaining==1),"incorrect WLAST");
      for (unsigned i=0;i<4;i++) if (dut.m_axi_wstrb&(1u<<i)) {
        uint32_t address=burst.address+i;
        require(address>=output_base && uint64_t(address)<uint64_t(output_base)+output_bytes,"write outside output");
        memory.at(address)=uint8_t(dut.m_axi_wdata>>(8*i)); ++written_bytes;
      }
      burst.address+=4;
      if (--burst.remaining==0) { writes.pop_front(); ++responses; }
    }
    dut.clk=1; dut.eval(); Verilated::timeInc(1); ++cycles;
    dut.clk=0; dut.eval();
  }
  Simulation() {
    dut.rst_n=0; dut.start=0; dut.done_ready=0; dut.inject_fault=0;
    for (unsigned i=0;i<40;i++) dut.config_words[i]=0;
    for (unsigned i=0;i<4;i++) tick();
    dut.rst_n=1; tick();
  }
  void store32(uint32_t address,int32_t value) {
    for (unsigned i=0;i<4;i++) memory.at(address+i)=uint8_t(uint32_t(value)>>(8*i));
  }
  void execute(const Config &config,bool fault) {
    require(dut.ready && empty(),"task begins before idle");
    auto start_aw=aw_count, start_b=b_count, start_bytes=written_bytes, start_cycles=cycles;
    for (unsigned i=0;i<40;i++) dut.config_words[i]=config[i];
    dut.inject_fault=fault; dut.start=1; tick(); dut.start=0;
    while (!dut.done_valid && cycles-start_cycles<100000) tick();
    require(dut.done_valid,"task did not complete");
    require(dut.error==(fault ? 2 : 0),"unexpected task status");
    require(dut.injected_errors==(fault ? 1u : 0u),"terminal error was not scheduled exactly once");
    require(dut.write_launches_in_failed==(fault ? 1u : 0u),"write launch did not exercise FAILED");
    require(dut.window_requests==2 && dut.window_completions==2,"window descriptors did not drain");
    require(empty() && dut.dma_idle && dut.write_idle,"completion before AXI drain");
    require(aw_count-start_aw==b_count-start_b,"write responses did not drain");
    require(written_bytes-start_bytes==(fault ? 16u : 32u),"unexpected output byte count");
    for (unsigned i=0;i<32;i++) {
      require(!dut.m_axi_arvalid && !dut.m_axi_awvalid && !dut.m_axi_wvalid,"transaction after completion");
      tick();
      require(dut.done_valid && dut.error==(fault ? 2 : 0) && empty(),"completion did not remain idle");
    }
    dut.done_ready=1; tick(); dut.done_ready=0; dut.inject_fault=0; tick();
    require(dut.ready && empty(),"engine did not return to idle");
  }
};

static int8_t quantize(int32_t value) {
  uint32_t magnitude=value<0 ? uint32_t(-int64_t(value)) : uint32_t(value);
  uint32_t rounded=magnitude>>5, remainder=magnitude&31;
  if (remainder>16 || (remainder==16 && (rounded&1))) ++rounded;
  int32_t result=value<0 ? -int32_t(rounded) : int32_t(rounded);
  return int8_t(std::max(-128,std::min(127,result)));
}

int main(int argc,char **argv) {
  Verilated::commandArgs(argc,argv);
  try {
    unsigned cases=0;
    Simulation simulation;
    for (unsigned random_wait=0;random_wait<2;random_wait++) {
      simulation.random_wait=random_wait;
      for (unsigned offset=0;offset<4;offset++) {
        Config config{};
        config[0]=0; config[2]=0x1ffb; config[3]=0x10003; config[4]=0x60ffc+offset;
        config[5]=0x20000; config[6]=0x30000; config[7]=0x40000;
        config[9]=uint32_t(-128); config[10]=127;
        config[11]=config[14]=config[15]=config[16]=1;
        config[12]=config[17]=2; config[13]=16;
        config[18]=config[19]=config[20]=config[21]=1;
        simulation.output_base=config[4];
        simulation.readable_ranges={{config[2],32},{config[3],16},{config[5],64},{config[6],64},{config[7],64}};
        std::fill(simulation.memory.begin(),simulation.memory.end(),0x5a);
        std::array<int8_t,32> expected_output{};
        for (unsigned channel=0;channel<16;channel++) {
          int8_t weight=int(channel%9)-4;
          simulation.memory[config[3]+channel]=uint8_t(weight);
          int32_t bias=int32_t(channel*7)-40;
          simulation.store32(config[5]+4*channel,bias);
          simulation.store32(config[6]+4*channel,0x40000000);
          simulation.store32(config[7]+4*channel,-4);
          for (unsigned position=0;position<2;position++) {
            int8_t input=int((position*16+channel)%43)-21;
            simulation.memory[config[2]+position*16+channel]=uint8_t(input);
            expected_output[position*16+channel]=quantize(int32_t(input)*weight+bias);
          }
        }
        auto expected=simulation.memory;
        for (unsigned i=0;i<16;i++) expected[config[4]+i]=uint8_t(expected_output[i]);
        simulation.execute(config,true);
        require(simulation.memory==expected,"error task altered an unexpected byte");
        ++cases;
        for (unsigned i=0;i<32;i++) expected[config[4]+i]=uint8_t(expected_output[i]);
        simulation.execute(config,false);
        require(simulation.memory==expected,"recovery task output or surrounding memory differs");
        ++cases;
        std::printf("CASE offset=%u random=%u fault_and_recovery=pass\n",offset,random_wait);
      }
    }
    std::printf("WINDOW_ERROR_PASS cases=%u injected_errors=8 recovery_tasks=8\n",cases);
    return 0;
  } catch (const std::exception &error) {
    std::fprintf(stderr,"WINDOW_ERROR_FAIL %s\n",error.what());
    return 1;
  }
}
