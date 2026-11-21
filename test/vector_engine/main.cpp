// SPDX-License-Identifier: Apache-2.0
#include "Vvector_engine_dma_top.h"
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
#ifndef TEST_BUS_WIDTH
#define TEST_BUS_WIDTH 32
#endif
static constexpr unsigned BUS_BYTES=TEST_BUS_WIDTH/8;
static_assert(TEST_BUS_WIDTH==32 || TEST_BUS_WIDTH==64,"supported AXI data width");
extern "C" int vector_engine_reference(const uint32_t*,const int8_t*,const int8_t*,const int32_t*,int32_t*,int32_t*,int8_t*);
static void require(bool condition,const std::string &s){if(!condition)throw std::runtime_error(s);}
struct Range{uint32_t base,size;};
struct Transaction{uint32_t addr,left,size;uint64_t ready_cycle=0;};
struct Result{uint64_t cycles,compute,wait,reads,writes,bursts;std::array<uint64_t,21> monitor;uint64_t write_transactions=0;};
using Config=std::array<uint32_t,40>;
class Sim {
public:
 Vvector_engine_dma_top top;
 std::vector<uint8_t> mem=std::vector<uint8_t>(1<<20,0x5a);
 std::vector<Range> ranges;
 std::deque<Transaction> reads,writes;
 std::deque<unsigned> responses;
 std::mt19937 rng{20261115};
 std::mt19937 data_rng{20261115};
 bool stable_stimulus=false;
 bool random_wait=true,rhold=false,bhold=false,read_fault=false,write_fault=false,fault_used=false;
 int64_t fault_addr=-1;
 uint64_t fault_write_transaction=0;
 uint32_t output_base=0,output_size=0;
 uint64_t cycles=0,read_bytes=0,write_bytes=0,bursts=0,next_read_cycle=0;
 uint64_t write_transactions=0;
 bool common_memory_service=false;
 bool ar_stall=false,aw_stall=false,w_stall=false;
 std::tuple<uint32_t,uint32_t,uint32_t> old_ar,old_aw;
 std::tuple<uint64_t,uint32_t,uint32_t> old_w;
 bool chance(){return !random_wait || rng()%4!=0;}
 uint32_t sample(){return stable_stimulus ? data_rng() : rng();}
 bool readable(uint32_t addr)const{for(auto r:ranges)if(addr>=r.base&&uint64_t(addr)<uint64_t(r.base)+r.size)return true;return false;}
 void tick(){
   top.clk=0;
   top.m_axi_arready=reads.size()<8 && chance();top.m_axi_awready=writes.size()<8 && chance();
   top.m_axi_wready=!writes.empty()&&chance();
   if(!rhold&&!reads.empty()&&chance()&&(!common_memory_service || (cycles>=next_read_cycle && cycles>=reads.front().ready_cycle))){
     auto r=reads.front();uint64_t word=0;
     for(unsigned i=0;i<r.size;i++)word|=uint64_t(mem.at(r.addr+i))<<(((r.addr+i)&(BUS_BYTES-1))*8);
     top.m_axi_rdata=word;top.m_axi_rlast=r.left==1;top.m_axi_rresp=0;
     if(read_fault&&!fault_used&&(fault_addr<0||(uint64_t(fault_addr)>=r.addr&&uint64_t(fault_addr)<uint64_t(r.addr)+r.size))){top.m_axi_rresp=2;fault_used=true;}
     rhold=true;
   }
   top.m_axi_rvalid=rhold;
   if(!bhold&&!responses.empty()&&chance()){bhold=true;top.m_axi_bresp=responses.front();}
   top.m_axi_bvalid=bhold;
   top.eval();
   auto ar=std::make_tuple(uint32_t(top.m_axi_araddr),uint32_t(top.m_axi_arlen),uint32_t(top.m_axi_arsize));
   auto aw=std::make_tuple(uint32_t(top.m_axi_awaddr),uint32_t(top.m_axi_awlen),uint32_t(top.m_axi_awsize));
   auto wd=std::make_tuple(uint64_t(top.m_axi_wdata),uint32_t(top.m_axi_wstrb),uint32_t(top.m_axi_wlast));
   if(top.rst_n){
     if(ar_stall)require(top.m_axi_arvalid&&ar==old_ar,"AR changed under backpressure");
     if(aw_stall)require(top.m_axi_awvalid&&aw==old_aw,"AW changed under backpressure");
     if(w_stall)require(top.m_axi_wvalid&&wd==old_w,"W changed under backpressure");
   }
   ar_stall=top.m_axi_arvalid&&!top.m_axi_arready;old_ar=ar;
   aw_stall=top.m_axi_awvalid&&!top.m_axi_awready;old_aw=aw;
   w_stall=top.m_axi_wvalid&&!top.m_axi_wready;old_w=wd;
   bool arh=top.m_axi_arvalid&&top.m_axi_arready;
   bool rh=top.m_axi_rvalid&&top.m_axi_rready;
   bool awh=top.m_axi_awvalid&&top.m_axi_awready;
   bool wh=top.m_axi_wvalid&&top.m_axi_wready;
   bool bh=top.m_axi_bvalid&&top.m_axi_bready;
   if(rh){auto &r=reads.front();r.addr+=r.size;bool last=--r.left==0;if(last)reads.pop_front();rhold=false;next_read_cycle=cycles+(last?3:2);}
   if(bh){responses.pop_front();bhold=false;}
   if(arh){
     uint32_t a=top.m_axi_araddr,n=top.m_axi_arlen+1,s=1u<<top.m_axi_arsize;
     require(top.m_axi_arburst==1&&s<=BUS_BYTES,"unsupported read burst");
     require((a&4095)+n*s<=4096,"read crossed 4 KiB");
     require(a%s==0,"unaligned read transfer");
     for(uint32_t i=0;i<n*s;i++)require(readable(a+i),"read outside allocations at "+std::to_string(a+i));
     reads.push_back({a,n,s,cycles+3});read_bytes+=uint64_t(n)*s;bursts++;
   }
   if(awh){
     ++write_transactions;
     uint32_t a=top.m_axi_awaddr,n=top.m_axi_awlen+1,s=1u<<top.m_axi_awsize;
     require(top.m_axi_awburst==1&&s==BUS_BYTES&&a%BUS_BYTES==0,"invalid write burst");
     require((a&4095)+n*s<=4096,"write crossed 4 KiB");writes.push_back({a,n,s});
   }
   if(wh){
     require(!writes.empty(),"write without address");auto &w=writes.front();
     require(bool(top.m_axi_wlast)==(w.left==1),"incorrect WLAST");
     for(unsigned i=0;i<BUS_BYTES;i++)if(top.m_axi_wstrb&(1u<<i)){
       uint32_t addr=w.addr+i;require(addr>=output_base&&uint64_t(addr)<uint64_t(output_base)+output_size,"write outside output");
       mem.at(addr)=uint8_t(top.m_axi_wdata>>(i*8));write_bytes++;
     }
     w.addr+=w.size;if(--w.left==0){writes.pop_front();unsigned resp=0;if(write_fault&&!fault_used&&
         (fault_write_transaction==0||write_transactions==fault_write_transaction)){resp=2;fault_used=true;}responses.push_back(resp);}
   }
   top.clk=1;top.eval();Verilated::timeInc(1);cycles++;top.clk=0;top.eval();
 }
 Sim(){top.rst_n=0;top.start=0;top.done_ready=0;for(unsigned i=0;i<40;i++)top.config_words[i]=0;for(int i=0;i<4;i++)tick();top.rst_n=1;tick();}
 Result execute(const Config &config,unsigned expected_error=0,bool mutate=true){
   for(unsigned i=0;!top.ready&&i<1000;i++)tick();require(top.ready,"engine did not become ready");
   require(reads.empty()&&writes.empty()&&responses.empty()&&!rhold&&!bhold,"transactions survived command");
   auto rb=read_bytes,wb=write_bytes,br=bursts,wt=write_transactions;fault_used=false;
   for(unsigned i=0;i<40;i++)top.config_words[i]=config[i];top.start=1;tick();top.start=0;
   if(mutate)for(unsigned i=0;i<40;i++)top.config_words[i]=0xa5a5a5a5;
   uint64_t deadline=cycles+10000000;
   while(!top.done_valid&&cycles<deadline)tick();require(top.done_valid,"command timed out");
   require(top.error==expected_error,"unexpected error "+std::to_string(top.error)+" expected "+std::to_string(expected_error)+
     " window elements="+std::to_string(top.observed_window_elements)+"/"+std::to_string(top.expected_window_elements));
   Result result{top.stat_cycles,top.stat_compute,top.stat_dma_wait,read_bytes-rb,write_bytes-wb,bursts-br,
     {top.cache_hits,top.cache_misses,top.cache_prefetch_lines,top.cache_prefetch_used,
      top.cache_prefetch_wasted,top.cache_prefetch_unused,top.cache_prefetch_bytes,top.cache_prefetch_late,
      top.quant_inputs,top.quant_consecutive,top.mac_quant_overlap,top.mac_write_overlap,top.all_overlap,
      top.write_bursts16,top.write_beats16,top.window_requests,top.window_completions,
      top.window_peak_outstanding,top.window_response_beats,top.window_consecutive_responses,
      top.window_request_response_overlap}};
   result.write_transactions=write_transactions-wt;
   if((config[0]&15)>3)for(size_t i=0;i<8;i++)result.monitor[i]=0;
   if((config[0]&15)==0 && expected_error==0)
     require(top.quant_inputs==uint64_t(config[13])*config[16]*config[17],"depthwise quantization input count");
   require(top.window_requests==top.window_completions,"window requests did not drain");
   require(top.write_beats16==(16/BUS_BYTES)*top.write_bursts16,"16-channel output burst count");
   for(int i=0;i<7;i++){tick();require(top.done_valid&&top.error==expected_error,"completion not retained");}
   require(reads.empty()&&writes.empty()&&responses.empty()&&!rhold&&!bhold,"DONE before AXI drain");
   top.done_ready=1;tick();top.done_ready=0;tick();return result;
 }
 template<class T>void put(uint32_t addr,const std::vector<T>&v){std::memcpy(mem.data()+addr,v.data(),v.size()*sizeof(T));}
};
static Config config(unsigned op){Config c{};c[0]=op;c[2]=0x1ffb;c[3]=0x10003;c[4]=0x60ffd;c[5]=0x20000;c[6]=0x30000;c[7]=0x40000;c[9]=uint32_t(-128);c[10]=127;c[18]=c[19]=c[20]=c[21]=1;return c;}
static void report(const char *name,const Result&r){
 std::printf("CASE %s cycles=%llu compute=%llu dma_wait=%llu read_bytes=%llu write_bytes=%llu bursts=%llu",name,(unsigned long long)r.cycles,(unsigned long long)r.compute,(unsigned long long)r.wait,(unsigned long long)r.reads,(unsigned long long)r.writes,(unsigned long long)r.bursts);
 static const char* labels[]={"cache_hits","cache_misses","pf_lines","pf_used","pf_wasted","pf_unused","pf_bytes","pf_late",
   "quant_inputs","quant_consecutive","mac_quant_overlap","mac_write_overlap","all_overlap","write_bursts16","write_beats16","window_requests","window_completions",
   "window_peak_outstanding","window_response_beats","window_consecutive_responses","window_request_response_overlap"};
 for(size_t i=0;i<r.monitor.size();i++)std::printf(" %s=%llu",labels[i],(unsigned long long)r.monitor[i]);
 std::printf("\n");
}
static unsigned cases=0;static uint64_t outputs=0;
static Result spatial(Sim&s,const std::string&name,unsigned op,int h,int w,int ch,int kh,int kw,int stride,int dilation,int pad,int offset,bool bias=true,int special=0,bool bypass=false,int output_h=0,int output_w=0,bool aligned=false,unsigned parameter_layout=0,bool cross_weight_page=false){
 auto c=config(op);c[11]=h;c[12]=w;c[13]=ch;c[14]=kh;c[15]=kw;c[18]=c[19]=stride;c[20]=c[21]=dilation;c[22]=c[23]=pad;
 if(aligned){c[2]=0x2000;c[3]=0x11000;c[4]=0x61000;}
 if(parameter_layout==1){c[5]=0x20004;c[6]=0x30ffc;c[7]=0x41000;}
 if(parameter_layout==2){c[5]=0x40000;c[6]=0x30000;c[7]=0x20004;}
 if(cross_weight_page)c[3]=0x10ffd;
 c[16]=(h+2*pad-(kh-1)*dilation-1)/stride+1;c[17]=(w+2*pad-(kw-1)*dilation-1)/stride+1;
 if(output_h)c[16]=output_h;if(output_w)c[17]=output_w;
 require(int(c[16])>0&&int(c[17])>0,"empty test shape");c[24]=uint32_t(offset);c[8]=op==0?uint32_t(-3):0;c[25]=bypass;
 if(!bias)c[5]=0;
 size_t ins=size_t(h)*w*ch,ws=size_t(kh)*kw*ch,outs=size_t(c[16])*c[17]*ch;
 std::vector<int8_t> input(ins),weight(ws),gold(outs);
 std::vector<int32_t> biases(ch),mult(ch),shift(ch);
 for(size_t i=0;i<ins;i++){
   input[i]=int8_t(int(s.sample()%256)-128);
   if(special==1)input[i]=int8_t(-1-int(s.sample()%127));
   if(special==2)input[i]=(i&1)?0:((i/2)&1)?-1:1;
   if(special==3){int magnitude=1+2*int((i%ch)/2%4);input[i]=(i/ch<ins/ch/2)?int8_t((i%ch)&1?-magnitude:magnitude):0;}
   if(special==4)input[i]=(i%ch)&1?-128:127;
   if(special==5)input[i]=(i/ch<62+((i%ch)&1))?((i%ch)&2?-1:1):0;
 }
 for(auto&v:weight)v=int8_t(int(s.sample()%17)-8);
 for(int i=0;i<ch;i++){biases[i]=int(s.sample()%2001)-1000;mult[i]=0x40000000+int(s.sample()%0x3fffffff);shift[i]=(i%7)-5;}
 s.put(c[2],input);s.put(c[3],weight);s.put(c[5]?c[5]:0x20000,biases);s.put(c[6],mult);s.put(c[7],shift);
 require(vector_engine_reference(c.data(),input.data(),weight.data(),bias?biases.data():nullptr,mult.data(),shift.data(),gold.data())==0,"independent RNE reference failure");
 std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+outs+16,0xa5);auto expected=s.mem;
 std::memcpy(expected.data()+c[4],gold.data(),outs);
 s.ranges={{c[2],uint32_t(ins)}};if(op==0){s.ranges.push_back({c[3],uint32_t(ws)});if(bias)s.ranges.push_back({c[5],uint32_t(ch*4)});s.ranges.push_back({c[6],uint32_t(ch*4)});s.ranges.push_back({c[7],uint32_t(ch*4)});}
 s.output_base=c[4];s.output_size=outs;auto r=s.execute(c);
 if(s.mem!=expected){for(size_t i=0;i<s.mem.size();i++)if(s.mem[i]!=expected[i])throw std::runtime_error(name+" mismatch at "+std::to_string(i)+" got "+std::to_string(int8_t(s.mem[i]))+" expected "+std::to_string(int8_t(expected[i])));}
 require(r.writes==outs,"output write count mismatch");report(name.c_str(),r);cases++;outputs+=outs;return r;
}
static void vector_case(Sim&s,const std::string&name,unsigned op,unsigned length,bool s16,int pattern=0){
 auto c=config(op);c[0]|=s16?256:0;c[1]=length;c[2]=s16?0x1ffe:0x1fff;c[3]=s16?0x10ffe:0x10ffd;c[4]=0x60ffc;
 std::vector<int16_t>a(length),b(length);std::vector<uint8_t>ab(length*(s16?2:1)),bb(ab.size());
 uint32_t sum=0;int32_t extremum=op==5?INT32_MIN:INT32_MAX;std::vector<int32_t>gold(op==8?length:1);
 for(unsigned i=0;i<length;i++){
   int lim=s16?32768:128;a[i]=int16_t(int(s.sample()%(2*lim))-lim);b[i]=int16_t(int(s.sample()%(2*lim))-lim);
   if(pattern==1){a[i]=int16_t(-lim);b[i]=int16_t(-lim);}if(pattern==2)a[i]=int16_t(-1-int(s.sample()%lim));
   if(s16){std::memcpy(ab.data()+2*i,&a[i],2);std::memcpy(bb.data()+2*i,&b[i],2);}else{ab[i]=uint8_t(a[i]);bb[i]=uint8_t(b[i]);}
   if(op==4)sum+=uint32_t(int32_t(a[i]));if(op==7)sum+=uint32_t(int32_t(a[i])*int32_t(b[i]));
   if(op==5)extremum=std::max(extremum,int32_t(a[i]));if(op==6)extremum=std::min(extremum,int32_t(a[i]));
   if(op==8)gold[i]=int32_t(a[i])*int32_t(b[i]);
 }
 if(op!=8)gold[0]=(op==5||op==6)?extremum:int32_t(sum);
 s.put(c[2],ab);s.put(c[3],bb);std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+gold.size()*4+16,0xa5);auto expected=s.mem;
 std::memcpy(expected.data()+c[4],gold.data(),gold.size()*4);s.ranges={{c[2],uint32_t(ab.size())}};if(op>=7)s.ranges.push_back({c[3],uint32_t(bb.size())});
 s.output_base=c[4];s.output_size=gold.size()*4;auto r=s.execute(c);
 if(s.mem!=expected){for(size_t i=0;i<s.mem.size();i++)if(s.mem[i]!=expected[i])throw std::runtime_error(name+" vector mismatch at "+std::to_string(i));}
 require(r.writes==gold.size()*4,"vector write count");report(name.c_str(),r);cases++;outputs+=gold.size();
}
static void quant_edges(Sim&s){
 auto c=config(0);c[11]=c[12]=c[14]=c[15]=c[16]=c[17]=1;
 std::vector<int32_t> bias{INT32_MAX,INT32_MIN,INT32_MAX,INT32_MIN,-1,1,-3,3,-5,5,-7,7,0,7,-7,1,-1};
 const unsigned count=unsigned(bias.size());c[13]=count;
 std::vector<int8_t> in(count,0),weight(count,0),gold(count);
 std::vector<int32_t> mult(count,0x40000000),shift(count,0);
 mult[0]=mult[1]=mult[2]=mult[3]=INT32_MAX;shift[2]=shift[3]=30;
 mult[12]=0;shift[12]=-31;shift[13]=shift[14]=-1;shift[15]=shift[16]=1;
 s.put(c[2],in);s.put(c[3],weight);s.put(c[5],bias);s.put(c[6],mult);s.put(c[7],shift);
 s.ranges={{c[2],count},{c[3],count},{c[5],count*4},{c[6],count*4},{c[7],count*4}};s.output_base=c[4];s.output_size=count;
 for(int offset:{0,127,-128}){
   c[8]=uint32_t(offset);
   require(vector_engine_reference(c.data(),in.data(),weight.data(),bias.data(),mult.data(),shift.data(),gold.data())==0,"edge reference");
   auto expected=s.mem;std::memcpy(expected.data()+c[4],gold.data(),gold.size());auto r=s.execute(c);
   require(s.mem==expected,"requantization edge mismatch");report(("quant_offset_"+std::to_string(offset)).c_str(),r);cases++;outputs+=count;
 }
}
static void invalid_cases(Sim&s){
 auto base=config(4);base[1]=17;base[4]=0x60000;
 std::vector<Config> tests;
 auto c=base;c[1]=0;tests.push_back(c);c=base;c[0]=15;tests.push_back(c);
 c=base;c[4]=c[2];tests.push_back(c);c=base;c[2]=0xfffffff8;tests.push_back(c);
 c=base;c[0]|=256;tests.push_back(c);
 c=config(2);c[11]=c[12]=c[13]=1;c[14]=c[15]=2;c[16]=c[17]=1;c[22]=3;tests.push_back(c);
 c=config(0);c[11]=c[12]=9;c[13]=1;c[14]=c[15]=8;c[16]=c[17]=2;tests.push_back(c);
 c=config(1);c[11]=c[14]=1;c[12]=c[15]=257;c[13]=c[16]=c[17]=1;tests.push_back(c);
 c=config(2);c[11]=c[12]=c[14]=c[15]=17;c[13]=c[16]=c[17]=1;tests.push_back(c);
 for(unsigned i=0;i<tests.size();i++){auto before=s.mem;auto r=s.execute(tests[i],1);require(!r.reads&&!r.writes&&s.mem==before,"invalid command touched memory");report(("invalid_"+std::to_string(i)).c_str(),r);cases++;}
}
static void errors(Sim&s){
 auto c=config(7);c[1]=33;c[2]=0x1fff;c[3]=0x10001;c[4]=0x60000;
 for(unsigned i=0;i<33;i++){s.mem[c[2]+i]=uint8_t(i);s.mem[c[3]+i]=uint8_t(2*i);}
 s.ranges={{c[2],33},{c[3],33}};s.output_base=c[4];s.output_size=4;
 auto before=s.mem;s.read_fault=true;s.fault_addr=c[2]+3;auto r=s.execute(c,2);
 require(s.fault_used&&r.writes==0&&s.mem==before,"read error handling");s.read_fault=false;report("read_error",r);cases++;
 r=s.execute(c);require(r.writes==4,"read error recovery");report("read_error_recovery",r);cases++;
 s.write_fault=true;r=s.execute(c,2);require(s.fault_used,"write error not injected");s.write_fault=false;report("write_error",r);cases++;
 r=s.execute(c);report("write_error_recovery",r);cases++;
 // Force the final loaded shift word out of range, then reuse the same addresses.
 c=config(0);c[11]=c[12]=c[14]=c[15]=c[16]=c[17]=1;c[13]=3;
 s.ranges={{c[2],3},{c[3],3},{c[5],12},{c[6],12},{c[7],12}};s.output_base=c[4];s.output_size=3;
 std::vector<int32_t> zero(3,0),mult(3,0x40000000),shift{0,0,31};s.put(c[5],zero);s.put(c[6],mult);s.put(c[7],shift);
 before=s.mem;r=s.execute(c,2);require(r.writes==0&&s.mem==before,"invalid shift wrote data");report("invalid_shift",r);cases++;
 shift[2]=-31;s.put(c[7],shift);r=s.execute(c);report("shift_recovery",r);cases++;
 // 参数各行分别注入总线错误，检查全部在途读取结束后再报告完成。
 for(unsigned parameter:{5u,6u,7u}){
   before=s.mem;s.read_fault=true;s.fault_addr=c[parameter]+4;r=s.execute(c,2);
   require(s.fault_used&&r.writes==0&&s.mem==before,"parameter read error wrote output");
   s.read_fault=false;report(("parameter_read_error_"+std::to_string(parameter)).c_str(),r);cases++;
   r=s.execute(c);require(r.writes==3,"parameter read recovery");
   report(("parameter_read_recovery_"+std::to_string(parameter)).c_str(),r);cases++;
 }
 mult[1]=-1;s.put(c[6],mult);before=s.mem;r=s.execute(c,2);
 require(r.writes==0&&s.mem==before,"invalid multiplier wrote data");report("invalid_multiplier",r);cases++;
 mult[1]=0x40000000;s.put(c[6],mult);r=s.execute(c);report("multiplier_recovery",r);cases++;
 before=s.mem;s.read_fault=true;s.fault_addr=c[2];r=s.execute(c,2);
 require(s.fault_used&&r.writes==0&&s.mem==before,"window read error wrote output");
 s.read_fault=false;report("window_read_error",r);cases++;
 r=s.execute(c);require(r.writes==3,"window read recovery");report("window_read_recovery",r);cases++;
}

static void weight_row_errors(Sim&s){
 auto c=config(0);c[11]=c[12]=c[16]=c[17]=3;c[13]=15;c[14]=c[15]=7;
 c[22]=c[23]=3;c[3]=0x10ffd;
 std::vector<int8_t> input(3*3*15),weight(7*7*15),gold(3*3*15);
 std::vector<int32_t> bias(15),mult(15,0x40000000),shift(15,-2);
 for(auto&v:input)v=int8_t(int(s.sample()%256)-128);
 for(auto&v:weight)v=int8_t(int(s.sample()%17)-8);
 for(auto&v:bias)v=int(s.sample()%1025)-512;
 s.put(c[2],input);s.put(c[3],weight);s.put(c[5],bias);s.put(c[6],mult);s.put(c[7],shift);
 require(vector_engine_reference(c.data(),input.data(),weight.data(),bias.data(),mult.data(),shift.data(),gold.data())==0,
         "weight row error recovery reference");
 s.ranges={{c[2],uint32_t(input.size())},{c[3],uint32_t(weight.size())},
           {c[5],60},{c[6],60},{c[7],60}};s.output_base=c[4];s.output_size=gold.size();
 // 首行、页面边界、中间行和末行分别返回错误，检查多行读取的完整排空。
 const unsigned offsets[]={0,3,24*15+7,48*15+14};
 for(unsigned fault=0;fault<4;fault++){
   std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+gold.size()+16,0xa5);
   auto before=s.mem;s.read_fault=true;s.fault_addr=c[3]+offsets[fault];auto r=s.execute(c,2);
   require(s.fault_used&&r.writes==0&&s.mem==before,"weight row error wrote output");
   s.read_fault=false;report(("weight_row_error_"+std::to_string(fault)).c_str(),r);cases++;
   auto expected=s.mem;std::memcpy(expected.data()+c[4],gold.data(),gold.size());
   r=s.execute(c);require(s.mem==expected&&r.writes==gold.size(),"weight row error recovery mismatch");
   report(("weight_row_recovery_"+std::to_string(fault)).c_str(),r);cases++;outputs+=gold.size();
 }
}

static void dw_tile_write_error(Sim&s){
 auto c=config(0);c[11]=c[12]=c[14]=c[15]=c[16]=c[17]=3;c[13]=32;
 c[22]=c[23]=1;c[2]=0x2000;c[3]=0x11000;c[4]=0x61000;c[24]=128;c[8]=uint32_t(-7);
 std::vector<int8_t> input(3*3*32),weight(3*3*32),gold(3*3*32);
 std::vector<int32_t> bias(32),mult(32,0x40000000),shift(32,-8);
 for(auto&v:input)v=int8_t(int(s.sample()%256)-128);
 for(auto&v:weight)v=int8_t(int(s.sample()%17)-8);
 for(auto&v:bias)v=int(s.sample()%1025)-512;
 s.put(c[2],input);s.put(c[3],weight);s.put(c[5],bias);s.put(c[6],mult);s.put(c[7],shift);
 require(vector_engine_reference(c.data(),input.data(),weight.data(),bias.data(),mult.data(),shift.data(),gold.data())==0,
         "tile write error reference");
 s.ranges={{c[2],uint32_t(input.size())},{c[3],uint32_t(weight.size())},
           {c[5],128},{c[6],128},{c[7],128}};s.output_base=c[4];s.output_size=gold.size();
 std::fill(s.mem.begin()+c[4]-16,s.mem.begin()+c[4]+gold.size()+16,0xa5);
 auto expected=s.mem;
 for(unsigned pixel=0;pixel<9;pixel++)std::memcpy(expected.data()+c[4]+32*pixel,gold.data()+32*pixel,16);
 // 第一组最后一次写响应返回错误，同时下一组权重读取可以已经开始。
 s.write_fault=true;s.fault_write_transaction=s.write_transactions+9;
 auto r=s.execute(c,2);require(s.fault_used&&r.writes==9*16&&s.mem==expected,"tile write error output mismatch");
 s.write_fault=false;s.fault_write_transaction=0;report("dw_tile_write_error",r);cases++;
 std::memcpy(expected.data()+c[4],gold.data(),gold.size());r=s.execute(c);
 require(r.writes==gold.size()&&s.mem==expected,"tile write error recovery mismatch");
 report("dw_tile_write_recovery",r);cases++;outputs+=gold.size();
}

static void cached_read_errors(Sim&s){
 for(bool global:{false,true}){
   auto c=config(global?1:2);c[11]=c[12]=4;c[13]=3;c[14]=c[15]=global?4:2;
   c[16]=c[17]=global?1:2;c[18]=c[19]=global?1:2;
   std::vector<int8_t>input(48),gold(size_t(c[16])*c[17]*3);
   for(auto&value:input)value=int8_t(int(s.sample()%256)-128);
   s.put(c[2],input);s.ranges={{c[2],48}};s.output_base=c[4];s.output_size=gold.size();
   auto before=s.mem;s.read_fault=true;s.fault_addr=c[2]+3;auto r=s.execute(c,2);
   require(s.fault_used&&r.writes==0&&s.mem==before,"cached input error handling");s.read_fault=false;
   report(global?"global_pool_read_error":"row_cache_read_error",r);cases++;
   require(vector_engine_reference(c.data(),input.data(),nullptr,nullptr,nullptr,nullptr,gold.data())==0,"cached input recovery reference");
   r=s.execute(c);require(std::memcmp(gold.data(),s.mem.data()+c[4],gold.size())==0,"cached input error recovery");
   report(global?"global_pool_read_recovery":"row_cache_read_recovery",r);cases++;outputs+=gold.size();
 }
}

#include "add_tests.h"
#include "softmax_tests.h"
#ifndef TEST_TILE_SIZE
#define TEST_TILE_SIZE 16
#endif

int main(int argc,char**argv){
 Verilated::commandArgs(argc,argv);
 try{
   bool perf=false,window_study=false,stable_stimulus=false;std::string replay,softmax_replay_path;
   for(int i=1;i<argc;i++){
     if(std::string(argv[i])=="--perf")perf=true;
     else if(std::string(argv[i])=="--window-study")window_study=true;
     else if(std::string(argv[i])=="--stable-stimulus")stable_stimulus=true;
     else if(std::string(argv[i])=="--replay"&&i+1<argc)replay=argv[++i];
     else if(std::string(argv[i])=="--softmax-replay"&&i+1<argc)softmax_replay_path=argv[++i];
     else throw std::runtime_error("unknown command argument");
   }
   Sim s;s.random_wait=!perf;s.stable_stimulus=stable_stimulus;
   if(window_study){
     s.random_wait=false;s.common_memory_service=true;
     spatial(s,"study_dw_48_c8_s1",0,48,48,8,3,3,1,1,1,128,true,0,false,48,48,true);
     spatial(s,"study_dw_48_c8_s2",0,48,48,8,3,3,2,1,0,128,true,0,false,24,24,true);
     spatial(s,"study_dw_48_c16_s2",0,48,48,16,3,3,2,1,0,128,true,0,false,24,24,true);
     spatial(s,"study_dw_24_c32_s2",0,24,24,32,3,3,2,1,0,128,true,0,false,12,12,true);
     spatial(s,"study_dw_12_c64_s2",0,12,12,64,3,3,2,1,0,128,true,0,false,6,6,true);
     spatial(s,"study_dw_6_c128_s2",0,6,6,128,3,3,2,1,0,128,true,0,false,3,3,true);
     std::printf("VECTOR_ENGINE_DMA_PASS cases=%u outputs=%llu add_cases=0 add_outputs=0 softmax_cases=0 softmax_outputs=0\n",cases,(unsigned long long)outputs);
     return 0;
   }
   if(perf){
     spatial(s,"perf_dw_c16",0,8,8,16,3,3,1,1,1,7);
     spatial(s,"perf_dw_c32",0,8,8,32,3,3,1,1,1,-9);
     spatial(s,"perf_dw_c64_s2",0,16,16,64,3,3,2,1,1,11);
     spatial(s,"perf_avg_c32",1,8,8,32,3,3,1,1,1,0);
     spatial(s,"perf_max_c32",2,8,8,32,2,2,2,1,0,0);
     spatial(s,"perf_mobile_dw_48_c8",0,48,48,8,3,3,1,1,1,128);
     spatial(s,"perf_mobile_dw_48_c16_s2",0,48,48,16,3,3,2,1,0,128,true,0,false,24,24);
     spatial(s,"perf_mobile_dw_24_c32",0,24,24,32,3,3,1,1,1,128);
     spatial(s,"perf_dscnn_dw_25x5_c64",0,25,5,64,3,3,1,1,1,128);
     spatial(s,"perf_mnist_max_28_c8",2,28,28,8,2,2,2,1,0,0);
     spatial(s,"perf_mnist_max_14_c16",2,14,14,16,2,2,2,1,0,0);
     spatial(s,"perf_global_avg_8x8_c64",1,8,8,64,8,8,1,1,0,0);
     spatial(s,"perf_global_avg_25x5_c64",1,25,5,64,25,5,1,1,0,0);
     spatial(s,"perf_global_avg_16x16_c3",1,16,16,3,16,16,1,1,0,0);
     vector_case(s,"perf_dot_s8",7,1024,false);vector_case(s,"perf_hadamard_s16",8,1024,true);
     auto params=resnet_add_params();const unsigned lengths[3]={16384,8192,4096};
     for(unsigned i=0;i<3;i++)add_random_case(s,"perf_add_resnet_"+std::to_string(lengths[i]),params[i],lengths[i],0);
   }else{
     spatial(s,"dw_tail_c3",0,5,5,3,3,3,1,1,1,7);
     spatial(s,"dw_same_address",0,5,5,3,3,3,1,1,1,-127);
     spatial(s,"dw_c17_stride2",0,7,9,17,3,3,2,1,1,128,false);
     spatial(s,"dw_rect_dilation",0,7,8,5,2,3,1,2,2,-11);
     spatial(s,"dw_7x7_c1",0,7,7,1,7,7,1,1,3,0);
     spatial(s,"dw_7x7_c17_page",0,3,3,17,7,7,1,1,3,0,true,0,false,0,0,false,0,true);
     spatial(s,"dw_1x1_c31",0,2,3,31,1,1,1,1,0,17);
     spatial(s,"dw_bias_only_padding",0,1,1,3,1,1,1,1,2,128);
     spatial(s,"dw_bypass",0,3,4,7,3,3,1,1,1,-5,true,0,true);
     for(unsigned layout:{1u,2u})for(bool bias:{false,true})
       spatial(s,"dw_parameter_layout_"+std::to_string(layout)+(bias?"_bias":"_zero_bias"),
               0,3,4,17,3,3,1,1,1,-7,bias,0,false,0,0,false,layout);
     spatial(s,"avg_negative_ties",1,2,4,3,2,2,1,1,0,0,true,2);
     spatial(s,"avg_padding_c17",1,4,5,17,3,3,2,1,1,0);
     spatial(s,"max_all_negative",2,4,5,5,3,3,1,1,1,0,true,1);
     spatial(s,"min_padding",3,4,5,3,3,3,1,1,1,0);
     spatial(s,"avg_8x8_c64",1,8,8,64,8,8,1,1,0,0);
     spatial(s,"avg_8x8_signed_ties_c17",1,8,8,17,8,8,1,1,0,0,true,3);
     spatial(s,"avg_25x5_c64",1,25,5,64,25,5,1,1,0,0);
     spatial(s,"avg_25x5_signed_rounding_c17",1,25,5,17,25,5,1,1,0,0,true,5);
     spatial(s,"avg_16x16_limit_c3",1,16,16,3,16,16,1,1,0,0,true,4);
     spatial(s,"max_8x8_negative_c17",2,8,8,17,8,8,1,1,0,0,true,1);
     spatial(s,"min_25x5_c31",3,25,5,31,25,5,1,1,0,0);
     spatial(s,"avg_8x8_padding_c5",1,8,8,5,8,8,2,1,3,0,true,3);
     for(int ch:{1,2,4,8,16,17,31,32,64}){
       spatial(s,"cache_dw_c"+std::to_string(ch),0,7,9,ch,3,3,1,1,1,128);
       spatial(s,"cache_dw_stride2_c"+std::to_string(ch),0,8,10,ch,3,3,2,1,0,-127,true,0,false,4,5);
       spatial(s,"cache_max_stride2_c"+std::to_string(ch),2,8,10,ch,2,2,2,1,0,0);
     }
     spatial(s,"dw_width64",0,3,64,3,3,3,1,1,1,-9);
     spatial(s,"dw_width65",0,3,65,3,3,3,1,1,1,11);
     for(unsigned op=4;op<=8;op++)for(bool wide:{false,true})for(unsigned n:{1u,3u,16u,17u,65u})
       vector_case(s,"v"+std::to_string(op)+(wide?"_s16_":"_s8_")+std::to_string(n),op,n,wide);
     vector_case(s,"dot_s16_wrap",7,65,true,1);vector_case(s,"max_negative_s16",5,33,true,2);
     invalid_cases(s);errors(s);weight_row_errors(s);
     if(TEST_TILE_SIZE==16)dw_tile_write_error(s);
     quant_edges(s);
     for(unsigned i=0;i<16;i++){
       int h=3+s.sample()%4,w=3+s.sample()%5,ch=1+s.sample()%21;unsigned op=i%4;
       spatial(s,"random_"+std::to_string(i),op,h,w,ch,3,3,1+i%2,1,1,op==0?int(s.sample()%256)-127:0,i%3!=0);
     }
     cached_read_errors(s);add_functional(s);add_invalid(s);
     softmax_functional(s,TEST_TILE_SIZE);softmax_invalid(s,TEST_TILE_SIZE);
   }
   if(!replay.empty())add_replay(s,replay);
   auto aligned=spatial(s,"pipeline_dw_c16",0,8,8,16,3,3,1,1,1,7,true,0,false,0,0,true);
   auto pointwise=spatial(s,"pipeline_dw_k1_c16",0,4,8,16,1,1,1,1,0,-5,true,0,false,0,0,true);
   spatial(s,"pipeline_dw_c64",0,8,8,64,3,3,1,1,1,128,true,0,false,0,0,true);
   spatial(s,"pipeline_dw_c128_s2",0,8,8,128,3,3,2,1,1,-127,true,0,false,0,0,true);
   if(TEST_TILE_SIZE==16){
     require(aligned.monitor[8]==1024 && aligned.monitor[9]==64*(16/s.top.quant_lane_count-1),"continuous quantization input groups");
     require(aligned.monitor[10]>0 && aligned.monitor[12]>0,"depthwise compute quantization and write overlap");
     require(aligned.monitor[11]>0,"MAC overlap with writeback");
     require(aligned.writes==1024 && aligned.write_transactions==16,"coalesced depthwise writes preserve all output bytes");
     if(perf)require(pointwise.write_transactions==8 && pointwise.writes==512,"pointwise coalesced write count");
     require(aligned.monitor[17]>=2,"multiple outstanding window requests");
     if(s.top.pe_count>=8)require(aligned.monitor[20]>0,"overlapping window request and response");
   }
   if(!softmax_replay_path.empty())softmax_replay(s,softmax_replay_path);
   s.top.final();
   std::printf("VECTOR_ENGINE_DMA_PASS cases=%u outputs=%llu add_cases=%u add_outputs=%llu softmax_cases=%u softmax_outputs=%llu\n",
     cases,(unsigned long long)outputs,add_cases,(unsigned long long)add_outputs,softmax_cases,(unsigned long long)softmax_outputs);return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
