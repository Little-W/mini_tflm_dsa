// SPDX-License-Identifier: Apache-2.0
#include "Vdma_page_guard_top.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <vector>

struct Request { uint32_t address, beats, at=0, fault=0; };
static void require(bool ok,const char *what) { if(!ok) throw std::runtime_error(what); }
static uint32_t data_at(uint32_t a) { return (a*0x12347u) ^ (a>>7) ^ 0x956af230u; }
static bool crossing(const Request &q) { return (q.address&4095u)+q.beats*4u>4096u; }

int main(int argc,char **argv) {
    Verilated::commandArgs(argc,argv);
    try {
        Vdma_page_guard_top d;
        std::mt19937 rng(18723);
        auto chance=[&](){return (rng()%4)!=0;};
        std::vector<Request> requests;
        for(unsigned i=0;i<192;i++) {
            uint32_t n=i%17==0?256u:1u+rng()%32u;
            uint32_t offset=i%3==0?0xff4u:i%3==1?0xffcu:0x400u;
            requests.push_back({0x10000u+i*0x2000u+offset,n});
        }
        requests[0]={0x10400,64}; requests[1]={0x12800,16};
        requests[2]={0x14c00,32}; requests[3]={0x16d00,16}; requests[4]={0x18ff4,8};
        std::map<uint32_t,unsigned> read_faults,write_faults;
        for(unsigned i=3;i<requests.size();i+=19) {
            read_faults[requests[i].address+4*(requests[i].beats/2)]=2;
            write_faults[requests[i].address+4*(requests[i].beats/2)]=2;
            if(crossing(requests[i])) write_faults[requests[i].address]=3;
        }
        std::deque<Request> physical_reads,logical_reads,physical_writes,logical_writes,logical_responses;
        for (const auto &q : requests) logical_writes.push_back(q);
        std::deque<unsigned> physical_responses;
        std::map<uint32_t,uint8_t> written,expected;
        unsigned ar_next=0,aw_next=0,read_done=0,write_done=0;
        unsigned read_bursts=0,write_bursts=0,read_errors=0,write_errors=0,max_rd=0,max_wr=0;
        unsigned cycles=0; bool rhold=false,bhold=false,read_split=false,write_split=false;
        auto edge=[&](){d.clk=0;d.eval();d.clk=1;d.eval();};
        d.rst_n=0;d.s_arvalid=0;d.s_awvalid=0;d.s_wvalid=0;d.m_rvalid=0;d.m_bvalid=0;
        d.s_rready=0;d.s_bready=0;d.m_arready=0;d.m_awready=0;d.m_wready=0;
        for(int i=0;i<5;i++) edge(); d.rst_n=1;
        while(read_done<requests.size() || write_done<requests.size()) {
            require(cycles++<2000000,"page guard timeout");
            d.s_arvalid=ar_next<requests.size() && logical_reads.size()<4;
            if(d.s_arvalid) { d.s_araddr=requests[ar_next].address;d.s_arlen=requests[ar_next].beats-1; }
            d.s_awvalid=aw_next<requests.size() && logical_responses.size()<4;
            if(d.s_awvalid) { d.s_awaddr=requests[aw_next].address;d.s_awlen=requests[aw_next].beats-1; }
            d.s_wvalid=!logical_writes.empty();
            if(d.s_wvalid) {
                const auto &q=logical_writes.front();
                d.s_wdata=data_at(q.address+4*q.at);d.s_wstrb=(q.at%5==0)?5:15;d.s_wlast=q.at+1==q.beats;
            }
            d.m_arready=physical_reads.size()<4 && chance();
            d.m_awready=physical_writes.size()+physical_responses.size()<4 && chance();
            d.m_wready=!physical_writes.empty() && chance();
            d.s_rready=chance();d.s_bready=chance();
            if(!rhold && !physical_reads.empty() && chance()) {
                const auto &q=physical_reads.front();uint32_t a=q.address+4*q.at;
                d.m_rdata=data_at(a);d.m_rresp=read_faults.count(a)?read_faults[a]:0;
                d.m_rlast=q.at+1==q.beats;rhold=true;
            }
            if(!bhold && !physical_responses.empty() && chance()) {d.m_bresp=physical_responses.front();bhold=true;}
            d.m_rvalid=rhold;d.m_bvalid=bhold;
            d.clk=0;d.eval();
            if(!read_split && d.s_arvalid && !crossing(requests[ar_next])) {
                require(d.m_arvalid && d.s_arready==d.m_arready && d.m_araddr==d.s_araddr &&
                        d.m_arlen==d.s_arlen,"page-local read path changed");
            }
            if(!write_split && d.s_awvalid && !crossing(requests[aw_next])) {
                require(d.m_awvalid && d.s_awready==d.m_awready && d.m_awaddr==d.s_awaddr &&
                        d.m_awlen==d.s_awlen,"page-local write address path changed");
            }
            bool sa=d.s_arvalid&&d.s_arready,ma=d.m_arvalid&&d.m_arready;
            bool sr=d.s_rvalid&&d.s_rready,mr=d.m_rvalid&&d.m_rready;
            bool swa=d.s_awvalid&&d.s_awready,mwa=d.m_awvalid&&d.m_awready;
            bool sw=d.s_wvalid&&d.s_wready,mw=d.m_wvalid&&d.m_wready;
            bool sb=d.s_bvalid&&d.s_bready,mb=d.m_bvalid&&d.m_bready;
            if(sa) {
                const auto &q=requests[ar_next++];
                if(crossing(q)) {require(logical_reads.empty(),"crossing read overtook an outstanding request");read_split=true;}
                logical_reads.push_back(q); max_rd=std::max(max_rd,unsigned(logical_reads.size()));
            }
            if(ma) {
                Request q{d.m_araddr,uint32_t(d.m_arlen)+1};
                require(!crossing(q) && d.m_arsize==2 && d.m_arburst==1 && !(q.address&3),"illegal physical read");
                physical_reads.push_back(q);read_bursts++;
            }
            if(sr) {
                require(!logical_reads.empty(),"extra logical read response");auto &q=logical_reads.front();
                uint32_t a=q.address+4*q.at;unsigned response=read_faults.count(a)?read_faults[a]:0;
                require(d.s_rdata==data_at(a),"logical read data/order mismatch");
                require(d.s_rresp==response,"RRESP propagation mismatch");
                require(bool(d.s_rlast)==(q.at+1==q.beats),"logical RLAST mismatch");
                if(response) read_errors++;
                if(++q.at==q.beats) {if(crossing(q)) read_split=false;logical_reads.pop_front();read_done++;}
            }
            if(mr) {require(!physical_reads.empty(),"extra physical response");auto &q=physical_reads.front();if(++q.at==q.beats)physical_reads.pop_front();rhold=false;}
            if(swa) {
                Request q=requests[aw_next++];
                if(crossing(q)) {require(logical_responses.empty(),"crossing write overtook an outstanding request");write_split=true;}
                for(unsigned i=0;i<q.beats;i++) if(!q.fault && write_faults.count(q.address+4*i))q.fault=write_faults[q.address+4*i];
                logical_responses.push_back(q);max_wr=std::max(max_wr,unsigned(logical_responses.size()));
            }
            if(mwa) {
                Request q{d.m_awaddr,uint32_t(d.m_awlen)+1};
                require(!crossing(q) && d.m_awsize==2 && d.m_awburst==1 && !(q.address&3),"illegal physical write");
                for(unsigned i=0;i<q.beats;i++) if(!q.fault && write_faults.count(q.address+4*i))q.fault=write_faults[q.address+4*i];
                physical_writes.push_back(q);write_bursts++;
            }
            if(sw) {
                require(!logical_writes.empty(),"extra logical write beat");auto &q=logical_writes.front();
                for(unsigned i=0;i<4;i++) if(d.s_wstrb&(1u<<i))expected[q.address+4*q.at+i]=uint8_t(d.s_wdata>>(8*i));
                if(++q.at==q.beats)logical_writes.pop_front();
            }
            if(mw) {
                require(!physical_writes.empty(),"write data without AW");auto &q=physical_writes.front();
                require(bool(d.m_wlast)==(q.at+1==q.beats),"physical WLAST mismatch");
                for(unsigned i=0;i<4;i++) if(d.m_wstrb&(1u<<i))written[q.address+4*q.at+i]=uint8_t(d.m_wdata>>(8*i));
                if(++q.at==q.beats) {physical_responses.push_back(q.fault);physical_writes.pop_front();}
            }
            if(sb) {
                require(!logical_responses.empty(),"extra logical B response");auto q=logical_responses.front();
                require(d.s_bresp==q.fault,"BRESP combination/order mismatch");if(q.fault)write_errors++;
                if(crossing(q))write_split=false;logical_responses.pop_front();write_done++;
            }
            if(mb) {require(!physical_responses.empty(),"extra physical B response");physical_responses.pop_front();bhold=false;}
            d.clk=1;d.eval();
        }
        require(written==expected,"write byte mask/data mismatch");
        require(d.read_idle && d.write_idle && physical_reads.empty() && physical_writes.empty() &&
                physical_responses.empty() && logical_writes.empty(),"transactions did not drain");
        require(max_rd==4 && max_wr==4 && read_errors>0 && write_errors>0,"required concurrency/fault coverage absent");
        d.s_arvalid=0;d.s_awvalid=0;d.s_wvalid=0;d.m_rvalid=0;d.m_bvalid=0;
        d.rst_n=0;edge();d.rst_n=1;edge();require(d.read_idle&&d.write_idle,"reset did not restore idle");
        std::cout<<"DMA_PAGE_GUARD_PASS reads="<<read_done<<" writes="<<write_done<<" physical_reads="<<read_bursts
                 <<" physical_writes="<<write_bursts<<" read_errors="<<read_errors<<" write_errors="<<write_errors
                 <<" max_read_outstanding="<<max_rd<<" max_write_outstanding="<<max_wr<<" cycles="<<cycles<<"\n";
        return 0;
    } catch(const std::exception &e) {std::cerr<<e.what()<<"\n";return 1;}
}
