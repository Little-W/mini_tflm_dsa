// SPDX-License-Identifier: Apache-2.0
#include "Vdw_pool_dma_top.h"
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
extern "C" int dw_pool_reference(const uint32_t*,const int8_t*,const int8_t*,const int32_t*,int32_t*,int32_t*,int8_t*);
static void require(bool condition,const std::string &s){if(!condition)throw std::runtime_error(s);}
struct Range{uint32_t base,size;};
struct Transaction{uint32_t addr,left,size;};
struct Result{uint64_t cycles,compute,wait,reads,writes,bursts;};
class Sim {
public:
 Vdw_pool_dma_top top;
 std::vector<uint8_t> mem=std::vector<uint8_t>(1<<20,0x5a);
 std::vector<Range> ranges;
 std::deque<Transaction> reads,writes;
 std::deque<unsigned> responses;
 std::mt19937 rng{20261115};
 bool random_wait=true,rhold=false,bhold=false,read_fault=false,write_fault=false,fault_used=false;
 int64_t fault_addr=-1;
 uint32_t output_base=0,output_size=0;
 uint64_t cycles=0,read_bytes=0,write_bytes=0,bursts=0;
 bool ar_stall=false,aw_stall=false,w_stall=false;
 std::tuple<uint32_t,uint32_t,uint32_t> old_ar,old_aw,old_w;
 bool chance(){return !random_wait || rng()%4!=0;}
 bool readable(uint32_t addr)const{for(auto r:ranges)if(addr>=r.base&&uint64_t(addr)<uint64_t(r.base)+r.size)return true;return false;}
 void tick(){
   top.clk=0;
   top.m_axi_arready=reads.size()<8 && chance();top.m_axi_awready=writes.size()<8 && chance();
   top.m_axi_wready=!writes.empty()&&chance();
   if(!rhold&&!reads.empty()&&chance()){
     auto r=reads.front();uint32_t word=0;
     for(unsigned i=0;i<r.size;i++)word|=uint32_t(mem.at(r.addr+i))<<(((r.addr+i)&3)*8);
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
   auto wd=std::make_tuple(uint32_t(top.m_axi_wdata),uint32_t(top.m_axi_wstrb),uint32_t(top.m_axi_wlast));
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
   if(rh){auto &r=reads.front();r.addr+=r.size;if(--r.left==0)reads.pop_front();rhold=false;}
   if(bh){responses.pop_front();bhold=false;}
   if(arh){
     uint32_t a=top.m_axi_araddr,n=top.m_axi_arlen+1,s=1u<<top.m_axi_arsize;
     require(top.m_axi_arburst==1&&s<=4,"unsupported read burst");
     require((a&4095)+n*s<=4096,"read crossed 4 KiB");
     require(a%s==0,"unaligned read transfer");
     for(uint32_t i=0;i<n*s;i++)require(readable(a+i),"read outside allocations at "+std::to_string(a+i));
     reads.push_back({a,n,s});read_bytes+=uint64_t(n)*s;bursts++;
   }
   if(awh){
     uint32_t a=top.m_axi_awaddr,n=top.m_axi_awlen+1,s=1u<<top.m_axi_awsize;
     require(top.m_axi_awburst==1&&s==4&&a%4==0,"invalid write burst");
     require((a&4095)+n*s<=4096,"write crossed 4 KiB");writes.push_back({a,n,s});
   }
   if(wh){
     require(!writes.empty(),"write without address");auto &w=writes.front();
     require(bool(top.m_axi_wlast)==(w.left==1),"incorrect WLAST");
     for(unsigned i=0;i<4;i++)if(top.m_axi_wstrb&(1u<<i)){
       uint32_t addr=w.addr+i;require(addr>=output_base&&uint64_t(addr)<uint64_t(output_base)+output_size,"write outside output");
       mem.at(addr)=uint8_t(top.m_axi_wdata>>(i*8));write_bytes++;
     }
     w.addr+=4;if(--w.left==0){writes.pop_front();unsigned resp=0;if(write_fault&&!fault_used){resp=2;fault_used=true;}responses.push_back(resp);}
   }
   top.clk=1;top.eval();Verilated::timeInc(1);cycles++;top.clk=0;top.eval();
 }
 Sim(){top.rst_n=0;top.start=0;top.done_ready=0;for(unsigned i=0;i<32;i++)top.config_words[i]=0;for(int i=0;i<4;i++)tick();top.rst_n=1;tick();}
 Result execute(const std::array<uint32_t,32> &config,unsigned expected_error=0,bool mutate=true){
   for(unsigned i=0;!top.ready&&i<1000;i++)tick();require(top.ready,"engine did not become ready");
   require(reads.empty()&&writes.empty()&&responses.empty()&&!rhold&&!bhold,"transactions survived command");
   auto rb=read_bytes,wb=write_bytes,br=bursts;fault_used=false;
   for(unsigned i=0;i<32;i++)top.config_words[i]=config[i];top.start=1;tick();top.start=0;
   if(mutate)for(unsigned i=0;i<32;i++)top.config_words[i]=0xa5a5a5a5;
   uint64_t deadline=cycles+10000000;
   while(!top.done_valid&&cycles<deadline)tick();require(top.done_valid,"command timed out");
   require(top.error==expected_error,"unexpected error "+std::to_string(top.error)+" expected "+std::to_string(expected_error));
   Result result{top.stat_cycles,top.stat_compute,top.stat_dma_wait,read_bytes-rb,write_bytes-wb,bursts-br};
   for(int i=0;i<7;i++){tick();require(top.done_valid&&top.error==expected_error,"completion not retained");}
   require(reads.empty()&&writes.empty()&&responses.empty()&&!rhold&&!bhold,"DONE before AXI drain");
   top.done_ready=1;tick();top.done_ready=0;tick();return result;
 }
 template<class T>void put(uint32_t addr,const std::vector<T>&v){std::memcpy(mem.data()+addr,v.data(),v.size()*sizeof(T));}
};
static std::array<uint32_t,32> config(unsigned op){std::array<uint32_t,32> c{};c[0]=op;c[2]=0x1ffb;c[3]=0x10003;c[4]=0x60ffd;c[5]=0x20000;c[6]=0x30000;c[7]=0x40000;c[9]=uint32_t(-128);c[10]=127;c[18]=c[19]=c[20]=c[21]=1;return c;}
static void report(const char *name,const Result&r){std::printf("CASE %s cycles=%llu compute=%llu dma_wait=%llu read_bytes=%llu write_bytes=%llu bursts=%llu\n",name,(unsigned long long)r.cycles,(unsigned long long)r.compute,(unsigned long long)r.wait,(unsigned long long)r.reads,(unsigned long long)r.writes,(unsigned long long)r.bursts);}
static unsigned cases=0;static uint64_t outputs=0;
static Result spatial(Sim&s,const std::string&name,unsigned op,int h,int w,int ch,int kh,int kw,int stride,int dilation,int pad,int offset,bool bias=true,int special=0,bool bypass=false){
 auto c=config(op);c[11]=h;c[12]=w;c[13]=ch;c[14]=kh;c[15]=kw;c[18]=c[19]=stride;c[20]=c[21]=dilation;c[22]=c[23]=pad;
 c[16]=(h+2*pad-(kh-1)*dilation-1)/stride+1;c[17]=(w+2*pad-(kw-1)*dilation-1)/stride+1;
 require(int(c[16])>0&&int(c[17])>0,"empty test shape");c[24]=uint32_t(offset);c[8]=op==0?uint32_t(-3):0;c[25]=bypass;
 if(!bias)c[5]=0;
 size_t ins=size_t(h)*w*ch,ws=size_t(kh)*kw*ch,outs=size_t(c[16])*c[17]*ch;
 std::vector<int8_t> input(ins),weight(ws),gold(outs);
 std::vector<int32_t> biases(ch),mult(ch),shift(ch);
 for(size_t i=0;i<ins;i++){input[i]=int8_t(int(s.rng()%256)-128);if(special==1)input[i]=int8_t(-1-int(s.rng()%127));if(special==2)input[i]=(i&1)?0:((i/2)&1)?-1:1;}
 for(auto&v:weight)v=int8_t(int(s.rng()%17)-8);
 for(int i=0;i<ch;i++){biases[i]=int(s.rng()%2001)-1000;mult[i]=0x40000000+int(s.rng()%0x3fffffff);shift[i]=(i%7)-5;}
 s.put(c[2],input);s.put(c[3],weight);s.put(c[5]?c[5]:0x20000,biases);s.put(c[6],mult);s.put(c[7],shift);
 require(dw_pool_reference(c.data(),input.data(),weight.data(),bias?biases.data():nullptr,mult.data(),shift.data(),gold.data())==0,"NMSIS reference failure");
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
   int lim=s16?32768:128;a[i]=int16_t(int(s.rng()%(2*lim))-lim);b[i]=int16_t(int(s.rng()%(2*lim))-lim);
   if(pattern==1){a[i]=int16_t(-lim);b[i]=int16_t(-lim);}if(pattern==2)a[i]=int16_t(-1-int(s.rng()%lim));
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
 auto c=config(0);c[11]=c[12]=c[14]=c[15]=c[16]=c[17]=1;c[13]=6;
 std::vector<int8_t> in(6,0),weight(6,0),gold(6);
 std::vector<int32_t> bias{INT32_MAX,INT32_MIN+1,-1,1,0,7};
 std::vector<int32_t> mult{INT32_MAX,INT32_MAX,0x40000000,0x40000000,0,INT32_MAX};
 std::vector<int32_t> shift{0,0,-1,-1,-31,0};
 s.put(c[2],in);s.put(c[3],weight);s.put(c[5],bias);s.put(c[6],mult);s.put(c[7],shift);
 s.ranges={{c[2],6},{c[3],6},{c[5],24},{c[6],24},{c[7],24}};s.output_base=c[4];s.output_size=6;
 for(int offset:{127,-128}){
   c[8]=uint32_t(offset);
   require(dw_pool_reference(c.data(),in.data(),weight.data(),bias.data(),mult.data(),shift.data(),gold.data())==0,"edge reference");
   auto expected=s.mem;std::memcpy(expected.data()+c[4],gold.data(),gold.size());auto r=s.execute(c);
   require(s.mem==expected,"requantization edge mismatch");report(("quant_offset_"+std::to_string(offset)).c_str(),r);cases++;outputs+=6;
 }
}
static void invalid_cases(Sim&s){
 auto base=config(4);base[1]=17;base[4]=0x60000;
 std::vector<std::array<uint32_t,32>> tests;
 auto c=base;c[1]=0;tests.push_back(c);c=base;c[0]=15;tests.push_back(c);
 c=base;c[4]=c[2];tests.push_back(c);c=base;c[2]=0xfffffff8;tests.push_back(c);
 c=base;c[0]|=256;tests.push_back(c);
 c=config(2);c[11]=c[12]=c[13]=1;c[14]=c[15]=2;c[16]=c[17]=1;c[22]=3;tests.push_back(c);
 c=config(0);c[11]=c[12]=9;c[13]=1;c[14]=c[15]=8;c[16]=c[17]=2;tests.push_back(c);
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
 before=s.mem;s.read_fault=true;s.fault_addr=c[2];r=s.execute(c,2);
 require(s.fault_used&&r.writes==0&&s.mem==before,"window read error wrote output");
 s.read_fault=false;report("window_read_error",r);cases++;
 r=s.execute(c);require(r.writes==3,"window read recovery");report("window_read_recovery",r);cases++;
}
int main(int argc,char**argv){
 Verilated::commandArgs(argc,argv);
 try{
   Sim s;bool perf=argc>1&&std::string(argv[1])=="--perf";s.random_wait=!perf;
   if(perf){
     spatial(s,"perf_dw_c16",0,8,8,16,3,3,1,1,1,7);
     spatial(s,"perf_dw_c32",0,8,8,32,3,3,1,1,1,-9);
     spatial(s,"perf_dw_c64_s2",0,16,16,64,3,3,2,1,1,11);
     spatial(s,"perf_avg_c32",1,8,8,32,3,3,1,1,1,0);
     spatial(s,"perf_max_c32",2,8,8,32,2,2,2,1,0,0);
     vector_case(s,"perf_dot_s8",7,1024,false);vector_case(s,"perf_hadamard_s16",8,1024,true);
   }else{
     spatial(s,"dw_tail_c3",0,5,5,3,3,3,1,1,1,7);
     spatial(s,"dw_same_address",0,5,5,3,3,3,1,1,1,-127);
     spatial(s,"dw_c17_stride2",0,7,9,17,3,3,2,1,1,128,false);
     spatial(s,"dw_rect_dilation",0,7,8,5,2,3,1,2,2,-11);
     spatial(s,"dw_7x7_c1",0,7,7,1,7,7,1,1,3,0);
     spatial(s,"dw_1x1_c31",0,2,3,31,1,1,1,1,0,17);
     spatial(s,"dw_bias_only_padding",0,1,1,3,1,1,1,1,2,128);
     spatial(s,"dw_bypass",0,3,4,7,3,3,1,1,1,-5,true,0,true);
     spatial(s,"avg_negative_ties",1,2,4,3,2,2,1,1,0,0,true,2);
     spatial(s,"avg_padding_c17",1,4,5,17,3,3,2,1,1,0);
     spatial(s,"max_all_negative",2,4,5,5,3,3,1,1,1,0,true,1);
     spatial(s,"min_padding",3,4,5,3,3,3,1,1,1,0);
     for(unsigned op=4;op<=8;op++)for(bool wide:{false,true})for(unsigned n:{1u,3u,16u,17u,65u})
       vector_case(s,"v"+std::to_string(op)+(wide?"_s16_":"_s8_")+std::to_string(n),op,n,wide);
     vector_case(s,"dot_s16_wrap",7,65,true,1);vector_case(s,"max_negative_s16",5,33,true,2);
     invalid_cases(s);errors(s);quant_edges(s);
     for(unsigned i=0;i<16;i++){
       int h=3+s.rng()%4,w=3+s.rng()%5,ch=1+s.rng()%21;unsigned op=i%4;
       spatial(s,"random_"+std::to_string(i),op,h,w,ch,3,3,1+i%2,1,1,op==0?int(s.rng()%256)-127:0,i%3!=0);
     }
   }
   std::printf("DW_POOL_DMA_PASS cases=%u outputs=%llu\n",cases,(unsigned long long)outputs);return 0;
 }catch(const std::exception&e){std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}
}
