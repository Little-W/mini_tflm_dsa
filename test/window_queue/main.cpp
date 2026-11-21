// SPDX-License-Identifier: Apache-2.0
// 以独立事务顺序模型验证多在途窗口的描述符、响应、停顿和恢复。
#include "Vconv_window_queue.h"
#include "verilated.h"
#include <cstdint>
#include <cstdio>
#include <deque>
#include <random>
#include <stdexcept>
#include <string>
#ifndef TEST_DEPTH
#define TEST_DEPTH 4
#endif
#ifndef TEST_LANES
#define TEST_LANES 8
#endif
#ifndef TEST_OUTSTANDING
#define TEST_OUTSTANDING 2
#endif
struct Request { uint32_t p,q,cols,tag; };
struct Active { Request request; unsigned beat,beats,latency; };
static void require(bool c,const char* s){if(!c)throw std::runtime_error(s);}
static uint16_t value(const Request&r,unsigned b,unsigned l){return uint16_t(r.p*17u+r.q*5u+b*31u+l);}
static void run(bool random_wait){
 Vconv_window_queue top;std::mt19937 rng(0x3217u+TEST_DEPTH+13u*random_wait+TEST_OUTSTANDING);
 std::deque<Request> expected;std::deque<Active> active;
 unsigned accepted=0,retired=0,launches=0,errors=0,previous_launch=0,consecutive=0,max_active=0,finish_launches=0,idle_launches=0,backpressure=0;
 bool failed=false;
 top.rst_n=0;top.enable=1;top.configure=0;top.req_valid=0;top.rsp_ready=0;top.frontend_ready=0;top.frontend_rsp_valid=0;top.frontend_error=0;
 for(unsigned t=0;t<4;t++){top.clk=0;top.eval();top.clk=1;top.eval();}
 top.rst_n=1;const unsigned count=random_wait?4000u:512u;
 for(unsigned cycle=0;cycle<300000;cycle++){
  top.clk=0;
  const bool configure=failed&&expected.empty();
  const bool fault=random_wait&&!failed&&!active.empty()&&errors<8&&rng()%257u==0u;
  top.configure=configure;top.frontend_error=fault;
  top.req_valid=accepted<count&&!failed&&!fault&&(!random_wait||rng()%4u!=0u);
  const Request offered{accepted*19u+1u,accepted*3u,accepted%23u,accepted%4u};
  top.req_p0=offered.p;top.req_q0=offered.q;top.req_cols=offered.cols;top.req_tag=offered.tag;
  top.rsp_ready=(!random_wait||rng()%4u!=0u)&&cycle>=16;
  top.frontend_rsp_valid=!active.empty()&&active.front().latency==0&&!failed;
  top.frontend_rsp_last=!active.empty()&&active.front().beat+1u==active.front().beats;
  top.frontend_rsp_col=active.empty()?0u:active.front().beat%16u;
  top.frontend_rsp_mask=(1u<<TEST_LANES)-1u;
  for(unsigned lane=0;lane<TEST_LANES;lane++)top.frontend_rsp_data[lane]=active.empty()?0u:value(active.front().request,active.front().beat,lane);
  top.frontend_ready=cycle>=16&&!failed&&(active.size()<TEST_OUTSTANDING||(top.frontend_rsp_valid&&top.frontend_rsp_last&&top.rsp_ready));
  top.eval();
  const bool accept=top.req_valid&&top.req_ready,response=top.rsp_valid&&top.rsp_ready,retire=response&&top.rsp_last,launch=top.frontend_valid&&top.frontend_ready;
  Request launched{};
  if(top.req_valid&&!top.req_ready)backpressure++;
  if(top.frontend_valid){
   require(expected.size()>active.size(),"descriptor selected an absent request");
   const Request&r=expected[active.size()];
   require(top.frontend_p0==r.p&&top.frontend_q0==r.q&&top.frontend_cols==r.cols,"descriptor order or payload differs");
   require(bool(top.frontend_cols_valid)==(r.cols>0u&&r.cols<=16u),"column validation differs");
   launched=r;
  }
  if(top.rsp_valid){
   require(!expected.empty(),"response has no accepted request");require(top.rsp_tag==expected.front().tag,"response tag differs");
   require(bool(top.rsp_error)==(failed||fault),"response error differs");
   if(top.rsp_error)require(top.rsp_last&&top.rsp_mask==0,"error response did not terminate");
   else{
    require(!active.empty()&&top.frontend_rsp_valid,"response precedes frontend data");
    require(top.rsp_col==active.front().beat%16u,"response column differs");
    require(top.rsp_mask==((1u<<TEST_LANES)-1u),"response mask differs");
    for(unsigned l=0;l<TEST_LANES;l++)require(top.rsp_data[l]==value(active.front().request,active.front().beat,l),"response data differs");
   }
  }
  if(launch){if(active.empty())idle_launches++;if(retire)finish_launches++;}
  top.clk=1;top.eval();
  for(auto &a:active)if(a.latency)a.latency--;
  if(response&&!retire)active.front().beat++;
  if(retire){expected.pop_front();retired++;if(!active.empty())active.pop_front();}
  if(accept){expected.push_back(offered);accepted++;}
  if(launch){
   require(!failed&&!fault,"invalid frontend launch");
   active.push_back({launched,0u,random_wait?1u+rng()%5u:1u,random_wait?rng()%4u:(launches<16u?3u:0u)});
   if(launches&&cycle==previous_launch+1u)consecutive++;
   previous_launch=cycle;launches++;if(active.size()>max_active)max_active=active.size();
   require(active.size()<=TEST_OUTSTANDING,"frontend outstanding capacity exceeded");
  }
  if(fault){failed=true;active.clear();errors++;}
  if(configure){failed=false;active.clear();}
  require(expected.size()<=TEST_DEPTH,"descriptor queue capacity exceeded");
  if(accepted==count&&expected.empty()&&active.empty()&&!top.busy){
   require(retired==accepted,"request count differs after drain");
   require(max_active==TEST_OUTSTANDING,"configured outstanding capacity was not exercised");
   require(idle_launches>0&&finish_launches>0,"idle and final-beat launch cases incomplete");
   if(!random_wait)require(consecutive>=count-80u,"single-beat windows contain an avoidable issue gap");
   if(random_wait)require(errors==8,"error recovery cases incomplete");
   std::printf("WINDOW_QUEUE_PASS depth=%u lanes=%u outstanding=%u random=%u accepted=%u retired=%u launches=%u consecutive=%u peak=%u idle=%u finish=%u stalls=%u errors=%u cycles=%u\n",TEST_DEPTH,TEST_LANES,TEST_OUTSTANDING,random_wait,accepted,retired,launches,consecutive,max_active,idle_launches,finish_launches,backpressure,errors,cycle+1u);
   top.final();return;
  }
 }
 throw std::runtime_error("window queue did not complete within the cycle limit");
}
int main(int argc,char**argv){Verilated::commandArgs(argc,argv);try{run(false);run(true);return 0;}catch(const std::exception&e){std::fprintf(stderr,"FAIL: %s\n",e.what());return 1;}}
