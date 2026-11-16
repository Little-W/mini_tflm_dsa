// SPDX-License-Identifier: Apache-2.0
#include "Vconv_axi_span_reader.h"
#include "verilated.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

static void require(bool value,const char *message) {
  if (!value) throw std::runtime_error(message);
}
static uint8_t value_at(uint32_t address) {
  return uint8_t(address^(address>>8)^(address>>16)^(address>>24)^0x9d);
}
struct Span { uint32_t address,bytes; };
struct Burst { uint32_t address,left,bytes,span; };

int main(int argc,char **argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Vconv_axi_span_reader dut;
    std::mt19937 rng{20261116};
    uint64_t all_bytes=0,all_handoffs=0,all_errors=0;
    unsigned cases=0;
    for (unsigned randomized=0;randomized<2;randomized++) {
      for (unsigned inject=0;inject<2;inject++) {
        std::vector<Span> spans;
        for (unsigned i=0;i<64;i++) spans.push_back({0x1000+16*i,16});
        const std::array<uint32_t,12> sizes={1,2,3,4,5,13,16,1023,1024,1025,4097,65535};
        for (unsigned i=0;i<48;i++)
          spans.push_back({0x20000+0x20000*i+4092+(i&3),sizes[i%sizes.size()]});
        spans.push_back({0xfffffff9u,7});
        dut.rst_n=0;dut.req_valid=0;dut.rsp_ready=0;dut.arready=0;dut.rvalid=0;
        for (unsigned i=0;i<3;i++) {
          dut.clk=0;dut.eval();dut.clk=1;dut.eval();Verilated::timeInc(1);
        }
        dut.rst_n=1;
        std::deque<Burst> bursts;
        std::vector<bool> injected(spans.size(),false);
        uint32_t sent=0,completed=0,received=0,issue_span=0,issued=0;
        uint64_t cycles=0,bytes=0,handoffs=0,errors=0;
        bool held=false,ar_stall=false,response_stall=false;
        std::tuple<uint32_t,uint32_t,uint32_t> old_ar;
        std::tuple<uint32_t,uint32_t,uint32_t,uint32_t,uint32_t> old_response;
        auto chance=[&]() { return !randomized || rng()%4!=0; };
        while (completed<spans.size() && cycles<3000000) {
          dut.clk=0;
          dut.req_valid=sent<spans.size();
          if (dut.req_valid) { dut.req_addr=spans[sent].address;dut.req_bytes=spans[sent].bytes; }
          dut.rsp_ready=chance();dut.arready=chance();
          if (!held && !bursts.empty() && chance()) {
            auto burst=bursts.front();uint32_t word=0;
            for (unsigned i=0;i<burst.bytes;i++)
              word|=uint32_t(value_at(burst.address+i))<<(((burst.address+i)&3)*8);
            dut.rdata=word;dut.rlast=burst.left==1;dut.rresp=0;
            if (inject && burst.span%11==0 && !injected[burst.span]) {
              dut.rresp=2;injected[burst.span]=true;
            }
            held=true;
          }
          dut.rvalid=held;dut.eval();
          auto ar=std::make_tuple(uint32_t(dut.araddr),uint32_t(dut.arlen),uint32_t(dut.arsize));
          auto response=std::make_tuple(uint32_t(dut.rsp_word_addr),uint32_t(dut.rsp_data),
                                      uint32_t(dut.rsp_strb),uint32_t(dut.rsp_last),uint32_t(dut.rsp_error));
          if (ar_stall) require(dut.arvalid && ar==old_ar,"AR payload changed under backpressure");
          if (response_stall) require(dut.rsp_valid && response==old_response,"response changed under backpressure");
          ar_stall=dut.arvalid && !dut.arready;old_ar=ar;
          response_stall=dut.rsp_valid && !dut.rsp_ready;old_response=response;
          bool request=dut.req_valid && dut.req_ready;
          bool response_fire=dut.rsp_valid && dut.rsp_ready;
          bool last=response_fire && dut.rsp_last;
          if (response_fire) {
            require(completed<sent,"response without accepted span");
            uint32_t expected=spans[completed].address+received;
            require(dut.rsp_word_addr==(expected&~3u),"incorrect response address");
            uint32_t count=0;
            for (unsigned lane=0;lane<4;lane++) if (dut.rsp_strb&(1u<<lane)) {
              require(dut.rsp_word_addr+lane==expected+count,"response skips bytes");
              require(uint8_t(dut.rsp_data>>(8*lane))==value_at(expected+count),"response data differs");
              ++count;
            }
            require(count>0 && received+count<=spans[completed].bytes,"incorrect response mask");
            received+=count;bytes+=count;
            require(bool(dut.rsp_error)==(dut.rresp!=0),"response error differs");
            errors+=dut.rsp_error;
            require(bool(dut.rsp_last)==(received==spans[completed].bytes),"incorrect span last flag");
            if (last) { ++completed;received=0; }
          }
          if (request) { ++sent;if(last)++handoffs; }
          if (dut.rvalid && dut.rready) {
            require(!bursts.empty(),"R without AR");
            auto &burst=bursts.front();burst.address+=burst.bytes;
            if (--burst.left==0) bursts.pop_front();
            held=false;
          }
          if (dut.arvalid && dut.arready) {
            require(issue_span<sent,"AR without accepted span");
            auto span=spans[issue_span];uint32_t count=dut.arlen+1,size=1u<<dut.arsize;
            require(dut.arburst==1 && (size==1 || size==4),"unsupported AR transfer");
            require(dut.araddr==span.address+issued && dut.araddr%size==0,"AR range or alignment differs");
            require(uint64_t(issued)+count*size<=span.bytes,"AR exceeds span");
            require((dut.araddr&4095)+count*size<=4096,"AR crosses a page");
            require(bursts.empty(),"more than one physical burst outstanding");
            bursts.push_back({dut.araddr,count,size,issue_span});issued+=count*size;
            if (issued==span.bytes) { ++issue_span;issued=0; }
          }
          dut.clk=1;dut.eval();Verilated::timeInc(1);++cycles;
        }
        require(completed==spans.size() && sent==completed,"span sequence did not complete");
        require(bursts.empty() && !held && !dut.busy,"last span did not drain");
        require(handoffs==spans.size()-1,"adjacent spans did not share their final response edge");
        require(errors==(inject ? 11u : 0u),"incorrect injected error count");
        all_bytes+=bytes;all_handoffs+=handoffs;all_errors+=errors;++cases;
        std::printf("SPAN_HANDOFF_CASE random=%u errors_enabled=%u spans=%zu cycles=%llu bytes=%llu handoffs=%llu errors=%llu\n",
                    randomized,inject,spans.size(),(unsigned long long)cycles,(unsigned long long)bytes,
                    (unsigned long long)handoffs,(unsigned long long)errors);
      }
    }
    std::printf("SPAN_HANDOFF_PASS cases=%u spans=452 handoffs=%llu bytes=%llu errors=%llu\n",cases,
                (unsigned long long)all_handoffs,(unsigned long long)all_bytes,(unsigned long long)all_errors);
    return 0;
  } catch (const std::exception &error) {
    std::fprintf(stderr,"SPAN_HANDOFF_FAIL %s\n",error.what());return 1;
  }
}
