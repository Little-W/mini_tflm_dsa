// SPDX-License-Identifier: Apache-2.0
#include "Vwindow_dma_top.h"
#include "verilated.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <random>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#ifndef WINDOW_RESPONSE_INTERVAL
#define WINDOW_RESPONSE_INTERVAL 3
#endif
#ifndef WINDOW_DESCRIPTOR_RESPONSE_INTERVAL
#define WINDOW_DESCRIPTOR_RESPONSE_INTERVAL 3
#endif
#ifndef WINDOW_SINGLE_RESPONSE_INTERVAL
#define WINDOW_SINGLE_RESPONSE_INTERVAL 1
#endif

static void check(bool value,const std::string& message) {
  if(!value) throw std::runtime_error(message);
}
struct Request {uint32_t p,q,cols,tag;bool error=false;};
struct Expected {Request request;std::vector<int16_t> values;unsigned received=0;};
struct Read {uint32_t address,left,size;};
class Simulation {
 public:
  Vwindow_dma_top top;
  std::array<uint32_t,16> config{};
  std::vector<uint8_t> memory=std::vector<uint8_t>(1<<20);
  std::deque<Read> reads;
  std::deque<Expected> expected;
  std::mt19937 random{11202026};
  std::vector<uint64_t> response_cycles;
  std::ofstream window_trace;
  bool trace_enabled=false;
  uint64_t cycle=0,accepted=0,completed=0,elements=0,error_responses=0,cancelled=0;
  uint64_t ordinary_completed=0,ordinary_words=0;
  bool random_memory=false,read_hold=false,inject_error=false,error_used=false,response_stalled=false;
  bool block_ar=false,configure_at_burst_boundary=false;
  uint64_t configuration_boundaries=0;
  std::array<uint32_t,9> held_response{};

  std::vector<int16_t> reference(const Request& request) const {
    std::vector<int16_t> result;
    for(unsigned col=0;col<request.cols;col++) {
      uint32_t q=request.q+col,channel=q%config[3],tap=q/config[3];
      int64_t y=int64_t(request.p/config[7])*config[8]-config[10]+tap/config[5];
      int64_t x=int64_t(request.p%config[7])*config[9]-config[11]+tap%config[5];
      int16_t value=0;
      if(q<config[4]*config[5]*config[3] && y>=0 && x>=0 && y<config[1] && x<config[2]) {
        const unsigned element_bytes=(config[15]&2)?2:1;
        const size_t address=config[0]+((y*config[2]+x)*config[3]+channel)*element_bytes;
        if(element_bytes==2)
          value=int16_t(uint16_t(memory.at(address))|(uint16_t(memory.at(address+1))<<8));
        else value=int16_t(int8_t(memory.at(address)))+int32_t(config[12]);
      }
      result.push_back(value);
    }
    return result;
  }
  std::array<uint32_t,9> response() const {
    return {top.rsp_tag,top.rsp_col,top.rsp_mask,top.rsp_last,top.rsp_error,
            top.rsp_data[0],top.rsp_data[1],top.rsp_data[2],top.rsp_data[3]};
  }
  bool tick(const Request* request=nullptr) {
    top.clk=0;
    top.arready=!block_ar && reads.size()<8 && (!random_memory || random()%4!=0);
    if(!read_hold && !reads.empty() && (!random_memory || random()%3!=0)) {
      auto r=reads.front();uint32_t word=0;
      for(unsigned i=0;i<r.size;i++) word|=uint32_t(memory.at(r.address+i))<<(((r.address+i)&3)*8);
      top.rdata=word;top.rlast=r.left==1;top.rresp=0;
      if(inject_error && !error_used) {top.rresp=2;error_used=true;}
      read_hold=true;
    }
    top.rvalid=read_hold;top.eval();
    if(configure_at_burst_boundary && top.rvalid && top.rready && top.rlast && expected.size()>1) {
      bool address_transfer=top.arvalid && top.arready;
      top.cfg_valid=1;top.eval();
      check(!top.cfg_ready && top.read_busy,"configuration accepted with queued window descriptors");
      check(top.rvalid && top.rready && top.rlast && bool(top.arvalid && top.arready)==address_transfer,
            "pending configuration changed the active memory transfer");
      configure_at_burst_boundary=false;configuration_boundaries++;
    }
    if(top.rst_n && top.cfg_valid && (!expected.empty() || !reads.empty() || read_hold))
      check(!top.cfg_ready && top.read_busy,"configuration accepted before read-side drain");
    if(top.rst_n && response_stalled)
      check(top.rsp_valid && response()==held_response,"response changed under backpressure");
    response_stalled=top.rsp_valid && !top.rsp_ready;held_response=response();
    bool request_fire=top.req_valid && top.req_ready;
    if(trace_enabled && window_trace.is_open()) {
      window_trace<<cycle<<','<<unsigned(top.req_valid)<<','<<unsigned(top.req_ready)
        <<','<<top.req_p0<<','<<top.req_q0<<','<<top.req_cols<<','<<unsigned(top.req_tag)
        <<','<<unsigned(top.rsp_valid)<<','<<unsigned(top.rsp_ready);
      if(top.rsp_valid) {
        for(auto value:response()) window_trace<<','<<value;
      } else {
        for(unsigned i=0;i<9;i++) window_trace<<",0";
      }
      window_trace<<','<<unsigned(top.arvalid)<<','<<unsigned(top.arready);
      if(top.arvalid) window_trace<<','<<top.araddr<<','<<unsigned(top.arlen)<<','<<unsigned(top.arsize);
      else window_trace<<",0,0,0";
      window_trace<<','<<unsigned(top.rvalid)<<','<<unsigned(top.rready);
      if(top.rvalid) window_trace<<','<<top.rdata<<','<<unsigned(top.rresp)<<','<<unsigned(top.rlast);
      else window_trace<<",0,0,0";
      window_trace<<','<<unsigned(top.busy)<<','<<unsigned(top.read_busy)<<'\n';
    }
    if(top.rst_n && request_fire) {
      check(request!=nullptr,"request without reference");
      expected.push_back({*request,reference(*request),0});accepted++;
    }
    if(top.rst_n && top.rsp_valid && top.rsp_ready) {
      check(!expected.empty(),"response without accepted request");
      auto& e=expected.front();check(top.rsp_tag==e.request.tag,"response tag/order mismatch");
      if(top.rsp_error) {
        check(e.request.error && top.rsp_last && top.rsp_mask==0,"invalid terminal error");
        error_responses++;
      } else {
        check(!e.request.error,"response data after expected terminal error");
        check(top.rsp_col==e.received,"response column/order mismatch");
        unsigned count=0;
        for(unsigned lane=0;lane<4;lane++) if(top.rsp_mask&(1u<<lane)) {
          check(e.received<e.values.size(),"excess response elements");
          check(int16_t(top.rsp_data[lane])==e.values[e.received],"window arithmetic mismatch");
          e.received++;count++;elements++;
        }
        check(count>0 && top.rsp_mask==((1u<<count)-1),"invalid response mask");
        check(bool(top.rsp_last)==(e.received==e.values.size()),"response last marker mismatch");
        response_cycles.push_back(cycle);
      }
      if(top.rsp_last) {expected.pop_front();completed++;}
    }
    if(top.rst_n && top.ordinary_raw_valid) {
      uint32_t value=0;
      for(unsigned i=0;i<4;i++) value|=uint32_t(memory.at(config[0]+64+(ordinary_words%4)*4+i))<<(i*8);
      check(top.ordinary_raw_data==value,"ordinary read data mismatch word="+std::to_string(ordinary_words)+" actual="+std::to_string(top.ordinary_raw_data)+" expected="+std::to_string(value)+" cycle="+std::to_string(cycle));ordinary_words++;
    }
    if(top.rst_n && top.ordinary_done) {
      check(!top.ordinary_error && ordinary_words==(ordinary_completed+1)*4,"ordinary read completion mismatch");
      ordinary_completed++;
    }
    bool rh=top.rvalid && top.rready,arh=top.arvalid && top.arready;
    if(rh) {auto& r=reads.front();r.address+=r.size;if(--r.left==0) reads.pop_front();read_hold=false;}
    if(arh) {
      uint32_t a=top.araddr,n=top.arlen+1,size=1u<<top.arsize;
      check(size<=4 && a%size==0 && (a&4095)+n*size<=4096,"invalid AXI read transfer");
      check(a>=config[0] && uint64_t(a)+n*size<=uint64_t(config[0])+uint64_t(config[1])*config[2]*config[3]*((config[15]&2)?2:1),"AXI read outside input");
      reads.push_back({a,n,size});
    }
    top.clk=1;top.eval();Verilated::timeInc(1);cycle++;top.clk=0;top.eval();
    return request_fire;
  }
  void reset() {
    cancelled+=expected.size();expected.clear();reads.clear();read_hold=false;response_stalled=false;
    block_ar=false;configure_at_burst_boundary=false;
    top.i_abort=0;top.ordinary_req=0;top.ordinary_start=0;top.req_valid=0;top.cfg_valid=0;top.rsp_ready=1;top.rst_n=0;top.rvalid=0;
    for(int i=0;i<4;i++) tick();top.rst_n=1;tick();
    check(!top.rsp_valid && !top.busy,"reset retained a window response");
  }
  Simulation() {
    for(size_t i=0;i<memory.size();i++) memory[i]=uint8_t((i*17+(i>>8)*29)&255);
    reset();
  }
  void configure(std::array<uint32_t,16> value) {
    check(expected.empty() && !top.busy,"configuration before request drain");
    for(unsigned i=0;!top.cfg_ready && i<100000;i++) tick();
    check(top.cfg_ready && reads.empty() && !read_hold,"configuration did not drain memory");
    config=value;for(unsigned i=0;i<config.size();i++) top.config_words[i]=config[i];
    top.cfg_valid=1;tick();top.cfg_valid=0;
    for(unsigned i=0;!top.cfg_ready && i<100000;i++) tick();
    check(top.cfg_ready,"configuration timeout");
  }
  void drive(const Request& request) {
    top.req_valid=1;top.req_p0=request.p;top.req_q0=request.q;top.req_cols=request.cols;top.req_tag=request.tag;
  }
  void finish_pending_configuration(const std::array<uint32_t,16>& next) {
    bool configured=false;
    for(unsigned i=0;i<100000;i++) {
      top.eval();bool fire=top.cfg_valid && top.cfg_ready;tick();
      if(fire) {
        check(expected.empty() && reads.empty() && !read_hold,"configuration overtook old work");
        config=next;configured=true;break;
      }
    }
    check(configured,"read-side configuration timeout");top.cfg_valid=0;
    for(unsigned i=0;!top.cfg_ready && i<100000;i++)tick();
    check(top.cfg_ready && !top.read_busy,"configuration did not become idle");
  }
  void configuration_before_address(const std::array<uint32_t,16>& next) {
    block_ar=true;Request request{0,0,16,0};drive(request);
    bool accepted_window=false;
    for(unsigned i=0;i<100000;i++) {
      if(tick(accepted_window ? nullptr : &request)) {accepted_window=true;top.req_valid=0;}
      if(accepted_window && top.arvalid)break;
    }
    check(accepted_window && top.arvalid && !top.arready && reads.empty(),"first AR was not retained");
    for(unsigned i=0;i<next.size();i++)top.config_words[i]=next[i];
    top.cfg_valid=1;
    for(unsigned i=0;i<24;i++) {
      tick();check(!top.cfg_ready && top.read_busy && top.arvalid,"configuration overtook stalled first AR");
    }
    block_ar=false;finish_pending_configuration(next);
  }
  void configuration_at_burst_boundary(const std::array<uint32_t,16>& next) {
    for(unsigned i=0;i<4;) {
      Request request{i,4*16,16,i};drive(request);if(tick(&request))i++;
    }
    top.req_valid=0;
    for(unsigned i=0;i<next.size();i++)top.config_words[i]=next[i];
    uint64_t before=configuration_boundaries;configure_at_burst_boundary=true;
    finish_pending_configuration(next);
    check(configuration_boundaries==before+1,"configuration with queued windows at a burst boundary was not exercised");
  }
  void configure_with_pending(std::array<uint32_t,16> next) {
    top.rsp_ready=0;
    for(unsigned i=0;i<4;) {
      Request request{0,0,16,i};drive(request);if(tick(&request))i++;
    }
    top.req_valid=0;
    check(expected.size()==4 && top.busy,"configuration setup did not retain requests");
    for(unsigned i=0;i<next.size();i++)top.config_words[i]=next[i];
    top.cfg_valid=1;top.eval();check(!top.cfg_ready,"configuration accepted before request drain");
    top.rsp_ready=1;bool configured=false;
    for(unsigned i=0;i<100000;i++) {
      top.eval();bool fire=top.cfg_ready;tick();
      if(fire) {
        check(expected.empty() && reads.empty() && !read_hold,"configuration overtook responses");
        config=next;configured=true;break;
      }
    }
    check(configured,"pending configuration timeout");top.cfg_valid=0;
    for(unsigned i=0;!top.cfg_ready && i<100000;i++)tick();
    check(top.cfg_ready && !top.busy,"new configuration did not become ready");
  }
  void cancel_window_reservations() {
    for(unsigned kind=0;kind<3;kind++) {
      const auto before=accepted;
      Request request{0,0,16,2};drive(request);
      check(!tick(&request),"window accepted before registered grant");
      check(top.window_granted,"window grant was not stored");
      if(kind==0) top.req_valid=0;
      if(kind==1) top.i_abort=1;
      if(kind==2) top.cfg_valid=1;
      check(!tick(&request),"cancelled window reservation was accepted");
      top.req_valid=0;top.i_abort=0;top.cfg_valid=0;
      for(unsigned i=0;i<4;i++) tick();
      check(!top.window_granted && accepted==before && expected.empty() && !top.busy,
            "cancelled window reservation retained state");
    }
  }
  void ordinary_after_window_grant() {
    const auto before=ordinary_completed, words=ordinary_words;
    Request request{0,0,16,1};drive(request);
    check(!tick(&request) && top.window_granted,"window reservation preparation");
    top.ordinary_req=1;
    top.eval();
    check(top.req_ready && !top.ordinary_granted,"stored window grant ownership before acceptance");
    check(tick(&request),"stored window request was not accepted");
    top.req_valid=0;
    for(unsigned i=0;!top.ordinary_granted;i++) {
      check(i<8,"ordinary request after window grant timed out");tick();
    }
    top.ordinary_start=1;tick();top.ordinary_start=0;top.ordinary_req=0;
    for(unsigned i=0;i<100000;i++) {
      if(expected.empty() && !top.busy && ordinary_completed==before+1) break;
      tick();
    }
    for(unsigned i=0;i<5;i++) tick();
    check(ordinary_completed==before+1 && ordinary_words==words+4 && expected.empty() && !top.busy,
          "ordinary read after stored window grant did not complete");
  }
  void concurrent_ordinary(unsigned start_delay) {
    auto before=ordinary_completed,words=ordinary_words;
    Request request{0,0,16,2};drive(request);top.ordinary_req=1;top.ordinary_start=start_delay==0;
    top.eval();check(!top.req_ready,"ordinary/window priority mismatch");
    for(unsigned i=0;!top.ordinary_granted;i++) {
      check(i<8,"ordinary grant preparation timeout");
      check(!tick(&request),"window accepted during ordinary grant preparation");
    }
    for(unsigned i=0;i<start_delay;i++) {
      check(!tick(&request),"window accepted during ordinary reservation");
      check(top.ordinary_granted && !top.req_ready,"ordinary reservation did not persist");
    }
    top.ordinary_start=1;check(!tick(&request),"window accepted at ordinary launch");
    top.ordinary_start=0;top.ordinary_req=0;
    bool accepted_window=false;
    for(unsigned i=0;i<100000;i++) {
      if(!accepted_window) drive(request);else top.req_valid=0;
      if(tick(accepted_window ? nullptr : &request))accepted_window=true;
      if(accepted_window && expected.empty() && !top.busy && ordinary_completed==before+1)break;
    }
    top.req_valid=0;
    for(unsigned i=0;i<8;i++)tick();
    check(ordinary_completed==before+1 && ordinary_words==words+4 && expected.empty() && !top.busy,
          "concurrent ordinary/window request did not complete once");
  }
  void run(const std::vector<Request>& requests,bool stalled=false) {
    size_t sent=0;uint64_t deadline=cycle+2000000,start=cycle;
    while(sent<requests.size() || !expected.empty() || top.busy) {
      check(cycle<deadline,"window completion timeout");
      if(sent<requests.size()) drive(requests[sent]);else top.req_valid=0;
      top.rsp_ready=!stalled || (cycle-start>=40 && random()%4!=0);
      if(tick(sent<requests.size() ? &requests[sent] : nullptr)) sent++;
    }
    top.req_valid=0;top.rsp_ready=1;
    for(int i=0;i<5;i++) tick();
    check(top.requests==top.completions,"hardware request/response count mismatch");
  }
};

static std::array<uint32_t,16> configuration(uint32_t base=0x2000,unsigned channels=16,unsigned kernel=1) {
  return {base,8,8,channels,kernel,kernel,8,8,1,1,kernel/2,kernel/2,37,1,0,0};
}
int main(int argc,char** argv) {
  Verilated::commandArgs(argc,argv);
  try {
    Simulation s;s.configure(configuration());
    s.run({{0,0,16,0}});
    size_t first=s.response_cycles.size();uint64_t before=s.elements;
    std::vector<Request> hits;for(unsigned i=0;i<128;i++) hits.push_back({0,0,16,i%4});
    std::string trace_arg=Verilated::commandArgsPlusMatch("WINDOW_TRACE=");
    const std::string trace_prefix="+WINDOW_TRACE=";
    if(trace_arg.rfind(trace_prefix,0)==0) {
      s.window_trace.open(trace_arg.substr(trace_prefix.size()));
      check(s.window_trace.good(),"cannot open window trace");
      s.trace_enabled=true;
    }
    s.run(hits);
    s.trace_enabled=false;s.window_trace.close();
    check(s.top.peak_outstanding==4,"four outstanding descriptors not reached");
    check(s.elements-before==128*16,"continuous hit payload count");
    auto last=s.response_cycles.size();
    check(last-first==512,"continuous hit response count");
    uint64_t maximum_interval=0,maximum_word_interval=0,maximum_descriptor_interval=0;
    unsigned stream_consecutive=0;
    for(size_t i=first+1;i<last;i++) {
      const uint64_t interval=s.response_cycles[i]-s.response_cycles[i-1];
      maximum_interval=std::max(maximum_interval,interval);
      stream_consecutive+=interval==1;
      if((i-first)%4==0) maximum_descriptor_interval=std::max(maximum_descriptor_interval,interval);
      else maximum_word_interval=std::max(maximum_word_interval,interval);
      const uint64_t allowed_interval=(i-first)%4==0 ?
        WINDOW_DESCRIPTOR_RESPONSE_INTERVAL : WINDOW_RESPONSE_INTERVAL;
      check(interval<=allowed_interval,"resident response interval exceeded");
    }
    check(s.response_cycles.back()-s.response_cycles[first]+1<=
          384*WINDOW_RESPONSE_INTERVAL+127*WINDOW_DESCRIPTOR_RESPONSE_INTERVAL+1,
          "hit stream exceeded the selected pipeline response interval");
    check(s.top.request_response_overlap>0,"requests did not overlap responses");
    std::printf("CASE consecutive_hits requests=128 beats=512 elements=2048 peak=4 consecutive=%u maximum_interval=%llu word_interval=%llu descriptor_interval=%llu cycles=%llu\n",
      stream_consecutive,
      static_cast<unsigned long long>(maximum_interval),
      static_cast<unsigned long long>(maximum_word_interval),
      static_cast<unsigned long long>(maximum_descriptor_interval),
      static_cast<unsigned long long>(s.response_cycles.back()-s.response_cycles[first]+1));
    // 暖缓存中的单拍窗口应逐周期返回，统计全部相邻响应间隔。
    std::vector<Request> short_hits;
    for(unsigned i=0;i<256;i++) short_hits.push_back({0,0,4,i%4});
    first=s.response_cycles.size();
    s.run(short_hits);
    last=s.response_cycles.size();
    check(last-first==256,"single-beat window response count");
    unsigned consecutive=0;
    uint64_t single_maximum_interval=0;
    for(size_t i=first+1;i<last;i++) {
      const uint64_t interval=s.response_cycles[i]-s.response_cycles[i-1];
      consecutive+=interval==1;
      single_maximum_interval=std::max(single_maximum_interval,interval);
    }
    check(single_maximum_interval<=WINDOW_SINGLE_RESPONSE_INTERVAL,
          "single-beat window response interval exceeded");
    if (WINDOW_SINGLE_RESPONSE_INTERVAL==1)
      check(consecutive==255,"single-beat windows did not return every cycle");
    std::printf("CASE single_beat_hits requests=256 consecutive=%u elements=1024 maximum_interval=%llu cycles=%llu\n",
      consecutive, static_cast<unsigned long long>(single_maximum_interval),
      static_cast<unsigned long long>(s.response_cycles.back()-s.response_cycles[first]+1));
    s.concurrent_ordinary(0);s.concurrent_ordinary(3);
    std::printf("CASE ordinary_window_concurrent same_cycle=1 reserved_cycles=3 ordinary_completions=2 window_completions=2\n");
    s.cancel_window_reservations();s.ordinary_after_window_grant();
    std::printf("CASE registered_window_grant withdrawal=1 abort=1 configuration=1 ordinary_after_grant=1\n");
    s.random_memory=true;s.configure(configuration(0x2ffd,7,3));
    std::vector<Request> mixed;
    for(unsigned i=0;i<240;i++) mixed.push_back({unsigned(s.random()%64),unsigned(s.random()%63),1+unsigned(s.random()%16),i%4});
    s.run(mixed,true);
    std::printf("CASE random_coordinates_backpressure requests=240 peak=%u\n",s.top.peak_outstanding);
    s.configure(configuration(0x5ffb,16,3));s.inject_error=true;s.error_used=false;
    s.run({{0,4*16,16,3,true},{1,4*16,16,0,true},{2,4*16,16,2,true},{3,4*16,16,1,true}});
    check(s.error_used,"read error was not injected");s.inject_error=false;
    check(s.error_responses==4,"accepted descriptors did not receive terminal errors");
    std::printf("CASE read_error_drain requests=4 completions=4\n");
    s.configure(configuration(0x5ffb,16,3));s.run({{0,4*16,16,0},{1,4*16,7,1},{2,4*16,16,2}});
    std::printf("CASE error_reconfigure_recovery requests=3\n");
    s.configure(configuration());
    s.run({{0,0,16,0},{0,32,16,1,true},{0,0,16,2,true},{0,0,16,3,true}});
    std::printf("CASE invalid_descriptor_order requests=4 completions=4\n");
    for(unsigned cols : {0u,17u,32u,33u}) {
      s.configure(configuration());
      s.run({{0,0,16,0},{0,0,cols,1,true},{0,0,16,2,true},{0,0,16,3,true}});
      std::printf("CASE invalid_cols cols=%u requests=4 completions=4\n",cols);
    }
    s.configure(configuration());s.run({{0,0,16,0}});
    s.configure_with_pending(configuration(0x9000,16,1));
    s.run({{0,0,16,3},{1,0,16,0},{2,0,16,1}});
    std::printf("CASE pending_configuration drained=4 recovery_requests=3\n");
    s.random_memory=false;s.configure(configuration(0xa000,16,1));
    s.configuration_before_address(configuration(0xb000,16,1));
    s.run({{0,0,16,0}});
    std::printf("CASE configuration_before_first_ar stalled_cycles=24 old_requests=1 recovery_requests=1\n");
    auto prefetch_config=configuration(0xc000,16,3);prefetch_config[14]=1;
    s.configure(prefetch_config);
    s.configuration_at_burst_boundary(configuration(0xd000,16,1));
    s.run({{0,0,16,0}});
    std::printf("CASE configuration_at_burst_boundary pending_windows_at_last_r=1 old_requests=4 recovery_requests=1\n");
    s.configure(configuration());s.run({{0,0,16,0}});
    s.top.rsp_ready=0;
    for(unsigned i=0;i<4;) {Request request{0,0,16,i};s.drive(request);if(s.tick(&request))i++;}
    check(s.expected.size()==4,"reset setup did not retain four requests");
    s.reset();s.configure(configuration(0x7ffb,3,3));s.run({{0,12,3,2},{10,0,16,1},{63,24,3,0}},true);
    std::printf("CASE reset_with_four_requests cancelled=4 recovery_requests=3\n");
    // 十六位输入复用同一窗口接口，检查准备项与当前返回字的同拍转发。
    auto wide_config=configuration(0x10000,16,1);
    wide_config[12]=0;wide_config[15]=2;
    s.random_memory=false;s.configure(wide_config);
    s.run({{0,0,16,0}});
    std::vector<Request> wide_hits;
    for(unsigned i=0;i<128;i++) wide_hits.push_back({0,0,2,i%4});
    first=s.response_cycles.size();s.run(wide_hits);last=s.response_cycles.size();
    check(last-first==128,"s16 single-beat response count");
    unsigned wide_consecutive=0;
    for(size_t i=first+1;i<last;i++) {
      check(s.response_cycles[i]-s.response_cycles[i-1]==1,"s16 single-beat response interval");
      wide_consecutive++;
    }
    std::printf("CASE s16_single_beat_hits requests=128 consecutive=%u elements=256 maximum_interval=1 cycles=%llu\n",
      wide_consecutive,(unsigned long long)(s.response_cycles.back()-s.response_cycles[first]+1));
    s.random_memory=true;
    std::vector<Request> wide_mixed;
    for(unsigned i=0;i<96;i++)
      wide_mixed.push_back({unsigned(s.random()%64),unsigned(s.random()%16),1+unsigned(s.random()%16),i%4});
    s.run(wide_mixed,true);
    std::printf("CASE s16_coordinates_backpressure requests=96\n");
    s.configure(wide_config);s.inject_error=true;s.error_used=false;
    s.run({{0,0,4,0,true},{1,0,7,1,true},{2,3,9,2,true},{3,4,12,3,true}});
    check(s.error_used,"s16 read error was not injected");s.inject_error=false;
    std::printf("CASE s16_read_error_drain requests=4 completions=4\n");
    s.configure(wide_config);s.run({{0,0,16,0}});s.top.rsp_ready=0;
    for(unsigned i=0;i<4;) {Request request{0,0,4,i};s.drive(request);if(s.tick(&request))i++;}
    check(s.expected.size()==4,"s16 reset did not retain four descriptors");
    s.reset();s.configure(wide_config);s.run({{0,0,4,0},{7,1,13,1},{63,15,4,2}},true);
    std::printf("CASE s16_reset_recovery cancelled=4 recovery_requests=3\n");
    check(s.accepted==s.completed+s.cancelled,"accepted requests were lost");
    std::printf("WINDOW_DMA_PASS accepted=%llu completed=%llu cancelled=%llu payload_elements=%llu errors=%llu\n",
      (unsigned long long)s.accepted,(unsigned long long)s.completed,(unsigned long long)s.cancelled,
      (unsigned long long)s.elements,(unsigned long long)s.error_responses);
    return 0;
  } catch(const std::exception& e) {std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
